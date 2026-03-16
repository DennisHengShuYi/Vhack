"""
LLM Provider Gateway — routes to Gemini or OpenAI via the OpenAI-compatible API.
Defaults to OpenAI (GPT-4o) if OPENAI_API_KEY is set, otherwise tries Gemini.
Set ACTIVE_PROVIDER=GEMINI or ACTIVE_PROVIDER=OPENAI in .env to override.
"""
import os
from openai import OpenAI

_client = None
_model = None


def get_client():
    global _client, _model
    if _client is not None:
        return _client, _model

    provider = os.getenv("ACTIVE_PROVIDER", "").upper()
    llm_model = os.getenv("LLM_MODEL", "")

    # Auto-detect provider from available keys if not set
    if not provider:
        if os.getenv("OPENAI_API_KEY"):
            provider = "OPENAI"
        elif os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY"):
            provider = "GEMINI"
        else:
            provider = "OPENAI"

    if not llm_model:
        if provider == "GEMINI":
            llm_model = "gemini-2.5-flash"
        else:
            llm_model = "gpt-4o"
    else:
        # Strip provider prefix if using litellm style e.g. gemini/gemini-2.5-flash
        if "/" in llm_model:
            llm_model = llm_model.split("/")[1]

    if provider == "GEMINI" or "gemini" in llm_model.lower():
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GEMINI_KEY")
        _client = OpenAI(
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        _model = llm_model
    else:
        api_key = os.getenv("OPENAI_API_KEY")
        _client = OpenAI(api_key=api_key)
        _model = llm_model

    return _client, _model


def completion(model=None, messages=None):
    client, default_model = get_client()
    use_model = model or default_model
    if "/" in use_model:
        use_model = use_model.split("/")[1]

    return client.chat.completions.create(
        model=use_model,
        messages=messages
    )
