# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据源适配层

模块组成（方案 2.1/2.3）：
    base.py        SourceAdapter 抽象（fetch(context) -> DataFrame）
    drivers.py     各数据库方言的 SQLAlchemy URL 构造与方言注册
    sql_guard.py   SQL 只读白名单校验（四道防线之第二道）
    db_adapter.py  DbAdapter：数据源 + 查询模板 + 参数 → 标准 DataFrame

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

from app.datasource.base import FetchContext, SourceAdapter
from app.datasource.db_adapter import DbAdapter, DatasourceError
from app.datasource.sql_guard import SqlGuardError, validate_select_only

__all__ = [
    "FetchContext",
    "SourceAdapter",
    "DbAdapter",
    "DatasourceError",
    "SqlGuardError",
    "validate_select_only",
]
