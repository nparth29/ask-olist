"""FastAPI wrapper around the Ask-Olist pipeline.

Run:  uvicorn api.main:app --port 8000
  POST /ask     {"question": "...", "use_rag": true}  -> answer, sql, assumptions, rows, ...
  GET  /health  -> checks that the database and the example index exist (makes no LLM call)
"""
from typing import Any

from fastapi import FastAPI, HTTPException
from google.genai import errors as genai_errors
from pydantic import BaseModel, ConfigDict, Field

from ask_olist import config, pipeline, retrieval

app = FastAPI(title="Ask-Olist", description="Ask the Olist e-commerce database a question in English.")


class AskRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)   # trim first, so "   " is rejected as too short

    question: str = Field(min_length=3, max_length=500, description="A data question in plain English.")
    use_rag: bool = Field(default=True, description="False = zero-shot (no retrieved examples in the prompt).")


class AskResponse(BaseModel):
    answer: str
    sql: str
    assumptions: list[str]
    columns: list[str]
    rows: list[list[Any]]          # first 20 rows
    attempts: int
    retrieved_example_ids: list[str]
    latency_s: float


@app.get("/health")
def health() -> dict[str, Any]:
    database_found = config.DB_PATH.exists()
    index_found = (config.INDEX_DIR / retrieval.INDEX_FILE).exists()
    return {
        "status": "ok" if database_found else "degraded",
        "database_found": database_found,
        "example_index_found": index_found,   # without it, only "use_rag": false works
    }


@app.post("/ask", response_model=AskResponse)
def ask(request: AskRequest) -> dict[str, Any]:
    # A plain `def` (not async): the pipeline blocks on network and SQL, so FastAPI runs it in a worker thread.
    try:
        return pipeline.ask(request.question, use_rag=request.use_rag)
    except FileNotFoundError as exc:      # no database or no example index yet
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except genai_errors.APIError as exc:  # Gemini quota, overload or timeout
        raise HTTPException(status_code=503, detail=f"The language model is unavailable right now ({exc.code}). Try again later.") from exc
    except RuntimeError as exc:           # for example a missing GEMINI_API_KEY
        raise HTTPException(status_code=503, detail=str(exc)) from exc
