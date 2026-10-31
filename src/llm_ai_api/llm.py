"""共通インターフェイス `llm("プロバイダー:モデル")`。"""

from __future__ import annotations

from typing import Any, AsyncIterator, Dict, Iterator, List, Optional, TypeVar, Union

from ._async_clients import (
    _AsyncAnthropicClient,
    _AsyncGoogleClient,
    _AsyncOpenAIClient,
    _AsyncOpenRouterClient,
)
from ._async_http import _AsyncBaseClient
from ._http import BaseClient
from .anthropic import AnthropicClient
from .errors import LLMConfigError
from .google import GoogleClient
from .lang import t
from .openai import OpenAIClient
from .openrouter import OpenRouterClient
from .types import ChatResult

_PROVIDERS = {
    "openai": OpenAIClient,
    "openrouter": OpenRouterClient,
    "google": GoogleClient,
    "anthropic": AnthropicClient,
    "claude": AnthropicClient,
}

# Internal async clients, created lazily by LLM.aask() / achat() / astream().
_ASYNC_PROVIDERS = {
    "openai": _AsyncOpenAIClient,
    "openrouter": _AsyncOpenRouterClient,
    "google": _AsyncGoogleClient,
    "anthropic": _AsyncAnthropicClient,
    "claude": _AsyncAnthropicClient,
}


class _Unset:
    """Type of `UNSET`: "this argument was not passed" (as opposed to an explicit `None`)."""

    _instance: "Optional[_Unset]" = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()

_T = TypeVar("_T")


def _pick(value: Union[_T, _Unset], default: _T) -> _T:
    """Return `default` only when `value` was not passed; an explicit `None` is kept."""
    return default if isinstance(value, _Unset) else value


def parse_model_spec(spec: str, lang: Optional[str] = None) -> "tuple[str, str]":
    """`"provider:model"` を (provider, model) に分ける。最初の `:` で分割する。"""
    provider, sep, model = spec.partition(":")
    provider = provider.strip().lower()
    model = model.strip()
    if not sep or not provider or not model:
        raise LLMConfigError(t("invalid_model_spec", lang, spec=spec), code="invalid_model_spec")
    if provider not in _PROVIDERS:
        raise LLMConfigError(
            t("unknown_provider", lang, provider=provider, supported=", ".join(sorted(_PROVIDERS))),
            code="unknown_provider",
        )
    return provider, model


class LLM:
    """プロバイダーの違いを意識せずに使える共通インターフェイス。会話履歴は持たない。"""

    def __init__(
        self,
        spec: str,
        *,
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
        **client_options: Any,
    ) -> None:
        provider, model = parse_model_spec(spec, client_options.get("lang"))
        self.provider = "anthropic" if provider == "claude" else provider
        self.model = model
        self.system = system
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra = extra
        self.client: BaseClient = _PROVIDERS[provider](**client_options)
        # Kept to create the async client on first use (see _get_async_client).
        self._client_options = dict(client_options)
        self._provider_key = provider
        self._async_client_instance: Optional[_AsyncBaseClient] = None

    def __repr__(self) -> str:
        return "LLM(%r)" % ("%s:%s" % (self.provider, self.model))

    def close(self) -> None:
        """下位クライアントを閉じる。"""
        self.client.close()

    def __enter__(self) -> "LLM":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def _prepare(
        self,
        messages: List[Dict[str, Any]],
        system: Union[Optional[str], _Unset],
        max_tokens: Union[Optional[int], _Unset],
        temperature: Union[Optional[float], _Unset],
        extra: Union[Optional[Dict[str, Any]], _Unset],
    ) -> Dict[str, Any]:
        # Per-call arguments override the defaults given to llm(). An explicit None turns
        # the default off for this call; UNSET (not passed) keeps it.
        system = _pick(system, self.system)
        merged: Optional[Dict[str, Any]] = None
        if isinstance(extra, _Unset):
            merged = dict(self.extra) if self.extra else None
        elif extra is not None:  # shallow merge on top of the defaults
            merged = dict(self.extra or {})
            merged.update(extra)
        msgs = list(messages)
        if system is not None:
            msgs.insert(0, {"role": "system", "content": system})
        return {
            "model": self.model,
            "messages": msgs,
            "max_tokens": _pick(max_tokens, self.max_tokens),
            "temperature": _pick(temperature, self.temperature),
            "extra": merged,
        }

    def chat(
        self,
        messages: List[Dict[str, Any]],
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
    ) -> ChatResult:
        """messages を渡して `ChatResult`（stop_reason や raw を含む）を受け取る。"""
        kw = self._prepare(messages, system, max_tokens, temperature, extra)
        return self.client.chat(**kw)  # type: ignore[attr-defined]

    def ask(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
    ) -> str:
        """1 つの質問を送り、回答のテキストだけを返す。"""
        msgs = [{"role": "user", "content": prompt}]
        return self.chat(
            msgs, system=system, max_tokens=max_tokens, temperature=temperature, extra=extra
        ).text

    def stream(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
    ) -> Iterator[str]:
        """1 つの質問を送り、回答のテキスト差分を順に返す。"""
        msgs = [{"role": "user", "content": prompt}]
        kw = self._prepare(msgs, system, max_tokens, temperature, extra)
        chunks = self.client.stream_chat(**kw)  # type: ignore[attr-defined]
        return (c.text for c in chunks if c.text)

    # --- async ---------------------------------------------------------------

    def _get_async_client(self) -> _AsyncBaseClient:
        """Return the internal async client, creating it on first use."""
        if self._async_client_instance is None:
            self._async_client_instance = _ASYNC_PROVIDERS[self._provider_key](
                **self._client_options
            )
        return self._async_client_instance

    async def achat(
        self,
        messages: List[Dict[str, Any]],
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
    ) -> ChatResult:
        """Async `chat()`: send messages and return a `ChatResult`."""
        kw = self._prepare(messages, system, max_tokens, temperature, extra)
        return await self._get_async_client().achat(**kw)  # type: ignore[attr-defined]

    async def aask(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
    ) -> str:
        """Async `ask()`: send one question and return only the answer text."""
        msgs = [{"role": "user", "content": prompt}]
        result = await self.achat(
            msgs, system=system, max_tokens=max_tokens, temperature=temperature, extra=extra
        )
        return result.text

    def astream(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
    ) -> AsyncIterator[str]:
        """Async `stream()`: return an async iterator of answer text deltas.

        Use it directly with `async for` (no `await`). The request starts at the first
        iteration, so connection and HTTP errors are raised there. Call `aclose()` on
        the returned iterator to stop a stream early.
        """
        msgs = [{"role": "user", "content": prompt}]
        return _AsyncTextStream(self, msgs, system, max_tokens, temperature, extra)

    async def aclose(self) -> None:
        """Close the async client (if it was created) and the sync client.

        Safe to call more than once. A closed `LLM` cannot be used again; create a new
        one with `llm()` (for example, one per `asyncio.run()`).
        """
        try:
            if self._async_client_instance is not None:
                await self._async_client_instance.aclose()
        finally:
            # Close the sync client even if closing the async client is cancelled.
            self.client.close()

    async def __aenter__(self) -> "LLM":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()


class _AsyncTextStream:
    """Async iterator returned by `LLM.astream()`; yields non-empty text deltas.

    The request is sent at the first `__anext__()`, not when the stream is created.
    """

    def __init__(
        self,
        owner: LLM,
        messages: List[Dict[str, Any]],
        system: Union[Optional[str], _Unset],
        max_tokens: Union[Optional[int], _Unset],
        temperature: Union[Optional[float], _Unset],
        extra: Union[Optional[Dict[str, Any]], _Unset],
    ) -> None:
        self._owner = owner
        self._args = (messages, system, max_tokens, temperature, extra)
        self._chunks: Any = None
        self._done = False

    def __aiter__(self) -> "_AsyncTextStream":
        return self

    async def __anext__(self) -> str:
        if self._done:
            raise StopAsyncIteration
        try:
            if self._chunks is None:
                kw = self._owner._prepare(*self._args)
                client = self._owner._get_async_client()
                self._chunks = await client.stream_chat(**kw)  # type: ignore[attr-defined]
            while True:
                chunk = await self._chunks.__anext__()
                if chunk.text:
                    return chunk.text
        except StopAsyncIteration:
            self._done = True
            raise
        except BaseException:
            # Errors and asyncio.CancelledError: release the response, then propagate.
            self._done = True
            await self._close_chunks()
            raise

    async def _close_chunks(self) -> None:
        if self._chunks is not None:
            await self._chunks.aclose()

    async def aclose(self) -> None:
        """Stop the stream and close the response. Safe to call more than once."""
        self._done = True
        await self._close_chunks()


def llm(spec: str, **options: Any) -> LLM:
    """`llm("openai:gpt-6-luna")` のようにモデルを指定して `LLM` を作る。"""
    return LLM(spec, **options)
