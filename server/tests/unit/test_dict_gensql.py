# -*- coding: utf-8 -*-
"""
数据字典 SQL 生成器单元测试（基于 fixture 迷你字典库）

覆盖：
    A. 单表：全列/选列、中文注释、默认 ROWNUM、关 ROWNUM、自定义 limit
    B. 多表：外键自动 JOIN（含 ON 方向）、joins 说明、无关联 CROSS 警告
    C. 条件：全部运算符白名单、值转义防注入（单引号双写）、IN/BETWEEN 拆分、
       IS NULL、DATE 列 TO_DATE、数字不加引号、非法运算符/列/别名拒绝
    D. 安全：所有生成 SQL 必须过 sql_guard 只读校验；恶意值不改变语句结构

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\unit\\test_dict_gensql.py
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

from app.datasource.sql_guard import validate_select_only  # noqa: E402
from app.services import dict_service  # noqa: E402
from app.services.dict_service import DictError  # noqa: E402
from scripts.import_pdm import build_dictionary  # noqa: E402

FIXTURE_DIR = SERVER_ROOT / "tests" / "fixtures" / "pdm"

failures: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(f"{name}: {detail}")


# ---- 共享 fixture 字典库 ----
_DB = Path(tempfile.mkdtemp(prefix="dict_gensql_")) / "dictionary.db"
build_dictionary(FIXTURE_DIR, _DB)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{_DB}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _tid(conn, code: str) -> int:
    return conn.execute("SELECT id FROM dict_table WHERE table_code = ?",
                        (code,)).fetchone()["id"]


def _gen_ok(name: str, conn, tables, conditions=None, limit=500, use_rownum=True) -> dict:
    """生成并自证过 guard；失败记 FAIL 并返回 None"""
    try:
        result = dict_service.generate_sql(
            conn, tables, conditions or [], limit=limit, use_rownum=use_rownum)
        validate_select_only(result["sql"])  # 独立再过一遍 guard
        return result
    except Exception as e:  # noqa: BLE001
        check(f"{name}（生成应成功且过 guard）", False, str(e))
        return {}


def _gen_err(name: str, conn, tables, conditions=None, expect: str = "") -> None:
    try:
        dict_service.generate_sql(conn, tables, conditions or [])
        check(name, False, "应抛 DictError 却成功生成")
    except DictError as e:
        ok = expect in str(e)
        check(name, ok, f"提示未含 '{expect}': {e}")


# =============================================================================
# A. 单表
# =============================================================================

def test_single_table() -> None:
    conn = _conn()
    t = _tid(conn, "TORDER")

    r = _gen_ok("A1 单表全列", conn, [{"table_id": t, "columns": [], "alias": None}])
    sql = r.get("sql", "")
    check("A2 默认 ROWNUM 500", "ROWNUM <= 500" in sql)
    check("A3 中文列注释", "-- 订单编号" in sql)
    check("A4 FROM 带默认别名 t1", "FROM TORDER t1" in sql)

    r = _gen_ok("A5 单表选列+自定义别名",
                conn, [{"table_id": t, "columns": ["vc_order_no", "en_amount"],
                        "alias": "od"}])
    sql = r.get("sql", "")
    check("A6 仅两列且别名生效",
          "od.vc_order_no" in sql and "od.en_amount" in sql
          and "l_order_id" not in sql and "FROM TORDER od" in sql, sql)

    r = _gen_ok("A7 关闭 ROWNUM", conn,
                [{"table_id": t, "columns": ["vc_order_no"], "alias": None}],
                use_rownum=False)
    check("A8 无 ROWNUM 子句", "ROWNUM" not in r.get("sql", ""))

    r = _gen_ok("A9 自定义 limit", conn,
                [{"table_id": t, "columns": ["vc_order_no"], "alias": None}],
                limit=50)
    check("A10 ROWNUM <= 50", "ROWNUM <= 50" in r.get("sql", ""))
    conn.close()


# =============================================================================
# B. 多表 JOIN
# =============================================================================

def test_multi_table() -> None:
    conn = _conn()
    t_order = _tid(conn, "TORDER")
    t_detail = _tid(conn, "TORDERDETAIL")
    t_product = _tid(conn, "TPRODUCT")

    r = _gen_ok("B1 双表自动 JOIN", conn,
                [{"table_id": t_order, "columns": ["vc_order_no"], "alias": None},
                 {"table_id": t_detail, "columns": ["en_qty"], "alias": None}])
    sql = r.get("sql", "")
    check("B2 JOIN 与 ON 方向（父.子等值）",
          "JOIN TORDERDETAIL t2 ON t1.l_order_id = t2.l_order_id" in sql, sql)
    check("B3 joins 说明含外键名",
          any("FK_DETAIL_ORDER" in j and "TORDERDETAIL" in j
              for j in r.get("joins", [])), str(r.get("joins")))
    check("B4 无警告", r.get("warnings") == [])

    r = _gen_ok("B5 无关联表 CROSS 警告", conn,
                [{"table_id": t_order, "columns": ["vc_order_no"], "alias": None},
                 {"table_id": t_product, "columns": ["vc_product_name"], "alias": None}])
    sql = r.get("sql", "")
    check("B6 CROSS JOIN 输出", "CROSS JOIN TPRODUCT t2" in sql, sql)
    check("B7 警告文案（无已知关联，请自行确认 JOIN 条件）",
          any("无已知" in w and "JOIN" in w for w in r.get("warnings", [])),
          str(r.get("warnings")))

    # 三表：TORDERDETAIL ↔ TORDER ↔ TORDERPAY（经 TORDER 桥接）
    t_pay = _tid(conn, "TORDERPAY")
    r = _gen_ok("B8 三表链路 JOIN", conn,
                [{"table_id": t_detail, "columns": ["l_id"], "alias": None},
                 {"table_id": t_pay, "columns": ["en_pay_amount"], "alias": None}])
    sql = r.get("sql", "")
    check("B9 中间表 TORDER 自动桥接",
          "JOIN TORDER" in sql and "TORDERDETAIL" in sql and "TORDERPAY" in sql,
          sql)
    check("B10 joins 说明提及中间表桥接",
          any("中间表" in j for j in r.get("joins", [])), str(r.get("joins")))
    conn.close()


# =============================================================================
# C. 条件构造
# =============================================================================

def test_conditions() -> None:
    conn = _conn()
    t = _tid(conn, "TORDER")
    base = [{"table_id": t, "columns": ["vc_order_no"], "alias": None}]

    def one(op, value, col="vc_order_no"):
        return _gen_ok(f"C 条件 {op}", conn, base,
                       [{"table_alias": "t1", "column": col,
                         "op": op, "value": value}]).get("sql", "")

    sql = one("=", "ABC123")
    check("C1 字符串加单引号", "t1.vc_order_no = 'ABC123'" in sql, sql)
    sql = one("=", "O'Brien")
    check("C2 单引号双写转义防注入", "'O''Brien'" in sql, sql)
    sql = one("!=", 100)
    check("C3 数字不加引号", "!= 100" in sql, sql)
    sql = one(">=", "-3.5")
    check("C4 负数小数原样", ">= -3.5" in sql, sql)
    sql = one("LIKE", "ORD%")
    check("C5 LIKE 通配", "LIKE 'ORD%'" in sql, sql)
    sql = one("IN", "A,B，C\nD")
    check("C6 IN 中英文逗号/换行拆分",
          "IN ('A', 'B', 'C', 'D')" in sql, sql)
    sql = one("BETWEEN", "1,100", col="en_amount")
    check("C7 BETWEEN 两值数字", "BETWEEN 1 AND 100" in sql, sql)
    sql = one("IS NULL", None, col="vc_status")
    check("C8 IS NULL 无值", "t1.vc_status IS NULL" in sql, sql)
    sql = one("IS NOT NULL", None, col="vc_status")
    check("C9 IS NOT NULL", "t1.vc_status IS NOT NULL" in sql, sql)
    sql = one(">=", "2026-01-01", col="d_order_date")
    check("C10 DATE 列自动 TO_DATE",
          "t1.d_order_date >= TO_DATE('2026-01-01', 'YYYY-MM-DD')" in sql, sql)

    # 恶意值：分号/注释/写关键字注入尝试
    sql = one("=", "x'; DROP TABLE t; --")
    check("C11 注入值被整体包裹转义",
          "'x''; DROP TABLE t; --'" in sql and sql.strip().startswith("SELECT"),
          sql)

    _gen_err("C12 非法运算符拒绝", conn, base,
             [{"table_alias": "t1", "column": "vc_order_no",
               "op": "REGEXP", "value": "x"}], expect="运算符非法")
    _gen_err("C13 未声明别名拒绝", conn, base,
             [{"table_alias": "t9", "column": "vc_order_no",
               "op": "=", "value": "x"}], expect="未选择的表别名")
    _gen_err("C14 不存在字段拒绝", conn, base,
             [{"table_alias": "t1", "column": "hack_col",
               "op": "=", "value": "x"}], expect="不存在字段")
    _gen_err("C15 空值条件拒绝", conn, base,
             [{"table_alias": "t1", "column": "vc_order_no",
               "op": "=", "value": "  "}], expect="条件值不能为空")
    _gen_err("C16 BETWEEN 单值拒绝", conn, base,
             [{"table_alias": "t1", "column": "en_amount",
               "op": "BETWEEN", "value": "100"}], expect="BETWEEN 需要恰好 2 个值")
    _gen_err("C17 选列不存在拒绝", conn,
             [{"table_id": t, "columns": ["no_such_col"], "alias": None}],
             expect="不存在字段")
    _gen_err("C18 别名重复拒绝", conn,
             [{"table_id": t, "columns": [], "alias": "a"},
              {"table_id": t, "columns": [], "alias": "a"}],
             expect="别名重复")
    _gen_err("C19 空表集拒绝", conn, [], expect="至少选择一张表")
    conn.close()


if __name__ == "__main__":
    test_single_table()
    test_multi_table()
    test_conditions()
    print(f"\n{'全部通过' if not failures else f'{len(failures)} 项失败'}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(0 if not failures else 1)
