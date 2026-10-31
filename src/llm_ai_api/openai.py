"""Clients for OpenAI and OpenAI-compatible chat APIs."""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple

from ._singleflight import singleflight
from ._events import apply_result_meta, note_request_error, note_stream_error
from ._http import BaseClient, _TaggedIter, error_message
from ._model_params import adjust_body
from .errors import APIStreamError, LLMError
from .types import ChatChunk, ChatResult, SSEEvent, Usage


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # a list of parts: concatenate the text ones
        return "".join(
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        )
    return ""


def _parse_response(raw: Dict[str, Any]) -> ChatResult:
    """Build a `ChatResult` from a `/chat/completions` response (shared by sync and async)."""
    choices = raw.get("choices") or [{}]
    choice = choices[0] or {}
    u = raw.get("usage")
    usage = (
        Usage(u.get("prompt_tokens"), u.get("completion_tokens"))
        if isinstance(u, dict)
        else None
    )
    return ChatResult(
        text=_text_of((choice.get("message") or {}).get("content")),
        model=raw.get("model"),
        stop_reason=choice.get("finish_reason"),
        usage=usage,
        raw=raw,
    )


def _chunk_from_event(
    ev: SSEEvent, stream_error_headline: str
) -> Tuple[Optional[ChatChunk], bool]:
    """Turn one SSE event into `(chunk, terminal)` (shared by sync and async).

    `terminal` is True at `data: [DONE]`. An `error` field raises `APIStreamError`.
    """
    if ev.data.strip() == "[DONE]":
        return None, True
    raw = ev.json()
    if raw.get("error"):
        # An error in the middle of a stream (e.g. OpenRouter sends `data: {"error": ...}`).
        # Without this it would look like an empty chunk and the stream would end "normally".
        detail = error_message(raw) or raw["error"]  # not translated: comes from the API
        raise APIStreamError("%s: %s" % (stream_error_headline, detail), body=raw)
    choices = raw.get("choices") or []
    delta = (choices[0].get("delta") if choices else None) or {}
    return ChatChunk(text=_text_of(delta.get("content")), raw=raw), False


class OpenAICompatClient(BaseClient):
    """Shared implementation for ``/chat/completions``-style APIs."""

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
        body: Dict[str, Any] = {"model": model, "messages": messages}
        if max_tokens is not None:
            body[self.max_tokens_field] = max_tokens
        if temperature is not None:
            body["temperature"] = temperature
        if stream:
            body["stream"] = True
            if self.stream_include_usage:
                body["stream_options"] = {"include_usage": True}
        if extra:
            body.update(extra)
        # After extra, so a rejected key cannot be put back. The raw request()
        # path does not call this.
        return adjust_body(
            self.provider, model, body, anthropic_version=getattr(self, "anthropic_version", None)
        )

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> ChatResult:
        """Call the chat once. Parameters that are not given are not sent.

        Fields the model is known to reject are removed after ``extra`` is
        merged (see ``_model_params``). ``timeout`` (seconds) is the client
        setting when ``None``, or an override for this call.
        """
        body = self._build_body(model, messages, max_tokens, temperature, extra, False)
        with singleflight(self, body):
            cached = self._lookup_chat_cache(body)
            if cached is not None:
                self._log_call(body, cached.raw, cached=True)
                return cached
            raw, meta = self._read_json("/chat/completions", body, timeout=timeout)
            result = apply_result_meta(_parse_response(raw), meta)
            self._cache_store(body, result)
            self._log_call(body, raw)
            return result

    def stream_chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Iterator[ChatChunk]:
        """Stream a chat and yield text deltas."""
        body = self._build_body(model, messages, max_tokens, temperature, extra, True)
        events, cached = self._stream_events("/chat/completions", body, timeout=timeout)
        chunks = self._log_chunks(body, self._iter_chunks(events), cached)
        return _TaggedIter(
            chunks,
            request_id=getattr(events, "request_id", None),
            retries=getattr(events, "retries", 0) or 0,
            started=getattr(events, "started", None),
            method=getattr(events, "method", None),
            path=getattr(events, "path", None),
            status_code=getattr(events, "status_code", None),
        )

    def _iter_chunks(self, events: Iterator[Any]) -> Iterator[ChatChunk]:
        headline = self._t("stream_error", provider=self.provider)
        request_id = getattr(events, "request_id", None)
        try:
            for ev in events:
                try:
                    chunk, terminal = _chunk_from_event(ev, headline)
                except APIStreamError as e:
                    note_stream_error(self, e, events)
                    raise
                except LLMError as e:
                    note_request_error(self, events, e.code)
                    raise
                if terminal:
                    break
                if chunk is not None:
                    chunk.request_id = request_id
                    yield chunk
            else:
                error = APIStreamError(
                    self._t("stream_incomplete", provider=self.provider),
                    code="stream_incomplete",
                )
                note_stream_error(self, error, events)
                raise error
        finally:
            close = getattr(events, "close", None)
            if close is not None:
                close()


class OpenAIClient(OpenAICompatClient):
    """Client for the OpenAI Chat Completions API."""

    provider = "openai"
    default_base_url = "https://api.openai.com/v1"
    api_key_env = "OPENAI_API_KEY"
    base_url_env = "OPENAI_BASE_URL"
    max_tokens_field = "max_completion_tokens"
    stream_include_usage = True
