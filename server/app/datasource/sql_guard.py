# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— SQL 只读白名单校验（四道防线之第二道：平台侧 SQL Guard）

规则（方案 2.4）：
    1. 恰好一条语句（空语句/纯注释忽略；多语句一律拒绝）；
    2. 第一个有效 token（跳过空白与注释）必须是 SELECT 或 WITH；
    3. 全文 token 级扫描（字符串字面量、引号标识符不误伤），命中黑名单
       关键字即拒绝：INSERT/UPDATE/DELETE/MERGE/REPLACE/DDL/DCL/CALL/
       EXEC(UTE)/INTO/LOCK 等（仅收录可在 SELECT 中段造成写/锁的词，
       语句级危险词由首关键字白名单拦截，避免裸列名误伤）。

调用时机（双校验）：
    - 查询模板**保存时**校验一次（路由层 400）；
    - 每次**执行前**再校验一次（防御库内数据被绕开接口直接篡改）。

已知边界（如实记录）：
    - 列名/别名若与保留字完全相同且未加引号（如 SELECT update FROM t），
      会被方言词法识别为关键字而误拦截；规范写法是加引号或换别名；
    - sqlparse 非完整 SQL 语法分析器，本校验为"白名单 + 黑名单"纵深
      防御的一环，不能替代数据库侧只读账号（防线一）。

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

import logging

import sqlparse
from sqlparse import tokens as T

logger = logging.getLogger(__name__)


class SqlGuardError(ValueError):
    """SQL 白名单校验未通过（消息为中文，可直接面向用户返回）"""


# 允许的首关键字
ALLOWED_FIRST_KEYWORDS = ("SELECT", "WITH")

# 黑名单关键字（token 级匹配，大小写不敏感）
#
# 收录原则：只收录**能够合法出现在 SELECT/WITH 语句中段**并造成写操作或
# 锁定的关键字；仅以语句开头形式出现的（如 SET/USE/BEGIN/COMMIT/DECLARE/
# EXPLAIN/VACUUM/SHUTDOWN 等）已由"首关键字白名单"拦截，不再重复收录——
# 避免裸列名误伤（如 SELECT comment / SELECT start / SELECT set 会被
# sqlparse 词法识别为 Keyword 而误拦截；函数调用如 REPLACE(...) 不受影响）。
FORBIDDEN_KEYWORDS = frozenset({
    # DML 写（含 WITH 包裹 DML：WITH x AS (...) DELETE FROM t）
    "INSERT", "UPDATE", "DELETE", "MERGE", "REPLACE", "UPSERT",
    # DDL / DCL
    "CREATE", "DROP", "ALTER", "TRUNCATE", "RENAME", "GRANT", "REVOKE",
    # 存储过程 / 动态执行
    "CALL", "EXEC", "EXECUTE",
    # SELECT INTO 建表写（MSSQL/Sybase）
    "INTO",
    # 行/表锁（FOR UPDATE、LOCK IN SHARE MODE）
    "LOCK",
})


def _flatten_keywords(statement) -> list:
    """提取语句中全部关键字 token 值（大写）；字符串/标识符不误判"""
    keywords = []
    for tok in statement.flatten():
        ttype = tok.ttype
        if ttype is None:
            continue
        if ttype in (T.Keyword, T.Keyword.DML, T.Keyword.DDL):
            keywords.append(tok.value.upper())
    return keywords


def validate_select_only(sql: str) -> str:
    """
    校验 SQL 为单条只读 SELECT（或 WITH 开头的查询）

    Args:
        sql: 待校验 SQL 文本

    Returns:
        去除首尾空白后的 SQL（供后续执行使用）

    Raises:
        SqlGuardError: 校验未通过（中文原因说明）
    """
    if not sql or not sql.strip():
        raise SqlGuardError("SQL 不能为空")

    stripped = sql.strip()

    try:
        statements = [
            s for s in sqlparse.parse(stripped)
            if s.token_first(skip_cm=True) is not None
        ]
    except Exception as e:  # noqa: BLE001  sqlparse 解析异常按拒绝处理
        raise SqlGuardError(f"SQL 解析失败：{e}") from None

    # ---- 1. 单语句限制 ----
    if not statements:
        raise SqlGuardError("SQL 不能为空（仅含空白或注释）")
    if len(statements) > 1:
        raise SqlGuardError(
            f"仅允许单条 SELECT 查询，检测到 {len(statements)} 条语句；"
            "多语句执行已被安全策略拦截"
        )

    statement = statements[0]

    # ---- 2. 首关键字白名单 ----
    first = statement.token_first(skip_cm=True)
    first_word = first.value.upper() if first is not None else ""
    if first_word not in ALLOWED_FIRST_KEYWORDS:
        raise SqlGuardError(
            f"仅允许 SELECT / WITH 开头的只读查询，检测到以 {first_word or '(无法识别)'} 开头；"
            "写操作、DDL、存储过程调用均被安全策略拦截"
        )

    # ---- 3. 黑名单关键字扫描 ----
    keywords = _flatten_keywords(statement)
    hits = [kw for kw in keywords if kw in FORBIDDEN_KEYWORDS]
    if hits:
        # 去重保持出现顺序
        uniq = list(dict.fromkeys(hits))
        raise SqlGuardError(
            f"SQL 包含被安全策略禁止的关键字: {', '.join(uniq)}；"
            "仅允许纯查询（SELECT/WITH），禁止写操作、DDL、存储过程与事务控制"
        )

    return stripped
