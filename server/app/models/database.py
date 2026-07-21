# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据库连接与初始化

- SQLite（WAL 模式，check_same_thread=False 支持后台线程）；
- 首次启动自动建库（data/o32ops.db）、建表；
- 初始化数据：初始管理员 admin（强制首登改密）；
- 规则导入：从 server/config/rule_config.json 导入 rule_code_mapping /
  rule_bulk_product / rule_threshold（仅当目标表为空时导入，不覆盖人工调整）。

作者：技术部
版本：1.0.0
日期：2026-07-17
"""

import json
import logging
from pathlib import Path
from typing import Optional

from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from app.core.config import RULE_CONFIG_JSON, get_settings
from app.core.security import hash_password
from app.models.entities import (
    Base,
    RuleBulkProduct,
    RuleCodeMapping,
    RuleThreshold,
    SysUser,
)

logger = logging.getLogger(__name__)

_engine: Optional[Engine] = None
_session_factory: Optional[sessionmaker] = None


def _enable_sqlite_wal(dbapi_conn, _connection_record) -> None:
    """SQLite 连接启用 WAL 模式（读多写少低并发场景）"""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def get_engine() -> Engine:
    """获取当前数据库引擎（须先调用 init_database）"""
    if _engine is None:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    return _engine


def get_session_factory() -> sessionmaker:
    """获取当前会话工厂（须先调用 init_database）"""
    if _session_factory is None:
        raise RuntimeError("数据库未初始化，请先调用 init_database()")
    return _session_factory


def init_database(db_path: Optional[Path] = None) -> None:
    """
    初始化数据库：建库建表 + 初始管理员 + 规则导入

    Args:
        db_path: SQLite 库文件路径，默认取集中配置 O32OPS_DB_PATH
                 （data/o32ops.db）；测试可注入临时路径
    """
    global _engine, _session_factory

    settings = get_settings()
    path = Path(db_path) if db_path else settings.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    _engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    event.listen(_engine, "connect", _enable_sqlite_wal)
    _session_factory = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)

    Base.metadata.create_all(_engine)
    logger.info(f"数据库初始化完成: {path}")

    # schema 迁移须在种子导入之前执行：ORM 实体已映射新列（如
    # rule_bulk_product.color），旧库结构未升级时种子查询会因缺列失败
    from app.models.migrations import run_migrations  # 延迟导入避免循环
    run_migrations(_engine)

    with _session_factory() as session:
        _init_admin(session, settings)
        _import_rules(session)
        _init_subject_price_rules(session)
        _init_sys_config(session)
        session.commit()


def _init_admin(session: Session, settings) -> None:
    """初始化管理员账号（仅当无任何 admin 用户时）"""
    exists = session.execute(
        select(SysUser).where(SysUser.role == "admin")
    ).scalars().first()
    if exists:
        return
    admin = SysUser(
        username=settings.INITIAL_ADMIN_USERNAME,
        password_hash=hash_password(settings.INITIAL_ADMIN_PASSWORD),
        role="admin",
        status="active",
        source="local",
        must_change_password=True,  # 首次登录强制改密
    )
    session.add(admin)
    logger.info(f"已创建初始管理员: {settings.INITIAL_ADMIN_USERNAME}（首次登录需修改初始密码）")


def _import_rules(session: Session) -> None:
    """
    从 rule_config.json 导入规则初始数据（仅当各规则表为空时）

    导入内容：rename_map → rule_code_mapping；special_products（新格式，
    兼容旧 bulk_products）→ rule_bulk_product；diff_threshold →
    rule_threshold.diff_pct；similarity_threshold → rule_threshold.fuzzy_sim
    """
    if not RULE_CONFIG_JSON.exists():
        logger.warning(f"规则配置 JSON 不存在，跳过规则导入: {RULE_CONFIG_JSON}")
        return

    with open(RULE_CONFIG_JSON, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 映射规则
    if session.execute(select(RuleCodeMapping)).scalars().first() is None:
        for source, target in config.get("rename_map", {}).items():
            session.add(RuleCodeMapping(
                source_code=source, target_code=target,
                enabled=True, updated_by="system-init",
            ))
        logger.info(f"规则导入: 代码映射 {len(config.get('rename_map', {}))} 条")

    # 特殊产品（新格式 special_products 对象数组优先，兼容旧格式 bulk_products 字符串数组）
    if session.execute(select(RuleBulkProduct)).scalars().first() is None:
        from app.services.rule_service import parse_special_products
        special = parse_special_products(config, str(RULE_CONFIG_JSON))
        for code, spec in special.items():
            session.add(RuleBulkProduct(
                product_code=code, description=spec.note, color=spec.color,
                enabled=True, updated_by="system-init",
            ))
        logger.info(f"规则导入: 特殊产品 {len(special)} 个")

    # 阈值
    if session.execute(select(RuleThreshold)).scalars().first() is None:
        session.add(RuleThreshold(
            param_key="diff_pct", param_value=str(config.get("diff_threshold", 1.0)),
            description="差异阈值(%)，超过标浅红并计入差异统计", updated_by="system-init",
        ))
        session.add(RuleThreshold(
            param_key="fuzzy_sim", param_value=str(config.get("similarity_threshold", 0.5)),
            description="模糊匹配相似度阈值(0-1)", updated_by="system-init",
        ))
        session.add(RuleThreshold(
            param_key="price_tol", param_value="0.0001",
            description="估值价格核对容差（M2 预留）", updated_by="system-init",
        ))
        logger.info("规则导入: 阈值 diff_pct / fuzzy_sim / price_tol(预留)")


def _init_sys_config(session: Session) -> None:
    """系统参数种子（仅当表为空时；定时自动任务不预置，由用户自行创建）"""
    from app.models.entities import SysConfig  # 延迟导入避免循环
    if session.execute(select(SysConfig)).scalars().first() is not None:
        return
    session.add(SysConfig(
        param_key="data_ready_time", param_value="17:30",
        description="数据就绪时间(HH:MM)：定时任务 file 模式判定文件就绪的基准时刻",
        updated_by="system-init",
    ))
    session.add(SysConfig(
        param_key="buffer_minutes", param_value="30",
        description="就绪缓冲(分钟)：data_ready_time + buffer 之前文件大概率未就绪",
        updated_by="system-init",
    ))
    session.add(SysConfig(
        param_key="schedule_retry_delay_minutes", param_value="5",
        description="定时任务失败重试间隔(分钟)：失败后隔此时长重试 1 次，仍失败置 failed",
        updated_by="system-init",
    ))
    logger.info("系统参数导入: data_ready_time=17:30 / buffer_minutes=30 / schedule_retry_delay_minutes=5")


def _init_subject_price_rules(session: Session) -> None:
    """M2 科目取价规则种子（仅当表为空时；默认 1101→市价、1501→单位成本）"""
    from app.models.entities import SysSubjectPriceRule  # 延迟导入避免循环
    if session.execute(select(SysSubjectPriceRule)).scalars().first() is not None:
        return
    session.add(SysSubjectPriceRule(
        subject_prefix="1101", price_field="市价",
        description="交易性金融资产", note="",
        enabled=True, sort_order=1, updated_by="system-init",
    ))
    session.add(SysSubjectPriceRule(
        subject_prefix="1501", price_field="单位成本",
        description="债权投资",
        note="摊余成本与市场估值口径差异，属正常",
        enabled=True, sort_order=2, updated_by="system-init",
    ))
    logger.info("M2 科目取价规则导入: 1101→市价 / 1501→单位成本")
