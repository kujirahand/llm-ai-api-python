"""Google Gemini API client, using Google's OpenAI-compatible endpoint."""

from __future__ import annotations

from .openai import OpenAICompatClient


class GoogleClient(OpenAICompatClient):
    """Client for the Gemini API through its OpenAI-compatible `/chat/completions` endpoint.

    The key is read from `GEMINI_API_KEY`, or `GOOGLE_API_KEY` if that is not set.
    """

    provider = "google"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    api_key_env = "GEMINI_API_KEY"
    api_key_env_fallbacks = ("GOOGLE_API_KEY",)
    base_url_env = "GOOGLE_BASE_URL"
