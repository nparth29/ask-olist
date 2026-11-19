"""Streamlit UI tests (headless, no browser). The pipeline is mocked, so no API calls are made."""
from pathlib import Path

import pytest
from google.genai import errors
from streamlit.testing.v1 import AppTest

from ask_olist import pipeline

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")

RESULT = {
    "answer": "Credit cards had the highest total payment value.",
    "sql": "SELECT payment_type FROM order_payments",
    "assumptions": ["Delivered orders only."],
    "columns": ["payment_type", "total"],
    "rows": [["credit_card", 10.5], ["boleto", 2.0]],
    "attempts": 2,
    "retrieved_example_ids": ["ex11"],
    "retrieved_examples": [{"id": "ex11", "question": "Average installments?", "sql": "SELECT 1", "score": 0.91}],
    "latency_s": 1.5,
}


def ask_button(at):
    return next(b for b in at.button if b.label == "Ask")   # not the sidebar sample buttons


def run_app(monkeypatch, fake_ask, question="What is the total payment value?"):
    monkeypatch.setattr(pipeline, "ask", fake_ask)
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.text_input(key="question").set_value(question)
    ask_button(at).click()
    return at.run()


def test_page_loads_with_no_error():
    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    assert at.title[0].value.endswith("Ask-Olist")
    assert at.toggle[0].value is True            # RAG is on by default


def test_shows_answer_sql_table_examples_and_attempts(monkeypatch):
    calls = []
    at = run_app(monkeypatch, lambda q, use_rag=True: calls.append((q, use_rag)) or RESULT)

    assert not at.exception
    assert calls == [("What is the total payment value?", True)]
    assert at.success[0].value == RESULT["answer"]
    assert "SELECT payment_type FROM order_payments" in [c.value for c in at.code]       # SQL in the expander
    assert at.dataframe[0].value.shape == (2, 2)                                          # result table
    assert any("ex11" in m.value and "0.910" in m.value for m in at.markdown)             # retrieved example + score
    assert any("Attempts needed: 2" in w.value for w in at.warning)                       # retry notice
    assert [m.label for m in at.metric] == ["Attempts", "Latency", "Retrieved examples"]


def test_toggle_off_runs_zero_shot(monkeypatch):
    seen = []
    monkeypatch.setattr(pipeline, "ask", lambda q, use_rag=True: seen.append(use_rag) or {**RESULT, "attempts": 1, "retrieved_examples": [], "retrieved_example_ids": []})
    at = AppTest.from_file(APP, default_timeout=30).run()
    at.toggle[0].set_value(False)
    at.text_input(key="question").set_value("How many orders are there?")
    ask_button(at).click()
    at.run()
    assert seen == [False]
    assert any("zero-shot" in c.value for c in at.caption)


def test_model_outage_shows_friendly_error(monkeypatch):
    def quota(q, use_rag=True):
        raise errors.ClientError(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}})

    at = run_app(monkeypatch, quota)
    assert not at.exception                      # no crash and no stack trace for the user
    assert "429" in at.error[0].value and "unavailable" in at.error[0].value


def test_short_question_is_not_sent(monkeypatch):
    calls = []
    at = run_app(monkeypatch, lambda q, use_rag=True: calls.append(q) or RESULT, question="a")
    assert calls == [] and at.warning[0].value == "Please type a question."


def test_sample_button_fills_the_question_box(monkeypatch):
    monkeypatch.setattr(pipeline, "ask", lambda q, use_rag=True: RESULT)
    at = AppTest.from_file(APP, default_timeout=30).run()
    first_sample = at.sidebar.button[0]
    first_sample.click()
    at.run()
    assert at.text_input(key="question").value == first_sample.label
