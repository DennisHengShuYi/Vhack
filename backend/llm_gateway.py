"""
LLM Provider Gateway — routes to OpenAI, Gemini, or Ollama (local/edge).
Provider priority: OPENAI → GEMINI → OLLAMA. Override with ACTIVE_PROVIDER env var.
"""
import os
import sys
from openai import OpenAI

_OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")


def _make_client(provider: str) -> tuple:
    """Return (OpenAI client, model_name) for the given provider string."""
    llm_model = os.getenv("LLM_MODEL", "")

    if provider == "OLLAMA":
        model = llm_model or _OLLAMA_MODEL
        client = OpenAI(
            api_key="ollama",
            base_url=f"{_OLLAMA_BASE}/v1/",
        )
        return client, model

    if provider == "GEMINI":
        key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")
        model = llm_model or "gemini-2.5-flash"
        if "/" in model:
            model = model.split("/")[1]
        client = OpenAI(
            api_key=key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        return client, model

    # Default: OPENAI
    key = os.getenv("OPENAI_API_KEY")
    model = llm_model or "gpt-4o"
    return OpenAI(api_key=key), model


def get_client(forced_provider: str | None = None):
    """Return (client, model). Uses ACTIVE_PROVIDER env or forced_provider override."""
    from dotenv import load_dotenv
    load_dotenv(override=True)

    provider = (forced_provider or os.getenv("ACTIVE_PROVIDER", "")).upper()
    if not provider:
        openai_key = os.getenv("OPENAI_API_KEY")
        gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")
        if openai_key and openai_key.strip():
            provider = "OPENAI"
        elif gemini_key and gemini_key.strip():
            provider = "GEMINI"
        else:
            provider = "OLLAMA"

    return _make_client(provider)


def health_check(provider: str) -> bool:
    """
    Quick liveness check for a provider. Returns True if reachable.
    Does NOT make a full inference call — just checks connectivity.
    """
    import urllib.request
    try:
        if provider == "OLLAMA":
            req = urllib.request.Request(f"{_OLLAMA_BASE}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=2):
                return True
        elif provider in ("OPENAI", "GEMINI"):
            client, _ = _make_client(provider)
            client.models.list()
            return True
    except Exception as e:
        print(f"[LLM HEALTH] {provider} unreachable: {e}", file=sys.stderr)
    return False


def completion(model=None, messages=None, forced_provider: str | None = None):
    client, default_model = get_client(forced_provider)
    use_model = model or default_model
    if "/" in use_model:
        use_model = use_model.split("/")[1]

    return client.chat.completions.create(
        model=use_model,
        messages=messages
    )
