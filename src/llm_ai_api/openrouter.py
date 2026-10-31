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
            if not any(k.lower() == "http-referer" for k in self._extra_headers):
                self._extra_headers["HTTP-Referer"] = app_url
        if app_name:
            if not any(k.lower() == "x-title" for k in self._extra_headers):
                self._extra_headers["X-Title"] = app_name
