# -*- coding: utf-8 -*-
"""
规则配置中心 API 冒烟测试（纯脚本，fastapi.testclient + 临时目录数据/归档）

覆盖链路：
    1. admin 登录改密 → 创建 operator / viewer（各自改密）
    2. 初始规则数据核验（映射 21 条 / 大宗 11 个 / 阈值 diff_pct+fuzzy_sim+price_tol）
    3. 权限边界：operator 查询 200 / 修改 403；viewer 查询 403；未登录 401
    4. 映射规则 CRUD：新增/重复源 400/源=目标 400/修改/删除/404
    5. 大宗产品 CRUD：新增/重复 400/修改/删除/404
    6. 阈值修改：合法值 200；超范围 400（diff_pct/fuzzy_sim/price_tol 边界）
    7. 导出：与验收基准 fund_reconciler_config.json 同构且内容一致
    8. 导入：整体替换（计数断言）→ 非法导入 400 且不落半截 → 导入基准配置恢复
    9. 热生效专项：改 fuzzy_sim=0.9 + 新增大宗 C1002 后立即跑 M1 黄金样本任务，
       断言统计变化（模糊 1→0、未匹配 1→2、大宗 2→3、差异 1→0）；
       恢复规则后再跑任务断言回到基线
    10. 审计日志落库核验（规则增删改/阈值/导入，detail 含变更前后值）

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\api\\test_api_rules.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

# =============================================================================
# 环境准备：导入 app 之前注入测试配置（临时数据/归档目录、测试密钥）
# =============================================================================

SERVER_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = SERVER_ROOT.parent
TMP_ROOT = Path(tempfile.mkdtemp(prefix="o32ops_rules_smoke_"))

os.environ["O32OPS_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["O32OPS_ARCHIVE_DIR"] = str(TMP_ROOT / "archive")
os.environ["O32OPS_DB_PATH"] = str(TMP_ROOT / "data" / "o32ops.db")
os.environ["O32OPS_SECRET_KEY"] = "rules-smoke-test-secret-key-do-not-use-in-prod"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

GOLDEN_DIR = SERVER_ROOT / "tests" / "golden"
FUND_SAMPLE = PROJECT_ROOT / "samples" / "golden" / "基金资产表_样本.xlsx"
NETVALUE_SAMPLE = PROJECT_ROOT / "samples" / "golden" / "净值查询表_样本.xlsx"
EXPECTED_STATS = GOLDEN_DIR / "expected" / "expected_stats.json"
REFERENCE_CONFIG = PROJECT_ROOT / "samples" / "reference" / "fund_reconciler_config.json"

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

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
    body = resp.json()
    token = body["access_token"]
    if body.get("must_change_password"):
        resp = client.post("/api/auth/change-password",
                           json={"old_password": old_pw, "new_password": new_pw},
                           headers=auth(token))
        check(f"{username} 修改密码返回200", resp.status_code == 200, resp.text)
    return token


def create_m1_job(client: TestClient, token: str) -> str:
    with open(FUND_SAMPLE, "rb") as f:
        fund_bytes = f.read()
    with open(NETVALUE_SAMPLE, "rb") as f:
        net_bytes = f.read()
    resp = client.post(
        "/api/recon/m1/jobs",
        files={
            "fund_file": (FUND_SAMPLE.name, fund_bytes, XLSX_MIME),
            "netvalue_file": (NETVALUE_SAMPLE.name, net_bytes, XLSX_MIME),
        },
        headers=auth(token),
    )
    check("创建 M1 任务返回200", resp.status_code == 200, resp.text)
    return resp.json()["job_id"]


def poll_job(client: TestClient, token: str, job_id: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/recon/jobs/{job_id}", headers=auth(token))
        if resp.status_code != 200:
            check(f"查询任务 {job_id} 返回200", False, resp.text)
        job = resp.json()
        if job["status"] in ("success", "failed"):
            return job
        time.sleep(0.3)
    raise TimeoutError(f"任务 {job_id} 轮询超时（{timeout}s）仍未结束")


def main() -> int:
    print("=" * 70)
    print("规则配置中心 API 冒烟测试（O32 日常运维平台 一期）")
    print(f"临时目录: {TMP_ROOT}")
    print("=" * 70)

    with open(EXPECTED_STATS, "r", encoding="utf-8") as f:
        expected_stats = json.load(f)
    with open(REFERENCE_CONFIG, "r", encoding="utf-8") as f:
        reference_config = json.load(f)

    with TestClient(app) as client:
        # ------------------------------------------------------------------
        # 1. 用户准备
        # ------------------------------------------------------------------
        print("--- 1. 用户准备 ---")
        admin_token = login_and_change(client, "admin", "Admin@123", "Admin@2026New")
        resp = client.post("/api/admin/users",
                           json={"username": "op01", "password": "Op@123456", "role": "operator"},
                           headers=auth(admin_token))
        check("创建 operator 返回200", resp.status_code == 200, resp.text)
        resp = client.post("/api/admin/users",
                           json={"username": "vw01", "password": "Vw@123456", "role": "viewer"},
                           headers=auth(admin_token))
        check("创建 viewer 返回200", resp.status_code == 200, resp.text)
        op_token = login_and_change(client, "op01", "Op@123456", "Op@654321New")
        vw_token = login_and_change(client, "vw01", "Vw@123456", "Vw@654321New")

        # ------------------------------------------------------------------
        # 2. 初始规则数据核验
        # ------------------------------------------------------------------
        print("--- 2. 初始规则数据 ---")
        resp = client.get("/api/rules/mappings", headers=auth(admin_token))
        check("映射列表返回200", resp.status_code == 200, resp.text)
        check("初始映射 21 条", len(resp.json()) == 21, str(len(resp.json())))

        resp = client.get("/api/rules/bulk-products", headers=auth(admin_token))
        check("大宗清单返回200", resp.status_code == 200, resp.text)
        check("初始大宗 11 个", len(resp.json()) == 11, str(len(resp.json())))

        resp = client.get("/api/rules/thresholds", headers=auth(admin_token))
        check("阈值列表返回200", resp.status_code == 200, resp.text)
        thresholds = {t["param_key"]: t["param_value"] for t in resp.json()}
        check("阈值含 diff_pct=1.0", thresholds.get("diff_pct") == "1.0", str(thresholds))
        check("阈值含 fuzzy_sim=0.5", thresholds.get("fuzzy_sim") == "0.5", str(thresholds))
        check("阈值含 price_tol=0.0001(预留)", thresholds.get("price_tol") == "0.0001",
              str(thresholds))

        # ------------------------------------------------------------------
        # 3. 权限边界
        # ------------------------------------------------------------------
        print("--- 3. 权限边界 ---")
        for path in ("/api/rules/mappings", "/api/rules/bulk-products",
                     "/api/rules/thresholds", "/api/rules/export"):
            resp = client.get(path, headers=auth(op_token))
            check(f"operator 查询 {path} 返回200", resp.status_code == 200, resp.text)

        resp = client.post("/api/rules/mappings",
                           json={"source_code": "X1", "target_code": "X2"},
                           headers=auth(op_token))
        check("operator 新增映射被拒(403)", resp.status_code == 403, resp.text)
        resp = client.put("/api/rules/thresholds/fuzzy_sim",
                          json={"value": 0.6}, headers=auth(op_token))
        check("operator 修改阈值被拒(403)", resp.status_code == 403, resp.text)
        resp = client.post("/api/rules/import",
                           json={"rename_map": {}, "bulk_products": []},
                           headers=auth(op_token))
        check("operator 导入被拒(403)", resp.status_code == 403, resp.text)
        resp = client.delete("/api/rules/bulk-products/1", headers=auth(op_token))
        check("operator 删除大宗被拒(403)", resp.status_code == 403, resp.text)

        resp = client.get("/api/rules/mappings", headers=auth(vw_token))
        check("viewer 查询映射被拒(403)", resp.status_code == 403, resp.text)
        resp = client.get("/api/rules/thresholds", headers=auth(vw_token))
        check("viewer 查询阈值被拒(403)", resp.status_code == 403, resp.text)
        resp = client.get("/api/rules/export", headers=auth(vw_token))
        check("viewer 导出被拒(403)", resp.status_code == 403, resp.text)

        resp = client.get("/api/rules/mappings")
        check("未登录查询被拒(401)", resp.status_code == 401, resp.text)

        # ------------------------------------------------------------------
        # 4. 映射规则 CRUD
        # ------------------------------------------------------------------
        print("--- 4. 映射规则 CRUD ---")
        resp = client.post("/api/rules/mappings",
                           json={"source_code": "T9001", "target_code": "T8001"},
                           headers=auth(admin_token))
        check("新增映射返回200", resp.status_code == 200, resp.text)
        mapping_id = resp.json()["id"]
        check("新增映射 updated_by=admin", resp.json().get("updated_by") == "admin",
              str(resp.json()))

        resp = client.get("/api/rules/mappings", headers=auth(admin_token))
        check("新增后映射 22 条", len(resp.json()) == 22, str(len(resp.json())))

        resp = client.post("/api/rules/mappings",
                           json={"source_code": "T9001", "target_code": "T8002"},
                           headers=auth(admin_token))
        check("重复原代码新增被拒(400)", resp.status_code == 400, resp.text)
        check("400 提示含'已存在'", "已存在" in resp.text, resp.text)

        resp = client.post("/api/rules/mappings",
                           json={"source_code": "T9100", "target_code": "T9100"},
                           headers=auth(admin_token))
        check("源=目标新增被拒(400)", resp.status_code == 400, resp.text)

        resp = client.put(f"/api/rules/mappings/{mapping_id}",
                          json={"target_code": "T8002", "enabled": False},
                          headers=auth(admin_token))
        check("修改映射返回200", resp.status_code == 200, resp.text)
        check("修改后 target=T8002 且停用",
              resp.json()["target_code"] == "T8002" and resp.json()["enabled"] is False,
              str(resp.json()))

        resp = client.put("/api/rules/mappings/999999",
                          json={"target_code": "X"}, headers=auth(admin_token))
        check("修改不存在映射返回404", resp.status_code == 404, resp.text)

        resp = client.delete(f"/api/rules/mappings/{mapping_id}", headers=auth(admin_token))
        check("删除映射返回200", resp.status_code == 200, resp.text)
        resp = client.get("/api/rules/mappings", headers=auth(admin_token))
        check("删除后映射回到 21 条", len(resp.json()) == 21, str(len(resp.json())))
        resp = client.delete(f"/api/rules/mappings/{mapping_id}", headers=auth(admin_token))
        check("重复删除返回404", resp.status_code == 404, resp.text)

        # ------------------------------------------------------------------
        # 5. 特殊产品 CRUD（note/color）
        # ------------------------------------------------------------------
        print("--- 5. 特殊产品 CRUD ---")
        resp = client.post("/api/rules/bulk-products",
                           json={"product_code": "AZ9999", "note": "测试特殊说明",
                                 "color": "92D050"},
                           headers=auth(admin_token))
        check("新增特殊产品返回200", resp.status_code == 200, resp.text)
        check("新增返回 note/color 生效",
              resp.json()["note"] == "测试特殊说明" and resp.json()["color"] == "92D050",
              str(resp.json()))
        bulk_id = resp.json()["id"]

        resp = client.post("/api/rules/bulk-products",
                           json={"product_code": "AZ9999"}, headers=auth(admin_token))
        check("重复特殊产品新增被拒(400)", resp.status_code == 400, resp.text)

        resp = client.post("/api/rules/bulk-products",
                           json={"product_code": "AZ9998", "color": "ZZZZZZ"},
                           headers=auth(admin_token))
        check("非法颜色新增被拒(400)", resp.status_code == 400, resp.text)
        check("颜色 400 中文提示",
              "颜色须为6位十六进制" in resp.json()["detail"], resp.text)
        resp = client.post("/api/rules/bulk-products",
                           json={"product_code": "AZ9998", "color": "#FFC000"},
                           headers=auth(admin_token))
        check("带#颜色新增被拒(400)", resp.status_code == 400, resp.text)

        resp = client.put(f"/api/rules/bulk-products/{bulk_id}",
                          json={"note": "测试特殊-改", "color": "00b0f0", "enabled": False},
                          headers=auth(admin_token))
        check("修改特殊产品返回200", resp.status_code == 200, resp.text)
        check("修改后 note/颜色已更新(小写转大写)且停用",
              resp.json()["note"] == "测试特殊-改"
              and resp.json()["color"] == "00B0F0"
              and resp.json()["enabled"] is False,
              str(resp.json()))

        resp = client.put(f"/api/rules/bulk-products/{bulk_id}",
                          json={"color": "12345"}, headers=auth(admin_token))
        check("非法颜色修改被拒(400)", resp.status_code == 400, resp.text)

        resp = client.put(f"/api/rules/bulk-products/{bulk_id}",
                          json={"note": ""}, headers=auth(admin_token))
        check("空串 note 清空(回退默认)", resp.status_code == 200
              and resp.json()["note"] is None, resp.text)

        resp = client.delete(f"/api/rules/bulk-products/{bulk_id}", headers=auth(admin_token))
        check("删除特殊产品返回200", resp.status_code == 200, resp.text)
        resp = client.get("/api/rules/bulk-products", headers=auth(admin_token))
        check("删除后特殊产品回到 11 个", len(resp.json()) == 11, str(len(resp.json())))
        check("存量行缺省 color=FFC000 且 note 为空(默认文案)",
              all(r["color"] == "FFC000" and r["note"] is None for r in resp.json()),
              str(resp.json()[:2]))
        resp = client.delete(f"/api/rules/bulk-products/{bulk_id}", headers=auth(admin_token))
        check("重复删除特殊产品返回404", resp.status_code == 404, resp.text)

        # ------------------------------------------------------------------
        # 6. 阈值修改与范围校验
        # ------------------------------------------------------------------
        print("--- 6. 阈值修改 ---")
        resp = client.put("/api/rules/thresholds/fuzzy_sim",
                          json={"value": 0.6}, headers=auth(admin_token))
        check("修改 fuzzy_sim=0.6 返回200", resp.status_code == 200, resp.text)
        check("返回值为 0.6", resp.json()["param_value"] == "0.6", str(resp.json()))
        resp = client.put("/api/rules/thresholds/fuzzy_sim",
                          json={"value": 0.5}, headers=auth(admin_token))
        check("恢复 fuzzy_sim=0.5 返回200", resp.status_code == 200, resp.text)

        for key, bad in (("diff_pct", 0.005), ("diff_pct", 200.0),
                         ("fuzzy_sim", 1.5), ("fuzzy_sim", -0.1), ("price_tol", 2.0)):
            resp = client.put(f"/api/rules/thresholds/{key}",
                              json={"value": bad}, headers=auth(admin_token))
            check(f"非法阈值 {key}={bad} 被拒(400)", resp.status_code == 400, resp.text)
        check("400 提示含合法范围", "合法范围" in resp.text, resp.text)

        resp = client.put("/api/rules/thresholds/no_such_key",
                          json={"value": 1.0}, headers=auth(admin_token))
        check("未知阈值键被拒(400)", resp.status_code == 400, resp.text)

        resp = client.put("/api/rules/thresholds/price_tol",
                          json={"value": 0.0002}, headers=auth(admin_token))
        check("修改 price_tol=0.0002 返回200", resp.status_code == 200, resp.text)
        resp = client.put("/api/rules/thresholds/price_tol",
                          json={"value": 0.0001}, headers=auth(admin_token))
        check("恢复 price_tol=0.0001 返回200", resp.status_code == 200, resp.text)

        resp = client.get("/api/rules/thresholds", headers=auth(admin_token))
        thresholds = {t["param_key"]: t["param_value"] for t in resp.json()}
        check("阈值全部恢复初始值",
              thresholds.get("diff_pct") == "1.0"
              and thresholds.get("fuzzy_sim") == "0.5"
              and thresholds.get("price_tol") == "0.0001",
              str(thresholds))

        # ------------------------------------------------------------------
        # 7. 导出：与基准 config 同构且内容一致
        # ------------------------------------------------------------------
        print("--- 7. 导出同构 ---")
        resp = client.get("/api/rules/export", headers=auth(admin_token))
        check("导出返回200", resp.status_code == 200, resp.text)
        exported = resp.json()
        for key in ("rename_map", "bulk_products", "diff_threshold", "similarity_threshold"):
            check(f"导出含键 {key}", key in exported, str(list(exported.keys())))
        check("导出 rename_map 为 dict 且与基准一致",
              isinstance(exported["rename_map"], dict)
              and exported["rename_map"] == reference_config["rename_map"],
              f"导出{len(exported.get('rename_map', {}))}条 基准{len(reference_config['rename_map'])}条")
        check("导出 bulk_products 为 list 且与基准一致（旧键兼容）",
              isinstance(exported["bulk_products"], list)
              and sorted(exported["bulk_products"]) == sorted(reference_config["bulk_products"]),
              str(exported.get("bulk_products")))
        check("导出 special_products 新格式（code/note/color 三键）",
              isinstance(exported.get("special_products"), list)
              and all(set(item.keys()) == {"code", "note", "color"}
                      for item in exported["special_products"])
              and sorted(i["code"] for i in exported["special_products"])
                  == sorted(reference_config["bulk_products"])
              and all(i["note"] is None and i["color"] == "FFC000"
                      for i in exported["special_products"]),
              str(exported.get("special_products"))[:200])
        check("导出 diff_threshold 与基准一致(1.0)",
              exported["diff_threshold"] == reference_config["diff_threshold"],
              str(exported["diff_threshold"]))
        check("导出 similarity_threshold 与基准一致(0.5)",
              exported["similarity_threshold"] == reference_config["similarity_threshold"],
              str(exported["similarity_threshold"]))
        check("导出含 output_settings(与基准同构)",
              "output_settings" in exported, str(list(exported.keys())))

        # ------------------------------------------------------------------
        # 8. 导入：整体替换 + 非法输入不落半截 + 恢复
        # ------------------------------------------------------------------
        print("--- 8. 导入 ---")
        modified_config = {
            "rename_map": {**reference_config["rename_map"],
                           "T0001": "T0002", "T0003": "T0004"},
            "bulk_products": reference_config["bulk_products"][:-1],
        }
        resp = client.post("/api/rules/import", json=modified_config, headers=auth(admin_token))
        check("导入修改配置返回200", resp.status_code == 200, resp.text)
        result = resp.json()
        check("导入计数 映射21→23",
              result["mappings_before"] == 21 and result["mappings_after"] == 23, str(result))
        check("导入计数 大宗11→10",
              result["bulk_before"] == 11 and result["bulk_after"] == 10, str(result))

        resp = client.get("/api/rules/mappings", headers=auth(admin_token))
        check("导入后映射 23 条", len(resp.json()) == 23, str(len(resp.json())))
        resp = client.get("/api/rules/bulk-products", headers=auth(admin_token))
        check("导入后大宗 10 个", len(resp.json()) == 10, str(len(resp.json())))

        bad_config = {"rename_map": {"A": "B"},
                      "bulk_products": ["X1", "X1"]}
        resp = client.post("/api/rules/import", json=bad_config, headers=auth(admin_token))
        check("大宗重复导入被拒(400)", resp.status_code == 400, resp.text)
        resp = client.get("/api/rules/mappings", headers=auth(admin_token))
        check("非法导入后映射仍为 23 条(未落半截)", len(resp.json()) == 23,
              str(len(resp.json())))

        bad_config2 = {"rename_map": {"A": "B"}, "bulk_products": ["X1"],
                       "similarity_threshold": 2.0}
        resp = client.post("/api/rules/import", json=bad_config2, headers=auth(admin_token))
        check("非法阈值导入被拒(400)", resp.status_code == 400, resp.text)
        resp = client.get("/api/rules/mappings", headers=auth(admin_token))
        check("非法阈值导入后映射仍为 23 条", len(resp.json()) == 23, str(len(resp.json())))

        # 新格式 special_products 导入（note/color 落库）
        new_fmt_config = {
            "rename_map": reference_config["rename_map"],
            "special_products": [
                {"code": "AZ0206", "note": "大额申赎差异(月末确认)", "color": "92d050"},
                {"code": "AZ0205", "note": None, "color": None},
                {"code": "AZ0207"},
            ],
        }
        resp = client.post("/api/rules/import", json=new_fmt_config, headers=auth(admin_token))
        check("新格式导入返回200", resp.status_code == 200, resp.text)
        check("新格式导入计数 特殊产品10→3",
              resp.json()["bulk_before"] == 10 and resp.json()["bulk_after"] == 3,
              str(resp.json()))
        resp = client.get("/api/rules/bulk-products", headers=auth(admin_token))
        by_code = {r["product_code"]: r for r in resp.json()}
        check("新格式 note/color 落库（小写转大写）",
              by_code["AZ0206"]["note"] == "大额申赎差异(月末确认)"
              and by_code["AZ0206"]["color"] == "92D050"
              and by_code["AZ0205"]["note"] is None
              and by_code["AZ0205"]["color"] == "FFC000"
              and by_code["AZ0207"]["color"] == "FFC000",
              str(by_code))
        bad_color_config = {"rename_map": {"A": "B"},
                            "special_products": [{"code": "X1", "color": "red"}]}
        resp = client.post("/api/rules/import", json=bad_color_config, headers=auth(admin_token))
        check("新格式非法颜色导入被拒(400)", resp.status_code == 400
              and "颜色须为6位十六进制" in resp.json()["detail"], resp.text)
        resp = client.get("/api/rules/bulk-products", headers=auth(admin_token))
        check("非法导入后特殊产品仍为 3 个(未落半截)", len(resp.json()) == 3,
              str(len(resp.json())))
        both_fmt = {"rename_map": {"A": "B"},
                    "special_products": [{"code": "Y1"}],
                    "bulk_products": ["Y2"]}
        resp = client.post("/api/rules/import", json=both_fmt, headers=auth(admin_token))
        check("双格式并存时 special_products 优先",
              resp.status_code == 200 and resp.json()["bulk_after"] == 1, resp.text)
        resp = client.get("/api/rules/bulk-products", headers=auth(admin_token))
        check("优先生效为 special_products(Y1)",
              len(resp.json()) == 1 and resp.json()[0]["product_code"] == "Y1", resp.text)

        resp = client.post("/api/rules/import", json=reference_config, headers=auth(admin_token))
        check("导入基准配置恢复返回200", resp.status_code == 200, resp.text)
        result = resp.json()
        check("恢复计数 映射23→21 / 大宗10→11",
              result["mappings_after"] == 21 and result["bulk_after"] == 11, str(result))
        resp = client.get("/api/rules/export", headers=auth(admin_token))
        check("恢复后导出与基准再次一致",
              resp.json()["rename_map"] == reference_config["rename_map"]
              and sorted(resp.json()["bulk_products"]) == sorted(reference_config["bulk_products"]),
              resp.text[:300])

        # ------------------------------------------------------------------
        # 9. 热生效专项：改规则 → 立即跑 M1 黄金样本任务 → 统计变化 → 恢复复验
        # ------------------------------------------------------------------
        print("--- 9. 热生效专项 ---")
        job_a = create_m1_job(client, op_token)
        final_a = poll_job(client, op_token, job_a)
        check("任务A(改前) 执行成功", final_a["status"] == "success",
              f"status={final_a['status']} error={final_a.get('error')}")
        check("任务A 统计=黄金基线(模糊1/未匹配1/大宗2/差异1)",
              final_a["stats"] == expected_stats,
              f"预期{expected_stats} 实际{final_a['stats']}")
        check("任务A 日志含'来源:数据库'(规则现取)",
              any("来源:数据库" in line for line in final_a["log_tail"]),
              str(final_a["log_tail"][-8:]))

        # 变更：fuzzy_sim 0.5→0.9（使 0.875 的模糊匹配场景变为未匹配）+ 新增大宗 C1002
        resp = client.put("/api/rules/thresholds/fuzzy_sim",
                          json={"value": 0.9}, headers=auth(admin_token))
        check("变更 fuzzy_sim=0.9 返回200", resp.status_code == 200, resp.text)
        resp = client.post("/api/rules/bulk-products",
                           json={"product_code": "C1002", "description": "热生效测试临时大宗"},
                           headers=auth(admin_token))
        check("新增大宗 C1002 返回200", resp.status_code == 200, resp.text)
        bulk_c1002_id = resp.json()["id"]

        expected_stats_b = {
            "总记录数": 16,
            "精确匹配": 14,
            "模糊匹配": 0,
            "未匹配": 2,
            "大宗产品数": 3,
            "差异>1.0%数量（非大宗）": 0,
        }
        job_b = create_m1_job(client, op_token)
        final_b = poll_job(client, op_token, job_b)
        check("任务B(改后) 执行成功", final_b["status"] == "success",
              f"status={final_b['status']} error={final_b.get('error')}")
        check("任务B 统计按新规则输出(模糊0/未匹配2/大宗3/差异0)",
              final_b["stats"] == expected_stats_b,
              f"预期{expected_stats_b} 实际{final_b['stats']}")
        check("任务B 日志含'模糊匹配完成: 0条'",
              any("模糊匹配完成: 0条" in line for line in final_b["log_tail"]),
              str(final_b["log_tail"][-8:]))
        check("任务B 日志含'来源:数据库'",
              any("来源:数据库" in line for line in final_b["log_tail"]),
              str(final_b["log_tail"][-8:]))

        # 恢复规则原值
        resp = client.put("/api/rules/thresholds/fuzzy_sim",
                          json={"value": 0.5}, headers=auth(admin_token))
        check("恢复 fuzzy_sim=0.5 返回200", resp.status_code == 200, resp.text)
        resp = client.delete(f"/api/rules/bulk-products/{bulk_c1002_id}",
                             headers=auth(admin_token))
        check("删除临时大宗 C1002 返回200", resp.status_code == 200, resp.text)

        job_c = create_m1_job(client, op_token)
        final_c = poll_job(client, op_token, job_c)
        check("任务C(恢复后) 执行成功", final_c["status"] == "success",
              f"status={final_c['status']} error={final_c.get('error')}")
        check("任务C 统计回到黄金基线(规则已恢复)",
              final_c["stats"] == expected_stats,
              f"预期{expected_stats} 实际{final_c['stats']}")

    # ----------------------------------------------------------------------
    # 10. 审计日志落库核验（直接查库）
    # ----------------------------------------------------------------------
    print("--- 10. 审计日志 ---")
    conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
    rows = dict(conn.execute(
        "SELECT action, COUNT(*) FROM sys_audit_log GROUP BY action").fetchall())
    for action in ("rule_mapping_create", "rule_mapping_update", "rule_mapping_delete",
                   "rule_bulk_create", "rule_bulk_update", "rule_bulk_delete",
                   "rule_threshold_update", "rule_import"):
        check(f"审计动作已记录: {action}", rows.get(action, 0) > 0, str(rows))
    detail = conn.execute(
        "SELECT detail FROM sys_audit_log WHERE action='rule_threshold_update' "
        "AND detail LIKE '%0.5→0.9%'").fetchone()
    check("阈值审计 detail 含变更前后值(0.5→0.9)", detail is not None,
          "未找到 0.5→0.9 的阈值变更记录")
    detail = conn.execute(
        "SELECT detail FROM sys_audit_log WHERE action='rule_mapping_update' "
        "AND detail LIKE '%T8001→T8002%'").fetchone()
    check("映射审计 detail 含变更前后值(T8001→T8002)", detail is not None,
          "未找到 T8001→T8002 的映射变更记录")
    detail = conn.execute(
        "SELECT detail FROM sys_audit_log WHERE action='rule_import' "
        "AND detail LIKE '%21→23%'").fetchone()
    check("导入审计 detail 含前后计数(21→23)", detail is not None,
          "未找到 21→23 的导入记录")
    conn.close()

    print("=" * 70)
    if failures:
        print(f"规则配置冒烟测试失败，共 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("规则配置中心 API 冒烟测试全部通过 ✅")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.exit(2)
