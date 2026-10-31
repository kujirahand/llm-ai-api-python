"""Anthropic (Claude) Messages API のクライアント。"""

from __future__ import annotations

from typing import Any, Dict, Iterator, List, Optional, Tuple

from ._http import BaseClient
from .errors import APIStreamError
from .types import ChatChunk, ChatResult, Usage

DEFAULT_MAX_TOKENS = 16000


def _split_system(messages: List[Dict[str, Any]]) -> Tuple[Any, List[Dict[str, Any]]]:
    """messages から system を取り出す。文字列だけなら連結した文字列、ブロックを含むなら配列を返す。"""
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


class AnthropicClient(BaseClient):
    """Anthropic Messages API のクライアント。"""

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
        return body

    def chat(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        *,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> ChatResult:
        """チャットを 1 回呼び出す。`max_tokens` 以外の未指定パラメータは送らない。"""
        body = self._build_body(model, messages, max_tokens, temperature, extra, False)
        cached = self._cache_lookup(body)
        if cached is not None:
            self._log_call(body, cached.raw, cached=True)
            return cached
        raw = self.request("/v1/messages", body)
        text = "".join(
            b.get("text", "")
            for b in raw.get("content") or []
            if isinstance(b, dict) and b.get("type") == "text"
        )
        u = raw.get("usage")
        usage = (
            Usage(u.get("input_tokens"), u.get("output_tokens")) if isinstance(u, dict) else None
        )
        result = ChatResult(
            text=text,
            model=raw.get("model"),
            stop_reason=raw.get("stop_reason"),
            usage=usage,
            raw=raw,
        )
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
    ) -> Iterator[ChatChunk]:
        """ストリーミングでチャットを呼び出し、差分を順に返す。"""
        body = self._build_body(model, messages, max_tokens, temperature, extra, True)
        events, cached = self._stream_events("/v1/messages", body)
        return self._log_chunks(body, self._iter_chunks(events), cached)

    def _iter_chunks(self, events: Iterator[Any]) -> Iterator[ChatChunk]:
        for ev in events:
            raw = ev.json() if ev.data else {}
            kind = raw.get("type") or ev.event
            if kind == "ping":
                continue
            if kind == "error":
                err = raw.get("error") or {}
                detail = err.get("message") or raw  # API が返したメッセージは翻訳しない
                raise APIStreamError(
                    "%s: %s" % (self._t("stream_error", provider=self.provider), detail),
                    body=raw,
                )
            if kind == "message_stop":
                break
            text = ""
            if kind == "content_block_delta":
                delta = raw.get("delta") or {}
                if delta.get("type") == "text_delta":
                    text = delta.get("text") or ""
            yield ChatChunk(text=text, raw=raw)
