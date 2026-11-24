"""Client for OpenRouter (OpenAI-compatible)."""

from __future__ import annotations

from .openai import OpenAICompatClient


class OpenRouterClient(OpenAICompatClient):
    """OpenRouter client. `app_url` is sent as HTTP-Referer and `app_name` as X-Title."""

    provider = "openrouter"
    default_base_url = "https://openrouter.ai/api/v1"
    api_key_optional = True
    api_key_env = "OPENROUTER_API_KEY"
    base_url_env = "OPENROUTER_BASE_URL"
    # Constructor options turned into headers by the base class. A header the caller
    # passed in `headers=` (any letter case) wins.
    header_options = (("app_url", "HTTP-Referer"), ("app_name", "X-Title"))
