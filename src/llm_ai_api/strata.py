"""Strata client using its OpenAI-compatible endpoint."""

from __future__ import annotations

from .openai import OpenAICompatClient


class StrataClient(OpenAICompatClient):
    """Client for Strata's local OpenAI-compatible `/chat/completions` endpoint."""

    provider = "strata"
    default_base_url = "http://127.0.0.1:8080/v1"
    api_key_env = "STRATA_API_KEY"
    base_url_env = "STRATA_BASE_URL"
    api_key_default = "local"
