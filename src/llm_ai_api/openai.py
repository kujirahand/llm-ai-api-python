"""OpenAI（および OpenAI 互換 API）のクライアント。"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple

from ._http import BaseClient, error_message
from .errors import APIStreamError
from .types import ChatChunk, ChatResult, SSEEvent, Usage


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # パーツ配列の場合は text を連結する
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
    """`/chat/completions` 形式の API の共通実装。"""

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
        return body

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
        """チャットを 1 回呼び出す。指定していないパラメータは送らない。

        `timeout`（秒）は `None` ならクライアントの設定、数値ならこの呼び出しだけ上書きする。
        """
        body = self._build_body(model, messages, max_tokens, temperature, extra, False)
        cached = self._cache_lookup(body)
        if cached is not None:
            self._log_call(body, cached.raw, cached=True)
            return cached
        raw = self.request("/chat/completions", body, timeout=timeout)
        result = _parse_response(raw)
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
        """ストリーミングでチャットを呼び出し、差分を順に返す。"""
        body = self._build_body(model, messages, max_tokens, temperature, extra, True)
        events, cached = self._stream_events("/chat/completions", body, timeout=timeout)
        return self._log_chunks(body, self._iter_chunks(events), cached)

    def _iter_chunks(self, events: Iterator[Any]) -> Iterator[ChatChunk]:
        headline = self._t("stream_error", provider=self.provider)
        for ev in events:
            chunk, terminal = _chunk_from_event(ev, headline)
            if terminal:
                break
            if chunk is not None:
                yield chunk


class OpenAIClient(OpenAICompatClient):
    """OpenAI Chat Completions API のクライアント。"""

    provider = "openai"
    default_base_url = "https://api.openai.com/v1"
    api_key_env = "OPENAI_API_KEY"
    base_url_env = "OPENAI_BASE_URL"
    max_tokens_field = "max_completion_tokens"
    stream_include_usage = True
