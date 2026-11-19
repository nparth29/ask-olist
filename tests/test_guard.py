import sqlite3

import pytest

from ask_olist import db
from ask_olist.guard import GuardError, check_sql


@pytest.mark.parametrize("sql", [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "INSERT INTO orders (order_id) VALUES ('x')",
    "UPDATE orders SET order_status = 'delivered'",
    "ATTACH DATABASE 'other.db' AS other",
    "PRAGMA table_info(orders)",
    "SELECT 1; SELECT 2",
    "SELECT 1; DROP TABLE orders",
    "CREATE TABLE t (a INTEGER)",
    "",
])
def test_guard_rejects(sql):
    with pytest.raises(GuardError):
        check_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT * FROM orders",
    "SELECT COUNT(*) FROM orders;",
    "WITH a AS (SELECT order_id FROM orders) SELECT COUNT(*) FROM a",
    "SELECT 1 UNION SELECT 2",
])
def test_guard_accepts(sql):
    assert check_sql(sql)


def test_guard_strips_trailing_semicolon():
    assert check_sql("SELECT 1;") == "SELECT 1"


@pytest.fixture()
def tiny_db(tmp_path):
    path = tmp_path / "tiny.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (a INTEGER)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    return path


def test_readonly_connection_cannot_write(tiny_db):
    con = db.connect_readonly(tiny_db)
    for statement in ["INSERT INTO t VALUES (2)", "DELETE FROM t", "DROP TABLE t", "CREATE TABLE u (b INTEGER)"]:
        with pytest.raises(sqlite3.OperationalError):
            con.execute(statement)
    con.close()
    # and the data is untouched
    assert db.run_query("SELECT COUNT(*) FROM t", tiny_db).rows == [(1,)]


def test_row_cap(tiny_db, monkeypatch):
    monkeypatch.setattr("ask_olist.config.MAX_ROWS", 3)
    result = db.run_query(
        "WITH RECURSIVE n(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM n WHERE x < 10) SELECT x FROM n", tiny_db
    )
    assert len(result.rows) == 3 and result.truncated
