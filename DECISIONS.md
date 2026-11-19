# Design Decisions

One entry per choice: what we chose, the main alternative, and why (written for a fresher).

## D1. LLM model: `gemini-3.5-flash`
- **Chosen:** `gemini-3.5-flash` (set once in `src/ask_olist/config.py`).
- **Alternative:** `gemini-3.8-flash` (the newest Flash) or `gemini-3.1-flash-lite` (faster, weaker).
- **Why:** On 20 Nov 2026 the 3.6/3.7/3.8 Flash models timed out or returned 503 "high demand". 3.5-flash worked (about 18 s for a tiny prompt). Model names live only in `config.py`, so switching later is a one-line change (but a new model name means a new cache key).

## D2. `pyproject.toml` with editable install
- **Chosen:** a minimal `pyproject.toml` and `pip install -e .` so `python -m ask_olist.smoke` works with the `src/` layout.
- **Alternative:** setting `PYTHONPATH=src` by hand each time.
- **Why:** the editable install works the same in PowerShell and Command Prompt and needs no extra dependency.

## D3. Local-only files are git-ignored
- **Chosen:** `.env`, `data/`, `cache/`, `logs/` and `.venv/` are listed in `.gitignore`, so they are never committed or pushed.
- **Alternative:** commit them.
- **Why:** `.env` holds the API key; `data/` holds the licensed dataset (CC BY-NC-SA 4.0), which must not be republished; `cache/`, `logs/` and `.venv/` can be rebuilt.
