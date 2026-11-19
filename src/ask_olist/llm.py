"""Gemini calls: disk-cached, with exponential backoff on rate-limit / overload errors."""
import json
import re
import time
from typing import Any

from google import genai
from google.genai import errors, types

from ask_olist import cache, config

_client: genai.Client | None = None

# 429 = rate limit. 503/504 = Google overloaded / timed out (seen on 20 Nov 2026), also worth retrying.
RETRYABLE_CODES = {429, 503, 504}


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is missing. Put it in .env")
        _client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(timeout=config.LLM_TIMEOUT_MS),
        )
    return _client


# If Google itself says "retry in more than this many seconds", waiting a few seconds will not help
# (for example the free-tier DAILY quota says ~12 hours), so we fail fast instead of sleeping in vain.
MAX_USEFUL_WAIT_S = 60


def retry_delay_seconds(exc: Exception) -> float | None:
    """Seconds Google asks us to wait (from its RetryInfo, e.g. 'retryDelay': '41799s'), or None."""
    match = re.search(r"retryDelay\W+(\d+(?:\.\d+)?)s", str(exc))
    return float(match.group(1)) if match else None


def _call_with_backoff(make_call):
    delay = 2.0
    for attempt in range(config.LLM_MAX_RETRIES + 1):
        try:
            return make_call()
        except errors.APIError as exc:
            if exc.code not in RETRYABLE_CODES or attempt == config.LLM_MAX_RETRIES:
                raise
            asked = retry_delay_seconds(exc)
            if asked is not None and asked > MAX_USEFUL_WAIT_S:
                raise
            time.sleep(delay)
            delay *= 2  # 2s, 4s, 8s, ...


class SqlOutput:  # shape of the JSON we ask Gemini for (a plain dict-schema keeps imports small)
    schema: dict[str, Any] = {
        "type": "OBJECT",
        "properties": {
            "sql": {"type": "STRING"},
            "assumptions": {"type": "ARRAY", "items": {"type": "STRING"}},
        },
        "required": ["sql", "assumptions"],
    }


def _cache_model_id() -> str:
    # Thinking level changes the output, so it is part of the cache key (default None keeps old keys valid).
    if config.LLM_THINKING_LEVEL is None:
        return config.LLM_MODEL
    return f"{config.LLM_MODEL}|thinking={config.LLM_THINKING_LEVEL}"


def _thinking_config() -> types.ThinkingConfig | None:
    if config.LLM_THINKING_LEVEL is None:
        return None
    return types.ThinkingConfig(thinking_level=types.ThinkingLevel(config.LLM_THINKING_LEVEL.upper()))


def generate_sql_json(prompt: str, prompt_version: str) -> dict[str, Any]:
    """Ask for {sql, assumptions} as structured JSON. Returns the parsed dict."""
    model = config.LLM_MODEL
    key = cache.make_key(_cache_model_id(), prompt_version, prompt)
    cached = cache.get("llm_json", key)
    if cached is not None:
        return cached

    gen_config = types.GenerateContentConfig(
        temperature=0,
        response_mime_type="application/json",
        response_schema=SqlOutput.schema,
        thinking_config=_thinking_config(),
    )
    response = _call_with_backoff(
        lambda: _get_client().models.generate_content(model=model, contents=prompt, config=gen_config)
    )
    result = json.loads(response.text)
    cache.put("llm_json", key, result)
    return result


def generate_text(prompt: str, prompt_version: str) -> str:
    """Plain-text generation (used for the English answer)."""
    model = config.LLM_MODEL
    key = cache.make_key(_cache_model_id(), prompt_version, prompt)
    cached = cache.get("llm_text", key)
    if cached is not None:
        return cached

    gen_config = types.GenerateContentConfig(temperature=0, thinking_config=_thinking_config())
    response = _call_with_backoff(
        lambda: _get_client().models.generate_content(model=model, contents=prompt, config=gen_config)
    )
    text = (response.text or "").strip()
    cache.put("llm_text", key, text)
    return text
