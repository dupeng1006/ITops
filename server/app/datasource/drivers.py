# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据库方言注册与 SQLAlchemy URL 构造

支持类型（页面暴露五种，方案 2.4 驱动说明）：
    oracle      python-oracledb（thin 模式，免 Oracle Client）
    mariadb     PyMySQL（纯 Python）
    mysql       PyMySQL（纯 Python）
    mssql       pymssql（自带 FreeTDS）
    postgresql  psycopg2-binary（自带 libpq）

内部测试方言（页面不暴露，仅供自动化测试与冒烟）：
    sqlite      SQLite 文件库（Python 内置）

Oracle 的库标识三选一：service_name（推荐）/ sid；其余库使用 db_name。

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

from typing import Optional

from sqlalchemy.engine import URL


class DatasourceConfigError(ValueError):
    """数据源连接配置非法（中文消息，可直接面向用户返回）"""


# 页面可见的数据源类型（下拉选项；sqlite 为内部测试方言，不出现在页面）
PUBLIC_DB_TYPES = ("oracle", "mariadb", "mysql", "mssql", "postgresql")
ALL_DB_TYPES = PUBLIC_DB_TYPES + ("sqlite",)

# 各类型默认端口（表单预填）
DEFAULT_PORTS = {
    "oracle": 1521,
    "mariadb": 3306,
    "mysql": 3306,
    "mssql": 1433,
    "postgresql": 5432,
    "sqlite": 0,
}

# 类型中文名（报错信息用）
DB_TYPE_LABELS = {
    "oracle": "Oracle",
    "mariadb": "MariaDB",
    "mysql": "MySQL",
    "mssql": "SQL Server",
    "postgresql": "PostgreSQL",
    "sqlite": "SQLite（内部测试）",
}


def build_connection_url(
    db_type: str,
    host: Optional[str] = None,
    port: Optional[int] = None,
    username: Optional[str] = None,
    password: Optional[str] = None,
    db_name: Optional[str] = None,
    service_name: Optional[str] = None,
    sid: Optional[str] = None,
) -> URL:
    """
    按方言构造 SQLAlchemy 连接 URL（口令等敏感字段由 URL.create 安全转义）

    Raises:
        DatasourceConfigError: 类型不支持或必填项缺失
    """
    db_type = (db_type or "").strip().lower()
    if db_type not in ALL_DB_TYPES:
        raise DatasourceConfigError(
            f"不支持的数据源类型: {db_type or '(空)'}，支持: {', '.join(PUBLIC_DB_TYPES)}"
        )

    if db_type == "sqlite":
        # 内部测试方言：db_name 即库文件路径
        if not db_name:
            raise DatasourceConfigError("SQLite 数据源必须提供库文件路径（db_name）")
        return URL.create("sqlite", database=db_name)

    # 其余类型：主机/账号必填
    if not host or not host.strip():
        raise DatasourceConfigError("数据库主机（host）不能为空")
    if not username or not username.strip():
        raise DatasourceConfigError("数据库账号不能为空")
    host = host.strip()
    port = port or DEFAULT_PORTS[db_type]

    if db_type == "oracle":
        # service_name 优先，sid 次之，二选一
        if service_name and service_name.strip():
            query = {"service_name": service_name.strip()}
            return URL.create("oracle+oracledb", username=username.strip(),
                              password=password or None, host=host, port=port, query=query)
        if sid and sid.strip():
            return URL.create("oracle+oracledb", username=username.strip(),
                              password=password or None, host=host, port=port,
                              database=sid.strip())
        raise DatasourceConfigError("Oracle 数据源必须提供 服务名(service_name) 或 SID 之一")

    if db_type in ("mariadb", "mysql"):
        if not db_name or not db_name.strip():
            raise DatasourceConfigError("MySQL/MariaDB 数据源必须提供库名")
        return URL.create("mysql+pymysql", username=username.strip(),
                          password=password or None, host=host, port=port,
                          database=db_name.strip(), query={"charset": "utf8mb4"})

    if db_type == "mssql":
        if not db_name or not db_name.strip():
            raise DatasourceConfigError("SQL Server 数据源必须提供库名")
        return URL.create("mssql+pymssql", username=username.strip(),
                          password=password or None, host=host, port=port,
                          database=db_name.strip())

    if db_type == "postgresql":
        if not db_name or not db_name.strip():
            raise DatasourceConfigError("PostgreSQL 数据源必须提供库名")
        return URL.create("postgresql+psycopg2", username=username.strip(),
                          password=password or None, host=host, port=port,
                          database=db_name.strip())

    raise DatasourceConfigError(f"不支持的数据源类型: {db_type}")  # pragma: no cover


def probe_sql(db_type: str) -> str:
    """连通性探测语句（测试连接用）"""
    return "SELECT 1 FROM DUAL" if (db_type or "").lower() == "oracle" else "SELECT 1"


def readonly_setup_sql(db_type: str) -> list:
    """
    只读事务设置语句（连接建立后、查询执行前逐条执行，尽力而为）

    各库口径（方案 2.4 防线三）：
        Oracle      SET TRANSACTION READ ONLY（须在事务首条语句）
        PostgreSQL  SET TRANSACTION READ ONLY
        MySQL/MariaDB  SET SESSION TRANSACTION READ ONLY（下一事务生效）+
                       START TRANSACTION READ ONLY 由驱动事务自动开启时尽力保证；
                       本实现采用 SET SESSION + 查询前显式 START TRANSACTION READ ONLY
                       不可行（与连接池事务模型冲突），故采用会话级设置并记录日志
        MSSQL       无会话级只读事务，跳过（依赖只读账号与 SQL Guard）
        SQLite      PRAGMA query_only = ON
    """
    db_type = (db_type or "").lower()
    if db_type == "oracle":
        return ["SET TRANSACTION READ ONLY"]
    if db_type == "postgresql":
        return ["SET TRANSACTION READ ONLY"]
    if db_type in ("mariadb", "mysql"):
        return ["SET SESSION TRANSACTION READ ONLY"]
    if db_type == "sqlite":
        return ["PRAGMA query_only = ON"]
    return []  # mssql：无会话级只读，跳过


def statement_timeout_setup_sql(db_type: str, timeout_seconds: int) -> list:
    """
    语句超时设置语句（尽力而为；不支持的方言返回空列表并记录日志）

        PostgreSQL  SET statement_timeout（毫秒）
        MySQL/MariaDB  SET SESSION max_execution_time（毫秒，5.7.8+）
        Oracle/MSSQL/SQLite  无通用会话级语句超时（依赖驱动/账号侧限制），跳过
    """
    db_type = (db_type or "").lower()
    millis = int(timeout_seconds * 1000)
    if db_type == "postgresql":
        return [f"SET statement_timeout = {millis}"]
    if db_type in ("mariadb", "mysql"):
        return [f"SET SESSION max_execution_time = {millis}"]
    return []
