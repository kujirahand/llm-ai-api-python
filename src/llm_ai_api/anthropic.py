"""Client for the Anthropic (Claude) Messages API."""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple

from ._singleflight import singleflight
from ._events import apply_result_meta, note_request_error, note_stream_error
from ._http import BaseClient, _TaggedIter
from ._model_params import adjust_body
from .errors import APIStreamError, LLMError
from .types import ChatChunk, ChatResult, SSEEvent, Usage

DEFAULT_MAX_TOKENS = 16000


def _sent_anthropic_version(client: Any) -> Optional[str]:
    """Return the ``anthropic-version`` value the request headers will send.

    ``_headers`` copies auth headers and then ``headers=``. A value under the
    exact key ``anthropic-version`` replaces the constructor's version, and
    that is the value the drop rules see. A differently cased name is a
    separate header entry, so it does not count as the version.
    """
    headers: Dict[str, Any] = {}
    headers.update(client._auth_headers())
    headers.update(getattr(client, "_extra_headers", None) or {})
    version = headers.get("anthropic-version")
    if isinstance(version, str):
        return version
    fallback = getattr(client, "anthropic_version", None)
    return fallback if isinstance(fallback, str) else None


def _split_system(messages: List[Dict[str, Any]]) -> Tuple[Any, List[Dict[str, Any]]]:
    """Pull system messages out. Join plain strings; return blocks if any part is not a string."""
    parts: List[Any] = []
    rest: List[Dict[str, Any]] = []
    for m in messages:
        if m.get("role") == "system":
            parts.append(m.get("content"))
        else:
            rest.append(m)
    if not parts:
        return None, rest
    if all(isinstance(p, str) for p in parts):
        return "\n\n".join(parts), rest
    blocks: List[Any] = []
    for p in parts:
        if isinstance(p, str):
            blocks.append({"type": "text", "text": p})
        elif isinstance(p, list):
            blocks.extend(p)
    return blocks, rest


def _parse_response(raw: Dict[str, Any]) -> ChatResult:
    """Build a `ChatResult` from a Messages API response (shared by sync and async)."""
    text = "".join(
        b.get("text", "")
        for b in raw.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    u = raw.get("usage")
    usage = (
        Usage(u.get("input_tokens"), u.get("output_tokens")) if isinstance(u, dict) else None
    )
    return ChatResult(
        text=text,
        model=raw.get("model"),
        stop_reason=raw.get("stop_reason"),
        usage=usage,
        raw=raw,
    )


def _chunk_from_event(
    ev: SSEEvent, stream_error_headline: str
) -> Tuple[Optional[ChatChunk], bool]:
    """Turn one SSE event into `(chunk, terminal)` (shared by sync and async).

    `ping` gives `(None, False)` (skip), `message_stop` gives `(None, True)`, and an
    `error` event raises `APIStreamError`.
    """
    raw = ev.json() if ev.data else {}
    kind = raw.get("type") or ev.event
    if kind == "ping":
        return None, False
    if kind == "error":
        err = raw.get("error") or {}
        detail = err.get("message") or raw  # not translated: comes from the API
        raise APIStreamError("%s: %s" % (stream_error_headline, detail), body=raw)
    if kind == "message_stop":
        return None, True
    text = ""
    if kind == "content_block_delta":
        delta = raw.get("delta") or {}
        if delta.get("type") == "text_delta":
            text = delta.get("text") or ""
    return ChatChunk(text=text, raw=raw), False


class AnthropicClient(BaseClient):
    """Client for the Anthropic Messages API."""

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
        system, rest = _split_system(messages)
        body: Dict[str, Any] = {
            "model": model,
            "messages": rest,
            "max_tokens": DEFAULT_MAX_TOKENS if max_tokens is None else max_tokens,
        }
        if system is not None:
            body["system"] = system
        if temperature is not None:
            body["temperature"] = temperature
        if stream:
            body["stream"] = True
        if extra:
            body.update(extra)
        # After extra, so a rejected key cannot be put back. Which keys are
        # rejected depends on the anthropic-version header that will be sent.
        # request() does not call this.
        return adjust_body(
            self.provider,
            model,
            body,
            anthropic_version=_sent_anthropic_version(self),
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
        """Call the chat once. Unspecified parameters other than ``max_tokens`` are not sent.

        When the sent ``anthropic-version`` is ``2026-10-21``, ``temperature``,
        ``top_p``, and ``top_k`` are removed after ``extra`` is merged. A
        ``headers`` entry with that exact name overrides ``anthropic_version``.
        ``timeout`` (seconds) is the client setting when ``None``, or an
        override for this call.
        """
        body = self._build_body(model, messages, max_tokens, temperature, extra, False)
        with singleflight(self, body):
            cached = self._lookup_chat_cache(body)
            if cached is not None:
                self._log_call(body, cached.raw, cached=True)
                return cached
            raw, meta = self._read_json("/v1/messages", body, timeout=timeout)
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
        events, cached = self._stream_events("/v1/messages", body, timeout=timeout)
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
