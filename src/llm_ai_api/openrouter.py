"""OpenRouter のクライアント。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from .openai import OpenAICompatClient


class OpenRouterClient(OpenAICompatClient):
    """OpenRouter（OpenAI 互換）のクライアント。"""

    provider = "openrouter"
    default_base_url = "https://openrouter.ai/api/v1"
    api_key_env = "OPENROUTER_API_KEY"
    base_url_env = "OPENROUTER_BASE_URL"

    def __init__(
        self,
        *args: Any,
        app_url: Optional[str] = None,
        app_name: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """`app_url` は HTTP-Referer、`app_name` は X-Title として送る。"""
        super().__init__(*args, **kwargs)
        if app_url:
            self._extra_headers.setdefault("HTTP-Referer", app_url)
        if app_name:
            self._extra_headers.setdefault("X-Title", app_name)
