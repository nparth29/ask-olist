"""Disk cache for LLM and embedding calls.

Key = sha256(model name + prompt version + input). A re-run of the same input makes zero API calls.
"""
import hashlib
import json
from pathlib import Path
from typing import Any

from ask_olist import config


def make_key(model: str, prompt_version: str, text: str) -> str:
    # The "\0" separator stops ("ab", "c") and ("a", "bc") from hashing to the same key.
    raw = "\0".join([model, prompt_version, text])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _path(kind: str, key: str) -> Path:
    return config.CACHE_DIR / kind / f"{key}.json"


def get(kind: str, key: str) -> Any | None:
    path = _path(kind, key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["value"]


def put(kind: str, key: str, value: Any) -> None:
    path = _path(kind, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Write to a temp file first so a crash never leaves a half-written cache entry.
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"value": value}), encoding="utf-8")
    tmp.replace(path)
