"""Embed the verified example questions and build the FAISS index in data/index/ (git-ignored, rebuildable).

Run:  python scripts/build_index.py
Only examples with `verified: true` are indexed. Embeddings are cached, so a re-run makes no API calls.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ask_olist import config, retrieval  # noqa: E402


def main() -> None:
    n = retrieval.build_index()
    print(f"Indexed {n} verified examples -> {config.INDEX_DIR}")


if __name__ == "__main__":
    main()
