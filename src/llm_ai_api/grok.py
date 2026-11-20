"""Grok (xAI) client using its OpenAI-compatible endpoint."""

from __future__ import annotations

from .openai import OpenAICompatClient


class GrokClient(OpenAICompatClient):
    """Client for xAI's OpenAI-compatible `/chat/completions` endpoint."""

    provider = "grok"
    default_base_url = "https://api.x.ai/v1"
    api_key_env = "XAI_API_KEY"
    base_url_env = "XAI_BASE_URL"
