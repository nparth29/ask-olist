"""API tests. The pipeline is mocked, so no API calls are made.

We call the endpoint functions directly (FastAPI's TestClient needs the `httpx` package, which is not a dependency).
The real HTTP server is checked with curl.
"""
import pytest
from fastapi import HTTPException
from google.genai import errors
from pydantic import ValidationError

from api import main
from ask_olist import config, pipeline

FAKE_RESULT = {
    "answer": "There are 3 rows.", "sql": "SELECT 1", "assumptions": ["mock"], "columns": ["n"],
    "rows": [[3]], "attempts": 1, "retrieved_example_ids": ["ex01"], "latency_s": 0.1,
}


def test_ask_passes_question_and_rag_flag_to_pipeline(monkeypatch):
    seen = {}

    def fake_ask(question, use_rag=True):
        seen.update(question=question, use_rag=use_rag)
        return FAKE_RESULT

    monkeypatch.setattr(pipeline, "ask", fake_ask)
    out = main.ask(main.AskRequest(question="  How many rows?  ", use_rag=False))
    assert seen == {"question": "How many rows?", "use_rag": False}   # trimmed, flag passed on
    assert out == FAKE_RESULT
    main.AskResponse(**out)   # the result has every field the response model needs


def test_rag_is_on_by_default():
    assert main.AskRequest(question="How many rows?").use_rag is True


@pytest.mark.parametrize("bad", ["", "  ", "     ", "a", "x" * 501])
def test_bad_questions_are_rejected(bad):
    with pytest.raises(ValidationError):
        main.AskRequest(question=bad)


def test_model_outage_becomes_503(monkeypatch):
    def quota(*args, **kwargs):
        raise errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})

    monkeypatch.setattr(pipeline, "ask", quota)
    with pytest.raises(HTTPException) as info:
        main.ask(main.AskRequest(question="How many rows?"))
    assert info.value.status_code == 503 and "429" in info.value.detail


def test_missing_index_becomes_503(monkeypatch):
    def no_index(*args, **kwargs):
        raise FileNotFoundError("No example index found. Run: python scripts/build_index.py")

    monkeypatch.setattr(pipeline, "ask", no_index)
    with pytest.raises(HTTPException) as info:
        main.ask(main.AskRequest(question="How many rows?"))
    assert info.value.status_code == 503 and "build_index" in info.value.detail


def test_health_reports_missing_files(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "missing.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "missing_index")
    assert main.health() == {"status": "degraded", "database_found": False, "example_index_found": False}


def test_health_ok_when_files_exist(tmp_path, monkeypatch):
    (tmp_path / "idx").mkdir()
    (tmp_path / "idx" / "examples.faiss").write_bytes(b"x")
    (tmp_path / "o.db").write_bytes(b"x")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "o.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "idx")
    assert main.health() == {"status": "ok", "database_found": True, "example_index_found": True}
