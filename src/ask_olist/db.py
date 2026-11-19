"""Read-only access to the Olist database. The app never writes to it."""
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

from ask_olist import config


@dataclass
class QueryResult:
    columns: list[str]
    rows: list[tuple]
    truncated: bool  # True if there were more than MAX_ROWS rows


def connect_readonly(db_path: Path | None = None) -> sqlite3.Connection:
    path = Path(db_path or config.DB_PATH)
    # Two layers: mode=ro is enforced by SQLite when opening the file,
    # query_only is a second switch that makes every write statement fail.
    con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    return con


def run_query(sql: str, db_path: Path | None = None) -> QueryResult:
    """Run one query with a row cap and a time limit. Raises sqlite3.Error on failure."""
    con = connect_readonly(db_path)
    try:
        deadline = time.monotonic() + config.QUERY_TIMEOUT_S

        def stop_if_too_slow() -> int:
            return 1 if time.monotonic() > deadline else 0  # non-zero aborts the query

        # SQLite calls this every 100000 VM steps, so a runaway query gets interrupted.
        con.set_progress_handler(stop_if_too_slow, 100_000)
        cur = con.execute(sql)
        columns = [d[0] for d in cur.description or []]
        rows = cur.fetchmany(config.MAX_ROWS + 1)
        truncated = len(rows) > config.MAX_ROWS
        return QueryResult(columns, rows[: config.MAX_ROWS], truncated)
    finally:
        con.close()
