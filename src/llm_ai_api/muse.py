"""Muse (Meta Model API) client using its OpenAI-compatible endpoint."""

from __future__ import annotations

from .openai import OpenAICompatClient


class MuseClient(OpenAICompatClient):
    """Client for Muse's OpenAI-compatible `/chat/completions` endpoint."""

    provider = "muse"
    default_base_url = "https://api.meta.ai/v1"
    api_key_env = "MODEL_API_KEY"
    base_url_env = "MUSE_BASE_URL"
