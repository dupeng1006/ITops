# -*- coding: utf-8 -*-
"""
数据源管理 API 冒烟测试（纯脚本，fastapi.testclient + 临时目录 + SQLite 样本库）

覆盖链路：
    1. admin 登录改密 → 创建 operator / viewer（各自改密）
    2. 数据源 CRUD：新增（sqlite 测试源）→ 列表/重复名 400/修改/404；
       密码密文落库断言（非明文、Fernet 可解）、接口读取永不返回明文（掩码）
    3. 密码维护：留空不修改（密文不变）、设置新密码（密文变化、可解密为新值）
    4. 测试连接：sqlite 成功；MySQL 不存在主机 → success=false + 中文友好报错
    5. 查询模板 CRUD：新增/修改/删除/404/重复名 400/非法模块 400/数据源不存在 400
    6. SQL Guard 保存时拦截：INSERT/DELETE/多语句/SELECT INTO 全部 400（中文提示）
    7. preview：参数绑定 + 字段映射 + 前 50 行结构；缺必填参数 400；写 SQL 模板
       即使库中被篡改（绕过接口直接改库）执行前二次校验也拦截
    8. 引用约束：数据源被模板引用时删除 400
    9. 权限边界：operator 查询/测试连接/preview 200、写操作 403；
       viewer 查询 403；未登录 401
    10. 审计留痕：ds_create/ds_update/ds_delete/ds_test/tpl_create/tpl_update/
        tpl_delete/tpl_preview 全部落库，且审计不含密码明文

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\api\\test_api_datasource.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

# =============================================================================
# 环境准备：导入 app 之前注入测试配置（临时数据/归档目录、测试密钥）
# =============================================================================

SERVER_ROOT = Path(__file__).resolve().parents[2]
TMP_ROOT = Path(tempfile.mkdtemp(prefix="o32ops_ds_smoke_"))

os.environ["O32OPS_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["O32OPS_ARCHIVE_DIR"] = str(TMP_ROOT / "archive")
os.environ["O32OPS_DB_PATH"] = str(TMP_ROOT / "data" / "o32ops.db")
os.environ["O32OPS_SECRET_KEY"] = "datasource-smoke-test-secret-key-do-not-use-in-prod"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

# Windows 控制台中文/符号输出兼容
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from fastapi.testclient import TestClient  # noqa: E402

from app.core.crypto import decrypt_secret  # noqa: E402
from app.main import app  # noqa: E402

failures: list = []

SAMPLE_DB = TMP_ROOT / "sample_biz.db"
DS_PASSWORD = "ReadOnly@2026"


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


def make_sample_db() -> None:
    """构造样本业务库：fund_asset(CODE, NAME, BIZ_DATE, AMOUNT) 60 行"""
    conn = sqlite3.connect(SAMPLE_DB)
    conn.execute("CREATE TABLE fund_asset (CODE TEXT, NAME TEXT, BIZ_DATE TEXT, AMOUNT REAL)")
    conn.executemany(
        "INSERT INTO fund_asset VALUES (?, ?, ?, ?)",
        [(f"C{i:04d}", f"产品{i}", "20260701" if i % 2 == 0 else "20260702", 1000.0 + i)
         for i in range(1, 61)],
    )
    conn.commit()
    conn.close()


def main() -> int:
    make_sample_db()
    with TestClient(app) as client:
        # ------------------------------------------------------------------
        # 1. 账号准备
        # ------------------------------------------------------------------
        print("--- 1. 账号准备 ---")
        admin_token = login_and_change(client, "admin", "Admin@123", "Admin@Smoke1")
        for uname, role in (("ds_operator", "operator"), ("ds_viewer", "viewer")):
            resp = client.post("/api/admin/users",
                               json={"username": uname, "password": "Init@12345", "role": role},
                               headers=auth(admin_token))
            check(f"创建 {role} 用户返回200", resp.status_code == 200, resp.text)
        op_token = login_and_change(client, "ds_operator", "Init@12345", "Oper@12345")
        viewer_token = login_and_change(client, "ds_viewer", "Init@12345", "View@12345")

        # ------------------------------------------------------------------
        # 2. 数据源 CRUD 与密码安全
        # ------------------------------------------------------------------
        print("--- 2. 数据源 CRUD 与密码安全 ---")
        resp = client.post("/api/datasources", json={
            "name": "测试源-SQLite", "db_type": "sqlite",
            "db_name": str(SAMPLE_DB), "username": "reader", "password": DS_PASSWORD,
        }, headers=auth(admin_token))
        check("新增数据源返回200", resp.status_code == 200, resp.text)
        ds_id = resp.json()["id"]
        check("返回密码为掩码", resp.json()["password"] == "********", resp.text)

        # 密文落库断言
        conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
        row = conn.execute(
            "SELECT password_enc FROM ds_connection WHERE id=?", (ds_id,)).fetchone()
        check("库中密码非明文", row is not None and DS_PASSWORD not in row[0], str(row))
        check("密文可解密为原密码", decrypt_secret(row[0]) == DS_PASSWORD)
        conn.close()

        resp = client.get("/api/datasources", headers=auth(admin_token))
        check("数据源列表返回200", resp.status_code == 200, resp.text)
        check("列表密码掩码且无密文泄露",
              all(d["password"] == "********" for d in resp.json())
              and DS_PASSWORD not in resp.text, resp.text[:300])

        resp = client.post("/api/datasources", json={
            "name": "测试源-SQLite", "db_type": "sqlite",
            "db_name": str(SAMPLE_DB), "username": "reader", "password": "x",
        }, headers=auth(admin_token))
        check("重复数据源名 400", resp.status_code == 400, resp.text)

        resp = client.post("/api/datasources", json={
            "name": "坏源", "db_type": "oracle", "host": "h", "username": "u", "password": "x",
        }, headers=auth(admin_token))
        check("Oracle 缺服务名/SID 400（中文提示）",
              resp.status_code == 400 and "服务名" in resp.text and "SID" in resp.text, resp.text)

        resp = client.post("/api/datasources", json={
            "name": "坏源2", "db_type": "db2", "host": "h", "username": "u", "password": "x",
        }, headers=auth(admin_token))
        check("非法数据源类型 400", resp.status_code == 400, resp.text)

        # 修改：留空密码不修改
        resp = client.put(f"/api/datasources/{ds_id}", json={
            "host": "placeholder-host", "password": ""}, headers=auth(admin_token))
        check("修改数据源返回200", resp.status_code == 200, resp.text)
        conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
        row2 = conn.execute(
            "SELECT password_enc FROM ds_connection WHERE id=?", (ds_id,)).fetchone()
        conn.close()
        check("留空密码密文不变", row2[0] == row[0])

        # 修改：设置新密码
        resp = client.put(f"/api/datasources/{ds_id}", json={
            "password": "NewPass@456"}, headers=auth(admin_token))
        check("更新密码返回200", resp.status_code == 200, resp.text)
        conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
        row3 = conn.execute(
            "SELECT password_enc FROM ds_connection WHERE id=?", (ds_id,)).fetchone()
        conn.close()
        check("新密码密文已变化且可解密", row3[0] != row[0] and decrypt_secret(row3[0]) == "NewPass@456")
        # 改回便于记忆
        client.put(f"/api/datasources/{ds_id}", json={"password": DS_PASSWORD},
                   headers=auth(admin_token))

        resp = client.get("/api/datasources/99999/test", headers=auth(admin_token))
        check("测试不存在数据源 404", resp.status_code == 404, resp.text)
        # 注意：/test 走 POST；上面 GET 若路由未注册返回 405 也算拦截，改用 POST 复核
        resp = client.post("/api/datasources/99999/test", headers=auth(admin_token))
        check("POST 测试不存在数据源 404", resp.status_code == 404, resp.text)

        # ------------------------------------------------------------------
        # 3. 测试连接
        # ------------------------------------------------------------------
        print("--- 3. 测试连接 ---")
        resp = client.post(f"/api/datasources/{ds_id}/test", headers=auth(admin_token))
        check("SQLite 测试连接成功", resp.status_code == 200 and resp.json()["success"] is True,
              resp.text)
        check("成功消息为中文", "连接成功" in resp.json()["message"], resp.text)

        resp = client.post("/api/datasources", json={
            "name": "不存在主机", "db_type": "mysql", "host": "nonexistent-o32.invalid",
            "port": 3306, "db_name": "d", "username": "u", "password": "p",
        }, headers=auth(admin_token))
        bad_ds_id = resp.json()["id"]
        resp = client.post(f"/api/datasources/{bad_ds_id}/test", headers=auth(admin_token))
        body = resp.json()
        check("不存在主机测试连接 success=false", resp.status_code == 200 and body["success"] is False,
              resp.text)
        check("失败消息中文友好（无法解析/无法连接）",
              ("无法解析" in body["message"] or "无法连接" in body["message"]
               or "超时" in body["message"]),
              body["message"])
        client.delete(f"/api/datasources/{bad_ds_id}", headers=auth(admin_token))

        # ------------------------------------------------------------------
        # 4. 查询模板 CRUD 与 SQL Guard 保存校验
        # ------------------------------------------------------------------
        print("--- 4. 查询模板 CRUD 与 SQL Guard ---")
        tpl_body = {
            "name": "基金资产查询", "module": "m1_fund", "ds_id": ds_id,
            "sql_text": "SELECT CODE, NAME, BIZ_DATE, AMOUNT FROM fund_asset WHERE BIZ_DATE = :biz_date",
            "column_map": {"CODE": "product_code", "NAME": "product_name", "BIZ_DATE": "biz_date"},
            "params_def": {"biz_date": {"type": "date", "required": True, "label": "业务日期"}},
        }
        resp = client.post("/api/query-templates", json=tpl_body, headers=auth(admin_token))
        check("新增模板返回200", resp.status_code == 200, resp.text)
        tpl_id = resp.json()["id"]
        check("模板返回含数据源名", resp.json()["ds_name"] == "测试源-SQLite", resp.text)

        resp = client.post("/api/query-templates", json=tpl_body, headers=auth(admin_token))
        check("重复模板名 400", resp.status_code == 400, resp.text)

        for bad_sql, label in (
            ("INSERT INTO fund_asset VALUES ('X','Y','20260701',1)", "INSERT"),
            ("DELETE FROM fund_asset", "DELETE"),
            ("SELECT * FROM fund_asset; DROP TABLE fund_asset", "多语句"),
            ("SELECT * INTO bak FROM fund_asset", "SELECT INTO"),
            ("SELECT * FROM fund_asset FOR UPDATE", "FOR UPDATE"),
        ):
            evil = dict(tpl_body, name=f"恶意-{label}", sql_text=bad_sql)
            resp = client.post("/api/query-templates", json=evil, headers=auth(admin_token))
            check(f"SQL Guard 保存拦截 {label} → 400",
                  resp.status_code == 400 and "安全" in resp.text, resp.text[:200])

        resp = client.post("/api/query-templates", json=dict(tpl_body, name="坏模块", module="m9_x"),
                           headers=auth(admin_token))
        check("非法模块 400", resp.status_code == 400, resp.text)
        resp = client.post("/api/query-templates", json=dict(tpl_body, name="坏数据源", ds_id=99999),
                           headers=auth(admin_token))
        check("数据源不存在 400", resp.status_code == 400, resp.text)

        resp = client.put(f"/api/query-templates/{tpl_id}",
                          json={"name": "基金资产查询-V2",
                                "sql_text": "SELECT CODE, NAME, BIZ_DATE, AMOUNT FROM fund_asset WHERE BIZ_DATE = :biz_date ORDER BY CODE"},
                          headers=auth(admin_token))
        check("修改模板返回200", resp.status_code == 200, resp.text)
        tpl_id_check = resp.json()["name"] == "基金资产查询-V2"
        check("模板名已更新", tpl_id_check, resp.text)

        resp = client.get("/api/query-templates", headers=auth(admin_token))
        check("模板列表返回200", resp.status_code == 200 and len(resp.json()) == 1, resp.text)
        resp = client.get("/api/query-templates?module=m2_valuation", headers=auth(admin_token))
        check("模板按模块过滤", resp.status_code == 200 and len(resp.json()) == 0, resp.text)

        # ------------------------------------------------------------------
        # 5. preview（参数绑定 + 字段映射 + 行数结构）
        # ------------------------------------------------------------------
        print("--- 5. 模板预览 ---")
        resp = client.post(f"/api/query-templates/{tpl_id}/preview",
                           json={"params": {"biz_date": "20260701"}}, headers=auth(admin_token))
        check("预览返回200", resp.status_code == 200, resp.text)
        body = resp.json()
        check("预览 30 行（偶数行 biz_date=20260701）", body["rows_returned"] == 30,
              str(body["rows_returned"]))
        check("预览列名已按映射重命名",
              body["columns"] == ["product_code", "product_name", "biz_date", "AMOUNT"],
              str(body["columns"]))
        check("预览行内容与样本一致",
              body["rows"][0]["product_code"] == "C0002"
              and body["rows"][0]["biz_date"] == "20260701",
              str(body["rows"][:1]))
        check("protections 含白名单/只读/行数",
              any("白名单" in p for p in body["protections"])
              and any("行数" in p for p in body["protections"]),
              str(body["protections"]))

        resp = client.post(f"/api/query-templates/{tpl_id}/preview",
                           json={"params": {}}, headers=auth(admin_token))
        check("缺必填参数 400 中文提示", resp.status_code == 400 and "业务日期" in resp.text,
              resp.text)
        resp = client.post(f"/api/query-templates/{tpl_id}/preview",
                           json={"params": {"biz_date": "2026/07/01"}}, headers=auth(admin_token))
        check("日期格式非法 400", resp.status_code == 400 and "格式" in resp.text, resp.text)
        resp = client.post("/api/query-templates/99999/preview",
                           json={"params": {"biz_date": "20260701"}}, headers=auth(admin_token))
        check("预览不存在模板 404", resp.status_code == 404, resp.text)

        # 库内篡改（绕过接口把 SQL 改为写操作）→ 执行前二次校验拦截
        conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
        conn.execute("UPDATE ds_query_template SET sql_text='DELETE FROM fund_asset' WHERE id=?",
                     (tpl_id,))
        conn.commit()
        conn.close()
        resp = client.post(f"/api/query-templates/{tpl_id}/preview",
                           json={"params": {"biz_date": "20260701"}}, headers=auth(admin_token))
        check("库内篡改写 SQL 执行前二次校验 400", resp.status_code == 400 and "安全" in resp.text,
              resp.text[:200])
        # 恢复原 SQL
        conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
        conn.execute("UPDATE ds_query_template SET sql_text=? WHERE id=?",
                     ("SELECT CODE, NAME, BIZ_DATE, AMOUNT FROM fund_asset WHERE BIZ_DATE = :biz_date ORDER BY CODE", tpl_id))
        conn.commit()
        conn.close()

        # ------------------------------------------------------------------
        # 6. 引用约束与删除
        # ------------------------------------------------------------------
        print("--- 6. 引用约束与删除 ---")
        resp = client.delete(f"/api/datasources/{ds_id}", headers=auth(admin_token))
        check("被引用数据源删除 400", resp.status_code == 400 and "引用" in resp.text, resp.text)
        resp = client.delete("/api/query-templates/99999", headers=auth(admin_token))
        check("删除不存在模板 404", resp.status_code == 404, resp.text)

        # ------------------------------------------------------------------
        # 7. 权限边界
        # ------------------------------------------------------------------
        print("--- 7. 权限边界 ---")
        resp = client.get("/api/datasources", headers=auth(op_token))
        check("operator 可查数据源列表", resp.status_code == 200, resp.text)
        resp = client.get("/api/query-templates", headers=auth(op_token))
        check("operator 可查模板列表", resp.status_code == 200, resp.text)
        resp = client.post(f"/api/datasources/{ds_id}/test", headers=auth(op_token))
        check("operator 可测试连接", resp.status_code == 200, resp.text)
        resp = client.post(f"/api/query-templates/{tpl_id}/preview",
                           json={"params": {"biz_date": "20260701"}}, headers=auth(op_token))
        check("operator 可预览", resp.status_code == 200, resp.text)
        resp = client.post("/api/datasources", json={
            "name": "op越权", "db_type": "sqlite", "db_name": "x",
            "username": "u", "password": "p"}, headers=auth(op_token))
        check("operator 新增数据源 403", resp.status_code == 403, resp.text)
        resp = client.put(f"/api/datasources/{ds_id}", json={"host": "h"}, headers=auth(op_token))
        check("operator 修改数据源 403", resp.status_code == 403, resp.text)
        resp = client.delete(f"/api/query-templates/{tpl_id}", headers=auth(op_token))
        check("operator 删除模板 403", resp.status_code == 403, resp.text)
        resp = client.post("/api/query-templates", json=tpl_body, headers=auth(op_token))
        check("operator 新增模板 403", resp.status_code == 403, resp.text)

        resp = client.get("/api/datasources", headers=auth(viewer_token))
        check("viewer 查数据源 403", resp.status_code == 403, resp.text)
        resp = client.get("/api/query-templates", headers=auth(viewer_token))
        check("viewer 查模板 403", resp.status_code == 403, resp.text)
        resp = client.get("/api/datasources")
        check("未登录访问 401", resp.status_code == 401, resp.text)

        # ------------------------------------------------------------------
        # 8. 删除模板与数据源（收尾，供审计断言）
        # ------------------------------------------------------------------
        print("--- 8. 删除收尾 ---")
        resp = client.delete(f"/api/query-templates/{tpl_id}", headers=auth(admin_token))
        check("删除模板返回200", resp.status_code == 200, resp.text)
        resp = client.delete(f"/api/datasources/{ds_id}", headers=auth(admin_token))
        check("删除数据源返回200", resp.status_code == 200, resp.text)
        resp = client.delete(f"/api/datasources/{ds_id}", headers=auth(admin_token))
        check("重复删除数据源 404", resp.status_code == 404, resp.text)

    # ----------------------------------------------------------------------
    # 9. 审计日志落库核验（直接查库）
    # ----------------------------------------------------------------------
    print("--- 9. 审计日志 ---")
    conn = sqlite3.connect(os.environ["O32OPS_DB_PATH"])
    rows = dict(conn.execute(
        "SELECT action, COUNT(*) FROM sys_audit_log GROUP BY action").fetchall())
    for action in ("ds_create", "ds_update", "ds_delete", "ds_test",
                   "tpl_create", "tpl_update", "tpl_delete", "tpl_preview"):
        check(f"审计动作已记录: {action}", rows.get(action, 0) > 0, str(rows))
    all_detail = " ".join(
        r[0] or "" for r in conn.execute("SELECT detail FROM sys_audit_log").fetchall())
    check("审计不含密码明文", DS_PASSWORD not in all_detail and "NewPass@456" not in all_detail)
    detail = conn.execute(
        "SELECT detail FROM sys_audit_log WHERE action='ds_update' AND detail LIKE '%密码已更新%'").fetchone()
    check("密码更新审计留痕（不含内容）", detail is not None)
    conn.close()

    print("=" * 70)
    if failures:
        print(f"数据源管理冒烟测试失败，共 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("数据源管理 API 冒烟测试全部通过 ✅")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        sys.exit(2)
