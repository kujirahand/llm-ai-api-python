"""LM Studio client using its OpenAI-compatible endpoint."""

from __future__ import annotations

from .openai import OpenAICompatClient


class LMStudioClient(OpenAICompatClient):
    """Client for LM Studio's local OpenAI-compatible `/chat/completions` endpoint."""

    provider = "lmstudio"
    default_base_url = "http://localhost:1234/v1"
    api_key_env = "LMSTUDIO_API_KEY"
    base_url_env = "LMSTUDIO_BASE_URL"
    api_key_default = "lm-studio"
