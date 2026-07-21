# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据库查询适配器（DbAdapter）

工作流程（方案 2.3）：
    连接配置（已解密，仅内存）→ SQLAlchemy 引擎（NullPool，用完即弃）
    → SQL Guard 执行前二次校验 → 参数绑定（:biz_date 等命名参数，防注入）
    → 只读事务/语句超时设置（尽力而为并记录）→ 流式读取（最大行数硬限制）
    → 按模板字段映射（大小写不敏感）重命名列 → 标准 DataFrame

错误处理：数据库/网络/驱动异常统一翻译为中文友好信息（DatasourceError），
不向前端泄露原始堆栈与连接串（含密码）。

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

import logging
import re
import socket
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.pool import NullPool

from app.datasource.base import FetchContext, SourceAdapter
from app.datasource.drivers import (
    DB_TYPE_LABELS,
    DatasourceConfigError,
    build_connection_url,
    probe_sql,
    readonly_setup_sql,
    statement_timeout_setup_sql,
)
from app.datasource.sql_guard import SqlGuardError, validate_select_only

logger = logging.getLogger(__name__)

# 建连超时（秒），避免不存在的主机/防火墙长时间挂起
CONNECT_TIMEOUT_SECONDS = 10


class DatasourceError(RuntimeError):
    """数据源访问失败（中文友好消息，可直接面向用户返回）"""


@dataclass
class ConnectionSpec:
    """解密后的连接参数（仅存在于内存，严禁落盘/记日志含密码）"""
    db_type: str
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    db_name: Optional[str] = None
    service_name: Optional[str] = None
    sid: Optional[str] = None
    extra: dict = field(default_factory=dict)  # 连接参数 JSON（预留，如 oracledb thick）


@dataclass
class QueryResult:
    """一次查询的执行结果与过程元信息（供预览与审计）"""
    df: pd.DataFrame
    columns: List[str]            # 映射后的列名
    rows_returned: int
    elapsed_ms: int
    protections: List[str]        # 实际生效的执行保护（审计用）


# =============================================================================
# 参数校验
# =============================================================================

_PARAM_TYPES = ("string", "number", "integer", "date")
_DATE_RE_1 = re.compile(r"^\d{8}$")                       # yyyyMMdd
_DATE_RE_2 = re.compile(r"^\d{4}-\d{2}-\d{2}$")           # yyyy-MM-dd


def validate_params(params_def: dict, params: Dict[str, str]) -> Dict[str, object]:
    """
    按模板参数定义校验并规范化参数值

    参数定义格式：{"biz_date": {"type": "date", "required": true, "label": "业务日期"}}
    类型：string / number / integer / date（yyyyMMdd 或 yyyy-MM-dd）
    值一律走 SQLAlchemy 绑定参数，天然防注入；此处做格式与必填校验。

    Returns:
        规范化后的参数字典（date 保持字符串，number→float，integer→int）

    Raises:
        DatasourceError: 缺必填参数/格式非法/出现未定义参数
    """
    params_def = params_def or {}
    params = params or {}
    bound: Dict[str, object] = {}

    for name in params:
        if name not in params_def:
            raise DatasourceError(
                f"参数 {name} 未在模板中定义（模板已定义: "
                f"{', '.join(params_def.keys()) or '无'}）"
            )

    for name, spec in params_def.items():
        ptype = (spec or {}).get("type", "string")
        label = (spec or {}).get("label") or name
        required = bool((spec or {}).get("required", False))
        if ptype not in _PARAM_TYPES:
            raise DatasourceError(f"模板参数 {name} 的类型非法: {ptype}（支持: {', '.join(_PARAM_TYPES)}）")

        raw = params.get(name)
        if raw is None or str(raw).strip() == "":
            if required:
                raise DatasourceError(f"缺少必填参数: {label}（{name}）")
            continue
        raw = str(raw).strip()

        if ptype == "date":
            if not (_DATE_RE_1.match(raw) or _DATE_RE_2.match(raw)):
                raise DatasourceError(
                    f"参数 {label}（{name}）日期格式非法: {raw}，应为 yyyyMMdd 或 yyyy-MM-dd")
            bound[name] = raw
        elif ptype == "integer":
            try:
                bound[name] = int(raw)
            except ValueError:
                raise DatasourceError(f"参数 {label}（{name}）应为整数: {raw}") from None
        elif ptype == "number":
            try:
                bound[name] = float(raw)
            except ValueError:
                raise DatasourceError(f"参数 {label}（{name}）应为数值: {raw}") from None
        else:
            if len(raw) > 500:
                raise DatasourceError(f"参数 {label}（{name}）超长（限 500 字符）")
            bound[name] = raw

    return bound


# =============================================================================
# 异常翻译（原始异常 → 中文友好，不含连接串/密码）
# =============================================================================

def _friendly_error(exc: Exception, spec: ConnectionSpec) -> DatasourceError:
    label = DB_TYPE_LABELS.get(spec.db_type, spec.db_type)
    target = spec.host or spec.db_name or "(未配置)"
    msg = str(exc)
    low = msg.lower()

    if isinstance(exc, (DatasourceConfigError, SqlGuardError, DatasourceError)):
        return exc if isinstance(exc, DatasourceError) else DatasourceError(str(exc))
    if isinstance(exc, socket.gaierror) or "name or service not known" in low \
            or "could not translate host" in low or "getaddrinfo failed" in low \
            or "getnameinfo failed" in low or "nodename nor servname" in low \
            or "temporary failure in name resolution" in low:
        return DatasourceError(f"无法解析数据库主机名 {target}，请检查主机地址是否正确")
    if isinstance(exc, (socket.timeout, TimeoutError)) or "timed out" in low or "timeout" in low:
        return DatasourceError(
            f"连接 {label}（{target}）超时，请检查网络连通性与防火墙（建连超时 {CONNECT_TIMEOUT_SECONDS}s）")
    if "connection refused" in low or "actively refused" in low or "无法连接" in low \
            or "could not connect" in low or "unreachable" in low:
        return DatasourceError(
            f"无法连接 {label}（{target}）：连接被拒绝或不可达，请确认主机、端口与监听状态")
    if "access denied" in low or "ora-01017" in low or "login failed" in low \
            or "password authentication failed" in low or "18456" in low:
        return DatasourceError(f"{label} 认证失败：账号或密码错误（{target}）")
    if "ora-12514" in low or "ora-12505" in low:
        return DatasourceError(f"Oracle 服务名/SID 不存在或监听未注册（{target}），请核对连接配置")
    if "unknown database" in low or "does not exist" in low and "database" in low:
        return DatasourceError(f"数据库名不存在（{target}），请核对库名配置")
    if "no module named" in low:
        return DatasourceError(f"{label} 驱动缺失，请联系运维检查部署包完整性")
    # 兜底：只给异常类型与摘要，不回传可能含连接串的完整报文
    summary = msg.split("\n")[0][:200]
    return DatasourceError(f"{label} 访问失败（{target}）：{type(exc).__name__}: {summary}")


def _connect_args(spec: ConnectionSpec) -> dict:
    """各驱动建连超时参数（尽力而为）"""
    t = spec.db_type
    if t in ("mariadb", "mysql"):
        return {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    if t == "postgresql":
        return {"connect_timeout": CONNECT_TIMEOUT_SECONDS}
    if t == "mssql":
        return {"login_timeout": CONNECT_TIMEOUT_SECONDS}
    if t == "oracle":
        # oracledb thin 模式 TCP 建连超时
        return {"tcp_connect_timeout": float(CONNECT_TIMEOUT_SECONDS)}
    return {}


# =============================================================================
# 查询执行
# =============================================================================

def execute_query(spec: ConnectionSpec, sql: str, params: Dict[str, str],
                  column_map: Optional[dict], context: FetchContext) -> QueryResult:
    """
    执行只读查询并返回标准 DataFrame（DbAdapter 与 preview 共用核心）

    Raises:
        DatasourceError: 配置/SQL/连接/执行/行数超限等失败（中文消息）
    """
    # ---- 执行前 SQL Guard 二次校验（双校验之第二道） ----
    try:
        sql = validate_select_only(sql)
    except SqlGuardError as e:
        raise DatasourceError(f"SQL 安全校验未通过：{e}") from None

    url = build_connection_url(
        spec.db_type, host=spec.host, port=spec.port,
        username=spec.username, password=spec.password,
        db_name=spec.db_name, service_name=spec.service_name, sid=spec.sid,
    )
    engine = create_engine(url, poolclass=NullPool, connect_args=_connect_args(spec))
    protections: List[str] = [f"SQL白名单校验(SELECT/WITH 单语句)"]
    started = time.monotonic()

    try:
        with engine.connect() as conn:
            # ---- 防线三：只读事务 + 语句超时（尽力而为并记录） ----
            for stmt in readonly_setup_sql(spec.db_type):
                try:
                    conn.execute(text(stmt))
                    protections.append(f"只读模式: {stmt}")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"只读事务设置失败（尽力而为，继续执行）: {stmt} -> {e}")
                    protections.append(f"只读模式设置失败已降级: {type(e).__name__}")
            for stmt in statement_timeout_setup_sql(spec.db_type, context.timeout_seconds):
                try:
                    conn.execute(text(stmt))
                    protections.append(f"语句超时: {stmt}")
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"语句超时设置失败（尽力而为，继续执行）: {stmt} -> {e}")
            protections.append(f"最大返回行数: {context.max_rows}")

            # ---- 执行与流式读取（行数硬限制） ----
            result = conn.execution_options(stream_results=True).execute(text(sql), params)
            columns = list(result.keys())
            hard_cap = context.max_rows + 1  # 多取 1 行用于超限判定
            rows: List[tuple] = []
            exceeded = False
            while True:
                batch = result.fetchmany(min(10000, hard_cap - len(rows)))
                if not batch:
                    break
                rows.extend(batch)
                if len(rows) >= hard_cap:
                    exceeded = True
                    break
            if exceeded:
                raise DatasourceError(
                    f"查询结果行数超过上限 {context.max_rows} 行，已中断；"
                    "请收窄查询条件（如限定业务日期范围）或联系管理员调整上限")

            # 预览等场景的额外截断（不改变超限语义）
            if context.limit_rows is not None and len(rows) > context.limit_rows:
                rows = rows[: context.limit_rows]

            df = pd.DataFrame(rows, columns=columns)
    except DatasourceError:
        raise
    except Exception as e:  # noqa: BLE001
        raise _friendly_error(e, spec) from None
    finally:
        engine.dispose()

    # ---- 字段映射（大小写不敏感；未映射列保留原名） ----
    if column_map:
        upper_map = {str(k).upper(): v for k, v in column_map.items()}
        rename = {c: upper_map[str(c).upper()] for c in df.columns
                  if str(c).upper() in upper_map}
        df = df.rename(columns=rename)
        if rename:
            protections.append(f"字段映射: {len(rename)}/{len(df.columns)} 列")

    elapsed_ms = int((time.monotonic() - started) * 1000)
    return QueryResult(
        df=df,
        columns=[str(c) for c in df.columns],
        rows_returned=len(df),
        elapsed_ms=elapsed_ms,
        protections=protections,
    )


def test_connection(spec: ConnectionSpec) -> QueryResult:
    """连通性测试（探测语句 + 只读/超时设置同样生效）"""
    return execute_query(
        spec, probe_sql(spec.db_type), params={}, column_map=None,
        context=FetchContext(params={}, timeout_seconds=CONNECT_TIMEOUT_SECONDS, max_rows=10),
    )


class DbAdapter(SourceAdapter):
    """数据库查询适配器：数据源 + 查询模板 + 参数 → 标准 DataFrame"""

    def __init__(self, spec: ConnectionSpec, sql: str,
                 column_map: Optional[dict] = None) -> None:
        self._spec = spec
        self._sql = sql
        self._column_map = column_map or {}
        self.last_result: Optional[QueryResult] = None

    def fetch(self, context: FetchContext) -> pd.DataFrame:
        self.last_result = execute_query(
            self._spec, self._sql, context.params, self._column_map, context)
        return self.last_result.df
