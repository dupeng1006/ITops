# -*- coding: utf-8 -*-
"""
DS-F5 补测：file 模式调度（待文件/重试就绪续跑）+ M2 调度执行冒烟

承接 test_api_schedule.py（主链路），本文件覆盖两条补测链路：

    A. M1 file 模式调度：
       空目录立即执行 → recon_job 标记 wait_file（"待文件"，错误含就绪时间参数）
       → 重试等待期内拷入黄金样本文件 → 重试复用同一任务行续跑
       → success 且统计==黄金基线 16/14/1/1/2/1（trigger_type=schedule）
    B. M2 db 模式调度：
       sqlite 灌 M2 双产品样本（biz_date=当日）→ groups_json 两组模板
       → 立即执行 → success 且统计==M2 基线，6301 报告生成
    C. M2 file 模式调度：
       监测目录放双产品四文件 → 立即执行 → success 且统计==M2 基线

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests/api/test_api_schedule_m2_file.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# =============================================================================
# 环境准备：导入 app 之前注入测试配置
# =============================================================================

SERVER_ROOT = Path(__file__).resolve().parents[2]
TMP_ROOT = Path(tempfile.mkdtemp(prefix="o32ops_sched_m2f_"))

os.environ["O32OPS_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["O32OPS_ARCHIVE_DIR"] = str(TMP_ROOT / "archive")
os.environ["O32OPS_DB_PATH"] = str(TMP_ROOT / "data" / "o32ops.db")
os.environ["O32OPS_SECRET_KEY"] = "sched-m2f-smoke-test-secret-key-do-not-use-in-prod"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PROJECT_ROOT = SERVER_ROOT.parent
M1_FUND_SAMPLE = PROJECT_ROOT / "samples" / "golden" / "基金资产表_样本.xlsx"
M1_NET_SAMPLE = PROJECT_ROOT / "samples" / "golden" / "净值查询表_样本.xlsx"
M1_EXPECTED_STATS = SERVER_ROOT / "tests" / "golden" / "expected" / "expected_stats.json"
M2_SAMPLE_DIR = SERVER_ROOT / "tests" / "golden" / "m2" / "samples"
M2_EXPECTED_STATS = SERVER_ROOT / "tests" / "golden" / "m2" / "expected" / "expected_stats.json"

BIZ = datetime.now().strftime("%Y%m%d")   # 调度执行以当日为业务日期
SQLITE_DB = TMP_ROOT / "test_source.db"
WATCH_M1 = TMP_ROOT / "watch_m1"          # M1 监测目录（先空后放）
WATCH_M2 = TMP_ROOT / "watch_m2"          # M2 监测目录（预先放四文件）

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


def poll_schedule(client: TestClient, token: str, schedule_id: int, want: tuple,
                  timeout: float = 120.0):
    """轮询 schedule_job.last_status 直至进入 want 集合，返回 (状态, last 记录)"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get("/api/schedule/jobs", headers=auth(token))
        last = next((r for r in resp.json() if r["id"] == schedule_id), None)
        st = last.get("last_status") if last else None
        if st in want:
            return st, last
        time.sleep(0.4)
    raise TimeoutError(f"定时任务 {schedule_id} 未在 {timeout}s 内进入 {want}（当前: {last}）")


def build_fixtures() -> None:
    """sqlite 灌 M2 双产品样本（biz_date=当日）；M2 监测目录放四文件；M1 监测目录先建空"""
    df_sys1 = pd.read_excel(M2_SAMPLE_DIR / "新综合信息查询_基金证券-6301.xlsx", header=0)
    df_sys2 = pd.read_excel(M2_SAMPLE_DIR / "新综合信息查询_基金证券-6302.xlsx", header=0)
    df_val1 = pd.read_excel(M2_SAMPLE_DIR / "证券投资基金估值表_6301-20260720.xlsx", skiprows=3, header=0)
    df_val2 = pd.read_excel(M2_SAMPLE_DIR / "证券投资基金估值表_6302-20260720.xlsx", skiprows=3, header=0)
    for df in (df_sys1, df_sys2, df_val1, df_val2):
        df["biz_date"] = BIZ
    conn = sqlite3.connect(SQLITE_DB)
    try:
        df_sys1.to_sql("t_m2_sys_6301", conn, index=False)
        df_sys2.to_sql("t_m2_sys_6302", conn, index=False)
        df_val1.to_sql("t_m2_val_6301", conn, index=False)
        df_val2.to_sql("t_m2_val_6302", conn, index=False)
    finally:
        conn.close()

    WATCH_M1.mkdir(parents=True, exist_ok=True)   # 先空（未就绪场景）
    WATCH_M2.mkdir(parents=True, exist_ok=True)
    for name in ("新综合信息查询_基金证券-6301.xlsx", "新综合信息查询_基金证券-6302.xlsx",
                 "证券投资基金估值表_6301-20260720.xlsx", "证券投资基金估值表_6302-20260720.xlsx"):
        shutil.copy2(M2_SAMPLE_DIR / name, WATCH_M2 / name)
    print(f"fixture 就绪: sqlite 4 表(biz_date={BIZ})；watch_m1(空)；watch_m2(4 文件)")


def main() -> int:
    print("=" * 70)
    print("DS-F5 补测：file 模式调度（待文件/续跑）+ M2 调度执行")
    print(f"临时目录: {TMP_ROOT}")
    print("=" * 70)

    build_fixtures()
    expected_m1 = json.loads(M1_EXPECTED_STATS.read_text(encoding="utf-8"))
    expected_m2 = json.loads(M2_EXPECTED_STATS.read_text(encoding="utf-8"))

    with TestClient(app) as client:
        # 0. 用户 + 重试间隔提速（0.1 分钟=6 秒，留出拷文件窗口）
        print("--- 0. 用户与参数准备 ---")
        admin_token = login_and_change(client, "admin", "Admin@123", "Admin@2026New")
        resp = client.post("/api/admin/users",
                           json={"username": "op07", "password": "Op@123456", "role": "operator"},
                           headers=auth(admin_token))
        check("创建 operator 返回200", resp.status_code == 200, resp.text)
        op_token = login_and_change(client, "op07", "Op@123456", "Op@654321New")
        resp = client.put("/api/admin/system/params",
                          json={"values": {"schedule_retry_delay_minutes": "0.1"}},
                          headers=auth(admin_token))
        check("重试间隔置 0.1 分钟（6 秒）", resp.status_code == 200, resp.text)

        # A. M1 file 模式调度：未就绪 → 待文件 → 重试就绪续跑
        print("--- A. M1 file 模式：wait_file → 重试续跑 success ---")
        resp = client.post("/api/schedule/jobs",
                           json={"name": "M1文件监测", "module": "m1", "fetch_mode": "file",
                                 "file_dir": str(WATCH_M1), "cron_expr": "7 18 * * 1-5"},
                           headers=auth(op_token))
        check("创建 M1 file 调度返回200", resp.status_code == 200, resp.text)
        m1f_id = resp.json()["id"]

        resp = client.post(f"/api/schedule/jobs/{m1f_id}/run-now", headers=auth(op_token))
        check("run-now 返回200", resp.status_code == 200, resp.text)
        st, last = poll_schedule(client, op_token, m1f_id, ("wait_file",), timeout=30.0)
        check("文件未就绪→任务标记 wait_file（待文件）", st == "wait_file", str(last))
        wait_job_id = last.get("last_job_id")
        check("wait_file 已落 recon_job", bool(wait_job_id), str(last))
        resp = client.get(f"/api/recon/jobs/{wait_job_id}", headers=auth(op_token))
        wait_job = resp.json()
        check("wait_file 任务 trigger_type=schedule", wait_job.get("trigger_type") == "schedule",
              str(wait_job.get("trigger_type")))
        check("wait_file 错误含监测目录与就绪时间提示",
              "监测目录" in (wait_job.get("error") or "") and "17:30" in (wait_job.get("error") or ""),
              str(wait_job.get("error")))

        # 重试等待期内拷入文件 → attempt2 复用同一任务行续跑
        shutil.copy2(M1_FUND_SAMPLE, WATCH_M1 / M1_FUND_SAMPLE.name)
        shutil.copy2(M1_NET_SAMPLE, WATCH_M1 / M1_NET_SAMPLE.name)
        st, last = poll_schedule(client, op_token, m1f_id, ("success", "failed"), timeout=90.0)
        check("重试就绪续跑最终 success", st == "success", str(last))
        check("续跑复用同一 recon_job 行", last.get("last_job_id") == wait_job_id,
              f"wait={wait_job_id} final={last.get('last_job_id')}")
        resp = client.get(f"/api/recon/jobs/{wait_job_id}", headers=auth(op_token))
        check("续跑任务统计==黄金基线(16/14/1/1/2/1)", resp.json().get("stats") == expected_m1,
              str(resp.json().get("stats")))

        # B. M2 db 模式调度：双产品 groups → success == M2 基线
        print("--- B. M2 db 模式调度执行 ---")
        resp = client.post("/api/datasources",
                           json={"name": "sqlite调度M2库", "db_type": "sqlite",
                                 "db_name": str(SQLITE_DB), "username": "na", "password": "na"},
                           headers=auth(admin_token))
        check("创建 sqlite 数据源返回200", resp.status_code == 200, resp.text)
        ds_id = resp.json()["id"]
        val_cols = ('"科目代码", "科目名称", "数量", "单位成本", "成本", "成本占净值%", '
                    '"市价", "市值", "市值占净值%", "估值增值", "停牌信息"')
        params_def = {"biz_date": {"type": "date", "required": True, "label": "业务日期"}}
        tpl_ids = {}
        for name, module, sql in [
            ("调度M2系统端-6301", "m2_system",
             "SELECT 证券代码, 证券名称, 持仓, 估值价格, 市值 FROM t_m2_sys_6301 WHERE biz_date = :biz_date"),
            ("调度M2估值表-6301", "m2_valuation", f"SELECT {val_cols} FROM t_m2_val_6301 WHERE biz_date = :biz_date"),
            ("调度M2系统端-6302", "m2_system",
             "SELECT 证券代码, 证券名称, 持仓, 估值价格, 市值 FROM t_m2_sys_6302 WHERE biz_date = :biz_date"),
            ("调度M2估值表-6302", "m2_valuation", f"SELECT {val_cols} FROM t_m2_val_6302 WHERE biz_date = :biz_date"),
        ]:
            resp = client.post("/api/query-templates",
                               json={"name": name, "module": module, "ds_id": ds_id,
                                     "sql_text": sql, "params_def": params_def},
                               headers=auth(admin_token))
            check(f"创建模板[{name}]返回200", resp.status_code == 200, resp.text)
            tpl_ids[name] = resp.json()["id"]

        groups = [
            {"product": "6301", "system_template_id": tpl_ids["调度M2系统端-6301"],
             "valuation_template_id": tpl_ids["调度M2估值表-6301"]},
            {"product": "6302", "system_template_id": tpl_ids["调度M2系统端-6302"],
             "valuation_template_id": tpl_ids["调度M2估值表-6302"]},
        ]
        resp = client.post("/api/schedule/jobs",
                           json={"name": "M2每日核对-db", "module": "m2", "fetch_mode": "db",
                                 "groups_json": json.dumps(groups, ensure_ascii=False),
                                 "cron_expr": "23 18 * * 1-5"},
                           headers=auth(op_token))
        check("创建 M2 db 调度返回200", resp.status_code == 200, resp.text)
        m2d_id = resp.json()["id"]
        resp = client.post(f"/api/schedule/jobs/{m2d_id}/run-now", headers=auth(op_token))
        check("M2 db run-now 返回200", resp.status_code == 200, resp.text)
        st, last = poll_schedule(client, op_token, m2d_id, ("success", "failed"), timeout=120.0)
        check("M2 db 调度执行 success", st == "success",
              str(last.get("last_error")) if last else "")
        m2_job_id = last.get("last_job_id")
        resp = client.get(f"/api/recon/jobs/{m2_job_id}", headers=auth(op_token))
        m2_job = resp.json()
        check("M2 db 任务 trigger_type=schedule", m2_job.get("trigger_type") == "schedule",
              str(m2_job.get("trigger_type")))
        check("M2 db 任务统计==基线", m2_job.get("stats") == expected_m2,
              f"预期{expected_m2} 实际{m2_job.get('stats')}")
        check("M2 结果文件名含产品报告", bool(m2_job.get("result_filename"))
              and "6301" in m2_job["result_filename"], str(m2_job.get("result_filename")))

        # C. M2 file 模式调度：监测目录四文件就绪 → success == M2 基线
        print("--- C. M2 file 模式调度执行 ---")
        resp = client.post("/api/schedule/jobs",
                           json={"name": "M2文件监测", "module": "m2", "fetch_mode": "file",
                                 "file_dir": str(WATCH_M2), "cron_expr": "37 18 * * *"},
                           headers=auth(op_token))
        check("创建 M2 file 调度返回200", resp.status_code == 200, resp.text)
        m2f_id = resp.json()["id"]
        resp = client.post(f"/api/schedule/jobs/{m2f_id}/run-now", headers=auth(op_token))
        check("M2 file run-now 返回200", resp.status_code == 200, resp.text)
        st, last = poll_schedule(client, op_token, m2f_id, ("success", "failed"), timeout=120.0)
        check("M2 file 调度执行 success", st == "success",
              str(last.get("last_error")) if last else "")
        resp = client.get(f"/api/recon/jobs/{last.get('last_job_id')}", headers=auth(op_token))
        m2f_job = resp.json()
        check("M2 file 任务统计==基线", m2f_job.get("stats") == expected_m2,
              f"预期{expected_m2} 实际{m2f_job.get('stats')}")

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
