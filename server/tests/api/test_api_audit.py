# -*- coding: utf-8 -*-
"""
系统日志查询（审计读取侧）API 冒烟测试（纯脚本，fastapi.testclient + 临时目录）

覆盖链路：
    1. 未登录 401（/api/audit-logs、/api/audit-logs/menus）
    2. 权限口径：仅 admin 可查（operator / viewer 均 403）
    3. 基础查询：login / change_password / user_create 留痕可读，
       响应含 mac / menu / display_name / department 字段键
    4. 过滤：action 精确 / username 模糊（编号 + 姓名双口径）/ menu 模糊 /
       ip 模糊（ip 与 mac 同口径）/ 日期区间
    5. 分页：page / page_size 语义正确、total 稳定、页间不重叠
    6. 操作菜单去重清单（/menus）

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\api\\test_api_audit.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-23
"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# =============================================================================
# 环境准备：导入 app 之前注入测试配置（临时数据/归档目录、测试密钥）
# =============================================================================

SERVER_ROOT = Path(__file__).resolve().parents[2]
TMP_ROOT = Path(tempfile.mkdtemp(prefix="o32ops_audit_smoke_"))

os.environ["O32OPS_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["O32OPS_ARCHIVE_DIR"] = str(TMP_ROOT / "archive")
os.environ["O32OPS_DB_PATH"] = str(TMP_ROOT / "data" / "o32ops.db")
os.environ["O32OPS_SECRET_KEY"] = "audit-smoke-test-secret-key-do-not-use-in-prod"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

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


def query(client: TestClient, token: str, params: dict) -> dict:
    resp = client.get("/api/audit-logs", params=params, headers=auth(token))
    check(f"查询审计日志 {params} 返回200", resp.status_code == 200, resp.text)
    return resp.json()


def main() -> int:
    print("=" * 70)
    print("系统日志查询（审计读取侧）API 冒烟测试")
    print(f"临时目录: {TMP_ROOT}")
    print("=" * 70)

    today = datetime.now().strftime("%Y-%m-%d")

    with TestClient(app) as client:
        # ------------------------------------------------------------------
        # 1. 未登录 401
        # ------------------------------------------------------------------
        print("--- 1. 未登录 401 ---")
        resp = client.get("/api/audit-logs")
        check("未登录查询审计日志返回401", resp.status_code == 401, resp.text)
        resp = client.get("/api/audit-logs/menus")
        check("未登录查询菜单清单返回401", resp.status_code == 401, resp.text)

        # ------------------------------------------------------------------
        # 2. 用户准备（制造 login / change_password / user_create 留痕）
        # ------------------------------------------------------------------
        print("--- 2. 用户准备（制造审计留痕） ---")
        admin_token = login_and_change(client, "admin", "Admin@123", "Admin@2026New")
        resp = client.post("/api/admin/users",
                           json={"username": "op01", "password": "Op@123456",
                                 "role": "operator"},
                           headers=auth(admin_token))
        check("创建 operator 返回200", resp.status_code == 200, resp.text)
        resp = client.post("/api/admin/users",
                           json={"username": "vw01", "password": "Vw@123456",
                                 "role": "viewer", "display_name": "张审计",
                                 "department": "技术部"},
                           headers=auth(admin_token))
        check("创建 viewer（含姓名/部门）返回200", resp.status_code == 200, resp.text)
        viewer_token = login_and_change(client, "vw01", "Vw@123456", "Vw@2026New")
        op_token = login_and_change(client, "op01", "Op@123456", "Op@2026New")

        # ------------------------------------------------------------------
        # 3. 权限口径：仅 admin 可查
        # ------------------------------------------------------------------
        print("--- 3. 权限口径 ---")
        resp = client.get("/api/audit-logs", headers=auth(viewer_token))
        check("viewer 查询审计日志返回403", resp.status_code == 403, resp.text)
        resp = client.get("/api/audit-logs", headers=auth(op_token))
        check("operator 查询审计日志返回403", resp.status_code == 403, resp.text)
        resp = client.get("/api/audit-logs/menus", headers=auth(viewer_token))
        check("viewer 查询菜单清单返回403", resp.status_code == 403, resp.text)

        # ------------------------------------------------------------------
        # 4. 基础查询与字段完整性
        # ------------------------------------------------------------------
        print("--- 4. 基础查询与字段完整性 ---")
        data = query(client, admin_token, {})
        # 留痕：admin login+改密、user_create×2、vw01/op01 login+改密 = 8 条
        check("审计日志总数 >= 8", data["total"] >= 8, f"total={data['total']}")
        check("默认分页 page=1/page_size=20",
              data["page"] == 1 and data["page_size"] == 20, str(data))
        item = data["items"][0]
        expected_keys = {"id", "time", "username", "display_name", "department",
                         "ip", "mac", "menu", "action", "detail"}
        check("审计条目字段键齐全（含 mac/menu/display_name/department）",
              expected_keys <= set(item.keys()), str(sorted(item.keys())))
        check("条目按 id 倒序（最新在前）",
              data["items"][0]["id"] > data["items"][-1]["id"],
              f"first={data['items'][0]['id']} last={data['items'][-1]['id']}")
        check("TestClient 来源 ip 已记录",
              all(i["ip"] for i in data["items"]),
              str([i["ip"] for i in data["items"]]))

        # ------------------------------------------------------------------
        # 5. 过滤
        # ------------------------------------------------------------------
        print("--- 5. 过滤 ---")
        data = query(client, admin_token, {"action": "login"})
        check("action=login 精确过滤 total>=3",
              data["total"] >= 3, f"total={data['total']}")
        check("action=login 过滤结果 action 全为 login",
              all(i["action"] == "login" for i in data["items"]))

        data = query(client, admin_token, {"username": "vw01"})
        check("username=vw01 编号模糊过滤 total>=2",
              data["total"] >= 2, f"total={data['total']}")
        check("username=vw01 过滤结果 username 全为 vw01",
              all(i["username"] == "vw01" for i in data["items"]))

        data = query(client, admin_token, {"username": "张审计"})
        check("username=张审计 姓名模糊过滤可命中",
              data["total"] >= 1, f"total={data['total']}")
        check("姓名过滤命中行 display_name/department 正确",
              all(i["display_name"] == "张审计" and i["department"] == "技术部"
                  for i in data["items"]),
              str([(i["display_name"], i["department"]) for i in data["items"]]))

        data = query(client, admin_token, {"menu": "登录页"})
        check("menu=登录页 模糊过滤 total>=4（login+change_password）",
              data["total"] >= 4, f"total={data['total']}")
        check("menu=登录页 过滤结果 menu 全含'登录页'",
              all("登录页" in (i["menu"] or "") for i in data["items"]))

        data = query(client, admin_token, {"action": "user_create"})
        check("action=user_create total==2",
              data["total"] == 2, f"total={data['total']}")
        check("user_create 留痕 menu 为'系统管理 · 用户维护'",
              all(i["menu"] == "系统管理 · 用户维护" for i in data["items"]),
              str([i["menu"] for i in data["items"]]))

        data = query(client, admin_token, {"ip": "test"})
        check("ip 模糊过滤（testclient 命中）total>=1",
              data["total"] >= 1, f"total={data['total']}")

        data = query(client, admin_token, {"date_from": today, "date_to": today})
        check("日期区间=今天 total>=1", data["total"] >= 1, f"total={data['total']}")
        data = query(client, admin_token, {"date_from": "2999-01-01"})
        check("date_from=未来 total==0", data["total"] == 0, f"total={data['total']}")
        data = query(client, admin_token, {"date_to": "2000-01-01"})
        check("date_to=过去 total==0", data["total"] == 0, f"total={data['total']}")

        # ------------------------------------------------------------------
        # 6. 分页
        # ------------------------------------------------------------------
        print("--- 6. 分页 ---")
        full = query(client, admin_token, {"page_size": 100})
        p1 = query(client, admin_token, {"page_size": 3, "page": 1})
        p2 = query(client, admin_token, {"page_size": 3, "page": 2})
        check("page_size=3 第1页返回3条", len(p1["items"]) == 3, str(len(p1["items"])))
        check("page_size=3 第2页返回3条", len(p2["items"]) == 3, str(len(p2["items"])))
        check("分页 total 与全量一致",
              p1["total"] == full["total"] == p2["total"],
              f"p1={p1['total']} p2={p2['total']} full={full['total']}")
        ids1 = {i["id"] for i in p1["items"]}
        ids2 = {i["id"] for i in p2["items"]}
        check("页间 id 不重叠", not (ids1 & ids2), str(ids1 & ids2))
        resp = client.get("/api/audit-logs", params={"page_size": 999, "page": 1},
                          headers=auth(admin_token))
        check("page_size 超上限被参数校验拦截（422）",
              resp.status_code == 422, resp.text)

        # ------------------------------------------------------------------
        # 7. 菜单去重清单
        # ------------------------------------------------------------------
        print("--- 7. 菜单去重清单 ---")
        resp = client.get("/api/audit-logs/menus", headers=auth(admin_token))
        check("菜单清单返回200", resp.status_code == 200, resp.text)
        menus = resp.json()
        check("菜单清单含'登录页'与'系统管理 · 用户维护'",
              "登录页" in menus and "系统管理 · 用户维护" in menus, str(menus))

    print("=" * 70)
    if failures:
        print(f"共 {len(failures)} 项失败：")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
