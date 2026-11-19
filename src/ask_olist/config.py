"""Central settings. Model names live ONLY here (set LLM_MODEL after Parth confirms it)."""
import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Chosen in Phase 0 after listing available models; None until Parth confirms.
LLM_MODEL: str | None = "gemini-3.5-flash"
EMBEDDING_MODEL = "gemini-embedding-001"

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "olist.db"
CACHE_DIR = ROOT / "cache"
LOG_DIR = ROOT / "logs"
RUN_LOG = LOG_DIR / "runs.jsonl"

PROMPTS_DIR = ROOT / "prompts"
SCHEMA_PATH = ROOT / "schema" / "schema.md"

# Prompt versions: changing a prompt's wording means a NEW version file (and so a new cache key).
SQL_PROMPT_VERSION = "sql_v1"
ANSWER_PROMPT_VERSION = "answer_v1"
FIX_PROMPT_VERSION = "fix_v1"

# Agent loop: after a failed attempt, send the SQL + error back to the LLM. 2 retries = 3 attempts at most.
MAX_RETRIES = 2

# Query limits (rule: the app only ever reads).
MAX_ROWS = 1000
QUERY_TIMEOUT_S = 10
ROWS_RETURNED = 20       # rows included in the pipeline result
ROWS_FOR_ANSWER = 50     # rows shown to the LLM when it writes the answer

# How much the model "thinks" before answering: None (model default), "low", "medium", ...
LLM_THINKING_LEVEL: str | None = None

# LLM call settings.
LLM_TIMEOUT_MS = 90_000
LLM_MAX_RETRIES = 5
