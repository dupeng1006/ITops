# -*- coding: utf-8 -*-
"""
PDM 数据字典解析导入单元测试

覆盖：
    A. fixture 迷你模型（tests/fixtures/pdm/mini_order.pdm）：
       - Package 嵌套表与 Model 直挂表均解析；
       - 主键标识（c:PrimaryKey → Key.Columns）；
       - 外键 Joins 解析（Object1/Object2 父子方向按列归属判定）；
       - 无 Joins 关联经 ParentKey 同名列推导（fallback）；
    B. 真实 PDM 目录（D:\\ITOps\\pdm-dictionary，不存在则整组 SKIP 不计失败）：
       - 20 个 XML 文件全量导入，二进制旧格式文件自动跳过；
       - 基线：4083 表 / 84176 字段 / 58 关联（grep 原始 XML 复核一致）；
         ※ 早期口述基线 4821/92638 含二进制文件（通用版投资管理系统.pdm，
           738 表/8462 字段无法 XML 解析），XML 可解析部分即 4083/84176；
       - 抽验 TTempFundCommision = 11 字段（grep 原始 XML 证实；
         早期口述"20 字段"与真实文件不符，如实记录待复核）。

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\unit\\test_pdm_import.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-20
"""

import sqlite3
import sys
import tempfile
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from scripts.import_pdm import build_dictionary, parse_pdm  # noqa: E402

FIXTURE_DIR = SERVER_ROOT / "tests" / "fixtures" / "pdm"
REAL_PDM_DIR = Path(r"D:\ITOps\pdm-dictionary")

failures: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


def skip(name: str, reason: str) -> None:
    print(f"[SKIP] {name}  -- {reason}")


# =============================================================================
# A. fixture 迷你模型解析
# =============================================================================

def test_fixture_parse() -> None:
    parsed = parse_pdm(FIXTURE_DIR / "mini_order.pdm")
    tables = {t["code"]: t for t in parsed["tables"]}

    check("A1 fixture 解析出 4 张表", len(parsed["tables"]) == 4,
          f"实际 {len(parsed['tables'])}")
    check("A2 Package 嵌套表解析（TORDER/TORDERDETAIL）",
          "TORDER" in tables and "TORDERDETAIL" in tables)
    check("A3 Model 直挂表解析（TPRODUCT/TORDERPAY）",
          "TPRODUCT" in tables and "TORDERPAY" in tables)

    torder = tables.get("TORDER", {})
    check("A4 表中文名与注释", torder.get("name") == "订单表"
          and "测试用" in (torder.get("comment") or ""))
    pk_cols = [c["code"] for c in torder.get("columns", []) if c["is_pk"]]
    check("A5 主键标识 l_order_id", pk_cols == ["l_order_id"], f"实际 {pk_cols}")
    check("A6 字段序号连续",
          [c["seq"] for c in torder.get("columns", [])] == [1, 2, 3, 4, 5])
    check("A7 字段类型解析",
          next(c for c in torder["columns"] if c["code"] == "d_order_date")
          ["data_type"] == "DATE")

    refs = {r["name"]: r for r in parsed["references"]}
    check("A8 解析出 2 个外键关联", len(refs) == 2, f"实际 {len(refs)}")
    fk = refs.get("FK_DETAIL_ORDER", {})
    check("A9 Joins 父子方向正确（父 TORDER.l_order_id）",
          len(fk.get("joins", [])) == 1
          and fk["joins"][0]["parent_col_xid"] == "o101"
          and fk["joins"][0]["child_col_xid"] == "o202",
          f"实际 {fk.get('joins')}")
    fk2 = refs.get("FK_PAY_ORDER", {})
    check("A10 无 Joins 经 ParentKey 同名列推导",
          len(fk2.get("joins", [])) == 1
          and fk2["joins"][0]["parent_col_xid"] == "o101"
          and fk2["joins"][0]["child_col_xid"] == "o402",
          f"实际 {fk2.get('joins')}")


def test_fixture_build_db() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="dict_fixture_")) / "dictionary.db"
    stats = build_dictionary(FIXTURE_DIR, tmp)
    check("A11 fixture 建库统计", stats["models"] == 1 and stats["tables"] == 4
          and stats["columns"] == 14 and stats["references"] == 2,
          f"实际 {stats}")

    conn = sqlite3.connect(str(tmp))
    conn.row_factory = sqlite3.Row
    r = conn.execute(
        "SELECT c.col_code, c.is_pk, t.table_code FROM dict_column c"
        " JOIN dict_table t ON t.id = c.table_id"
        " WHERE t.table_code = 'TORDERDETAIL' AND c.col_code = 'l_order_id'"
    ).fetchone()
    check("A12 明细表外键列非主键", r is not None and r["is_pk"] == 0)
    r = conn.execute(
        "SELECT joins_json FROM dict_reference WHERE ref_name = 'FK_PAY_ORDER'"
    ).fetchone()
    check("A13 推导关联字段对落库",
          r is not None and '"parent_col": "l_order_id"' in r["joins_json"],
          f"实际 {r['joins_json'] if r else None}")
    conn.close()


# =============================================================================
# B. 真实 PDM 目录全量基线
# =============================================================================

def test_real_baseline() -> None:
    if not REAL_PDM_DIR.exists():
        skip("B1~B5 真实 PDM 目录基线", f"目录不存在: {REAL_PDM_DIR}")
        return
    tmp = Path(tempfile.mkdtemp(prefix="dict_real_")) / "dictionary.db"
    stats = build_dictionary(REAL_PDM_DIR, tmp)

    check("B1 20 个 XML 模型导入 + 1 个二进制文件跳过",
          stats["models"] == 20 and stats["skipped_files"] == ["通用版投资管理系统.pdm"],
          f"实际 models={stats['models']} skipped={stats['skipped_files']}")
    check("B2 表数基线 4083（grep XML 复核口径）", stats["tables"] == 4083,
          f"实际 {stats['tables']}")
    check("B3 字段数基线 84176", stats["columns"] == 84176,
          f"实际 {stats['columns']}")
    check("B4 关联数基线 58", stats["references"] == 58,
          f"实际 {stats['references']}")

    conn = sqlite3.connect(str(tmp))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT t.id, m.file_name FROM dict_table t JOIN dict_model m"
        " ON m.id = t.model_id WHERE t.table_code = 'TTempFundCommision'"
    ).fetchall()
    counts = [
        conn.execute("SELECT COUNT(*) c FROM dict_column WHERE table_id = ?",
                     (r["id"],)).fetchone()["c"]
        for r in rows
    ]
    check("B5 抽验 TTempFundCommision = 11 字段（2 个模型同表）",
          len(rows) == 2 and all(c == 11 for c in counts),
          f"实际 {[(r['file_name'], c) for r, c in zip(rows, counts)]}")
    conn.close()


if __name__ == "__main__":
    test_fixture_parse()
    test_fixture_build_db()
    test_real_baseline()
    print(f"\n{'全部通过' if not failures else f'{len(failures)} 项失败'}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(0 if not failures else 1)
