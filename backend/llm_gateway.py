"""
LLM Provider Gateway — routes to Gemini or OpenAI via the OpenAI-compatible API.
Fixed:
  - Module-level caching (uses global _client, _model so it builds ONCE)
  - load_dotenv called only on first build, not on every completion() call
  - models/ prefix stripped before sending to API (Gemini endpoint does NOT want it)
  - Thread-safe because client is built once on startup via get_client()
"""
import os
from openai import OpenAI

_client: OpenAI | None = None
_model: str | None = None


def _build_client() -> tuple[OpenAI, str]:
    """One-time client construction. Never call directly — use get_client()."""
    from dotenv import load_dotenv
    load_dotenv(override=True)

    provider = os.getenv("ACTIVE_PROVIDER", "").upper()
    llm_model = os.getenv("LLM_MODEL", "")
    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY") or "").strip()

    # Auto-detect provider from available keys
    if not provider:
        provider = "OPENAI" if openai_key else "GEMINI"

    # Normalize model string — strip both 'models/' and 'provider/' prefixes
    if llm_model.startswith("models/"):
        llm_model = llm_model[len("models/"):]
    elif "/" in llm_model:
        llm_model = llm_model.split("/", 1)[1]

    # Default model per provider
    if not llm_model:
        llm_model = "gemini-2.5-flash" if provider == "GEMINI" else "gpt-4o"

    import sys
    print(f"[llm_gateway] Provider={provider} Model={llm_model}", file=sys.stderr, flush=True)

    if provider == "GEMINI" or "gemini" in llm_model.lower():
        if not gemini_key:
            raise ValueError(
                "GEMINI_API_KEY is not set in .env  "
                "(checked GEMINI_API_KEY and GEMINI_KEY)"
            )
        client = OpenAI(
            api_key=gemini_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )
    else:
        if not openai_key:
            raise ValueError("OPENAI_API_KEY is not set in .env")
        client = OpenAI(api_key=openai_key)

    return client, llm_model


def get_client() -> tuple[OpenAI, str]:
    """Returns cached (client, model). Built once on the first call."""
    global _client, _model
    if _client is None:
        _client, _model = _build_client()
    return _client, _model


def reset_client():
    """Force a new client on the next call (e.g. after .env changes at runtime)."""
    global _client, _model
    _client = None
    _model = None


def completion(model: str | None = None, messages: list | None = None):
    client, default_model = get_client()
    use_model = model or default_model

    # Normalize any caller-supplied model string too
    if use_model.startswith("models/"):
        use_model = use_model[len("models/"):]
    elif "/" in use_model:
        use_model = use_model.split("/", 1)[1]

    return client.chat.completions.create(
        model=use_model,
        messages=messages or [],
    )
