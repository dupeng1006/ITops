# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— 数据字典服务（字典库访问 + SQL 生成）

字典库为独立 SQLite（data/dictionary.db，由 scripts/import_pdm.py 重建），
与平台库分离，便于模型更新后独立重导。本模块只做只读访问。

SQL 生成安全约束（与数据源模块同一套纵深防御）：
    - 表/列/别名一律来自字典库白名单（用户输入只作 id/code 匹配键，不直接拼入 SQL）；
    - 运算符白名单（=,!=,>,>=,<,<=,LIKE,IN,BETWEEN,IS NULL,IS NOT NULL）；
    - 条件值：纯数字原样，其余单引号包裹并双写转义；DATE 列日期值自动 TO_DATE；
    - 生成后统一过 sql_guard.validate_select_only 自证只读。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import List, Optional

from app.core.config import get_settings
from app.datasource.sql_guard import validate_select_only

logger = logging.getLogger(__name__)

# 条件运算符白名单（前端下拉与此保持一致）
COND_OPS = ("=", "!=", ">", ">=", "<", "<=", "LIKE", "IN", "BETWEEN",
            "IS NULL", "IS NOT NULL")

_ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,19}$")
_NUM_RE = re.compile(r"[-+]?\d+(\.\d+)?")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATETIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?")

DEFAULT_ROW_LIMIT = 500
MAX_ROW_LIMIT = 100000


class DictError(ValueError):
    """数据字典业务错误（消息为中文，可直接面向用户返回）"""


# =============================================================================
# 连接与基础查询
# =============================================================================

def dict_db_path() -> Path:
    return get_settings().DICT_DB_PATH


def dict_available() -> bool:
    return dict_db_path().exists()


def get_conn() -> sqlite3.Connection:
    """打开字典库只读连接（每请求一个，sqlite 开销可忽略）"""
    path = dict_db_path()
    if not path.exists():
        raise DictError(
            "数据字典库未初始化：请先运行 server/scripts/import_pdm.py 导入 PDM 模型")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {k: row[k] for k in row.keys()}


def list_models(conn: sqlite3.Connection) -> list:
    """模型清单（按业务组排序）"""
    rows = conn.execute(
        "SELECT id, file_name, model_name, biz_group, table_count, column_count,"
        " imported_at FROM dict_model ORDER BY biz_group, file_name"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


# =============================================================================
# 表搜索（表代码/中文名/字段名 模糊，标注命中点）
# =============================================================================

def search_tables(conn: sqlite3.Connection, keyword: str = "",
                  model_id: Optional[int] = None,
                  page: int = 1, page_size: int = 20,
                  fav_ids: Optional[List[int]] = None) -> dict:
    """
    模糊搜索表：匹配表代码/中文名/字段代码/字段中文名

    Returns:
        {total, page, page_size, items: [{..., matched_on: [...], matched_columns: [...], is_favorite: bool}]}
    """
    fav_ids = set(int(i) for i in (fav_ids or []))
    kw = (keyword or "").strip()
    like = f"%{kw}%"
    cond = "1=1"
    params: dict = {}
    if model_id:
        cond += " AND t.model_id = :mid"
        params["mid"] = model_id

    if kw:
        where = (f"{cond} AND (t.table_code LIKE :like OR t.table_name LIKE :like"
                 " OR t.id IN (SELECT DISTINCT table_id FROM dict_column"
                 "              WHERE col_code LIKE :like OR col_name LIKE :like))")
        params["like"] = like
        order = ("CASE WHEN t.table_code LIKE :like THEN 0"
                 "       WHEN t.table_name LIKE :like THEN 1 ELSE 2 END, t.table_code")
    else:
        where = cond
        order = "t.table_code"

    # 收藏优先：命中的收藏表排在最前
    if fav_ids:
        fav_sql = ",".join(str(i) for i in fav_ids)
        order = f"CASE WHEN t.id IN ({fav_sql}) THEN 0 ELSE 1 END, {order}"

    total = conn.execute(
        f"SELECT COUNT(*) c FROM dict_table t WHERE {where}", params
    ).fetchone()["c"]

    page = max(1, page)
    page_size = min(max(1, page_size), 100)
    rows = conn.execute(
        f"SELECT t.id, t.model_id, t.table_code, t.table_name,"
        f"       m.biz_group, m.file_name"
        f" FROM dict_table t JOIN dict_model m ON m.id = t.model_id"
        f" WHERE {where} ORDER BY {order}"
        f" LIMIT :lim OFFSET :off",
        {**params, "lim": page_size, "off": (page - 1) * page_size},
    ).fetchall()

    items = []
    for r in rows:
        item = _row_to_dict(r)
        matched_on = []
        matched_columns = []
        if kw:
            if like_match(r["table_code"], kw):
                matched_on.append("table_code")
            if r["table_name"] and like_match(r["table_name"], kw):
                matched_on.append("table_name")
            cols = conn.execute(
                "SELECT col_code, col_name FROM dict_column"
                " WHERE table_id = ? AND (col_code LIKE ? OR col_name LIKE ?)"
                " ORDER BY seq LIMIT 4",
                (r["id"], like, like),
            ).fetchall()
            matched_columns = [_row_to_dict(c) for c in cols]
            if matched_columns:
                matched_on.append("column")
        item["matched_on"] = matched_on
        item["matched_columns"] = matched_columns
        item["is_favorite"] = r["id"] in fav_ids
        items.append(item)

    return {"total": total, "page": page, "page_size": page_size, "items": items}


def like_match(text: Optional[str], kw: str) -> bool:
    """与 SQLite LIKE 一致的大小写不敏感包含（ASCII）"""
    return kw.lower() in (text or "").lower()


def get_table_detail(conn: sqlite3.Connection, table_id: int) -> Optional[dict]:
    """表详情：基本信息 + 全字段（含主键标识，按 seq 排序）"""
    t = conn.execute(
        "SELECT t.id, t.model_id, t.table_code, t.table_name, t.comment,"
        "       m.biz_group, m.file_name, m.model_name"
        " FROM dict_table t JOIN dict_model m ON m.id = t.model_id WHERE t.id = ?",
        (table_id,),
    ).fetchone()
    if t is None:
        return None
    cols = conn.execute(
        "SELECT id, col_code, col_name, data_type, is_pk, seq, comment"
        " FROM dict_column WHERE table_id = ? ORDER BY seq",
        (table_id,),
    ).fetchall()
    result = _row_to_dict(t)
    result["columns"] = [_row_to_dict(c) for c in cols]
    return result


def get_table_references(conn: sqlite3.Connection, table_id: int) -> dict:
    """表的关联（父子两向）"""
    def _load(side: str) -> list:
        # side: parent（本表为父，查子表）/ child（本表为子，查父表）
        if side == "parent":
            sql = ("SELECT r.id, r.ref_name, r.joins_json,"
                   "       t.id other_id, t.table_code other_code, t.table_name other_name,"
                   "       m.biz_group other_biz_group"
                   " FROM dict_reference r"
                   " JOIN dict_table t ON t.id = r.child_table_id"
                   " JOIN dict_model m ON m.id = t.model_id"
                   " WHERE r.parent_table_id = ?")
        else:
            sql = ("SELECT r.id, r.ref_name, r.joins_json,"
                   "       t.id other_id, t.table_code other_code, t.table_name other_name,"
                   "       m.biz_group other_biz_group"
                   " FROM dict_reference r"
                   " JOIN dict_table t ON t.id = r.parent_table_id"
                   " JOIN dict_model m ON m.id = t.model_id"
                   " WHERE r.child_table_id = ?")
        out = []
        for r in conn.execute(sql, (table_id,)).fetchall():
            d = _row_to_dict(r)
            d["joins"] = json.loads(d.pop("joins_json"))
            out.append(d)
        return out

    return {"as_parent": _load("parent"), "as_child": _load("child")}


# =============================================================================
# JOIN 推导（dict_reference 无向图 BFS）
# =============================================================================

def find_join_paths(conn: sqlite3.Connection, table_ids: list) -> tuple:
    """
    以 table_ids[0] 为根，BFS 寻找到其余各表的关联路径（路径可经过未选择的
    中间表，中间表仅参与 JOIN、不进 SELECT 列）

    Returns:
        (join_tree, unreachable)
        join_tree: 自根向叶有序 [(new_table_id, (p_id, c_id, ref_name, joins))]
                   —— new_table_id 是每一步新接入树的节点
        unreachable: 与根无已知关联路径的 table_id 列表
    """
    if len(table_ids) <= 1:
        return [], []

    # 无向邻接表（同一模型/跨模型 reference 均参与）
    adj: dict = {}
    for r in conn.execute(
            "SELECT id, parent_table_id, child_table_id, ref_name, joins_json"
            " FROM dict_reference").fetchall():
        edge = (r["parent_table_id"], r["child_table_id"],
                r["ref_name"], json.loads(r["joins_json"]))
        adj.setdefault(r["parent_table_id"], []).append(edge)
        adj.setdefault(r["child_table_id"], []).append(edge)

    root = table_ids[0]
    remaining = set(table_ids[1:])
    tree_parent: dict = {}   # node -> (prev_node, edge)（关联树）

    while remaining:
        seen = {root} | set(tree_parent.keys())
        path_edge: dict = {}
        found = None
        queue = list(seen)
        while queue and found is None:
            nxt = []
            for cur in queue:
                for edge in adj.get(cur, []):
                    p, c = edge[0], edge[1]
                    other = c if p == cur else p
                    if other in seen:
                        continue
                    seen.add(other)
                    path_edge[other] = (cur, edge)
                    if other in remaining:
                        found = other
                        break
                    nxt.append(other)
                if found is not None:
                    break
            queue = nxt
        if found is None:
            break  # 剩余目标不可达
        node = found
        while node in path_edge:
            prev, edge = path_edge[node]
            tree_parent[node] = (prev, edge)
            node = prev
        remaining.discard(found)

    # 自根向叶展开（DFS）：保证每条 JOIN 的对端已先在树中
    children: dict = {}
    for node, (prev, edge) in tree_parent.items():
        children.setdefault(prev, []).append((node, edge))
    join_tree = []

    def _walk(node):
        for child, edge in children.get(node, []):
            join_tree.append((child, edge))
            _walk(child)

    _walk(root)
    unreachable = [t for t in table_ids[1:] if t in remaining]
    return join_tree, unreachable


# =============================================================================
# SQL 生成（Oracle 方言）
# =============================================================================

def _valid_alias(alias: str, fallback: str) -> str:
    alias = (alias or "").strip()
    return alias if _ALIAS_RE.match(alias) else fallback


def _scalar_literal(value) -> str:
    """条件值 → SQL 字面量：纯数字原样，其余单引号包裹并双写转义"""
    s = str(value).strip()
    if _NUM_RE.fullmatch(s):
        return s
    return "'" + s.replace("'", "''") + "'"


def _value_literal(value, data_type: Optional[str]) -> str:
    """标量值格式化（DATE/TIMESTAMP 列日期值自动 TO_DATE）"""
    s = str(value).strip()
    dt = (data_type or "").upper()
    if ("DATE" in dt or "TIMESTAMP" in dt) and not _NUM_RE.fullmatch(s):
        if _DATETIME_RE.fullmatch(s):
            fmt = "YYYY-MM-DD HH24:MI:SS"
            return f"TO_DATE('{s.replace('T', ' ')}', '{fmt}')"
        if _DATE_RE.fullmatch(s):
            return f"TO_DATE('{s}', 'YYYY-MM-DD')"
    return _scalar_literal(s)


def _split_values(value) -> list:
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [p.strip() for p in re.split(r"[,，\n]+", str(value)) if p.strip()]


def format_condition(column_sql: str, op: str, value,
                     data_type: Optional[str]) -> str:
    """拼装单个条件（op 须已过白名单）"""
    op = op.upper().strip()
    if op in ("IS NULL", "IS NOT NULL"):
        return f"{column_sql} {op}"
    if op == "IN":
        parts = _split_values(value)
        if not parts:
            raise DictError(f"IN 条件值不能为空（字段 {column_sql}）")
        lits = ", ".join(_value_literal(p, data_type) for p in parts)
        return f"{column_sql} IN ({lits})"
    if op == "BETWEEN":
        parts = _split_values(value)
        if len(parts) != 2:
            raise DictError(
                f"BETWEEN 需要恰好 2 个值（字段 {column_sql}，逗号分隔）")
        return (f"{column_sql} BETWEEN {_value_literal(parts[0], data_type)}"
                f" AND {_value_literal(parts[1], data_type)}")
    if value is None or str(value).strip() == "":
        raise DictError(f"条件值不能为空（字段 {column_sql} {op}）")
    return f"{column_sql} {op} {_value_literal(value, data_type)}"


def generate_sql(conn: sqlite3.Connection, tables: list, conditions: list,
                 limit: int = DEFAULT_ROW_LIMIT,
                 use_rownum: bool = True) -> dict:
    """
    生成 Oracle SELECT 语句

    Args:
        tables: [{table_id, columns: [col_code...], alias}]（columns 空 = 全部列）
        conditions: [{table_alias, column, op, value}]
        limit: ROWNUM 上限（use_rownum=True 时生效）
        use_rownum: 是否附加 ROWNUM 限制

    Returns:
        {sql, joins: [说明...], warnings: [...]}

    Raises:
        DictError: 入参非法（中文说明）
    """
    if not tables:
        raise DictError("请至少选择一张表")
    if len(tables) > 10:
        raise DictError("单次最多选择 10 张表")

    # ---- 载入表与列（白名单校验：全部来自字典库） ----
    table_infos = []
    used_aliases = set()
    for i, spec in enumerate(tables):
        tid = spec.get("table_id")
        detail = get_table_detail(conn, int(tid)) if tid is not None else None
        if detail is None:
            raise DictError(f"表不存在: id={tid}")
        alias = _valid_alias(spec.get("alias"), f"t{i + 1}")
        if alias in used_aliases:
            raise DictError(f"表别名重复: {alias}")
        used_aliases.add(alias)

        all_cols = {c["col_code"]: c for c in detail["columns"]}
        wanted = [str(c).strip() for c in (spec.get("columns") or []) if str(c).strip()]
        if wanted:
            unknown = [c for c in wanted if c not in all_cols]
            if unknown:
                raise DictError(
                    f"表 {detail['table_code']} 不存在字段: {', '.join(unknown)}")
            sel_cols = [all_cols[c] for c in wanted]
        else:
            sel_cols = detail["columns"]
        table_infos.append({"detail": detail, "alias": alias, "sel_cols": sel_cols})

    alias_of_table = {t["detail"]["id"]: t["alias"] for t in table_infos}

    # ---- SELECT 列（逗号在注释前，避免行注释吞掉逗号） ----
    select_parts = []
    flat_cols = [
        (t["alias"], c) for t in table_infos for c in t["sel_cols"]
    ]
    for idx, (alias, c) in enumerate(flat_cols):
        sep = "," if idx < len(flat_cols) - 1 else ""
        comment = f"  -- {c['col_name']}" if c.get("col_name") else ""
        select_parts.append(f"    {alias}.{c['col_code']}{sep}{comment}")
    select_clause = "\n".join(select_parts)

    # ---- FROM / JOIN ----
    warnings: list = []
    join_notes: list = []
    first = table_infos[0]
    from_lines = [f"FROM {first['detail']['table_code']} {first['alias']}"]
    if len(table_infos) > 1:
        join_tree, unreachable = find_join_paths(
            conn, [t["detail"]["id"] for t in table_infos])
        # 中间表（不在选择集）自动分配别名，仅参与 JOIN
        alias_map = dict(alias_of_table)
        auto_n = 0
        code_of_table = {t["detail"]["id"]: t["detail"]["table_code"]
                         for t in table_infos}
        for new_id, (p_id, c_id, ref_name, joins) in join_tree:
            for nid in (p_id, c_id):
                if nid not in code_of_table:
                    row = conn.execute(
                        "SELECT table_code FROM dict_table WHERE id = ?",
                        (nid,)).fetchone()
                    if row is None:
                        raise DictError(f"关联路径引用了不存在的表: id={nid}")
                    code_of_table[nid] = row["table_code"]
                if nid not in alias_map:
                    auto_n += 1
                    alias_map[nid] = f"x{auto_n}"

        joined_ids = {first["detail"]["id"]}
        for new_id, (p_id, c_id, ref_name, joins) in join_tree:
            if new_id in joined_ids:
                continue
            on_parts = [
                f"{alias_map[p_id]}.{j['parent_col']}"
                f" = {alias_map[c_id]}.{j['child_col']}" for j in joins
            ]
            joined_ids.add(new_id)
            selected = new_id in alias_of_table
            if selected:
                join_notes.append(
                    f"已按外键 {ref_name or '-'} 自动 JOIN {code_of_table[new_id]}")
            else:
                join_notes.append(
                    f"经中间表 {code_of_table[new_id]}"
                    f"（外键 {ref_name or '-'}）桥接关联路径")
            from_lines.append(
                f"JOIN {code_of_table[new_id]} {alias_map[new_id]}"
                f" ON {' AND '.join(on_parts)}"
                + ("" if selected else "  -- 关联中间表"))
        for tid in unreachable:
            t = next(t for t in table_infos if t["detail"]["id"] == tid)
            warnings.append(
                f"表 {t['detail']['table_code']} 与已选表无已知外键关联，"
                "已按 CROSS JOIN 输出，请自行确认 JOIN 条件")
            from_lines.append(
                f"CROSS JOIN {t['detail']['table_code']} {t['alias']}"
                f"  /* 警告：无已知外键关联，请自行确认 JOIN 条件 */")

    # ---- WHERE ----
    where_parts = []
    for cond in conditions or []:
        op = str(cond.get("op", "")).upper().strip()
        if op not in COND_OPS:
            raise DictError(f"运算符非法: {op}，支持: {', '.join(COND_OPS)}")
        c_alias = str(cond.get("table_alias", "")).strip()
        t = next((t for t in table_infos if t["alias"] == c_alias), None)
        if t is None:
            raise DictError(f"条件引用了未选择的表别名: {c_alias or '(空)'}")
        col_code = str(cond.get("column", "")).strip()
        col = next((c for c in t["detail"]["columns"]
                    if c["col_code"] == col_code), None)
        if col is None:
            raise DictError(
                f"表 {t['detail']['table_code']} 不存在字段: {col_code}")
        where_parts.append(format_condition(
            f"{c_alias}.{col_code}", op, cond.get("value"), col.get("data_type")))

    if use_rownum:
        limit = int(limit or DEFAULT_ROW_LIMIT)
        if not (1 <= limit <= MAX_ROW_LIMIT):
            raise DictError(f"行数限制须为 1~{MAX_ROW_LIMIT} 的整数: {limit}")
        where_parts.append(f"ROWNUM <= {limit}")

    sql = "SELECT\n" + select_clause + "\n" + "\n".join(from_lines)
    if where_parts:
        sql += "\nWHERE " + "\n  AND ".join(where_parts)

    # ---- 自证只读 ----
    validate_select_only(sql)

    return {"sql": sql, "joins": join_notes, "warnings": warnings}
