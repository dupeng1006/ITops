# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 轻量 schema 迁移机制

适用场景：SQLite 单库、变更频率低、无 Alembic 依赖的部署形态。

机制：
    - schema_version 表记录已应用版本（version 主键, applied_at）；
    - SCHEMA_MIGRATIONS 为有序迁移列表，每项 (version, description, func)，
      version 严格递增；启动期按序补齐未应用的迁移；
    - 迁移函数必须幂等（用 PRAGMA table_info 检查列是否存在再
      ALTER TABLE ADD COLUMN），重复执行不产生副作用；
    - 每个迁移在独立事务中执行，成功后登记版本，失败即抛错中止启动。

迁移清单：
    v1 → v2: rule_bulk_product 增加 color 列（行填充色，默认 FFC000）；
             同时将历史占位说明文案（"大宗产品（初始导入）"等）置 NULL，
             激活 description 列为"差异说明"语义（NULL = 默认文案，
             保证 M1 结果与升级前一字不差）。
    v2 → v3: sys_user 增加 display_name（用户姓名）、department（部门）两列。
    v3 → v4: 新增 dict_favorite（数据字典表收藏）。
    v4 → v5: sys_audit_log 增加 mac（来源 MAC，服务端 ARP 解析）、
             menu（操作菜单）两列（存量日志该两列为 NULL，无损）。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import logging
from datetime import datetime
from typing import Callable, List, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

# 历史占位说明文案（非真实差异说明，升级时置 NULL 以保持 M1 默认输出不变）
LEGACY_PLACEHOLDER_NOTES = ("大宗产品（初始导入）", "大宗产品（配置导入）")

Migration = Tuple[int, str, Callable[[Engine], None]]


def _table_columns(engine: Engine, table: str) -> set:
    """读取表的全部列名（PRAGMA table_info）"""
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1] for r in rows}


def _migrate_v2(engine: Engine) -> None:
    """v1 → v2：rule_bulk_product 增加 color 列 + 清理历史占位说明"""
    columns = _table_columns(engine, "rule_bulk_product")
    with engine.begin() as conn:
        if "color" not in columns:
            conn.execute(text(
                "ALTER TABLE rule_bulk_product"
                " ADD COLUMN color VARCHAR(7) NOT NULL DEFAULT 'FFC000'"
            ))
            logger.info("迁移 v2: rule_bulk_product 已增加 color 列（默认 FFC000）")
        else:
            logger.info("迁移 v2: color 列已存在，跳过 ADD COLUMN（幂等）")
        # 历史占位说明置 NULL（幂等；仅清占位文案，不动真实说明）
        for placeholder in LEGACY_PLACEHOLDER_NOTES:
            result = conn.execute(
                text("UPDATE rule_bulk_product SET description = NULL"
                     " WHERE description = :ph"), {"ph": placeholder})
            if result.rowcount:
                logger.info(
                    f"迁移 v2: 清理历史占位说明 '{placeholder}' {result.rowcount} 行 → NULL")


def _migrate_v3(engine: Engine) -> None:
    """v2 → v3：sys_user 增加 display_name / department 两列（可空）"""
    columns = _table_columns(engine, "sys_user")
    with engine.begin() as conn:
        for col, ddl in (
            ("display_name", "ALTER TABLE sys_user ADD COLUMN display_name VARCHAR(100)"),
            ("department", "ALTER TABLE sys_user ADD COLUMN department VARCHAR(100)"),
        ):
            if col not in columns:
                conn.execute(text(ddl))
                logger.info(f"迁移 v3: sys_user 已增加 {col} 列")
            else:
                logger.info(f"迁移 v3: {col} 列已存在，跳过（幂等）")


def _migrate_v4(engine: Engine) -> None:
    """v3 → v4：新增 dict_favorite（数据字典表收藏）"""
    columns = _table_columns(engine, "dict_favorite")
    with engine.begin() as conn:
        if not columns:
            conn.execute(text(
                "CREATE TABLE dict_favorite ("
                " id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " user_id INTEGER NOT NULL,"
                " table_id INTEGER NOT NULL,"
                " table_code VARCHAR(100) NOT NULL,"
                " table_name VARCHAR(200),"
                " created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            ))
            conn.execute(text(
                "CREATE INDEX idx_dict_favorite_user_id ON dict_favorite(user_id)"
            ))
            logger.info("迁移 v4: dict_favorite 表已创建")
        else:
            logger.info("迁移 v4: dict_favorite 表已存在，跳过")


def _migrate_v5(engine: Engine) -> None:
    """v4 → v5：sys_audit_log 增加 mac / menu 两列（可空，存量无损）"""
    columns = _table_columns(engine, "sys_audit_log")
    with engine.begin() as conn:
        for col, ddl in (
            ("mac", "ALTER TABLE sys_audit_log ADD COLUMN mac VARCHAR(20)"),
            ("menu", "ALTER TABLE sys_audit_log ADD COLUMN menu VARCHAR(100)"),
        ):
            if col not in columns:
                conn.execute(text(ddl))
                logger.info(f"迁移 v5: sys_audit_log 已增加 {col} 列")
            else:
                logger.info(f"迁移 v5: {col} 列已存在，跳过（幂等）")


def _migrate_v6(engine: Engine) -> None:
    """v5 → v6：新增 Trello 集成三张表（trello_config / trello_board / trello_card）"""
    tables = {
        "trello_config": """
            CREATE TABLE trello_config (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name VARCHAR(100) NOT NULL UNIQUE,
                api_key VARCHAR(200) NOT NULL,
                token_enc TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT 1,
                sync_min INTEGER NOT NULL DEFAULT 5,
                last_sync_at DATETIME,
                last_sync_status VARCHAR(20),
                last_sync_error TEXT,
                updated_by VARCHAR(50),
                created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "trello_board": """
            CREATE TABLE trello_board (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_id INTEGER NOT NULL,
                board_id VARCHAR(50) NOT NULL,
                name VARCHAR(200) NOT NULL,
                url VARCHAR(500),
                is_closed BOOLEAN NOT NULL DEFAULT 0,
                synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
        "trello_card": """
            CREATE TABLE trello_card (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                config_id INTEGER NOT NULL,
                card_id VARCHAR(50) NOT NULL,
                board_id VARCHAR(50) NOT NULL,
                board_name VARCHAR(200),
                list_id VARCHAR(50) NOT NULL,
                list_name VARCHAR(200),
                name VARCHAR(500) NOT NULL,
                desc TEXT,
                status VARCHAR(50),
                due_date DATETIME,
                due_complete BOOLEAN NOT NULL DEFAULT 0,
                labels_json TEXT,
                members_json TEXT,
                url VARCHAR(500),
                pos FLOAT,
                synced_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """,
    }
    with engine.begin() as conn:
        for table_name, ddl in tables.items():
            columns = _table_columns(engine, table_name)
            if not columns:
                conn.execute(text(ddl))
                if table_name in ("trello_board", "trello_card"):
                    conn.execute(text(f"CREATE INDEX idx_{table_name}_config_id ON {table_name}(config_id)"))
                logger.info(f"迁移 v6: {table_name} 表已创建")
            else:
                logger.info(f"迁移 v6: {table_name} 表已存在，跳过（幂等）")


# 有序迁移列表（version 严格递增，禁止插序/改序）
SCHEMA_MIGRATIONS: List[Migration] = [
    (2, "rule_bulk_product 增加 color 列并清理历史占位说明", _migrate_v2),
    (3, "sys_user 增加 display_name / department 两列", _migrate_v3),
    (4, "新增 dict_favorite 数据字典表收藏", _migrate_v4),
    (5, "sys_audit_log 增加 mac / menu 两列", _migrate_v5),
    (6, "新增 Trello 集成三张表（trello_config / trello_board / trello_card）", _migrate_v6),
]


def run_migrations(engine: Engine) -> None:
    """
    按序应用未执行的 schema 迁移（每个迁移独立事务 + 版本登记）

    Args:
        engine: 平台库引擎（init_database 之后调用）
    """
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            " version INTEGER PRIMARY KEY,"
            " applied_at TEXT NOT NULL)"
        ))

    with engine.connect() as conn:
        applied = {r[0] for r in conn.execute(
            text("SELECT version FROM schema_version")).fetchall()}

    for version, description, func in SCHEMA_MIGRATIONS:
        if version in applied:
            continue
        logger.info(f"开始应用 schema 迁移 v{version}: {description}")
        func(engine)
        with engine.begin() as conn:
            conn.execute(
                text("INSERT INTO schema_version(version, applied_at)"
                     " VALUES(:v, :t)"),
                {"v": version, "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})
        logger.info(f"schema 迁移 v{version} 应用完成")
