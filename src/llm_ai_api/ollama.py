"""Ollama client using its OpenAI-compatible endpoint."""

from __future__ import annotations

from .openai import OpenAICompatClient


class OllamaClient(OpenAICompatClient):
    """Client for Ollama's local OpenAI-compatible `/chat/completions` endpoint."""

    provider = "ollama"
    default_base_url = "http://localhost:11434/v1"
    api_key_env = "OLLAMA_API_KEY"
    base_url_env = "OLLAMA_BASE_URL"
    api_key_default = "ollama"
