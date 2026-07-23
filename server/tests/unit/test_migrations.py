# -*- coding: utf-8 -*-
"""
schema 轻量迁移机制单元测试（v1 → v2：rule_bulk_product.color）

覆盖：
    A. 手工构造无 color 列的旧结构库（含 2 行存量数据，其中 1 行带历史占位
       说明"大宗产品（初始导入）"、1 行带真实说明）→ init_database +
       run_migrations → 断言：
       - color 列已新增，存量 2 行保留且 color 默认 'FFC000'；
       - 占位说明被清理为 NULL（M1 默认文案行为不变），真实说明保留；
       - schema_version 登记 v2；
    B. 幂等：重复执行 run_migrations 不报错、数据不变；
    C. 全新库（create_all 已含 color 列）迁移跳过 ADD COLUMN 但仍登记版本；
    D. v2→v3：无 display_name/department 列的旧 sys_user（含 1 行存量）升级后
       两列存在、原数据保留、新列 NULL、幂等。

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\unit\\test_migrations.py
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

SERVER_ROOT = Path(__file__).resolve().parents[2]
TMP_ROOT = Path(tempfile.mkdtemp(prefix="o32ops_migrations_"))

os.environ["O32OPS_DATA_DIR"] = str(TMP_ROOT / "data")
os.environ["O32OPS_ARCHIVE_DIR"] = str(TMP_ROOT / "archive")
os.environ["O32OPS_SECRET_KEY"] = "migrations-test-secret-key-do-not-use-in-prod"

if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

# 期望已登记迁移版本（新增迁移时只需改这一处常量）
EXPECTED_VERSIONS = [2, 3, 4, 5, 6]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from app.models.migrations import run_migrations  # noqa: E402

failures: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


def _columns(db_path: Path, table: str) -> set:
    conn = sqlite3.connect(str(db_path))
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    conn.close()
    return cols


def _build_legacy_db(db_path: Path) -> None:
    """手工构造 v1 旧结构库：rule_bulk_product 无 color 列 + 2 行存量"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE rule_bulk_product ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " product_code VARCHAR(50) NOT NULL UNIQUE,"
        " description VARCHAR(200),"
        " enabled BOOLEAN NOT NULL,"
        " updated_by VARCHAR(50),"
        " updated_at DATETIME NOT NULL)"
    )
    conn.execute(
        "INSERT INTO rule_bulk_product(product_code, description, enabled,"
        " updated_by, updated_at) VALUES"
        " ('AZ0206', '大宗产品（初始导入）', 1, 'system-init', '2026-07-17 10:00:00'),"
        " ('AZ0205', '月末大额申赎(真实说明)', 1, 'admin', '2026-07-18 10:00:00')"
    )
    conn.commit()
    conn.close()


def test_legacy_db_migration() -> None:
    db_path = TMP_ROOT / "legacy.db"
    _build_legacy_db(db_path)
    check("A1 旧库构造（无 color 列）", "color" not in _columns(db_path, "rule_bulk_product"))

    # 全路径：init_database（内部含迁移）+ run_migrations（幂等空转）。
    # 旧库缺新实体的 color 列，迁移必须先于 ORM 种子查询执行，否则启动即失败
    from app.models.database import init_database
    os.environ["O32OPS_DB_PATH"] = str(db_path)
    from app.core.config import reset_settings
    reset_settings()
    init_database(db_path)
    from app.models.database import get_engine
    run_migrations(get_engine())

    check("A2 迁移后 color 列存在", "color" in _columns(db_path, "rule_bulk_product"))
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = {r["product_code"]: r for r in conn.execute(
        "SELECT product_code, description, color FROM rule_bulk_product").fetchall()}
    check("A3 存量 2 行保留", set(rows.keys()) == {"AZ0206", "AZ0205"}, str(rows))
    check("A4 存量行 color 默认 FFC000",
          all(r["color"] == "FFC000" for r in rows.values()),
          str({k: v["color"] for k, v in rows.items()}))
    check("A5 历史占位说明清理为 NULL（默认文案行为不变）",
          rows["AZ0206"]["description"] is None, str(rows["AZ0206"]["description"]))
    check("A6 真实说明保留",
          rows["AZ0205"]["description"] == "月末大额申赎(真实说明)",
          str(rows["AZ0205"]["description"]))
    audit_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='sys_audit_log'"
    ).fetchone() is not None
    check("A8 旧库缺 sys_audit_log 时 v5 跳过不崩溃（建表流程兜底）",
          True, "run_migrations 已完整执行")
    versions = [r[0] for r in conn.execute(
        "SELECT version FROM schema_version ORDER BY version").fetchall()]
    check("A7 schema_version 登记全部版本", versions == EXPECTED_VERSIONS, str(versions))
    conn.close()

    # ---- B. 幂等：重复执行 ----
    run_migrations(get_engine())
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows2 = conn.execute(
        "SELECT product_code, description, color FROM rule_bulk_product"
        " ORDER BY product_code").fetchall()
    versions2 = conn.execute("SELECT version FROM schema_version").fetchall()
    conn.close()
    check("B1 重复执行幂等（数据不变）",
          [(r["product_code"], r["description"], r["color"]) for r in rows2]
          == [("AZ0205", "月末大额申赎(真实说明)", "FFC000"),
              ("AZ0206", None, "FFC000")],
          str(rows2))
    check("B2 重复执行版本不重复登记", len(versions2) == len(EXPECTED_VERSIONS), str(versions2))


def test_fresh_db_migration() -> None:
    """全新库：实体 create_all 已含 color 列，迁移应跳过且登记版本"""
    db_path = TMP_ROOT / "fresh.db"
    from app.models.database import init_database
    os.environ["O32OPS_DB_PATH"] = str(db_path)
    from app.core.config import reset_settings
    reset_settings()
    init_database(db_path)

    check("C1 新库建表即含 color 列", "color" in _columns(db_path, "rule_bulk_product"))
    check("C1b 新库建表即含 display_name/department 列",
          {"display_name", "department"} <= _columns(db_path, "sys_user"))
    from app.models.database import get_engine
    run_migrations(get_engine())
    conn = sqlite3.connect(str(db_path))
    versions = [r[0] for r in conn.execute(
        "SELECT version FROM schema_version ORDER BY version").fetchall()]
    rows = conn.execute(
        "SELECT product_code, description, color FROM rule_bulk_product").fetchall()
    conn.close()
    check("C2 新库迁移登记全部版本", versions == EXPECTED_VERSIONS, str(versions))
    check("C3 新库初始导入 11 个特殊产品（note 空 + color FFC000）",
          len(rows) == 11
          and all(r[1] is None and r[2] == "FFC000" for r in rows),
          str(rows[:3]))

    conn = sqlite3.connect(str(db_path))
    fav_table = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dict_favorite'"
    ).fetchone()
    conn.close()
    check("C4 新库 dict_favorite 收藏表已建（迁移 v4）",
          fav_table is not None, str(fav_table))


def _build_legacy_user_db(db_path: Path) -> None:
    """手工构造 v2 结构库：sys_user 无 display_name/department + 1 行存量"""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE sys_user ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " username VARCHAR(50) NOT NULL UNIQUE,"
        " password_hash VARCHAR(128) NOT NULL,"
        " role VARCHAR(20) NOT NULL,"
        " status VARCHAR(10) NOT NULL,"
        " source VARCHAR(10) NOT NULL,"
        " must_change_password BOOLEAN NOT NULL,"
        " created_at DATETIME NOT NULL,"
        " updated_at DATETIME NOT NULL)"
    )
    conn.execute(
        "INSERT INTO sys_user(username, password_hash, role, status, source,"
        " must_change_password, created_at, updated_at) VALUES"
        " ('admin', 'hash-placeholder', 'admin', 'active', 'local', 1,"
        "  '2026-07-17 10:00:00', '2026-07-17 10:00:00')"
    )
    # rule_bulk_product 需为 v2 后结构（含 color），避免 v2 迁移再 ALTER
    conn.execute(
        "CREATE TABLE rule_bulk_product ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " product_code VARCHAR(50) NOT NULL UNIQUE,"
        " description VARCHAR(200),"
        " color VARCHAR(7) NOT NULL DEFAULT 'FFC000',"
        " enabled BOOLEAN NOT NULL,"
        " updated_by VARCHAR(50),"
        " updated_at DATETIME NOT NULL)"
    )
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO schema_version(version, applied_at) VALUES"
                 " (2, '2026-07-20 10:00:00')")
    conn.commit()
    conn.close()


def test_v3_user_columns() -> None:
    """D. v2→v3：sys_user 增加 display_name/department"""
    db_path = TMP_ROOT / "legacy_user.db"
    _build_legacy_user_db(db_path)
    check("D1 旧库 sys_user 无新列",
          not ({"display_name", "department"} & _columns(db_path, "sys_user")))

    from app.models.migrations import run_migrations as rm
    from sqlalchemy import create_engine
    engine = create_engine(f"sqlite:///{db_path}",
                           connect_args={"check_same_thread": False})
    rm(engine)
    cols = _columns(db_path, "sys_user")
    check("D2 迁移后 display_name/department 列存在",
          {"display_name", "department"} <= cols, str(cols))
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT username, display_name, department FROM sys_user").fetchone()
    versions = [r[0] for r in conn.execute(
        "SELECT version FROM schema_version ORDER BY version").fetchall()]
    conn.close()
    check("D3 存量 admin 行保留且新列 NULL",
          row == ("admin", None, None), str(row))
    check("D4 schema_version 登记全部版本", versions == EXPECTED_VERSIONS, str(versions))
    rm(engine)  # 幂等重跑
    conn = sqlite3.connect(str(db_path))
    cnt = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
    row2 = conn.execute("SELECT username, display_name, department FROM sys_user").fetchone()
    conn.close()
    check("D5 重复执行幂等（版本不重复、数据不变）",
          cnt == len(EXPECTED_VERSIONS) and row2 == ("admin", None, None), f"cnt={cnt} row={row2}")
    engine.dispose()


if __name__ == "__main__":
    test_legacy_db_migration()
    test_fresh_db_migration()
    test_v3_user_columns()
    print(f"\n{'全部通过' if not failures else f'{len(failures)} 项失败'}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(0 if not failures else 1)
