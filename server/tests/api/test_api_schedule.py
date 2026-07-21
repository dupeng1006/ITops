# -*- coding: utf-8 -*-
"""
DS-F5 任务调度中心 + 统计看板冒烟测试（纯脚本，fastapi.testclient + SQLite 内部测试方言）

覆盖链路：
    1. admin 登录改密 → 创建 operator / viewer
    2. 系统参数：GET 默认值（data_ready_time=17:30/buffer_minutes=30）、
       PUT 合法修改与规范化、非法值 400、未知键 400、viewer 读/写均 403
    3. sqlite 数据源 + 好模板（数据=黄金样本，biz_date=当日，匹配调度当日取数）
       + 坏模板（指向不存在表，制造确定性取数失败）
    4. 定时任务 CRUD 校验：cron 非法 400 / m1 db 缺模板 400 / 模板不存在 404 /
       模块不匹配 400 / viewer 403；创建与列表；启停切换
    5. 立即执行（db 模式）：recon_job 生成且 trigger_type=schedule、
       统计==黄金基线 16/14/1/1/2/1、recon_job_item 16 行、执行历史可查
    6. 失败重试：坏模板立即执行 → 先 retrying 后 failed（间隔取系统参数
       schedule_retry_delay_minutes，测试置 0.05 分钟）→ 重试 1 次后置 failed，
       补记 failed recon_job
    7. 看板三接口：diff-trend 当日点==基线；persistent-diff 插历史明细验证
       次数/最大/最近与 min_times 过滤；health 计数与最近执行
    8. viewer 看板/调度全 403；审计留痕断言

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests/api/test_api_schedule.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

# =============================================================================
# 环境准备：导入 app 之前注入测试配置（临时数据/归档目录、测试密钥）
# =============================================================================

SERVER_ROOT = Path(__file__).resolve().parents[2]
TMP_ROOT = Path(tempfile.mkdtemp(prefix="o32ops_sched_smoke_"))

os.environ["O32OPS_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["O32OPS_ARCHIVE_DIR"] = str(TMP_ROOT / "archive")
os.environ["O32OPS_DB_PATH"] = str(TMP_ROOT / "data" / "o32ops.db")
os.environ["O32OPS_SECRET_KEY"] = "sched-smoke-test-secret-key-do-not-use-in-prod"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PROJECT_ROOT = SERVER_ROOT.parent
M1_FUND_SAMPLE = PROJECT_ROOT / "samples" / "golden" / "基金资产表_样本.xlsx"
M1_NET_SAMPLE = PROJECT_ROOT / "samples" / "golden" / "净值查询表_样本.xlsx"
M1_EXPECTED_STATS = SERVER_ROOT / "tests" / "golden" / "expected" / "expected_stats.json"

# 调度执行以"当日"为业务日期：fixture 表 biz_date 取当日，保证 db 模式取到数
BIZ = datetime.now().strftime("%Y%m%d")
SQLITE_DB = TMP_ROOT / "test_source.db"

failures: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def login_and_change(client: TestClient, username: str, old_pw: str, new_pw: str) -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": old_pw})
    check(f"登录 {username} 返回200", resp.status_code == 200, resp.text)
    token = resp.json()["access_token"]
    if resp.json().get("must_change_password"):
        resp2 = client.post("/api/auth/change-password",
                            json={"old_password": old_pw, "new_password": new_pw},
                            headers=auth(token))
        check(f"{username} 修改密码返回200", resp2.status_code == 200, resp2.text)
    return token


def poll_schedule_status(client: TestClient, token: str, schedule_id: int,
                         timeout: float = 120.0):
    """轮询定时任务 last_status 变化，返回 (最终状态, 期间出现过的状态集合, 最后一条记录)"""
    seen = []
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get("/api/schedule/jobs", headers=auth(token))
        rows = resp.json()
        last = next((r for r in rows if r["id"] == schedule_id), None)
        st = last.get("last_status") if last else None
        if st and (not seen or seen[-1] != st):
            seen.append(st)
        if st in ("success", "failed", "wait_file"):
            return st, seen, last
        time.sleep(0.5)
    raise TimeoutError(f"定时任务 {schedule_id} 状态轮询超时（已见: {seen}）")


def build_sqlite_fixture() -> None:
    """构造 SQLite 测试库：表数据 = 黄金样本同数据（biz_date=当日，匹配调度当日取数）"""
    df_fund = pd.read_excel(M1_FUND_SAMPLE, header=0)
    df_net = pd.read_excel(M1_NET_SAMPLE, header=0)
    df_fund["biz_date"] = BIZ
    df_net["biz_date"] = BIZ
    conn = sqlite3.connect(SQLITE_DB)
    try:
        df_fund.to_sql("t_fund", conn, index=False)
        df_net.to_sql("t_net", conn, index=False)
    finally:
        conn.close()
    print(f"SQLite 测试库已构造: {SQLITE_DB}（t_fund/t_net，数据=黄金样本，biz_date={BIZ}）")


def seed_history_items() -> None:
    """直接插历史 recon_job + recon_job_item（看板 persistent-diff 验证用）"""
    conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
    fmt = "%Y-%m-%d %H:%M:%S.%f"
    try:
        for i, (job_id, days_ago, diff) in enumerate([
            ("seedhist00000001", 1, 2.5),
            ("seedhist00000002", 2, 3.1),
            ("seedhist00000003", 3, 4.2),   # 另一产品单次出现，应被 min_times=2 过滤
        ]):
            ts = datetime.now() - timedelta(days=days_ago)
            conn.execute(
                "INSERT INTO recon_job (id, module, biz_date, fetch_mode, status, trigger_type,"
                " progress, stats_json, created_by, created_at, finished_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (job_id, "M1", (ts).strftime("%Y%m%d"), "file", "success", "manual",
                 100, "{}", "test-seed", ts.strftime(fmt), ts.strftime(fmt)))
            code = "SEED001" if i < 2 else "SEED002"
            conn.execute(
                "INSERT INTO recon_job_item (job_id, product_code, product_name, max_diff_pct,"
                " match_method, is_bulk, created_at) VALUES (?,?,?,?,?,?,?)",
                (job_id, code, "种子产品" + code, diff, "精确", 0, ts.strftime(fmt)))
        conn.commit()
    finally:
        conn.close()
    print("历史明细已插入: SEED001×2（2.5/3.1），SEED002×1（4.2）")


def main() -> int:
    print("=" * 70)
    print("DS-F5 任务调度中心 + 统计看板冒烟测试")
    print(f"临时目录: {TMP_ROOT}")
    print("=" * 70)

    build_sqlite_fixture()
    expected_m1_stats = json.loads(M1_EXPECTED_STATS.read_text(encoding="utf-8"))

    with TestClient(app) as client:
        # 1. 用户准备
        print("--- 1. 用户准备 ---")
        admin_token = login_and_change(client, "admin", "Admin@123", "Admin@2026New")
        resp = client.post("/api/admin/users",
                           json={"username": "op06", "password": "Op@123456", "role": "operator"},
                           headers=auth(admin_token))
        check("创建 operator 返回200", resp.status_code == 200, resp.text)
        resp = client.post("/api/admin/users",
                           json={"username": "vw06", "password": "Vw@123456", "role": "viewer"},
                           headers=auth(admin_token))
        check("创建 viewer 返回200", resp.status_code == 200, resp.text)
        op_token = login_and_change(client, "op06", "Op@123456", "Op@654321New")
        vw_token = login_and_change(client, "vw06", "Vw@123456", "Vw@654321New")

        # 2. 系统参数读写
        print("--- 2. 系统参数（data_ready_time/buffer_minutes/重试间隔） ---")
        resp = client.get("/api/admin/system/params", headers=auth(op_token))
        check("operator 读系统参数返回200", resp.status_code == 200, resp.text)
        params = {p["param_key"]: p["param_value"] for p in resp.json()}
        check("默认 data_ready_time=17:30", params.get("data_ready_time") == "17:30", str(params))
        check("默认 buffer_minutes=30", params.get("buffer_minutes") == "30", str(params))
        resp = client.put("/api/admin/system/params",
                          json={"values": {"data_ready_time": "18:07",
                                           "schedule_retry_delay_minutes": "0.05"}},
                          headers=auth(admin_token))
        check("PUT 系统参数返回200", resp.status_code == 200, resp.text)
        params = {p["param_key"]: p["param_value"] for p in resp.json()}
        check("data_ready_time 已更新为 18:07", params.get("data_ready_time") == "18:07", str(params))
        check("重试间隔已置 0.05 分钟（3 秒，供重试测试提速）",
              params.get("schedule_retry_delay_minutes") == "0.05", str(params))
        resp = client.put("/api/admin/system/params",
                          json={"values": {"data_ready_time": "25:00"}}, headers=auth(admin_token))
        check("非法 data_ready_time 返回400", resp.status_code == 400, resp.text)
        resp = client.put("/api/admin/system/params",
                          json={"values": {"unknown_key": "x"}}, headers=auth(admin_token))
        check("未知参数键返回400", resp.status_code == 400, resp.text)
        resp = client.get("/api/admin/system/params", headers=auth(vw_token))
        check("viewer 读系统参数返回403", resp.status_code == 403, resp.text)
        resp = client.put("/api/admin/system/params",
                          json={"values": {"buffer_minutes": "10"}}, headers=auth(vw_token))
        check("viewer 写系统参数返回403", resp.status_code == 403, resp.text)

        # 3. sqlite 数据源 + 好/坏模板
        print("--- 3. sqlite 数据源与查询模板 ---")
        resp = client.post("/api/datasources",
                           json={"name": "sqlite调度测试库", "db_type": "sqlite",
                                 "db_name": str(SQLITE_DB), "username": "na", "password": "na"},
                           headers=auth(admin_token))
        check("创建 sqlite 数据源返回200", resp.status_code == 200, resp.text)
        ds_id = resp.json()["id"]

        fund_cols = ", ".join(f"列{i}" for i in range(28))
        net_cols = ", ".join(f"列{i}" for i in range(9))
        params_def = {"biz_date": {"type": "date", "required": True, "label": "业务日期"}}
        tpl_ids = {}
        for name, module, sql in [
            ("调度基金资产模板", "m1_fund", f"SELECT {fund_cols} FROM t_fund WHERE biz_date = :biz_date"),
            ("调度净值查询模板", "m1_netvalue", f"SELECT {net_cols} FROM t_net WHERE biz_date = :biz_date"),
            ("坏基金资产模板", "m1_fund", f"SELECT {fund_cols} FROM t_no_such_fund WHERE biz_date = :biz_date"),
            ("坏净值查询模板", "m1_netvalue", f"SELECT {net_cols} FROM t_no_such_net WHERE biz_date = :biz_date"),
        ]:
            resp = client.post("/api/query-templates",
                               json={"name": name, "module": module, "ds_id": ds_id,
                                     "sql_text": sql, "params_def": params_def},
                               headers=auth(admin_token))
            check(f"创建模板[{name}]返回200", resp.status_code == 200, resp.text)
            tpl_ids[name] = resp.json()["id"]

        # 4. 定时任务 CRUD 校验
        print("--- 4. 定时任务创建校验（cron/参数/权限） ---")
        base_body = {"name": "x", "module": "m1", "fetch_mode": "db",
                     "fund_template_id": tpl_ids["调度基金资产模板"],
                     "netvalue_template_id": tpl_ids["调度净值查询模板"],
                     "cron_expr": "7 18 * * 1-5"}
        resp = client.post("/api/schedule/jobs", json={**base_body, "cron_expr": "bad cron"},
                           headers=auth(op_token))
        check("cron 非法返回400中文", resp.status_code == 400 and "cron" in resp.text, resp.text)
        resp = client.post("/api/schedule/jobs",
                           json={k: v for k, v in base_body.items() if k != "netvalue_template_id"},
                           headers=auth(op_token))
        check("m1 db 缺净值模板返回400", resp.status_code == 400, resp.text)
        resp = client.post("/api/schedule/jobs", json={**base_body, "fund_template_id": 99999},
                           headers=auth(op_token))
        check("模板不存在返回404", resp.status_code == 404, resp.text)
        resp = client.post("/api/schedule/jobs",
                           json={**base_body, "fund_template_id": tpl_ids["调度净值查询模板"]},
                           headers=auth(op_token))
        check("模板模块不匹配返回400", resp.status_code == 400, resp.text)
        resp = client.post("/api/schedule/jobs", json=base_body, headers=auth(vw_token))
        check("viewer 创建定时任务返回403", resp.status_code == 403, resp.text)

        resp = client.post("/api/schedule/jobs",
                           json={**base_body, "name": "每日M1核对-好"}, headers=auth(op_token))
        check("创建定时任务（好模板）返回200", resp.status_code == 200, resp.text)
        good_id = resp.json()["id"]
        check("新建任务默认启用", resp.json()["enabled"] is True, str(resp.json()))
        resp = client.post("/api/schedule/jobs",
                           json={**base_body, "name": "每日M1核对-坏",
                                 "fund_template_id": tpl_ids["坏基金资产模板"],
                                 "netvalue_template_id": tpl_ids["坏净值查询模板"]},
                           headers=auth(op_token))
        check("创建定时任务（坏模板）返回200", resp.status_code == 200, resp.text)
        bad_id = resp.json()["id"]
        resp = client.get("/api/schedule/jobs", headers=auth(op_token))
        check("定时任务列表=2", len(resp.json()) == 2, str(len(resp.json())))

        # 启停切换
        resp = client.post(f"/api/schedule/jobs/{good_id}/toggle", headers=auth(op_token))
        check("启停切换→停用", resp.status_code == 200 and resp.json()["enabled"] is False, resp.text)
        resp = client.post(f"/api/schedule/jobs/{good_id}/toggle", headers=auth(op_token))
        check("启停切换→启用", resp.status_code == 200 and resp.json()["enabled"] is True, resp.text)
        resp = client.post(f"/api/schedule/jobs/{good_id}/toggle", headers=auth(vw_token))
        check("viewer 启停返回403", resp.status_code == 403, resp.text)

        # 5. 立即执行（db 模式好模板）
        print("--- 5. 立即执行：db 模式调度任务全流程 ---")
        resp = client.post(f"/api/schedule/jobs/{good_id}/run-now", headers=auth(op_token))
        check("立即执行返回200", resp.status_code == 200, resp.text)
        st, seen, last = poll_schedule_status(client, op_token, good_id)
        check("定时执行最终状态=success", st == "success", f"seen={seen} last={last}")
        job_id = last.get("last_job_id")
        check("schedule 记录最近 recon_job ID", bool(job_id), str(last))

        resp = client.get(f"/api/recon/jobs/{job_id}", headers=auth(op_token))
        job = resp.json()
        check("调度产生 recon_job trigger_type=schedule", job.get("trigger_type") == "schedule",
              str(job.get("trigger_type")))
        check("调度任务 fetch_mode=db", job.get("fetch_mode") == "db", str(job.get("fetch_mode")))
        check("调度任务 biz_date=当日", job.get("biz_date") == BIZ,
              f"预期{BIZ} 实际{job.get('biz_date')}")
        check("调度任务统计==黄金基线(16/14/1/1/2/1)", job.get("stats") == expected_m1_stats,
              f"预期{expected_m1_stats} 实际{job.get('stats')}")

        conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
        item_count = conn.execute(
            "SELECT COUNT(*) FROM recon_job_item WHERE job_id=?", (job_id,)).fetchone()[0]
        conn.close()
        check("recon_job_item 明细=16 行（M1 成功写入）", item_count == 16, str(item_count))

        resp = client.get("/api/schedule/executions", headers=auth(op_token))
        check("执行历史返回200", resp.status_code == 200, resp.text)
        check("执行历史含本次任务", any(e["job_id"] == job_id for e in resp.json()),
              str([e["job_id"] for e in resp.json()]))
        resp = client.get(f"/api/schedule/executions?schedule_id={good_id}", headers=auth(op_token))
        check("执行历史按 schedule_id 过滤生效",
              all(e["job_id"] == job_id for e in resp.json()) and len(resp.json()) >= 1, resp.text)

        # 6. 失败重试（坏模板 → 取数确定性失败 → 重试 1 次 → failed）
        print("--- 6. 失败重试：重试 1 次后置 failed ---")
        resp = client.post(f"/api/schedule/jobs/{bad_id}/run-now", headers=auth(op_token))
        check("坏任务立即执行返回200", resp.status_code == 200, resp.text)
        st, seen, last = poll_schedule_status(client, op_token, bad_id, timeout=90.0)
        check("失败任务最终状态=failed", st == "failed", f"seen={seen}")
        check("失败后经 retrying（重试已安排）", "retrying" in seen, f"seen={seen}")
        bad_job_id = last.get("last_job_id")
        check("重试仍失败已补记 recon_job", bool(bad_job_id), str(last))
        if bad_job_id:
            resp = client.get(f"/api/recon/jobs/{bad_job_id}", headers=auth(op_token))
            bad_job = resp.json()
            check("补记任务 status=failed", bad_job.get("status") == "failed", str(bad_job.get("status")))
            check("补记任务 trigger_type=schedule", bad_job.get("trigger_type") == "schedule",
                  str(bad_job.get("trigger_type")))
            check("补记任务 error 含失败原因", bool(bad_job.get("error")), str(bad_job.get("error")))

        # 7. 统计看板
        print("--- 7. 统计看板三接口 ---")
        seed_history_items()
        resp = client.get("/api/dashboard/diff-trend?days=30", headers=auth(op_token))
        check("diff-trend 返回200", resp.status_code == 200, resp.text)
        points = {p["biz_date"]: p for p in resp.json()["points"]}
        today_point = points.get(BIZ)
        check("diff-trend 含当日点", today_point is not None, str(points.keys()))
        if today_point:
            check("当日点统计==基线(16/14/1/1/2/1)",
                  (today_point["total"], today_point["exact"], today_point["fuzzy"],
                   today_point["unmatched"], today_point["bulk"], today_point["diff"])
                  == (16, 14, 1, 1, 2, 1), str(today_point))

        resp = client.get("/api/dashboard/persistent-diff?days=7&min_times=2", headers=auth(op_token))
        check("persistent-diff 返回200", resp.status_code == 200, resp.text)
        body = resp.json()
        check("persistent-diff 阈值=1.0", body["threshold_pct"] == 1.0, str(body["threshold_pct"]))
        items = {i["product_code"]: i for i in body["items"]}
        seed1 = items.get("SEED001")
        check("持续差异含 SEED001（7 天内 2 次）", seed1 is not None, str(items))
        if seed1:
            check("SEED001 次数=2", seed1["times"] == 2, str(seed1))
            check("SEED001 最大差异=3.1", abs((seed1["max_diff_pct"] or 0) - 3.1) < 1e-6, str(seed1))
            check("SEED001 最近差异=2.5", abs((seed1["last_diff_pct"] or 0) - 2.5) < 1e-6, str(seed1))
        check("SEED002（仅 1 次）被 min_times=2 过滤", "SEED002" not in items, str(items))

        resp = client.get("/api/dashboard/health", headers=auth(op_token))
        check("health 返回200", resp.status_code == 200, resp.text)
        h = resp.json()
        check("health 定时任务总数=2", h["schedule_total"] == 2, str(h["schedule_total"]))
        check("health 启用数=2", h["schedule_enabled"] == 2, str(h["schedule_enabled"]))
        check("health 近30天 scheduled 成功≥1", h["last30d"].get("success", 0) >= 1, str(h["last30d"]))
        check("health 近30天 scheduled 失败≥1", h["last30d"].get("failed", 0) >= 1, str(h["last30d"]))
        check("health 最近执行非空", len(h["recent"]) >= 1, str(len(h["recent"])))
        check("health 回显 data_ready_time=18:07", h["data_ready_time"] == "18:07",
              str(h["data_ready_time"]))

        # 8. viewer 看板/调度只读全禁 + 审计
        print("--- 8. viewer 403 与审计 ---")
        for label, method, url in [
            ("调度列表", "get", "/api/schedule/jobs"),
            ("执行历史", "get", "/api/schedule/executions"),
            ("diff-trend", "get", "/api/dashboard/diff-trend"),
            ("persistent-diff", "get", "/api/dashboard/persistent-diff"),
            ("health", "get", "/api/dashboard/health"),
        ]:
            resp = getattr(client, method)(url, headers=auth(vw_token))
            check(f"viewer {label} 返回403", resp.status_code == 403, resp.text)
        resp = client.post(f"/api/schedule/jobs/{good_id}/run-now", headers=auth(vw_token))
        check("viewer 立即执行返回403", resp.status_code == 403, resp.text)

        conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
        actions = {r[0] for r in conn.execute(
            "SELECT DISTINCT action FROM sys_audit_log").fetchall()}
        conn.close()
        for a in ("schedule_create", "schedule_toggle", "schedule_run_now", "sys_params_update"):
            check(f"审计含 {a}", a in actions, str(sorted(actions)))

    print("=" * 70)
    if failures:
        print(f"共 {len(failures)} 项失败:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
