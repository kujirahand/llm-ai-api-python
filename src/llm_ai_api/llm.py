"""共通インターフェイス `llm("プロバイダー:モデル")`。"""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, TypeVar, Union

from ._async_clients import (
    _AsyncAnthropicClient,
    _AsyncGoogleClient,
    _AsyncOpenAIClient,
    _AsyncOpenRouterClient,
)
from ._async_http import _AsyncBaseClient
from ._http import BaseClient, _check_retry_after_max
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

# Internal async clients, created lazily by LLM.aask() / achat() / aask_stream() / achat_stream().
_ASYNC_PROVIDERS = {
    "openai": _AsyncOpenAIClient,
    "openrouter": _AsyncOpenRouterClient,
    "google": _AsyncGoogleClient,
    "anthropic": _AsyncAnthropicClient,
    "claude": _AsyncAnthropicClient,
}

# Client attributes that LLM.set_config() can change after construction.
_RETRY_SETTINGS = ("max_retries", "retry_read_timeout", "retry_after_max")


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
        """下位の同期クライアントを閉じる。

        非同期クライアントは閉じない。非同期 API を使った場合は `aclose()` を使うこと。
        """
        self.client.close()

    def set_config(
        self,
        *,
        max_retries: Union[int, _Unset] = UNSET,
        retry_read_timeout: Union[bool, _Unset] = UNSET,
        retry_after_max: Union[float, _Unset] = UNSET,
    ) -> None:
        """生成後にリトライ設定を変更する。渡した引数だけを変え、他はそのまま。

        同期クライアントと、作成済みなら非同期クライアントの両方に反映する
        （非同期クライアントを後で作る場合も、その時点の値を使う）。
        """
        changes = {
            "max_retries": max_retries,
            "retry_read_timeout": retry_read_timeout,
            "retry_after_max": retry_after_max,
        }
        if not isinstance(retry_after_max, _Unset):
            # Validate before applying anything, so a bad value changes nothing.
            _check_retry_after_max(retry_after_max, self.client.lang)
        clients: List[Any] = [self.client]
        if self._async_client_instance is not None:
            clients.append(self._async_client_instance)
        for name, value in changes.items():
            if isinstance(value, _Unset):
                continue
            for client in clients:
                setattr(client, name, value)

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
        timeout: Optional[float] = None,
    ) -> ChatResult:
        """messages を渡して `ChatResult`（stop_reason や raw を含む）を受け取る。

        `timeout`（秒）は、この呼び出しだけクライアントのタイムアウトを上書きする（`None` なら
        クライアントの設定）。操作ごとのタイムアウトで、合計の期限ではない（リトライで延びる）。
        """
        kw = self._prepare(messages, system, max_tokens, temperature, extra)
        return self.client.chat(timeout=timeout, **kw)  # type: ignore[attr-defined]

    def ask(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
        timeout: Optional[float] = None,
    ) -> str:
        """1 つの質問を送り、回答のテキストだけを返す。`timeout` は `chat()` と同じ。"""
        msgs = [{"role": "user", "content": prompt}]
        return self.chat(
            msgs,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            timeout=timeout,
        ).text

    def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
        timeout: Optional[float] = None,
    ) -> Iterator[str]:
        """Send messages and yield text deltas. `timeout` matches `chat()`
        (for a stream it is the time to wait for the next data).

        The returned iterator has `request_id` and `retries` as soon as `chat_stream()`
        returns (response headers have already been received). Read the iterator
        to the end, or call `close()`, to release the connection. Dropping it
        also closes the response when it is garbage-collected.
        """
        kw = self._prepare(messages, system, max_tokens, temperature, extra)
        chunks = self.client.stream_chat(timeout=timeout, **kw)  # type: ignore[attr-defined]
        return _TextStream(chunks)

    def ask_stream(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
        timeout: Optional[float] = None,
    ) -> Iterator[str]:
        """Send one question and yield text deltas. Same as `chat_stream()` with a
        single user message; the returned iterator is the same.
        """
        msgs = [{"role": "user", "content": prompt}]
        return self.chat_stream(
            msgs,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            timeout=timeout,
        )

    def stream(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
        timeout: Optional[float] = None,
    ) -> Iterator[str]:
        """Deprecated: use `ask_stream()`. Kept as an alias that delegates to it."""
        return self.ask_stream(
            prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            timeout=timeout,
        )

    # --- async ---------------------------------------------------------------

    def _get_async_client(self) -> _AsyncBaseClient:
        """Return the internal async client, creating it on first use."""
        if self._async_client_instance is None:
            options = dict(self._client_options)
            # Mirror the sync client: reuse the settings it resolved at
            # construction instead of resolving the raw options again, which
            # could pick up global changes made after llm() (set_cache() and
            # friends) and would build separate cache/log instances.
            options["base_url"] = self.client.base_url
            options["cache"] = self.client.cache
            options["connection"] = self.client.connection
            options["log"] = self.client.log
            options["api" + "_key"] = getattr(self.client, "_api" + "_key")  # resolved key
            # Current retry settings, including changes made by set_config().
            for name in _RETRY_SETTINGS:
                options[name] = getattr(self.client, name)
            client = _ASYNC_PROVIDERS[self._provider_key](**options)
            # One listener list for sync and async calls on this LLM.
            client._events = self.client._events
            self._async_client_instance = client
        return self._async_client_instance

    def add_event_listener(self, event: Optional[str], listener: Callable[..., Any]) -> None:
        """Register ``listener`` for ``event``, or for every event when ``event`` is None.

        ``listener(event, payload)`` is called synchronously with a plain dict,
        including from ``aask`` / ``achat`` / ``aask_stream`` / ``achat_stream`` (on the event loop thread,
        so a listener should not block). ``Exception`` raised by a listener is
        discarded and does not affect the request, retries, or later listeners.
        ``BaseException`` (cancellation, keyboard interrupt) is not caught.

        The same function can be registered more than once; each registration is
        called, in registration order. Listeners on this ``LLM`` are shared by
        the sync client and the async client. ``m.client.add_event_listener``
        registers on that same list.

        Unknown event names raise ``LLMConfigError`` (``code="invalid_event"``).
        A listener that is not callable raises ``LLMConfigError``
        (``code="invalid_listener"``).

        Events (payloads never include the API key, auth headers, or bodies):

        - ``retry``: a failed attempt will be retried. Keys: ``provider``,
          ``method``, ``path``, ``stream``, ``attempt`` (0-based index of the
          attempt that failed), ``retries`` (same number: retries already
          finished before that attempt), ``max_retries``, ``delay`` (seconds
          to sleep), ``reason`` (``status``, ``connect``, ``timeout``,
          ``read_timeout``, ``transport``), ``status_code``, ``request_id``.
        - ``connection_error``: a transport failure that will not be retried,
          including a drop while reading a stream. Keys: those of ``retry``
          except ``max_retries`` and ``delay``, plus ``latency`` (seconds) and
          ``code`` (``timeout`` or ``connection_error``).
        - ``response``: an HTTP response with status < 400 was accepted.
          ``latency`` is time-to-body for a normal call and time-to-headers
          for a stream. ``cached`` is False.
        - ``http_error``: a final HTTP error (raised as ``APIStatusError``).
        - ``request_error``: the library rejected the body (``code`` is
          ``response_too_large`` or ``invalid_json_response``).
        - ``stream_error``: an error event in the stream (raised as
          ``APIStreamError``). Keys: ``provider``, ``request_id``, ``retries``,
          ``latency``, ``stream``, ``code``.
        - ``stream_end``: a live stream was closed after a terminal SSE event.
          Keys: ``provider``, ``request_id``, ``retries``, ``latency`` (until
          close), ``stream``, ``complete``.
        - ``cache_hit``: ``chat`` / ``stream_chat`` (and the async twins) served
          a stored response. No ``response`` event is emitted. Keys:
          ``provider``, ``stream``, ``model``, ``request_id``, ``retries``,
          ``latency`` (the stored values), ``cached``.
        """
        self.client.add_event_listener(event, listener)

    def remove_event_listener(self, event: Optional[str], listener: Callable[..., Any]) -> None:
        """Remove one registration of ``listener`` for ``event``.

        ``event`` must match the value passed to ``add_event_listener`` (``None``
        only removes an all-events registration). An unknown event name raises
        ``LLMConfigError`` (``code="invalid_event"``). Removing a listener that
        was not registered does nothing. Comparison is by identity.
        """
        self.client.remove_event_listener(event, listener)

    async def achat(
        self,
        messages: List[Dict[str, Any]],
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
        timeout: Optional[float] = None,
    ) -> ChatResult:
        """Async `chat()`: send messages and return a `ChatResult`.

        `timeout` (seconds) overrides the client timeout for this call only (`None` keeps
        the client's setting). It is a per-operation timeout, not a total deadline: retries
        extend it. Use `asyncio.wait_for()` for a hard deadline.
        """
        kw = self._prepare(messages, system, max_tokens, temperature, extra)
        return await self._get_async_client().achat(timeout=timeout, **kw)  # type: ignore[attr-defined]

    async def aask(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
        timeout: Optional[float] = None,
    ) -> str:
        """Async `ask()`: send one question and return only the answer text.

        `timeout` is the same as in `achat()`.
        """
        msgs = [{"role": "user", "content": prompt}]
        result = await self.achat(
            msgs,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            timeout=timeout,
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
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        """Deprecated: use `aask_stream()`. Kept as an alias that delegates to it."""
        return self.aask_stream(
            prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            timeout=timeout,
        )

    def aask_stream(
        self,
        prompt: str,
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        """Async `ask_stream()`: send one question and iterate answer text deltas.

        Same as `achat_stream()` with a single user message (use `async for`, no `await`).
        """
        msgs = [{"role": "user", "content": prompt}]
        return self.achat_stream(
            msgs,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            extra=extra,
            timeout=timeout,
        )

    def achat_stream(
        self,
        messages: List[Dict[str, Any]],
        *,
        system: Union[Optional[str], _Unset] = UNSET,
        max_tokens: Union[Optional[int], _Unset] = UNSET,
        temperature: Union[Optional[float], _Unset] = UNSET,
        extra: Union[Optional[Dict[str, Any]], _Unset] = UNSET,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[str]:
        """Async `chat_stream()`: return an async iterator of answer text deltas.

        Use it directly with `async for` (no `await`). The request starts at the first
        iteration, so connection and HTTP errors are raised there. `request_id` and
        `retries` are set once that iteration has received the response headers,
        before the first text delta is yielded (they stay None if the call fails
        before headers). Call `aclose()` on the returned iterator to stop a stream
        early. `timeout` is the same as in `achat()` (for a stream it is the time
        to wait for the next data).
        """
        return _AsyncTextStream(self, messages, system, max_tokens, temperature, extra, timeout)

    async def aclose(self) -> None:
        """Close both the async client (if it was created) and the sync client.

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


class _TextStream:
    """Iterator of non-empty text deltas returned by `LLM.chat_stream()` / `ask_stream()`.

    `request_id` and `retries` are copied from the underlying chunk iterator,
    which already has them when `chat_stream()` returns.
    """

    def __init__(self, chunks: Any) -> None:
        self._chunks = chunks
        self.request_id = getattr(chunks, "request_id", None)
        self.retries = getattr(chunks, "retries", 0) or 0
        self._closed = False

    def __iter__(self) -> "_TextStream":
        return self

    def __next__(self) -> str:
        if self._closed:
            raise StopIteration
        while True:
            chunk = next(self._chunks)
            if getattr(chunk, "text", None):
                return chunk.text

    def close(self) -> None:
        """Stop the stream and close the response. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        close = getattr(self._chunks, "close", None)
        if close is None:
            return
        try:
            close()
        except Exception:
            pass

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass


class _AsyncTextStream:
    """Async iterator returned by `LLM.achat_stream()` / `aask_stream()`; yields non-empty text deltas.

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
        timeout: Optional[float] = None,
    ) -> None:
        self._owner = owner
        self._args = (messages, system, max_tokens, temperature, extra)
        self._timeout = timeout
        self._chunks: Any = None
        self._done = False
        # Filled once the first iteration has received response headers.
        self.request_id: Optional[str] = None
        self.retries: int = 0

    def __aiter__(self) -> "_AsyncTextStream":
        return self

    async def __anext__(self) -> str:
        if self._done:
            raise StopAsyncIteration
        try:
            if self._chunks is None:
                kw = self._owner._prepare(*self._args)
                client = self._owner._get_async_client()
                self._chunks = await client.stream_chat(timeout=self._timeout, **kw)  # type: ignore[attr-defined]
                self.request_id = getattr(self._chunks, "request_id", None)
                self.retries = getattr(self._chunks, "retries", 0) or 0
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
