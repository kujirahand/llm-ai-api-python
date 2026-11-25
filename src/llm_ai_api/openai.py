"""Clients for OpenAI and OpenAI-compatible chat APIs."""

from __future__ import annotations

import copy
from typing import Any, Dict, Iterator, List, Optional, Tuple

from ._tools import make_tool_call
from ._singleflight import singleflight
from ._events import apply_result_meta, note_request_error, note_stream_error
from ._http import BaseClient, _StreamAccumulator, _TaggedIter, build_auth_header, error_message
from ._model_params import adjust_body
from .errors import APIStreamError, LLMError
from .types import ChatChunk, ChatResult, SSEEvent, ToolCall, Usage, _optional_int


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


def _usage_from(u: Any) -> Optional[Usage]:
    """Build a `Usage` from a `usage` object (shared by responses and streams)."""
    if not isinstance(u, dict):
        return None
    prompt_details = u.get("prompt_tokens_details")
    completion_details = u.get("completion_tokens_details")
    return Usage(
        u.get("prompt_tokens"),
        u.get("completion_tokens"),
        cache_read_tokens=_optional_int(
            prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None
        ),
        reasoning_tokens=_optional_int(
            completion_details.get("reasoning_tokens")
            if isinstance(completion_details, dict)
            else None
        ),
    )


def _derive_openai(raw: Dict[str, Any]) -> Tuple[List[ToolCall], Optional[str], Optional[Dict[str, Any]]]:
    """Read `(tool_calls, thinking, message)` from a response without changing it."""
    choices = raw.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else None
    message = choice.get("message") if isinstance(choice, dict) else None
    if not isinstance(message, dict):
        return [], None, None

    tool_calls: List[ToolCall] = []
    elements = message.get("tool_calls")
    for element in elements if isinstance(elements, list) else []:
        if not isinstance(element, dict):
            continue
        kind = element.get("type")
        kind = kind if isinstance(kind, str) else ""
        inner = element.get(kind) if kind else None
        if kind == "function":
            fn = element.get("function")
            source = fn if isinstance(fn, dict) else {}
            name, arguments = source.get("name"), source.get("arguments")
        elif isinstance(inner, dict):
            name = inner.get("name")
            arguments = inner["arguments"] if "arguments" in inner else inner.get("input")
        else:
            name = element.get("name")
            arguments = element["arguments"] if "arguments" in element else element.get("input")
        call = make_tool_call(element.get("id"), name, arguments, kind, element)
        if call is not None:
            tool_calls.append(call)

    thinking: Optional[str] = None
    for key in ("reasoning_content", "reasoning"):
        value = message.get(key)
        if isinstance(value, str) and value:
            thinking = value
            break
    return tool_calls, thinking, copy.deepcopy(message)


def _parse_response(raw: Dict[str, Any]) -> ChatResult:
    """Build a `ChatResult` from a `/chat/completions` response (shared by sync and async)."""
    choices = raw.get("choices") or [{}]
    choice = choices[0] or {}
    usage = _usage_from(raw.get("usage"))
    tool_calls, thinking, message = _derive_openai(raw)
    return ChatResult(
        text=_text_of((choice.get("message") or {}).get("content")),
        model=raw.get("model"),
        stop_reason=choice.get("finish_reason"),
        usage=usage,
        raw=raw,
        tool_calls=tool_calls,
        thinking=thinking,
        message=message,
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


class _OpenAIStreamResult(_StreamAccumulator):
    """Stream accumulator for `/chat/completions` events (shared by sync and async)."""

    def __init__(self) -> None:
        super().__init__()
        self._usage_raw: Optional[Dict[str, Any]] = None

    def _observe(self, raw: Dict[str, Any]) -> None:
        if isinstance(raw.get("model"), str):
            self.model = raw["model"]
        choices = raw.get("choices") or []
        choice = choices[0] if choices else None
        if isinstance(choice, dict) and choice.get("finish_reason") is not None:
            self.stop_reason = choice["finish_reason"]
        if isinstance(raw.get("usage"), dict):
            self._usage_raw = raw["usage"]

    def _usage(self) -> Optional[Usage]:
        return _usage_from(self._usage_raw)


class OpenAICompatClient(BaseClient):
    """Shared implementation for ``/chat/completions``-style APIs."""

    max_tokens_field = "max_tokens"
    stream_include_usage = False

    def _auth_headers(self) -> Dict[str, str]:
        headers = dict(self.fixed_headers)
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
            self.rules_provider or self.provider,
            model,
            body,
            anthropic_version=getattr(self, "anthropic_version", None),
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
                cached.tool_calls, cached.thinking, cached.message = _derive_openai(cached.raw)
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
        acc = _OpenAIStreamResult()
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


class OpenAIClient(OpenAICompatClient):
    """Client for the OpenAI Chat Completions API."""

    provider = "openai"
    default_base_url = "https://api.openai.com/v1"
    api_key_env = "OPENAI_API_KEY"
    base_url_env = "OPENAI_BASE_URL"
    max_tokens_field = "max_completion_tokens"
    stream_include_usage = True
    supports_audio = True
