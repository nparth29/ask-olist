"""RAG retrieval: find the verified examples most similar to a question.

Embeddings are normalised to length 1, and FAISS IndexFlatIP ranks by inner product,
which for unit vectors equals cosine similarity (1.0 = same meaning).
"""
import json
from dataclasses import dataclass

import faiss
import numpy as np
import yaml

from ask_olist import config, llm

INDEX_FILE = "examples.faiss"
META_FILE = "examples_meta.json"


@dataclass
class Retrieved:
    id: str
    question: str
    sql: str
    score: float  # cosine similarity


def normalise(vectors: list[list[float]]) -> np.ndarray:
    matrix = np.array(vectors, dtype="float32")
    faiss.normalize_L2(matrix)  # in place: divides each row by its length
    return matrix


def load_verified_examples() -> list[dict]:
    examples = yaml.safe_load(config.EXAMPLES_PATH.read_text(encoding="utf-8"))
    return [e for e in examples if e.get("verified") is True]  # only examples Parth has checked


def build_index() -> int:
    """Embed the verified example questions and save the FAISS index. Returns how many were indexed."""
    examples = load_verified_examples()
    if not examples:
        raise RuntimeError("No verified examples: set `verified: true` in examples/examples.yaml first.")
    matrix = normalise(llm.embed_texts([e["question"] for e in examples]))

    index = faiss.IndexFlatIP(matrix.shape[1])
    index.add(matrix)

    config.INDEX_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(config.INDEX_DIR / INDEX_FILE))
    meta = [{"id": e["id"], "question": e["question"], "sql": e["sql"].strip()} for e in examples]
    (config.INDEX_DIR / META_FILE).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    return len(examples)


def retrieve(question: str, k: int | None = None) -> list[Retrieved]:
    """Top-k verified examples for the question, best first."""
    index_path, meta_path = config.INDEX_DIR / INDEX_FILE, config.INDEX_DIR / META_FILE
    if not index_path.exists() or not meta_path.exists():
        raise FileNotFoundError("No example index found. Run: python scripts/build_index.py")
    index = faiss.read_index(str(index_path))
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    query = normalise(llm.embed_texts([question]))
    scores, positions = index.search(query, min(k or config.RAG_K, index.ntotal))
    return [
        Retrieved(meta[pos]["id"], meta[pos]["question"], meta[pos]["sql"], float(score))
        for score, pos in zip(scores[0], positions[0])
    ]
