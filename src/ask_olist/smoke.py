"""Phase 0 check: key works, list Flash models, send 'Reply with OK'."""
import re
import sys

from google import genai

from ask_olist import config


def list_flash_models(client: genai.Client) -> list[str]:
    names = []
    for m in client.models.list():
        actions = m.supported_actions or []
        name = (m.name or "").removeprefix("models/")
        if "generateContent" in actions and name.startswith("gemini-") and "flash" in name:
            names.append(name)
    return sorted(names)


def newest_plain_flash(names: list[str]) -> str | None:
    """Newest 'gemini-<version>-flash'; skips lite/image/preview/omni variants."""
    plain = [(float(m.group(1)), n) for n in names if (m := re.fullmatch(r"gemini-(\d+(?:\.\d+)?)-flash", n))]
    return max(plain)[1] if plain else None


def main() -> int:
    if not config.GEMINI_API_KEY:
        print("GEMINI_API_KEY is missing from .env")
        return 1
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    flash = list_flash_models(client)
    print("Flash models supporting generateContent:")
    for name in flash:
        print("  ", name)
    model = config.LLM_MODEL or newest_plain_flash(flash)
    if model is None:
        print("No Flash model found.")
        return 1
    print(f"\nUsing: {model}")
    reply = client.models.generate_content(model=model, contents="Reply with OK")
    print("Reply:", (reply.text or "").strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
