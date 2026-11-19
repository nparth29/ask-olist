"""Agent-loop tests. The LLM is mocked, so no API calls are made."""
import json
import sqlite3

import pytest
from google.genai import errors

from ask_olist import config, llm, pipeline


@pytest.fixture()
def env(tmp_path, monkeypatch):
    path = tmp_path / "tiny.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (a INTEGER)")
    con.executemany("INSERT INTO t VALUES (?)", [(1,), (2,), (3,)])
    con.commit()
    con.close()
    monkeypatch.setattr(config, "DB_PATH", path)
    monkeypatch.setattr(config, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(config, "RUN_LOG", tmp_path / "logs" / "runs.jsonl")
    return tmp_path


def mock_llm(monkeypatch, replies):
    """The LLM returns the given SQL strings in order. Records (prompt_version, prompt) of each call."""
    calls = []
    remaining = list(replies)

    def fake_generate_sql_json(prompt, prompt_version):
        calls.append((prompt_version, prompt))
        return {"sql": remaining.pop(0), "assumptions": ["mock"]}

    monkeypatch.setattr(llm, "generate_sql_json", fake_generate_sql_json)
    monkeypatch.setattr(llm, "generate_text", lambda prompt, version: "There are 3 rows.")
    return calls


def read_log(tmp_path):
    return [json.loads(line) for line in (tmp_path / "logs" / "runs.jsonl").read_text().splitlines()]


def test_retry_after_sql_error(env, monkeypatch):
    calls = mock_llm(monkeypatch, ["SELECT missing_column FROM t", "SELECT COUNT(*) AS n FROM t"])

    out = pipeline.ask("How many rows?")

    assert out["attempts"] == 2
    assert out["rows"] == [[3]]
    assert out["answer"] == "There are 3 rows."
    # Attempt 2 used the fix prompt, which contains the bad SQL and the error message.
    assert [version for version, _ in calls] == ["sql_v1", "fix_v1"]
    assert "SELECT missing_column FROM t" in calls[1][1]
    assert "missing_column" in calls[1][1] and "OperationalError" in calls[1][1]
    # Both attempts were logged: 1 failed, 2 succeeded.
    log = read_log(env)
    assert [(e["attempt"], e["ok"]) for e in log] == [(1, False), (2, True)]
    assert "no such column" in log[0]["error"]


def test_retry_after_guard_rejection(env, monkeypatch):
    calls = mock_llm(monkeypatch, ["DROP TABLE t", "SELECT COUNT(*) AS n FROM t"])

    out = pipeline.ask("How many rows?")

    assert out["attempts"] == 2 and out["rows"] == [[3]]
    assert "GuardError" in calls[1][1]
    # The table is still there: the DROP never ran.
    assert sqlite3.connect(config.DB_PATH).execute("SELECT COUNT(*) FROM t").fetchone() == (3,)


def test_gives_up_after_two_retries(env, monkeypatch):
    calls = mock_llm(monkeypatch, ["SELECT x FROM t", "SELECT y FROM t", "SELECT z FROM t"])

    out = pipeline.ask("How many rows?")

    assert out["attempts"] == 3          # 1 first try + 2 retries
    assert len(calls) == 3
    assert out["rows"] == [] and "could not run a valid query" in out["answer"]
    assert [e["ok"] for e in read_log(env)] == [False, False, False]


def test_no_retry_when_first_attempt_works(env, monkeypatch):
    calls = mock_llm(monkeypatch, ["SELECT COUNT(*) AS n FROM t"])
    out = pipeline.ask("How many rows?")
    assert out["attempts"] == 1 and len(calls) == 1


# ---- fast-fail on the daily quota (llm.py) ----

def quota_error(retry_delay: str) -> errors.ClientError:
    body = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                      "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": retry_delay}]}}
    return errors.ClientError(429, body)


def test_retry_delay_is_parsed():
    assert llm.retry_delay_seconds(quota_error("41799s")) == 41799
    assert llm.retry_delay_seconds(quota_error("3.5s")) == 3.5
    assert llm.retry_delay_seconds(ValueError("no delay here")) is None


def test_daily_quota_429_fails_fast(monkeypatch):
    sleeps, calls = [], []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)

    def always_quota():
        calls.append(1)
        raise quota_error("41799s")

    with pytest.raises(errors.ClientError):
        llm._call_with_backoff(always_quota)
    assert len(calls) == 1 and sleeps == []   # no waiting, no retrying


def test_short_429_is_retried_with_backoff(monkeypatch):
    sleeps = []
    monkeypatch.setattr(llm.time, "sleep", sleeps.append)
    attempts = []

    def flaky():
        attempts.append(1)
        if len(attempts) < 3:
            raise quota_error("5s")
        return "ok"

    assert llm._call_with_backoff(flaky) == "ok"
    assert sleeps == [2.0, 4.0]               # exponential: 2 s, then 4 s
