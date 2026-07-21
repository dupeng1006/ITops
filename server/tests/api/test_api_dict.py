# -*- coding: utf-8 -*-
"""
数据字典查询 API 冒烟测试（纯脚本，fastapi.testclient + fixture 迷你字典库）

覆盖：
    1. 未认证 401；viewer 查询 403（需求：operator 及以上可查）
    2. GET /api/dict/models 模型清单
    3. GET /api/dict/tables 搜索：表代码/中文名/字段名三种命中点 + 分页 + 收藏置顶
    4. GET /api/dict/tables/{id} 详情（字段 + 主键标识）；不存在 404
    5. GET /api/dict/tables/{id}/references 父子两向
    6. POST /api/dict/gen-sql：单表（ROWNUM）、多表自动 JOIN、无关联 CROSS 警告、
       非法运算符 400、生成 SQL 过 sql_guard；审计留痕
    7. POST /api/dict/save-template：admin 成功（模块=custom 且可被
       /api/query-templates?module=custom 查到）、operator 403、重名 400、
       写 SQL 被 guard 拦截 400
    8. 收藏：GET /POST /DELETE /api/dict/favorites；搜索收藏置顶；重复/不存在/权限校验

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests/api/test_api_dict.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# =============================================================================
# 环境准备：导入 app 之前注入测试配置（临时平台库 + fixture 迷你字典库）
# =============================================================================

SERVER_ROOT = Path(__file__).resolve().parents[2]
TMP_ROOT = Path(tempfile.mkdtemp(prefix="o32ops_dict_smoke_"))

os.environ["O32OPS_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["O32OPS_ARCHIVE_DIR"] = str(TMP_ROOT / "archive")
os.environ["O32OPS_DB_PATH"] = str(TMP_ROOT / "data" / "o32ops.db")
os.environ["O32OPS_DICT_DB_PATH"] = str(TMP_ROOT / "data" / "dictionary.db")
os.environ["O32OPS_SECRET_KEY"] = "dict-smoke-test-secret-key-do-not-use-in-prod"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from fastapi.testclient import TestClient  # noqa: E402

from app.datasource.sql_guard import validate_select_only  # noqa: E402
from app.main import app  # noqa: E402
from scripts.import_pdm import build_dictionary  # noqa: E402

FIXTURE_DIR = SERVER_ROOT / "tests" / "fixtures" / "pdm"

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


def main() -> int:
    # fixture 迷你字典库
    dict_db = Path(os.environ["O32OPS_DICT_DB_PATH"])
    dict_db.parent.mkdir(parents=True, exist_ok=True)
    stats = build_dictionary(FIXTURE_DIR, dict_db)
    check("fixture 字典库构建", stats["tables"] == 4 and stats["references"] == 2,
          str(stats))

    with TestClient(app) as client:
        # ---- 0. 账号：admin 改密 + 建 operator / viewer ----
        admin_token = login_and_change(client, "admin", "Admin@123", "Admin@12345")
        resp = client.post("/api/admin/users", headers=auth(admin_token),
                           json={"username": "operator", "password": "Operator@123",
                                 "role": "operator"})
        check("创建 operator 返回200/201", resp.status_code in (200, 201), resp.text)
        resp = client.post("/api/admin/users", headers=auth(admin_token),
                           json={"username": "viewer", "password": "Viewer@123",
                                 "role": "viewer"})
        check("创建 viewer 返回200/201", resp.status_code in (200, 201), resp.text)
        op_token = login_and_change(client, "operator", "Operator@123", "Operator@12345")
        vw_token = login_and_change(client, "viewer", "Viewer@123", "Viewer@12345")

        # 数据源（保存模板用）
        resp = client.post("/api/datasources", headers=auth(admin_token),
                           json={"name": "字典冒烟Oracle源", "db_type": "oracle",
                                 "host": "10.0.0.1", "port": 1521,
                                 "service_name": "O32", "username": "readonly",
                                 "password": "x"})
        check("创建数据源返回200/201", resp.status_code in (200, 201), resp.text)
        ds_id = resp.json()["id"]

        # ---- 1. 认证与角色 ----
        resp = client.get("/api/dict/models")
        check("未认证 401", resp.status_code == 401, str(resp.status_code))
        resp = client.get("/api/dict/models", headers=auth(vw_token))
        check("viewer 查询 403", resp.status_code == 403, resp.text)

        # ---- 2. 模型清单 ----
        resp = client.get("/api/dict/models", headers=auth(op_token))
        check("models 返回200", resp.status_code == 200, resp.text)
        models = resp.json()
        check("models 含迷你模型且统计正确",
              len(models) == 1 and models[0]["table_count"] == 4
              and models[0]["column_count"] == 14
              and models[0]["biz_group"] == "mini_order",
              str(models))

        # ---- 3. 搜索 ----
        resp = client.get("/api/dict/tables", headers=auth(op_token),
                          params={"keyword": "TORDER"})
        items = resp.json()["items"]
        check("按表代码命中（TORDER 前缀 3 表）",
              resp.json()["total"] == 3
              and all("table_code" in i["matched_on"] for i in items),
              str([(i["table_code"], i["matched_on"]) for i in items]))

        resp = client.get("/api/dict/tables", headers=auth(op_token),
                          params={"keyword": "订单明细"})
        items = resp.json()["items"]
        check("按中文名命中",
              resp.json()["total"] == 1 and items[0]["table_code"] == "TORDERDETAIL"
              and "table_name" in items[0]["matched_on"], str(items))

        resp = client.get("/api/dict/tables", headers=auth(op_token),
                          params={"keyword": "订单日期"})
        items = resp.json()["items"]
        check("按字段中文名命中（标注命中列）",
              resp.json()["total"] == 1 and items[0]["table_code"] == "TORDER"
              and "column" in items[0]["matched_on"]
              and items[0]["matched_columns"][0]["col_code"] == "d_order_date",
              str(items))

        resp = client.get("/api/dict/tables", headers=auth(op_token),
                          params={"keyword": "vc_order_no"})
        check("按字段代码命中", resp.json()["total"] == 1, resp.text)

        resp = client.get("/api/dict/tables", headers=auth(op_token),
                          params={"page": 2, "page_size": 3})
        check("分页（共4表，第2页1条）",
              resp.json()["total"] == 4 and len(resp.json()["items"]) == 1,
              str(resp.json()["total"]))

        # ---- 4. 表详情 ----
        torder_id = next(i["id"] for i in client.get(
            "/api/dict/tables", headers=auth(op_token),
            params={"keyword": "TORDER", "page_size": 50}).json()["items"]
            if i["table_code"] == "TORDER")
        resp = client.get(f"/api/dict/tables/{torder_id}", headers=auth(op_token))
        detail = resp.json()
        check("表详情：5 字段且 l_order_id 主键",
              resp.status_code == 200 and len(detail["columns"]) == 5
              and [c["col_code"] for c in detail["columns"] if c["is_pk"]] == ["l_order_id"],
              str(detail.get("columns")))
        resp = client.get("/api/dict/tables/999999", headers=auth(op_token))
        check("表不存在 404", resp.status_code == 404, str(resp.status_code))

        # ---- 5. 关联（父子两向） ----
        resp = client.get(f"/api/dict/tables/{torder_id}/references",
                          headers=auth(op_token))
        refs = resp.json()
        check("TORDER 为父：TORDERDETAIL + TORDERPAY",
              {r["other_code"] for r in refs["as_parent"]}
              == {"TORDERDETAIL", "TORDERPAY"}
              and refs["as_child"] == [], str(refs))
        pay = next(r for r in refs["as_parent"] if r["other_code"] == "TORDERPAY")
        check("推导关联字段对（parent l_order_id → child l_order_id）",
              pay["joins"] == [{"parent_col": "l_order_id",
                                "child_col": "l_order_id"}], str(pay["joins"]))

        # ---- 6. gen-sql ----
        tdetail_id = next(i["id"] for i in client.get(
            "/api/dict/tables", headers=auth(op_token),
            params={"keyword": "TORDERDETAIL"}).json()["items"]
            if i["table_code"] == "TORDERDETAIL")
        tproduct_id = next(i["id"] for i in client.get(
            "/api/dict/tables", headers=auth(op_token),
            params={"keyword": "TPRODUCT"}).json()["items"]
            if i["table_code"] == "TPRODUCT")

        resp = client.post("/api/dict/gen-sql", headers=auth(op_token), json={
            "tables": [{"table_id": torder_id,
                        "columns": ["vc_order_no", "d_order_date"], "alias": None}],
            "conditions": [{"table_alias": "t1", "column": "d_order_date",
                            "op": ">=", "value": "2026-01-01"}],
            "limit": 100, "use_rownum": True})
        check("gen-sql 单表 200", resp.status_code == 200, resp.text)
        sql = resp.json()["sql"]
        check("单表 SQL 内容（TO_DATE + ROWNUM 100）",
          "FROM TORDER t1" in sql
          and "TO_DATE('2026-01-01', 'YYYY-MM-DD')" in sql
          and "ROWNUM <= 100" in sql, sql)
        try:
            validate_select_only(sql)
            check("生成 SQL 过 sql_guard（独立复核）", True)
        except Exception as e:  # noqa: BLE001
            check("生成 SQL 过 sql_guard（独立复核）", False, str(e))

        resp = client.post("/api/dict/gen-sql", headers=auth(op_token), json={
            "tables": [{"table_id": torder_id, "columns": ["vc_order_no"], "alias": None},
                       {"table_id": tdetail_id, "columns": ["en_qty"], "alias": None}],
            "conditions": [], "limit": 500, "use_rownum": True})
        body = resp.json()
        check("多表自动 JOIN（ON 父子等值）",
              "JOIN TORDERDETAIL t2 ON t1.l_order_id = t2.l_order_id" in body["sql"]
              and any("FK_DETAIL_ORDER" in j for j in body["joins"])
              and body["warnings"] == [], str(body))

        resp = client.post("/api/dict/gen-sql", headers=auth(op_token), json={
            "tables": [{"table_id": torder_id, "columns": ["vc_order_no"], "alias": None},
                       {"table_id": tproduct_id, "columns": ["vc_product_name"], "alias": None}],
            "conditions": [], "limit": 500, "use_rownum": True})
        body = resp.json()
        check("无关联 CROSS + 警告文案",
              "CROSS JOIN TPRODUCT t2" in body["sql"]
              and any("无已知" in w and "自行确认 JOIN 条件" in w
                      for w in body["warnings"]), str(body))

        resp = client.post("/api/dict/gen-sql", headers=auth(op_token), json={
            "tables": [{"table_id": torder_id, "columns": [], "alias": None}],
            "conditions": [{"table_alias": "t1", "column": "vc_order_no",
                            "op": "DROP", "value": "x"}],
            "limit": 500, "use_rownum": True})
        check("非法运算符 400 中文提示", resp.status_code == 400
              and "运算符非法" in resp.json()["detail"], resp.text)

        # 审计留痕
        conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
        cnt = conn.execute(
            "SELECT COUNT(*) FROM sys_audit_log WHERE action = 'dict_gen_sql'"
        ).fetchone()[0]
        conn.close()
        check("gen-sql 审计留痕", cnt >= 3, f"audit count={cnt}")

        # ---- 7. save-template ----
        good_sql = ("SELECT t1.vc_order_no, t2.en_qty FROM TORDER t1"
                    " JOIN TORDERDETAIL t2 ON t1.l_order_id = t2.l_order_id"
                    " WHERE ROWNUM <= 500")
        resp = client.post("/api/dict/save-template", headers=auth(op_token),
                           json={"name": "字典冒烟模板", "ds_id": ds_id,
                                 "sql_text": good_sql})
        check("operator 保存模板 403（复用模板创建权限=admin）",
              resp.status_code == 403, resp.text)

        resp = client.post("/api/dict/save-template", headers=auth(admin_token),
                           json={"name": "字典冒烟模板", "ds_id": ds_id,
                                 "sql_text": good_sql})
        check("admin 保存模板 200 且模块=custom",
              resp.status_code == 200 and resp.json()["module"] == "custom",
              resp.text)
        tpl_id = resp.json()["id"] if resp.status_code == 200 else None

        resp = client.get("/api/query-templates", headers=auth(admin_token),
                          params={"module": "custom"})
        check("模板列表 module=custom 可查到",
              resp.status_code == 200
              and any(t["id"] == tpl_id for t in resp.json()), resp.text)

        resp = client.post("/api/dict/save-template", headers=auth(admin_token),
                           json={"name": "字典冒烟模板", "ds_id": ds_id,
                                 "sql_text": good_sql})
        check("重名 400", resp.status_code == 400
              and "已存在" in resp.json()["detail"], resp.text)

        resp = client.post("/api/dict/save-template", headers=auth(admin_token),
                           json={"name": "字典冒烟模板2", "ds_id": ds_id,
                                 "sql_text": "DELETE FROM TORDER"})
        check("写 SQL 被 guard 拦截 400", resp.status_code == 400
              and "安全校验" in resp.json()["detail"], resp.text)

        resp = client.post("/api/dict/save-template", headers=auth(admin_token),
                           json={"name": "字典冒烟模板3", "ds_id": 999999,
                                 "sql_text": good_sql})
        check("数据源不存在 400", resp.status_code == 400
              and "数据源不存在" in resp.json()["detail"], resp.text)

        # ---- 8. 字典表收藏（收藏置顶） ----
        # 初始为空
        resp = client.get("/api/dict/favorites", headers=auth(op_token))
        check("favorites 初始为空", resp.status_code == 200 and resp.json() == [], resp.text)

        # 收藏 TORDER
        resp = client.post("/api/dict/favorites", headers=auth(op_token),
                           json={"table_id": torder_id, "table_code": "TORDER",
                                 "table_name": "订单主表"})
        check("收藏 TORDER 200", resp.status_code == 200
              and resp.json()["table_id"] == torder_id, resp.text)

        # 重复收藏 400
        resp = client.post("/api/dict/favorites", headers=auth(op_token),
                           json={"table_id": torder_id, "table_code": "TORDER",
                                 "table_name": "订单主表"})
        check("重复收藏 400", resp.status_code == 400
              and "已收藏" in resp.json()["detail"], resp.text)

        # 收藏不存在的表 404
        resp = client.post("/api/dict/favorites", headers=auth(op_token),
                           json={"table_id": 999999, "table_code": "NOTEXIST",
                                 "table_name": "不存在"})
        check("收藏不存在表 404", resp.status_code == 404, resp.text)

        # 列表返回
        resp = client.get("/api/dict/favorites", headers=auth(op_token))
        favs = resp.json()
        check("favorites 列表含 TORDER",
              resp.status_code == 200 and len(favs) == 1
              and favs[0]["table_code"] == "TORDER", str(favs))

        # 搜索时收藏置顶（TORDER 应排在第一位，即使按字母顺序 TORDERDETAIL 更前）
        resp = client.get("/api/dict/tables", headers=auth(op_token),
                          params={"keyword": "TORDER"})
        items = resp.json()["items"]
        check("搜索 TORDER 收藏置顶",
              items[0]["table_code"] == "TORDER"
              and items[0]["is_favorite"] is True, str(items))

        # viewer 无权收藏
        resp = client.post("/api/dict/favorites", headers=auth(vw_token),
                           json={"table_id": torder_id, "table_code": "TORDER",
                                 "table_name": "订单主表"})
        check("viewer 收藏 403", resp.status_code == 403, resp.text)

        # 取消收藏
        resp = client.delete(f"/api/dict/favorites/{torder_id}", headers=auth(op_token))
        check("取消收藏 204", resp.status_code == 204, resp.text)
        resp = client.get("/api/dict/favorites", headers=auth(op_token))
        check("取消收藏后列表为空", resp.status_code == 200 and resp.json() == [], resp.text)

        # 取消未收藏 404
        resp = client.delete(f"/api/dict/favorites/{torder_id}", headers=auth(op_token))
        check("取消未收藏 404", resp.status_code == 404, resp.text)

    print(f"\n{'全部通过' if not failures else f'{len(failures)} 项失败'}")
    for f in failures:
        print(f"  - {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
