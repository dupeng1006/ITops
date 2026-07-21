# -*- coding: utf-8 -*-
"""
SQL Guard（只读白名单）单元测试 —— 数据源模块最重要的安全门禁

覆盖：
    A. 合法放行：各类 SELECT / WITH / 子查询 / UNION / 注释前后缀 /
       字符串内分号与危险词 / 保留字列名（comment/start/set）/ REPLACE 函数
    B. 非法拦截：INSERT/UPDATE/DELETE/MERGE/REPLACE 写操作、全部 DDL、DCL、
       CALL/EXEC/存储过程、多语句、SELECT INTO、FOR UPDATE、
       LOCK IN SHARE MODE、WITH 包裹写、注释绕过、空 SQL
    C. 边界：字符串字面量内的危险词不误伤、大小写混合、空白/注释填充

运行（工作目录 server/）：
    .venv\\Scripts\\python.exe tests\\unit\\test_sql_guard.py
退出码：全部通过 0；任一失败非零。

作者：技术部
版本：1.0.0
日期：2026-07-18
"""

import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

# Windows 控制台中文/符号输出兼容
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

from app.datasource.sql_guard import SqlGuardError, validate_select_only  # noqa: E402

failures: list = []


def check_pass(name: str, sql: str) -> None:
    try:
        out = validate_select_only(sql)
        print(f"[PASS] 放行 | {name}")
    except SqlGuardError as e:
        print(f"[FAIL] 放行 | {name}  -- 被误拦: {e}")
        failures.append(f"{name}: 合法 SQL 被误拦: {e}")


def check_block(name: str, sql: str, expect_keyword: str = "") -> None:
    try:
        validate_select_only(sql)
        print(f"[FAIL] 拦截 | {name}  -- 未被拦截（放行）")
        failures.append(f"{name}: 非法 SQL 未被拦截")
    except SqlGuardError as e:
        msg = str(e)
        if expect_keyword and expect_keyword not in msg:
            print(f"[FAIL] 拦截 | {name}  -- 提示未含 '{expect_keyword}': {msg}")
            failures.append(f"{name}: 拦截提示缺少 '{expect_keyword}'")
        else:
            print(f"[PASS] 拦截 | {name}  -- {msg[:60]}")


def main() -> int:
    print("=" * 70)
    print("A. 合法语句放行（不得误拦）")
    print("=" * 70)
    check_pass("简单 SELECT", "SELECT * FROM fund_asset")
    check_pass("小写 select", "select code, name from t")
    check_pass("大小写混合 SeLeCt", "SeLeCt * FROM t")
    check_pass("带 WHERE/ORDER/GROUP", "SELECT code, SUM(amt) FROM t WHERE dt='20260701' GROUP BY code ORDER BY code")
    check_pass("子查询", "SELECT * FROM t WHERE code IN (SELECT code FROM x WHERE flag=1)")
    check_pass("JOIN", "SELECT a.*, b.name FROM t a LEFT JOIN x b ON a.id=b.id")
    check_pass("UNION", "SELECT code FROM t1 UNION ALL SELECT code FROM t2")
    check_pass("WITH 单 CTE", "WITH a AS (SELECT 1 AS x) SELECT * FROM a")
    check_pass("WITH 多 CTE", "WITH a AS (SELECT 1 AS x), b AS (SELECT 2 AS y) SELECT * FROM a JOIN b ON a.x=b.y")
    check_pass("WITH RECURSIVE", "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x+1 FROM n WHERE x<5) SELECT * FROM n")
    check_pass("行首单行注释", "-- 查询说明\nSELECT * FROM t")
    check_pass("行首块注释", "/* 查询说明 */ SELECT * FROM t")
    check_pass("行尾分号", "SELECT * FROM t;")
    check_pass("行尾分号+注释", "SELECT * FROM t; -- end")
    check_pass("行尾分号+块注释", "SELECT * FROM t; /* end */")
    check_pass("前导空白换行", "  \n\t SELECT * FROM t")
    check_pass("字符串内含分号", "SELECT * FROM t WHERE memo='a;b;c'")
    check_pass("字符串内含危险词", "SELECT * FROM t WHERE memo='delete drop insert'")
    check_pass("字符串内含注释符", "SELECT * FROM t WHERE memo='-- not comment' AND x='/*'")
    check_pass("别名含危险词形", "SELECT code AS update_time, name AS deleted_flag FROM t")
    check_pass("REPLACE 函数", "SELECT REPLACE(col, 'a', 'b') FROM t")
    check_pass("保留字列名 comment", "SELECT comment FROM t")
    check_pass("保留字列名 start/set", "SELECT start, [set] FROM t")
    check_pass("限定名含保留字", "SELECT c.comment, c.start FROM t c")
    check_pass("Oracle 风格 hint 注释", "SELECT /*+ INDEX(t idx_code) */ * FROM t")
    check_pass("绑定参数", "SELECT * FROM t WHERE biz_date = :biz_date AND code = :code")
    check_pass("CAST/窗口函数", "SELECT code, ROW_NUMBER() OVER (PARTITION BY grp ORDER BY amt DESC) rn FROM t")

    print("=" * 70)
    print("B. 非法语句拦截（必须全部拦下）")
    print("=" * 70)
    check_block("INSERT", "INSERT INTO t VALUES (1)", "INSERT")
    check_block("INSERT SELECT", "INSERT INTO t SELECT * FROM x", "INSERT")
    check_block("UPDATE", "UPDATE t SET x=1", "UPDATE")
    check_block("DELETE", "DELETE FROM t WHERE id=1", "DELETE")
    check_block("MERGE", "MERGE INTO t USING x ON t.id=x.id WHEN MATCHED THEN UPDATE SET y=1", "MERGE")
    check_block("REPLACE 语句(MySQL)", "REPLACE INTO t VALUES (1)", "REPLACE")
    check_block("DROP TABLE", "DROP TABLE t", "DROP")
    check_block("CREATE TABLE", "CREATE TABLE t (id INT)", "CREATE")
    check_block("CREATE INDEX", "CREATE INDEX i ON t(c)", "CREATE")
    check_block("ALTER TABLE", "ALTER TABLE t ADD COLUMN c INT", "ALTER")
    check_block("TRUNCATE", "TRUNCATE TABLE t", "TRUNCATE")
    check_block("RENAME", "RENAME TABLE a TO b", "RENAME")
    check_block("GRANT", "GRANT SELECT ON t TO u", "GRANT")
    check_block("REVOKE", "REVOKE SELECT ON t FROM u", "REVOKE")
    check_block("CALL 存储过程", "CALL proc_name(1)", "CALL")
    check_block("EXEC(MSSQL)", "EXEC sp_help 't'", "EXEC")
    check_block("EXECUTE 动态", "EXECUTE IMMEDIATE 'DROP TABLE t'", "EXECUTE")
    check_block("多语句 查询+写", "SELECT 1; DROP TABLE t", "单条")
    check_block("多语句 两条查询", "SELECT 1; SELECT 2", "单条")
    check_block("多语句 写在前", "DELETE FROM t; SELECT * FROM t", "单条")
    check_block("SELECT INTO(MSSQL 建表)", "SELECT * INTO new_table FROM t", "INTO")
    check_block("FOR UPDATE 行锁", "SELECT * FROM t FOR UPDATE", "UPDATE")
    check_block("FOR UPDATE NOWAIT", "SELECT * FROM t WHERE id=1 FOR UPDATE NOWAIT", "UPDATE")
    check_block("LOCK IN SHARE MODE", "SELECT * FROM t LOCK IN SHARE MODE", "LOCK")
    check_block("WITH 包裹 DELETE(PG)", "WITH x AS (SELECT 1) DELETE FROM t", "DELETE")
    check_block("WITH 包裹 INSERT(PG)", "WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x", "INSERT")
    check_block("CTE 内 DML RETURNING", "WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x", "DELETE")
    check_block("注释后藏写", "-- 说明\nDROP TABLE t", "DROP")
    check_block("块注释后藏写", "/* 说明 */ DELETE FROM t", "DELETE")
    check_block("注释分隔伪装", "SELECT 1 /*;*/ ; DROP TABLE t", "单条")
    check_block("小写 insert 绕过", "insert into t values (1)", "INSERT")
    check_block("大小写混合 dRoP", "dRoP TaBlE t", "DROP")
    check_block("SET 会话", "SET TRANSACTION READ WRITE", "SET")
    check_block("USE 切库", "USE other_db", "USE")
    check_block("BEGIN 事务", "BEGIN; DELETE FROM t; COMMIT", "单条")
    check_block("COMMIT", "COMMIT", "COMMIT")
    check_block("EXPLAIN 前缀(仅查询亦不放行)", "EXPLAIN SELECT * FROM t", "EXPLAIN")
    check_block("SHOW(MySQL)", "SHOW TABLES", "SHOW")
    check_block("空 SQL", "")
    check_block("纯空白", "   \n\t  ")
    check_block("纯注释", "-- 只有注释\n/* 也是注释 */")
    check_block("xp_cmdshell 链", "SELECT 1; EXEC master..xp_cmdshell 'dir'", "单条")

    print("=" * 70)
    print("C. 误伤防护复核（危险词在字符串/引号标识符中）")
    print("=" * 70)
    check_pass("字符串含 INTO", "SELECT * FROM t WHERE note='insert into log'")
    check_pass("字符串含 FOR UPDATE", "SELECT * FROM t WHERE note='for update now'")
    check_pass("字符串含分号+写", "SELECT * FROM t WHERE note='x; DROP TABLE y'")
    check_pass("引号标识符 update", 'SELECT "update" FROM t')
    check_pass("反引号标识符 delete", "SELECT `delete` FROM t")
    check_pass("方括号标识符 lock", "SELECT [lock] FROM t")

    print("=" * 70)
    if failures:
        print(f"SQL Guard 单测失败，共 {len(failures)} 项：")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("SQL Guard 单元测试全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
