"""One question, start to finish: prompt -> Gemini -> guard -> read-only run -> plain-English answer.

If the SQL is rejected by the guard or fails to run, the error is sent back to Gemini to fix it
(the "agent" loop, max config.MAX_RETRIES retries).
"""
import json
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any

from ask_olist import config, db, guard, llm


def _read_prompt(version: str) -> str:
    return (config.PROMPTS_DIR / f"{version}.txt").read_text(encoding="utf-8")


def build_sql_prompt(question: str) -> str:
    schema = config.SCHEMA_PATH.read_text(encoding="utf-8")
    # str.replace, not str.format: the prompt contains literal { } for the JSON example.
    return _read_prompt(config.SQL_PROMPT_VERSION).replace("{schema}", schema).replace("{question}", question)


def build_fix_prompt(question: str, previous_sql: str, error: str) -> str:
    schema = config.SCHEMA_PATH.read_text(encoding="utf-8")
    return (
        _read_prompt(config.FIX_PROMPT_VERSION)
        .replace("{schema}", schema)
        .replace("{question}", question)
        .replace("{previous_sql}", previous_sql)
        .replace("{error}", error)
    )


def _format_rows(columns: list[str], rows: list[tuple]) -> str:
    lines = [" | ".join(columns)]
    lines += [" | ".join("NULL" if v is None else str(v) for v in row) for row in rows]
    return "\n".join(lines)


def build_answer_prompt(question: str, sql: str, assumptions: list[str], result: db.QueryResult) -> str:
    shown = result.rows[: config.ROWS_FOR_ANSWER]
    total = f"{len(result.rows)}+" if result.truncated else str(len(result.rows))
    row_note = f"{len(shown)} of {total} rows shown" if len(shown) < len(result.rows) or result.truncated else f"{total} rows"
    return (
        _read_prompt(config.ANSWER_PROMPT_VERSION)
        .replace("{question}", question)
        .replace("{sql}", sql)
        .replace("{assumptions}", "; ".join(assumptions) if assumptions else "none")
        .replace("{row_note}", row_note)
        .replace("{result}", _format_rows(result.columns, shown))
    )


def _log_attempt(entry: dict[str, Any]) -> None:
    config.LOG_DIR.mkdir(exist_ok=True)
    with config.RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def ask(question: str) -> dict[str, Any]:
    started = time.perf_counter()
    prompt, prompt_version = build_sql_prompt(question), config.SQL_PROMPT_VERSION
    sql, assumptions = "", []
    result: db.QueryResult | None = None
    attempt = 0

    while True:
        attempt += 1
        error = None
        try:
            generated = llm.generate_sql_json(prompt, prompt_version)
            sql = generated["sql"]
            assumptions = generated.get("assumptions", [])
            sql = guard.check_sql(sql)
            result = db.run_query(sql)
        except (guard.GuardError, sqlite3.Error) as exc:
            error = f"{type(exc).__name__}: {exc}"

        _log_attempt({
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "question": question,
            "attempt": attempt,
            "prompt_version": prompt_version,
            "sql": sql,
            "error": error,
            "ok": error is None,
        })

        if error is None or attempt > config.MAX_RETRIES:
            break
        # The agent step: show the model its own SQL and the error, and ask for a fix.
        prompt, prompt_version = build_fix_prompt(question, sql, error), config.FIX_PROMPT_VERSION

    if error is not None:
        answer = f"Sorry, I could not run a valid query for this question after {attempt} attempts. ({error})"
        rows, columns = [], []
    else:
        answer = llm.generate_text(build_answer_prompt(question, sql, assumptions, result), config.ANSWER_PROMPT_VERSION)
        rows, columns = [list(r) for r in result.rows[: config.ROWS_RETURNED]], result.columns

    return {
        "answer": answer,
        "sql": sql,
        "assumptions": assumptions,
        "columns": columns,
        "rows": rows,
        "attempts": attempt,
        "retrieved_example_ids": [],
        "latency_s": round(time.perf_counter() - started, 2),
    }
