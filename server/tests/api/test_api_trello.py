# -*- coding: utf-8 -*-
"""
Trello 集成 API 冒烟测试（纯脚本，fastapi.testclient + 临时目录）

覆盖链路：
    1. 未登录 401（configs / boards / cards）
    2. 权限口径：配置 CRUD/test/sync 仅 admin（viewer 403）；boards/cards 查询全角色 200
    3. 配置 CRUD：新增（掩码回显）/ 重名 400 / 列表 / 修改（凭据留空不修改）/ 删除 / 404
    4. 凭据加密断言：api_key 与 token_enc 落库均非明文，且可解密还原（v7 口径）
    5. /test 与 /sync 全程使用 Fake TrelloClient（monkeypatch，严禁外网）：
       同步落库 trello_board / trello_card，closed board 与未加入 board 的卡片被过滤
    6. boards / cards 查询：status / search 过滤、非法 status 400
    7. updated_by_name 冗余字段：随列表/单条响应输出（admin 无姓名 → 回退编号）

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\api\\test_api_trello.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-23
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
TMP_ROOT = Path(tempfile.mkdtemp(prefix="o32ops_trello_smoke_"))

os.environ["O32OPS_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["O32OPS_ARCHIVE_DIR"] = str(TMP_ROOT / "archive")
os.environ["O32OPS_DB_PATH"] = str(TMP_ROOT / "data" / "o32ops.db")
os.environ["O32OPS_SECRET_KEY"] = "trello-smoke-test-secret-key-do-not-use-in-prod"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

DB_PATH = Path(os.environ["O32OPS_DB_PATH"])

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


def db_rows(sql: str) -> list:
    conn = sqlite3.connect(str(DB_PATH))
    rows = conn.execute(sql).fetchall()
    conn.close()
    return rows


# =============================================================================
# Fake TrelloClient（严禁外网：patch 两处引用点）
# =============================================================================

class FakeTrelloClient:
    """替代 TrelloClient 的内存假客户端（记录构造入参以便断言解密口径）"""

    instances: list = []

    def __init__(self, api_key: str, token: str, delay: float = 0.0):
        self.api_key = api_key
        self.token = token
        FakeTrelloClient.instances.append(self)

    def get_member(self) -> dict:
        return {"id": "me1", "fullName": "测试用户", "username": "tester"}

    def get_my_boards(self) -> list:
        return [
            {"id": "b1", "name": "运维看板", "url": "https://trello.com/b/b1",
             "closed": False},
            {"id": "b2", "name": "已归档看板", "url": "https://trello.com/b/b2",
             "closed": True},
        ]

    def get_board_lists(self, board_id: str) -> list:
        return [{"id": "l1", "name": "待办"}, {"id": "l2", "name": "进行中"}]

    def get_my_cards(self, limit: int = 1000) -> list:
        return [
            {"id": "c1", "idBoard": "b1", "idList": "l1", "name": "修复核对任务",
             "desc": "M1 差异排查", "labels": [{"name": "Done"}],
             "due": None, "dueComplete": False, "idMembers": ["me1"],
             "url": "https://trello.com/c/c1", "pos": 1.0},
            # 未加入的 board：应被同步过滤
            {"id": "c2", "idBoard": "bX", "idList": "l9", "name": "外部卡片",
             "desc": "", "labels": [], "due": None, "dueComplete": False,
             "idMembers": ["me1"], "url": "https://trello.com/c/c2", "pos": 2.0},
        ]


def patch_trello_client() -> None:
    import app.api.routes_trello as routes_trello_mod
    import app.services.trello_service as trello_service_mod
    routes_trello_mod.TrelloClient = FakeTrelloClient
    trello_service_mod.TrelloClient = FakeTrelloClient


def main() -> int:
    print("=" * 70)
    print("Trello 集成 API 冒烟测试")
    print(f"临时目录: {TMP_ROOT}")
    print("=" * 70)

    with TestClient(app) as client:
        # ------------------------------------------------------------------
        # 1. 未登录 401
        # ------------------------------------------------------------------
        print("--- 1. 未登录 401 ---")
        for path in ("/api/trello/configs", "/api/trello/boards", "/api/trello/cards"):
            resp = client.get(path)
            check(f"未登录 GET {path} 返回401", resp.status_code == 401, resp.text)

        # ------------------------------------------------------------------
        # 2. 用户准备
        # ------------------------------------------------------------------
        print("--- 2. 用户准备 ---")
        admin_token = login_and_change(client, "admin", "Admin@123", "Admin@2026New")
        resp = client.post("/api/admin/users",
                           json={"username": "vw01", "password": "Vw@123456",
                                 "role": "viewer", "display_name": "张看板"},
                           headers=auth(admin_token))
        check("创建 viewer 返回200", resp.status_code == 200, resp.text)
        viewer_token = login_and_change(client, "vw01", "Vw@123456", "Vw@2026New")

        # ------------------------------------------------------------------
        # 3. 权限口径（viewer 写操作 403）
        # ------------------------------------------------------------------
        print("--- 3. 权限口径 ---")
        resp = client.get("/api/trello/configs", headers=auth(viewer_token))
        check("viewer 查询配置列表返回403", resp.status_code == 403, resp.text)
        resp = client.post("/api/trello/configs",
                           json={"name": "x", "api_key": "k", "token": "t"},
                           headers=auth(viewer_token))
        check("viewer 新增配置返回403", resp.status_code == 403, resp.text)
        resp = client.post("/api/trello/configs/1/sync", headers=auth(viewer_token))
        check("viewer 手动同步返回403", resp.status_code == 403, resp.text)

        # ------------------------------------------------------------------
        # 4. 新增配置（掩码回显 + 落库加密断言）
        # ------------------------------------------------------------------
        print("--- 4. 新增配置与凭据加密 ---")
        resp = client.post("/api/trello/configs",
                           json={"name": "主看板", "api_key": "plain-key-abc123",
                                 "token": "tok-xyz-789", "enabled": True,
                                 "sync_min": 5},
                           headers=auth(admin_token))
        check("新增配置返回200", resp.status_code == 200, resp.text)
        cfg = resp.json()
        cfg_id = cfg["id"]
        check("响应 api_key 为掩码", cfg["api_key"] == "********", cfg["api_key"])
        check("响应 token 为掩码", cfg["token"] == "********", cfg["token"])
        check("响应 updated_by 为 admin", cfg["updated_by"] == "admin", str(cfg))
        check("响应 updated_by_name 回退编号（admin 无姓名）",
              cfg.get("updated_by_name") == "admin", str(cfg.get("updated_by_name")))

        rows = db_rows("SELECT api_key, token_enc FROM trello_config"
                       f" WHERE id={cfg_id}")
        check("落库 api_key 非明文", rows and rows[0][0] != "plain-key-abc123",
              str(rows))
        check("落库 token_enc 非明文", rows and rows[0][1] != "tok-xyz-789",
              str(rows))
        from app.core.crypto import decrypt_secret
        check("落库 api_key 可解密还原",
              rows and decrypt_secret(rows[0][0]) == "plain-key-abc123")
        check("落库 token_enc 可解密还原",
              rows and decrypt_secret(rows[0][1]) == "tok-xyz-789")
        cipher_key_v1 = rows[0][0]
        cipher_token_v1 = rows[0][1]

        resp = client.post("/api/trello/configs",
                           json={"name": "主看板", "api_key": "k2", "token": "t2"},
                           headers=auth(admin_token))
        check("重名配置返回400", resp.status_code == 400, resp.text)

        # ------------------------------------------------------------------
        # 5. /test 与 /sync（Fake TrelloClient，严禁外网）
        # ------------------------------------------------------------------
        print("--- 5. 测试连接与手动同步（mock） ---")
        patch_trello_client()

        resp = client.post(f"/api/trello/configs/{cfg_id}/test",
                           headers=auth(admin_token))
        check("测试连接返回200", resp.status_code == 200, resp.text)
        body = resp.json()
        check("测试连接成功且含成员姓名",
              body["success"] is True and "测试用户" in body["message"],
              str(body))
        check("FakeClient 收到的 api_key 为解密后明文",
              FakeTrelloClient.instances
              and FakeTrelloClient.instances[-1].api_key == "plain-key-abc123",
              str(FakeTrelloClient.instances[-1].api_key if FakeTrelloClient.instances else None))
        check("FakeClient 收到的 token 为解密后明文",
              FakeTrelloClient.instances[-1].token == "tok-xyz-789")

        resp = client.post(f"/api/trello/configs/{cfg_id}/sync",
                           headers=auth(admin_token))
        check("手动同步返回200", resp.status_code == 200, resp.text)
        body = resp.json()
        check("同步成功：1 board（closed 被过滤）、1 card（外部 board 被过滤）",
              body["success"] is True and body["boards"] == 1 and body["cards"] == 1,
              str(body))

        boards = db_rows(f"SELECT board_id, name, is_closed FROM trello_board"
                         f" WHERE config_id={cfg_id}")
        check("trello_board 落库 1 行（b1/运维看板/未归档）",
              boards == [("b1", "运维看板", 0)], str(boards))
        cards = db_rows(f"SELECT card_id, board_name, list_name, status, name"
                        f" FROM trello_card WHERE config_id={cfg_id}")
        check("trello_card 落库 1 行（list_name/status 映射正确）",
              cards == [("c1", "运维看板", "待办", "Done", "修复核对任务")],
              str(cards))
        rows = db_rows(f"SELECT last_sync_status FROM trello_config WHERE id={cfg_id}")
        check("配置 last_sync_status=success",
              rows and rows[0][0] == "success", str(rows))

        # ------------------------------------------------------------------
        # 6. boards / cards 查询（全角色）
        # ------------------------------------------------------------------
        print("--- 6. boards / cards 查询 ---")
        resp = client.get("/api/trello/boards", headers=auth(viewer_token))
        check("viewer 查询 boards 返回200 且 1 条",
              resp.status_code == 200 and len(resp.json()) == 1, resp.text)
        resp = client.get("/api/trello/cards", headers=auth(viewer_token))
        check("viewer 查询 cards 返回200 且 total==1",
              resp.status_code == 200 and resp.json()["total"] == 1, resp.text)
        resp = client.get("/api/trello/cards", params={"status": "Done"},
                          headers=auth(viewer_token))
        check("cards status=Done 过滤 total==1",
              resp.json()["total"] == 1, resp.text)
        resp = client.get("/api/trello/cards", params={"status": "Ongoing"},
                          headers=auth(viewer_token))
        check("cards status=Ongoing 过滤 total==0",
              resp.json()["total"] == 0, resp.text)
        resp = client.get("/api/trello/cards", params={"status": "不存在的状态"},
                          headers=auth(viewer_token))
        check("cards 非法 status 返回400", resp.status_code == 400, resp.text)
        resp = client.get("/api/trello/cards", params={"search": "核对"},
                          headers=auth(viewer_token))
        check("cards search=核对 过滤 total==1",
              resp.json()["total"] == 1, resp.text)

        # ------------------------------------------------------------------
        # 7. 配置列表 / 修改（凭据留空不修改）
        # ------------------------------------------------------------------
        print("--- 7. 配置列表与修改 ---")
        resp = client.get("/api/trello/configs", headers=auth(admin_token))
        check("配置列表返回200 且 1 条",
              resp.status_code == 200 and len(resp.json()) == 1, resp.text)
        item = resp.json()[0]
        check("列表 api_key/token 均为掩码",
              item["api_key"] == "********" and item["token"] == "********",
              str(item))
        check("列表含 updated_by_name 字段",
              item.get("updated_by_name") == "admin", str(item.get("updated_by_name")))
        check("列表 last_sync_status=success",
              item["last_sync_status"] == "success", str(item))

        resp = client.put(f"/api/trello/configs/{cfg_id}",
                          json={"sync_min": 10},
                          headers=auth(admin_token))
        check("修改 sync_min 返回200", resp.status_code == 200, resp.text)
        check("修改后 sync_min=10", resp.json()["sync_min"] == 10, resp.text)
        rows = db_rows(f"SELECT api_key, token_enc FROM trello_config WHERE id={cfg_id}")
        check("凭据留空时密文不变",
              rows and rows[0][0] == cipher_key_v1 and rows[0][1] == cipher_token_v1)

        resp = client.put(f"/api/trello/configs/{cfg_id}",
                          json={"api_key": "plain-key-def456"},
                          headers=auth(admin_token))
        check("修改 api_key 返回200", resp.status_code == 200, resp.text)
        rows = db_rows(f"SELECT api_key FROM trello_config WHERE id={cfg_id}")
        check("api_key 密文已更新且非明文",
              rows and rows[0][0] not in (cipher_key_v1, "plain-key-def456"),
              str(rows))
        check("新 api_key 可解密还原",
              rows and decrypt_secret(rows[0][0]) == "plain-key-def456")

        resp = client.put("/api/trello/configs/9999",
                          json={"sync_min": 15}, headers=auth(admin_token))
        check("修改不存在配置返回404", resp.status_code == 404, resp.text)

        # ------------------------------------------------------------------
        # 8. 删除
        # ------------------------------------------------------------------
        print("--- 8. 删除 ---")
        resp = client.delete(f"/api/trello/configs/{cfg_id}",
                             headers=auth(admin_token))
        check("删除配置返回200", resp.status_code == 200, resp.text)
        resp = client.get("/api/trello/configs", headers=auth(admin_token))
        check("删除后配置列表为空",
              resp.status_code == 200 and resp.json() == [], resp.text)
        resp = client.delete(f"/api/trello/configs/{cfg_id}",
                             headers=auth(admin_token))
        check("重复删除返回404", resp.status_code == 404, resp.text)

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
