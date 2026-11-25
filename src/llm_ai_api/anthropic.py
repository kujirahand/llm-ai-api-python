"""Client for the Anthropic (Claude) Messages API."""

from __future__ import annotations

import copy
from dataclasses import fields
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ._tools import make_tool_call
from ._singleflight import singleflight
from ._events import apply_result_meta, note_request_error, note_stream_error
from ._http import BaseClient, _StreamAccumulator, _TaggedIter, build_auth_header
from ._model_params import adjust_body
from .errors import APIStreamError, LLMError
from .types import ChatChunk, ChatResult, SSEEvent, ToolCall, Usage, _optional_int

DEFAULT_MAX_TOKENS = 16000


def _sent_anthropic_version(client: Any) -> Optional[str]:
    """Return the version in the effective chat request headers."""
    version = client._headers(False, None).get("anthropic-version")
    return version if isinstance(version, str) else None


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


def _usage_from(u: Any) -> Optional[Usage]:
    """Build a `Usage` from a `usage` object (shared by responses and streams)."""
    if not isinstance(u, dict):
        return None
    return Usage(
        u.get("input_tokens"),
        u.get("output_tokens"),
        cache_read_tokens=_optional_int(u.get("cache_read_input_tokens")),
        cache_creation_tokens=_optional_int(u.get("cache_creation_input_tokens")),
    )


def _derive_anthropic(
    raw: Dict[str, Any],
) -> Tuple[List[ToolCall], Optional[str], Optional[Dict[str, Any]]]:
    """Read `(tool_calls, thinking, message)` from a response without changing it."""
    content = raw.get("content")
    if not isinstance(content, list):
        return [], None, None
    tool_calls: List[ToolCall] = []
    thoughts: List[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "tool_use":
            call = make_tool_call(block.get("id"), block.get("name"), block.get("input"), "tool_use", block)
            if call is not None:
                tool_calls.append(call)
        elif kind == "thinking" and isinstance(block.get("thinking"), str) and block["thinking"]:
            thoughts.append(block["thinking"])
    thinking = "\n\n".join(thoughts) if thoughts else None
    return tool_calls, thinking, {"role": "assistant", "content": copy.deepcopy(content)}


def _parse_response(raw: Dict[str, Any]) -> ChatResult:
    """Build a `ChatResult` from a Messages API response (shared by sync and async)."""
    text = "".join(
        b.get("text", "")
        for b in raw.get("content") or []
        if isinstance(b, dict) and b.get("type") == "text"
    )
    tool_calls, thinking, message = _derive_anthropic(raw)
    return ChatResult(
        text=text,
        model=raw.get("model"),
        stop_reason=raw.get("stop_reason"),
        usage=_usage_from(raw.get("usage")),
        raw=raw,
        tool_calls=tool_calls,
        thinking=thinking,
        message=message,
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


class _AnthropicStreamResult(_StreamAccumulator):
    """Stream accumulator for Messages API events (shared by sync and async).

    `message_start` carries the model and the input-side usage; `message_delta`
    carries `stop_reason` and the output usage. Usage is merged field by field,
    keeping the last non-None value of each.
    """

    def __init__(self) -> None:
        super().__init__()
        self._usage_merged: Optional[Usage] = None

    def _merge_usage(self, u: Any) -> None:
        new = _usage_from(u)
        if new is None:
            return
        if self._usage_merged is None:
            self._usage_merged = Usage()
        for f in fields(Usage):
            value = getattr(new, f.name)
            if value is not None:
                setattr(self._usage_merged, f.name, value)

    def _observe(self, raw: Dict[str, Any]) -> None:
        kind = raw.get("type")
        if kind == "message_start":
            message = raw.get("message")
            if isinstance(message, dict):
                if isinstance(message.get("model"), str):
                    self.model = message["model"]
                self._merge_usage(message.get("usage"))
        elif kind == "message_delta":
            delta = raw.get("delta")
            if isinstance(delta, dict) and delta.get("stop_reason") is not None:
                self.stop_reason = delta["stop_reason"]
            self._merge_usage(raw.get("usage"))

    def _usage(self) -> Optional[Usage]:
        return self._usage_merged


class AnthropicClient(BaseClient):
    """Client for the Anthropic Messages API."""

    provider = "anthropic"
    default_base_url = "https://api.anthropic.com"
    api_key_env = "ANTHROPIC_API_KEY"
    base_url_env = "ANTHROPIC_BASE_URL"
    api_format = "anthropic"
    auth_header = "x-api-key"
    auth_scheme = ""
    models_style = "anthropic"

    def __init__(
        self, *args: Any, anthropic_version: str = "2026-10-21", **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.anthropic_version = anthropic_version

    def _cache_context(self) -> Dict[str, Any]:
        """Add the API version to the cache key context (it is sent as a header)."""
        context = super()._cache_context()
        context["anthropic_version"] = _sent_anthropic_version(self)
        return context

    def _auth_headers(self) -> Dict[str, str]:
        headers = dict(self.fixed_headers)
        headers["anthropic-version"] = self.anthropic_version
        headers.update(build_auth_header(self.auth_header, self.auth_scheme, self._api_key))
        return headers

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
            self.rules_provider or self.provider,
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
        ``headers`` entry with that name, regardless of case, overrides ``anthropic_version``.
        ``timeout`` (seconds) is the client setting when ``None``, or an
        override for this call.
        """
        body = self._build_body(model, messages, max_tokens, temperature, extra, False)
        with singleflight(self, body):
            cached = self._lookup_chat_cache(body)
            if cached is not None:
                self._log_call(body, cached.raw, cached=True)
                cached.tool_calls, cached.thinking, cached.message = _derive_anthropic(cached.raw)
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
        acc = _AnthropicStreamResult()
        chunks = self._log_chunks(body, self._iter_chunks(events, acc), cached)
        return _TaggedIter(
            chunks,
            result_source=acc,
            request_id=getattr(events, "request_id", None),
            retries=getattr(events, "retries", 0) or 0,
            started=getattr(events, "started", None),
            method=getattr(events, "method", None),
            path=getattr(events, "path", None),
            status_code=getattr(events, "status_code", None),
        )

    def _iter_chunks(
        self, events: Iterator[Any], acc: Optional[_StreamAccumulator] = None
    ) -> Iterator[ChatChunk]:
        headline = self._t("stream_error", provider=self.provider)
        request_id = getattr(events, "request_id", None)
        terminal_seen = False
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
                    terminal_seen = True
                    break
                if chunk is not None:
                    chunk.request_id = request_id
                    if acc is not None:
                        acc.add(chunk)
                    yield chunk
                elif acc is not None:
                    # The parser skips this event (ping); it still belongs in
                    # the result's raw["events"].
                    acc.add_event(ev.json() if ev.data else {})
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
            # Complete only after the event stream is closed, so a failure
            # while closing cannot leave a result behind.
            if terminal_seen and acc is not None:
                acc.complete(getattr(events, "started", None))
