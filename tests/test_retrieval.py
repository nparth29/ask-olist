"""Retrieval and RAG-prompt tests. Embeddings are faked (word counts), so no API calls are made."""
import sqlite3

import numpy as np
import pytest
import yaml

from ask_olist import cache, config, llm, pipeline, retrieval

VOCAB = ["late", "deliveries", "revenue", "state", "customers", "review", "score", "category", "month"]


def fake_embed(texts):
    """Word-count vectors over a tiny vocabulary: similar words -> similar vectors."""
    return [[float(text.lower().count(word)) + 0.01 for word in VOCAB] for text in texts]


EXAMPLES = [
    {"id": "a1", "question": "Which states have late deliveries?", "sql": "SELECT 1", "verified": True},
    {"id": "a2", "question": "What is the revenue per month?", "sql": "SELECT 2", "verified": True},
    {"id": "a3", "question": "Average review score per category", "sql": "SELECT 3", "verified": True},
    {"id": "a4", "question": "Customers per state", "sql": "SELECT 4", "verified": True},
    {"id": "x9", "question": "late deliveries late late", "sql": "SELECT 9", "verified": False},  # must NOT be indexed
]


@pytest.fixture()
def rag_env(tmp_path, monkeypatch):
    examples_path = tmp_path / "examples.yaml"
    examples_path.write_text(yaml.safe_dump(EXAMPLES), encoding="utf-8")
    monkeypatch.setattr(config, "EXAMPLES_PATH", examples_path)
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(llm, "embed_texts", fake_embed)
    return tmp_path


def test_normalise_gives_unit_length_vectors():
    matrix = retrieval.normalise([[3.0, 4.0], [0.0, 2.0]])
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1.0)


def test_only_verified_examples_are_indexed(rag_env):
    assert retrieval.build_index() == 4
    results = retrieval.retrieve("late late deliveries", k=10)
    assert "x9" not in [r.id for r in results]


def test_retrieve_returns_most_similar_first_with_cosine_scores(rag_env):
    retrieval.build_index()
    results = retrieval.retrieve("Which states had the most late deliveries?", k=3)
    assert len(results) == 3
    assert results[0].id == "a1"
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)
    assert all(-1.0001 <= s <= 1.0001 for s in scores)   # cosine similarity range
    assert results[0].sql == "SELECT 1"


def test_retrieve_without_index_gives_clear_error(rag_env):
    with pytest.raises(FileNotFoundError, match="build_index"):
        retrieval.retrieve("anything")


def test_build_index_needs_verified_examples(rag_env):
    unverified = [{**e, "verified": False} for e in EXAMPLES]
    (rag_env / "examples.yaml").write_text(yaml.safe_dump(unverified), encoding="utf-8")
    with pytest.raises(RuntimeError, match="verified"):
        retrieval.build_index()


# ---- the pipeline uses the RAG prompt only when asked ----

@pytest.fixture()
def pipeline_env(rag_env, monkeypatch):
    db_path = rag_env / "tiny.db"
    con = sqlite3.connect(db_path)
    con.execute("CREATE TABLE t (a INTEGER)")
    con.execute("INSERT INTO t VALUES (1)")
    con.commit()
    con.close()
    monkeypatch.setattr(config, "DB_PATH", db_path)
    monkeypatch.setattr(config, "LOG_DIR", rag_env / "logs")
    monkeypatch.setattr(config, "RUN_LOG", rag_env / "logs" / "runs.jsonl")
    seen = []
    monkeypatch.setattr(llm, "generate_sql_json",
                        lambda prompt, version: seen.append((version, prompt)) or {"sql": "SELECT COUNT(*) AS n FROM t", "assumptions": []})
    monkeypatch.setattr(llm, "generate_text", lambda prompt, version: "ok")
    retrieval.build_index()
    return seen


def test_rag_prompt_contains_examples_and_returns_their_ids(pipeline_env):
    out = pipeline.ask("Which states had the most late deliveries?", use_rag=True)
    version, prompt = pipeline_env[0]
    assert version == "sql_v2"
    assert "Which states have late deliveries?" in prompt and "SELECT 1" in prompt
    assert "{examples}" not in prompt and "{schema}" not in prompt
    assert out["retrieved_example_ids"][0] == "a1" and len(out["retrieved_example_ids"]) == 3


def test_no_rag_uses_zero_shot_prompt(pipeline_env):
    out = pipeline.ask("Which states had the most late deliveries?", use_rag=False)
    version, prompt = pipeline_env[0]
    assert version == "sql_v1" and "Example 1" not in prompt
    assert out["retrieved_example_ids"] == []


def test_embeddings_are_cached_per_text(tmp_path, monkeypatch):
    """The real llm.embed_texts: a text already in the cache is not sent to the API again."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    calls = []

    class FakeResponse:
        def __init__(self, n):
            self.embeddings = [type("E", (), {"values": [1.0, 2.0, 3.0]})() for _ in range(n)]

    class FakeModels:
        def embed_content(self, model, contents, config):
            calls.append(list(contents))
            return FakeResponse(len(contents))

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(llm, "_get_client", lambda: FakeClient())
    llm.embed_texts(["one", "two"])
    llm.embed_texts(["two", "three"])       # only "three" is new
    assert calls == [["one", "two"], ["three"]]
    key = cache.make_key(config.EMBEDDING_MODEL, "embed_semantic_similarity_v1", "one")
    assert cache.get("embedding", key) == [1.0, 2.0, 3.0]
