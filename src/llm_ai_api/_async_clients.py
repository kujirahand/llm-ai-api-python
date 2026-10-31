"""Async provider clients (internal; used by `LLM.aask()` / `achat()` / `astream()`).

Body building, response parsing and per-event stream parsing are shared with the
sync clients; only the I/O differs.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ._async_http import _AsyncBaseClient, _AsyncChunks, _AsyncLoggedChunks
from .anthropic import AnthropicClient
from .anthropic import _chunk_from_event as _anthropic_chunk
from .anthropic import _parse_response as _anthropic_parse
from .openai import OpenAICompatClient
from .openai import _chunk_from_event as _openai_chunk
from .openai import _parse_response as _openai_parse
from ._events import apply_result_meta
from .types import ChatResult


class _AsyncOpenAICompatClient(_AsyncBaseClient):
    """Async client for `/chat/completions`-style APIs."""

    max_tokens_field = "max_tokens"
    stream_include_usage = False

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": "Bearer " + self._api_key}

    def _build_body(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int],
        temperature: Optional[float],
        extra: Optional[Dict[str, Any]],
        stream: bool,
    ) -> Dict[str, Any]:
        # Reuse the sync implementation. It reads max_tokens_field,
        # stream_include_usage, and provider, which this class sets the same way.
        return OpenAICompatClient._build_body(
            self, model, messages, max_tokens, temperature, extra, stream  # type: ignore[arg-type]
        )

    async def achat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> ChatResult:
        """Call the chat once. Parameters that are not given are not sent."""
        body = self._build_body(model, messages, max_tokens, temperature, extra, False)
        cached = await self._alookup_chat_cache(body)
        if cached is not None:
            await self._alog_call(body, cached.raw, cached=True)
            return cached
        raw, meta = await self._read_json("/chat/completions", body, timeout=timeout)
        result = apply_result_meta(_openai_parse(raw), meta)
        await self._acache_store(body, result)
        await self._alog_call(body, raw)
        return result

    async def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> _AsyncLoggedChunks:
        """Start a streaming chat and return the chunks. HTTP errors are raised here."""
        body = self._build_body(model, messages, max_tokens, temperature, extra, True)
        events, cached = await self._astream_events("/chat/completions", body, timeout=timeout)
        headline = self._t("stream_error", provider=self.provider)
        chunks = _AsyncChunks(events, lambda ev: _openai_chunk(ev, headline), self)
        return self._alog_chunks(chunks, body, cached)


class _AsyncOpenAIClient(_AsyncOpenAICompatClient):
    provider = "openai"
    default_base_url = "https://api.openai.com/v1"
    api_key_env = "OPENAI_API_KEY"
    base_url_env = "OPENAI_BASE_URL"
    max_tokens_field = "max_completion_tokens"
    stream_include_usage = True


class _AsyncOpenRouterClient(_AsyncOpenAICompatClient):
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
        """`app_url` is sent as HTTP-Referer and `app_name` as X-Title."""
        super().__init__(*args, **kwargs)
        if app_url:
            self._extra_headers.setdefault("HTTP-Referer", app_url)
        if app_name:
            self._extra_headers.setdefault("X-Title", app_name)


class _AsyncGoogleClient(_AsyncOpenAICompatClient):
    provider = "google"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
    api_key_env = "GEMINI_API_KEY"
    api_key_env_fallbacks = ("GOOGLE_API_KEY",)
    base_url_env = "GOOGLE_BASE_URL"


class _AsyncAnthropicClient(_AsyncBaseClient):
    """Async client for the Anthropic Messages API."""

    provider = "anthropic"
    default_base_url = "https://api.anthropic.com"
    api_key_env = "ANTHROPIC_API_KEY"
    base_url_env = "ANTHROPIC_BASE_URL"

    def __init__(
        self, *args: Any, anthropic_version: str = "2026-10-21", **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.anthropic_version = anthropic_version

    def _cache_context(self) -> Dict[str, Any]:
        """Add the API version to the cache key context (it is sent as a header)."""
        context = super()._cache_context()
        context["anthropic_version"] = self.anthropic_version
        return context

    def _auth_headers(self) -> Dict[str, str]:
        return {"x-api-key": self._api_key, "anthropic-version": self.anthropic_version}

    def _build_body(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int],
        temperature: Optional[float],
        extra: Optional[Dict[str, Any]],
        stream: bool,
    ) -> Dict[str, Any]:
        # Reuse the sync implementation. It reads provider, anthropic_version,
        # and _extra_headers so the drop rules follow the version header that
        # will be sent. This class defines those the same way.
        return AnthropicClient._build_body(
            self, model, messages, max_tokens, temperature, extra, stream  # type: ignore[arg-type]
        )

    async def achat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> ChatResult:
        """Call the chat once. Unspecified parameters other than `max_tokens` are not sent."""
        body = self._build_body(model, messages, max_tokens, temperature, extra, False)
        cached = await self._alookup_chat_cache(body)
        if cached is not None:
            await self._alog_call(body, cached.raw, cached=True)
            return cached
        raw, meta = await self._read_json("/v1/messages", body, timeout=timeout)
        result = apply_result_meta(_anthropic_parse(raw), meta)
        await self._acache_store(body, result)
        await self._alog_call(body, raw)
        return result

    async def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> _AsyncLoggedChunks:
        """Start a streaming chat and return the chunks. HTTP errors are raised here."""
        body = self._build_body(model, messages, max_tokens, temperature, extra, True)
        events, cached = await self._astream_events("/v1/messages", body, timeout=timeout)
        headline = self._t("stream_error", provider=self.provider)
        chunks = _AsyncChunks(events, lambda ev: _anthropic_chunk(ev, headline), self)
        return self._alog_chunks(chunks, body, cached)
