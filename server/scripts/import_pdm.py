# -*- coding: utf-8 -*-
"""
O32 日常运维平台 —— PDM 数据字典导入工具（数据字典查询）

解析 PowerDesigner 15/16 XML 格式 .pdm 文件，重建独立字典库 dictionary.db：

    dict_model      模型文件清单（文件名/业务组/表数/字段数/导入时间）
    dict_table      表（模型ID/表代码/中文名/注释）
    dict_column     字段（表ID/字段代码/中文名/数据类型/是否主键/序号/注释）
    dict_reference  外键关联（父表/子表/关联字段对 JSON，供 JOIN 推导）

解析要点：
    - 命名空间 xmlns:a=attribute xmlns:c=collection xmlns:o=object；
    - 仅收集带 Id 属性的元素（<o:Table Ref="..."/> 为引用，跳过）；
    - 主键：c:PrimaryKey → o:Key Ref → c:Key.Columns 列引用集合；
    - 外键：o:Reference 的 c:Joins/o:ReferenceJoin（Object1/Object2 按列实际
      归属表判定父子方向）；无 Joins 时经 c:ParentKey 主键列与子表同名列推导；
    - 非 XML 旧格式（二进制）文件解析失败自动跳过并计入 skipped_files。

用法（工作目录 server/）：
    .venv\\Scripts\\python.exe scripts/import_pdm.py --dir D:\\ITOps\\pdm-dictionary
    .venv\\Scripts\\python.exe scripts/import_pdm.py --dir <pdm目录> --db <字典库路径>

注意：PDM 文件不进部署包，字典库随包交付；模型更新后重跑本脚本即可。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import argparse
import json
import logging
import sqlite3
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("import_pdm")

NS = {"a": "attribute", "c": "collection", "o": "object"}
A = f"{{{NS['a']}}}"
C = f"{{{NS['c']}}}"
O = f"{{{NS['o']}}}"

SCHEMA_SQL = """
DROP TABLE IF EXISTS dict_reference;
DROP TABLE IF EXISTS dict_column;
DROP TABLE IF EXISTS dict_table;
DROP TABLE IF EXISTS dict_model;

CREATE TABLE dict_model (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name    TEXT NOT NULL UNIQUE,   -- PDM 文件名
    model_name   TEXT NOT NULL,          -- 模型名（PDM 内 a:Name）
    biz_group    TEXT NOT NULL,          -- 业务组（从文件名提取）
    table_count  INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    imported_at  TEXT NOT NULL           -- 导入时间 YYYY-MM-DD HH:MM:SS
);

CREATE TABLE dict_table (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id   INTEGER NOT NULL REFERENCES dict_model(id),
    table_code TEXT NOT NULL,            -- 表代码（Oracle 表名）
    table_name TEXT,                     -- 中文名
    comment    TEXT,
    UNIQUE (model_id, table_code)
);
CREATE INDEX idx_dict_table_code ON dict_table(table_code);

CREATE TABLE dict_column (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    table_id  INTEGER NOT NULL REFERENCES dict_table(id),
    col_code  TEXT NOT NULL,             -- 字段代码
    col_name  TEXT,                      -- 中文字段名
    data_type TEXT,                      -- 数据类型（如 VARCHAR2(30)）
    is_pk     INTEGER NOT NULL DEFAULT 0,
    seq       INTEGER NOT NULL,          -- 字段序号（PDM 内出现顺序，1 起）
    comment   TEXT
);
CREATE INDEX idx_dict_column_table ON dict_column(table_id);
CREATE INDEX idx_dict_column_code ON dict_column(col_code);

CREATE TABLE dict_reference (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id        INTEGER NOT NULL REFERENCES dict_model(id),
    ref_name        TEXT,                -- 关联名（如 ZRT_FK_1_USER）
    parent_table_id INTEGER NOT NULL REFERENCES dict_table(id),
    child_table_id  INTEGER NOT NULL REFERENCES dict_table(id),
    joins_json      TEXT NOT NULL        -- [{"parent_col": "...", "child_col": "..."}]
);
CREATE INDEX idx_dict_ref_parent ON dict_reference(parent_table_id);
CREATE INDEX idx_dict_ref_child ON dict_reference(child_table_id);
"""


def _text(elem, tag: str):
    """取 a: 属性文本，缺失返回 None"""
    child = elem.find(f"{A}{tag}")
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def biz_group_of(file_name: str) -> str:
    """从文件名提取业务组：去"投资管理系统O3.2_"类前缀与扩展名"""
    stem = Path(file_name).stem
    for prefix in ("投资管理系统O3.2_", "投资管理系统o3.2_",
                   "投资管理系统O3.2", "投资管理系统o3.2"):
        if stem.startswith(prefix):
            stem = stem[len(prefix):].lstrip("_")
            break
    return stem or Path(file_name).stem


def parse_pdm(path: Path) -> dict:
    """
    解析单个 PDM 文件

    Returns:
        {
            "model_name": str,
            "tables": [ {xid, code, name, comment,
                         columns: [{xid, code, name, data_type, is_pk, seq, comment}]} ],
            "references": [ {name, parent_xid, child_xid,
                             joins: [{parent_col_xid, child_col_xid}]} ],
        }

    Raises:
        ET.ParseError 等：非 XML 格式（如二进制旧版）时抛出，由调用方跳过
    """
    tree = ET.parse(str(path))
    root = tree.getroot()

    # ---- 第一遍：表与字段、键 ----
    tables = []                 # 定义顺序
    table_by_xid = {}           # xid -> table dict
    column_owner = {}           # column xid -> table xid
    key_columns = {}            # key xid -> [column xid]

    for elem in root.iter(f"{O}Table"):
        xid = elem.get("Id")
        if not xid:
            continue  # <o:Table Ref="..."/> 引用，跳过
        table = {
            "xid": xid,
            "code": _text(elem, "Code") or "",
            "name": _text(elem, "Name"),
            "comment": _text(elem, "Comment"),
            "columns": [],
            "_pk_xids": set(),
            "_key_refs": [],     # (key_xid, [column_xid])
        }
        # 字段
        cols_elem = elem.find(f"{C}Columns")
        if cols_elem is not None:
            seq = 0
            for col in cols_elem.iter(f"{O}Column"):
                col_xid = col.get("Id")
                if not col_xid:
                    continue  # Ref 引用（理论上不出现于此）
                seq += 1
                table["columns"].append({
                    "xid": col_xid,
                    "code": _text(col, "Code") or "",
                    "name": _text(col, "Name"),
                    "data_type": _text(col, "DataType"),
                    "comment": _text(col, "Comment"),
                    "seq": seq,
                })
                column_owner[col_xid] = xid
        # 键（含主键引用）
        keys_elem = elem.find(f"{C}Keys")
        if keys_elem is not None:
            for key in keys_elem.iter(f"{O}Key"):
                key_xid = key.get("Id")
                if not key_xid:
                    continue
                col_refs = [
                    c.get("Ref")
                    for c in key.iter(f"{O}Column")
                    if c.get("Ref")
                ]
                key_columns[key_xid] = col_refs
                table["_key_refs"].append(key_xid)
        pk_elem = elem.find(f"{C}PrimaryKey/{O}Key")
        if pk_elem is not None and pk_elem.get("Ref"):
            table["_pk_key"] = pk_elem.get("Ref")
        else:
            table["_pk_key"] = None
        tables.append(table)
        table_by_xid[xid] = table

    # 主键列标记
    for table in tables:
        pk_xids = set(key_columns.get(table["_pk_key"], [])) if table["_pk_key"] else set()
        for col in table["columns"]:
            col["is_pk"] = 1 if col["xid"] in pk_xids else 0

    # 模型名（根 Model 的 a:Name）
    model_elem = next(root.iter(f"{O}Model"), None)
    model_name = _text(model_elem, "Name") if model_elem is not None else None

    # ---- 第二遍：外键关联 ----
    references = []
    for elem in root.iter(f"{O}Reference"):
        if not elem.get("Id"):
            continue
        parent_ref = elem.find(f"{C}ParentTable/{O}Table")
        child_ref = elem.find(f"{C}ChildTable/{O}Table")
        if parent_ref is None or child_ref is None:
            continue
        parent_xid = parent_ref.get("Ref")
        child_xid = child_ref.get("Ref")
        if parent_xid not in table_by_xid or child_xid not in table_by_xid:
            continue  # 跨模型引用（目标表不在本文件），跳过

        joins = []
        joins_elem = elem.find(f"{C}Joins")
        if joins_elem is not None:
            for rj in joins_elem.iter(f"{O}ReferenceJoin"):
                obj1 = rj.find(f"{C}Object1/{O}Column")
                obj2 = rj.find(f"{C}Object2/{O}Column")
                if obj1 is None or obj2 is None:
                    continue
                c1, c2 = obj1.get("Ref"), obj2.get("Ref")
                # 按列实际归属表判定父子方向
                if column_owner.get(c1) == parent_xid:
                    joins.append({"parent_col_xid": c1, "child_col_xid": c2})
                elif column_owner.get(c2) == parent_xid:
                    joins.append({"parent_col_xid": c2, "child_col_xid": c1})

        # 无 Joins 时经 ParentKey 主键列与子表同名列推导
        if not joins:
            pk_ref = elem.find(f"{C}ParentKey/{O}Key")
            if pk_ref is not None and pk_ref.get("Ref"):
                parent_pk_cols = key_columns.get(pk_ref.get("Ref"), [])
                child_by_code = {
                    c["code"].upper(): c for c in table_by_xid[child_xid]["columns"]
                }
                for pc_xid in parent_pk_cols:
                    pc = next((c for c in table_by_xid[parent_xid]["columns"]
                               if c["xid"] == pc_xid), None)
                    if pc is None:
                        continue
                    match = child_by_code.get(pc["code"].upper())
                    if match is not None:
                        joins.append({"parent_col_xid": pc_xid,
                                      "child_col_xid": match["xid"]})

        if not joins:
            continue  # 无法推导字段对，跳过该关联
        references.append({
            "name": _text(elem, "Code") or _text(elem, "Name"),
            "parent_xid": parent_xid,
            "child_xid": child_xid,
            "joins": joins,
        })

    return {"model_name": model_name or path.stem,
            "tables": tables, "references": references}


def build_dictionary(pdm_dir: Path, db_path: Path) -> dict:
    """
    扫描目录解析全部 PDM，重建字典库（整库 DROP 重建）

    Returns:
        统计 dict：files/skipped_files/models/tables/columns/references
    """
    pdm_dir = Path(pdm_dir)
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_SQL)
        imported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats = {"files": 0, "skipped_files": [], "models": 0,
                 "tables": 0, "columns": 0, "references": 0}

        for pdm_file in sorted(pdm_dir.glob("*.pdm")):
            stats["files"] += 1
            try:
                parsed = parse_pdm(pdm_file)
            except Exception as e:  # noqa: BLE001  二进制旧格式等，跳过
                logger.warning(f"跳过无法解析的文件 {pdm_file.name}: {e}")
                stats["skipped_files"].append(pdm_file.name)
                continue

            tables = parsed["tables"]
            col_total = sum(len(t["columns"]) for t in tables)
            cur = conn.execute(
                "INSERT INTO dict_model(file_name, model_name, biz_group,"
                " table_count, column_count, imported_at) VALUES(?,?,?,?,?,?)",
                (pdm_file.name, parsed["model_name"], biz_group_of(pdm_file.name),
                 len(tables), col_total, imported_at),
            )
            model_id = cur.lastrowid
            stats["models"] += 1

            table_id_by_xid = {}
            col_code_by_xid = {}
            for t in tables:
                cur = conn.execute(
                    "INSERT INTO dict_table(model_id, table_code, table_name, comment)"
                    " VALUES(?,?,?,?)",
                    (model_id, t["code"], t["name"], t["comment"]),
                )
                tid = cur.lastrowid
                table_id_by_xid[t["xid"]] = tid
                for c in t["columns"]:
                    col_code_by_xid[c["xid"]] = c["code"]
                conn.executemany(
                    "INSERT INTO dict_column(table_id, col_code, col_name,"
                    " data_type, is_pk, seq, comment) VALUES(?,?,?,?,?,?,?)",
                    [(tid, c["code"], c["name"], c["data_type"],
                      c["is_pk"], c["seq"], c["comment"]) for c in t["columns"]],
                )
            stats["tables"] += len(tables)
            stats["columns"] += col_total

            ref_rows = []
            for r in parsed["references"]:
                joins = [
                    {"parent_col": col_code_by_xid.get(j["parent_col_xid"], ""),
                     "child_col": col_code_by_xid.get(j["child_col_xid"], "")}
                    for j in r["joins"]
                ]
                joins = [j for j in joins if j["parent_col"] and j["child_col"]]
                if not joins:
                    continue
                ref_rows.append((
                    model_id, r["name"],
                    table_id_by_xid[r["parent_xid"]], table_id_by_xid[r["child_xid"]],
                    json.dumps(joins, ensure_ascii=False),
                ))
            conn.executemany(
                "INSERT INTO dict_reference(model_id, ref_name, parent_table_id,"
                " child_table_id, joins_json) VALUES(?,?,?,?,?)",
                ref_rows,
            )
            stats["references"] += len(ref_rows)

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return stats


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(levelname)s - %(message)s")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.config import get_settings  # 延迟导入（需先就位 sys.path）

    parser = argparse.ArgumentParser(description="PDM 数据字典导入（重建 dictionary.db）")
    parser.add_argument("--dir", required=True, help="PDM 文件所在目录")
    parser.add_argument("--db", default=None,
                        help="字典库输出路径（默认 O32OPS_DICT_DB_PATH 或 data/dictionary.db）")
    args = parser.parse_args()

    db_path = Path(args.db) if args.db else get_settings().DICT_DB_PATH
    logger.info(f"开始导入: 目录={args.dir} → 字典库={db_path}")
    stats = build_dictionary(Path(args.dir), db_path)
    logger.info(
        "导入完成: 文件 %d 个（跳过 %d: %s）；模型 %d；表 %d；字段 %d；关联 %d",
        stats["files"], len(stats["skipped_files"]),
        ",".join(stats["skipped_files"]) or "无",
        stats["models"], stats["tables"], stats["columns"], stats["references"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
