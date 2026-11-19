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
