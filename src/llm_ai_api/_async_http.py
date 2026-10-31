"""Async HTTP layer (internal): httpx.AsyncClient, SSE reading, retries.

The async counterpart of `_http.BaseClient`. It is not exported; the public async API
is `LLM.aask()` / `achat()` / `astream()`. HTTP control is duplicated in a small form
instead of being merged with the sync client; pure helpers are imported from `_http`.

Streams are plain classes implementing `__anext__` / `aclose` rather than async
generators, so closing them never needs an `await` inside a generator's `finally`.
httpx exceptions are converted to package exceptions here and never escape.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import time
import warnings
from typing import Any, AsyncIterable, AsyncIterator, Callable, Dict, List, Mapping, Optional, Tuple

import httpx

from . import _http
from ._events import (
    EventDispatcher,
    _CallMeta,
    cache_hit_payload,
    note_request_error,
    note_stream_error,
    request_id_of,
    retry_payload,
)
from ._http import (
    _DEFAULT_RETRY_AFTER_MAX,
    _RETRY_STATUS,
    _check_retry_after_max,
    _is_retryable_transport_error,
    _mask_url,
    _is_terminal_event,
    _retry_after_delay,
    _transport_reason,
    _SSEDecoder,
    _user_agent,
    error_message,
)
from ._connection import build_httpx_kwargs, resolve_connection
from .cache import CACHE_NOT_SET, SQLiteCache, cache_key, resolve_cache
from .errors import (
    APIConnectionError,
    APIStatusError,
    APIStreamError,
    APITimeoutError,
    LLMConfigError,
    LLMError,
    status_error_class,
)
from .lang import t
from .log import LOG_NOT_SET, resolve_log
from .types import ChatChunk, ChatResult, SSEEvent


async def aiter_sse(
    lines: AsyncIterable[str], lang: Optional[str] = None
) -> AsyncIterator[SSEEvent]:
    """Async version of `iter_sse()`: yield SSE events from an async iterable of lines."""
    decoder = _SSEDecoder(lang)
    async for line in lines:
        ev = decoder.feed(line)
        if ev is not None:
            yield ev
    ev = decoder.flush()
    if ev is not None:
        yield ev


async def _close_quietly(it: Any) -> None:
    """Call `it.aclose()` if it exists, ignoring errors (best-effort cleanup)."""
    aclose = getattr(it, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        pass


class _AsyncBaseClient:
    """Async counterpart of `_http.BaseClient` (raw layer). Internal only."""

    provider = ""
    default_base_url = ""
    api_key_env = ""
    api_key_env_fallbacks: Tuple[str, ...] = ()  # tried after `api_key_env`
    base_url_env = ""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 600.0,
        max_retries: int = 2,
        headers: Optional[Dict[str, str]] = None,
        *,
        retry_read_timeout: bool = False,
        retry_after_max: float = _DEFAULT_RETRY_AFTER_MAX,
        lang: Optional[str] = None,
        cache: Any = CACHE_NOT_SET,
        log: Any = LOG_NOT_SET,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        connection: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Same arguments as `BaseClient`; `transport` is for tests (`httpx.MockTransport`).

        `connection` mirrors `BaseClient`: it overrides `set_connection()` settings per key
        and is validated but not applied to httpx when `transport` is specified.
        """
        self.lang = lang
        _check_retry_after_max(retry_after_max, lang)
        self._events = EventDispatcher()
        self.cache = resolve_cache(cache, lang=lang)
        self.log = resolve_log(log, lang=lang)
        key = api_key
        for name in (self.api_key_env,) + self.api_key_env_fallbacks:
            key = key or os.environ.get(name)
        if not key:
            raise LLMConfigError(
                t("missing_api_key", lang, provider=self.provider, env=self.api_key_env),
                code="missing_api_key",
            )
        self._api_key = key
        self.base_url = (
            base_url or os.environ.get(self.base_url_env) or self.default_base_url
        ).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_read_timeout = retry_read_timeout
        self.retry_after_max = retry_after_max
        self.connection = resolve_connection(connection, lang=lang)
        self._connect_timeout = self.connection["connect_timeout"]
        self._extra_headers = dict(headers or {})
        if transport is not None:
            self._client = httpx.AsyncClient(
                transport=transport,
                timeout=httpx.Timeout(timeout, connect=self._connect_timeout),
            )
        else:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(timeout, connect=self._connect_timeout),
                **build_httpx_kwargs(self.connection, lang=lang),
            )

    def add_event_listener(self, event: Optional[str], listener: Any) -> None:
        """Same contract as ``BaseClient.add_event_listener`` (internal client)."""
        self._events.add(event, listener, self.lang)

    def remove_event_listener(self, event: Optional[str], listener: Any) -> None:
        """Same contract as ``BaseClient.remove_event_listener`` (internal client)."""
        self._events.remove(event, listener, self.lang)

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        self._events.emit(event, payload)

    def __repr__(self) -> str:
        return "%s(base_url=%r)" % (type(self).__name__, _mask_url(self.base_url))

    async def aclose(self) -> None:
        """Close the internal HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "_AsyncBaseClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.aclose()

    # --- cache and log (same as BaseClient; file I/O runs in a thread) ---------

    def _cache_context(self) -> Dict[str, Any]:
        """Client settings that can change a response for the same body (see BaseClient)."""
        return {
            "base_url": self.base_url,
            "headers": dict(self._extra_headers),
        }

    def _cache_lookup(self, body: Dict[str, Any]) -> Optional[ChatResult]:
        if self.cache is None:
            return None
        try:
            key = cache_key(self.provider, body, self._cache_context(), self._api_key)
            if isinstance(self.cache, SQLiteCache):
                return self.cache.get(key, secret=self._api_key)
            return self.cache.get(key)
        except Exception:
            # The cache is best-effort at runtime: treat any failure as a miss.
            return None

    def _cache_store(self, body: Dict[str, Any], result: ChatResult) -> None:
        if self.cache is None:
            return
        try:
            key = cache_key(self.provider, body, self._cache_context(), self._api_key)
            if isinstance(self.cache, SQLiteCache):
                self.cache.put(key, self.provider, result, secret=self._api_key)
            else:
                self.cache.put(key, self.provider, result)
        except Exception:
            # A cache failure must not lose an API response the caller already paid for.
            pass

    def _log_call(
        self, body: Dict[str, Any], response: Any, *, stream: bool = False, cached: bool = False
    ) -> None:
        if self.log is None:
            return
        try:
            self.log.write(
                self.provider, body.get("model"), body, response, stream=stream, cached=cached
            )
        except Exception:
            # A log failure must not lose an API response the caller already paid for.
            pass

    async def _acache_lookup(self, body: Dict[str, Any]) -> Optional[ChatResult]:
        if self.cache is None:
            return None
        return await asyncio.to_thread(self._cache_lookup, body)

    async def _acache_store(self, body: Dict[str, Any], result: ChatResult) -> None:
        if self.cache is None:
            return
        await asyncio.to_thread(self._cache_store, body, result)

    async def _alog_call(
        self, body: Dict[str, Any], response: Any, *, stream: bool = False, cached: bool = False
    ) -> None:
        if self.log is None:
            return
        await asyncio.to_thread(self._log_call, body, response, stream=stream, cached=cached)

    def _alog_chunks(
        self, chunks: Any, body: Dict[str, Any], cached: bool
    ) -> "_AsyncLoggedChunks":
        """Pass chunks through and log the whole stream once it has been read to the end."""
        return _AsyncLoggedChunks(self, chunks, body, cached)

    async def _alookup_chat_cache(self, body: Dict[str, Any]) -> Optional[ChatResult]:
        """Return a cached chat result and emit ``cache_hit``, or None on a miss."""
        cached = await self._acache_lookup(body)
        if cached is None:
            return None
        self._emit("cache_hit", cache_hit_payload(self.provider, False, body.get("model"), cached))
        return cached

    async def _astream_events(
        self, path: str, body: Dict[str, Any], timeout: Optional[float] = None
    ) -> Tuple[Any, bool]:
        """`request_stream()` with the response cache: replay a hit, record a miss.

        Returns the events (an async iterator with `aclose()`) and whether they were
        replayed from the cache. The iterator exposes `request_id` and `retries`.
        """
        cached = await self._acache_lookup(body)
        if cached is not None and isinstance(cached.raw.get("events"), list):
            replay = [SSEEvent(e.get("event"), e.get("data", "")) for e in cached.raw["events"]]
            self._emit(
                "cache_hit", cache_hit_payload(self.provider, True, body.get("model"), cached)
            )
            return _ReplayEvents(replay, cached.request_id, cached.retries), True
        events = await self.request_stream(path, body, timeout=timeout)
        if self.cache is None:
            return events, False
        return _AsyncRecordedEvents(self, events, body), False

    # --- implemented by subclasses ---------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        raise NotImplementedError

    # --- raw layer -------------------------------------------------------------

    async def request(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send JSON and return the response JSON (dict) as is."""
        value, _meta = await self._read_json(
            path, body, method=method, headers=headers, timeout=timeout
        )
        return value

    async def _read_json(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[Dict[str, Any], _CallMeta]:
        """Like ``request()``, but also return call metadata for ``achat()``."""
        resp, meta = await self._aopen(method, path, body, headers, timeout, stream=False)
        try:
            if len(resp.content) > _http._MAX_RESPONSE_BYTES:
                self._emit_request_error(meta, "response_too_large")
                raise _http._too_large(_http._MAX_RESPONSE_BYTES, self.lang)
            try:
                value = resp.json()
            except ValueError as e:
                self._emit_request_error(meta, "invalid_json_response")
                raise LLMError(
                    self._t("invalid_json_response", preview=resp.text[:200]),
                    code="invalid_json_response",
                ) from e
            if not isinstance(value, dict):
                # Valid JSON but not an object (array, scalar, null).
                self._emit_request_error(meta, "invalid_json_response")
                raise LLMError(
                    self._t("invalid_json_response", preview=resp.text[:200]),
                    code="invalid_json_response",
                )
            return value, meta
        finally:
            await resp.aclose()

    async def request_stream(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> "_AsyncEventStream":
        """Send JSON and return the SSE events. HTTP errors are raised by this call.

        The returned stream has ``request_id`` and ``retries`` as soon as this returns.
        """
        resp, meta = await self._aopen("POST", path, body, headers, timeout, stream=True)
        return _AsyncEventStream(self, resp, meta)

    # --- internals -------------------------------------------------------------

    def _headers(self, stream: bool, extra: Optional[Dict[str, str]]) -> Dict[str, str]:
        h = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "User-Agent": _user_agent(),
        }
        h.update(self._auth_headers())
        h.update(self._extra_headers)
        h.update(extra or {})
        return h

    def _t(self, msg_id: str, **params: Any) -> str:
        return t(msg_id, self.lang, **params)

    def _hint(self, status: int) -> Optional[str]:
        if status >= 500:
            return self._t("hint_server")
        if status in (400, 401, 403, 404, 429):
            return self._t("hint_%d" % status)
        return None

    async def _sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    def _retry_delay(self, attempt: int, retry_after: Optional[str]) -> float:
        delay = _retry_after_delay(retry_after, self.retry_after_max)
        if delay is None:
            delay = min(8.0, 0.5 * (2 ** attempt)) * (0.75 + random.random() / 2)
        return delay

    async def _emit_retry(
        self,
        method: str,
        path: str,
        stream: bool,
        attempt: int,
        reason: str,
        status_code: Optional[int],
        request_id: Optional[str],
        retry_after: Optional[str] = None,
    ) -> None:
        delay = self._retry_delay(attempt, retry_after)
        self._emit(
            "retry",
            retry_payload(
                self.provider,
                method,
                path,
                stream,
                attempt,
                self.max_retries,
                delay,
                reason,
                status_code,
                request_id,
            ),
        )
        await self._sleep(delay)

    def _call_meta(
        self,
        method: str,
        path: str,
        stream: bool,
        started: float,
        attempt: int,
        resp: Optional[httpx.Response],
    ) -> _CallMeta:
        return _CallMeta(
            method=method,
            path=path,
            stream=stream,
            started=started,
            request_id=None if resp is None else request_id_of(resp.headers),
            retries=attempt,
            status_code=None if resp is None else resp.status_code,
            latency=time.monotonic() - started,
        )

    def _emit_request_error(self, meta: _CallMeta, code: str) -> None:
        self._emit(
            "request_error",
            {
                "provider": self.provider,
                "method": meta.method,
                "path": meta.path,
                "stream": meta.stream,
                "attempt": meta.retries,
                "retries": meta.retries,
                "status_code": meta.status_code,
                "request_id": meta.request_id,
                "latency": meta.latency,
                "code": code,
            },
        )

    def _emit_connection_error(
        self,
        exc: BaseException,
        *,
        method: str,
        path: str,
        stream: bool,
        attempt: int,
        request_id: Optional[str],
        status_code: Optional[int],
        latency: float,
        code: str,
    ) -> None:
        self._emit(
            "connection_error",
            {
                "provider": self.provider,
                "method": method,
                "path": path,
                "stream": stream,
                "attempt": attempt,
                "retries": attempt,
                "status_code": status_code,
                "request_id": request_id,
                "latency": latency,
                "code": code,
                "reason": _transport_reason(exc),
            },
        )

    async def _aopen(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
        timeout: Optional[float],
        stream: bool,
    ) -> Tuple[httpx.Response, _CallMeta]:
        url = self.base_url + "/" + path.lstrip("/")
        content = (
            None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        )
        kwargs: Dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = httpx.Timeout(timeout, connect=self._connect_timeout)
        started = time.monotonic()
        attempt = 0
        while True:
            try:
                req = self._client.build_request(
                    method, url, content=content, headers=self._headers(stream, headers), **kwargs
                )
            except httpx.InvalidURL as e:
                raise LLMConfigError(
                    self._t("invalid_url", url=_mask_url(url)), code="invalid_url"
                ) from e
            resp = None
            try:
                # Always send with stream=True so Content-Length can be checked before
                # a non-stream body is read.
                resp = await self._client.send(req, stream=True)
                if resp.status_code >= 400 or not stream:
                    try:
                        if _http._declared_too_large(resp):
                            raise _http._too_large(_http._MAX_RESPONSE_BYTES, self.lang)
                        buffer = _http._ResponseBuffer(self.lang)
                        async for chunk in resp.aiter_bytes():
                            buffer.add(chunk)
                        resp._content = buffer.content()
                    except LLMError:
                        meta = self._call_meta(method, path, stream, started, attempt, resp)
                        await resp.aclose()
                        self._emit_request_error(meta, "response_too_large")
                        raise
            except httpx.RequestError as e:
                if resp is not None:
                    await resp.aclose()
                if attempt < self.max_retries and _is_retryable_transport_error(
                    e, self.retry_read_timeout
                ):
                    await self._emit_retry(
                        method, path, stream, attempt, _transport_reason(e), None, None
                    )
                    attempt += 1
                    continue
                latency = time.monotonic() - started
                if isinstance(e, httpx.TimeoutException):
                    err: APIConnectionError = APITimeoutError(
                        self._t("timeout"),
                        code="timeout",
                        provider=self.provider,
                        request_id=None,
                        retries=attempt,
                        latency=latency,
                    )
                else:
                    err = APIConnectionError(
                        self._t("connection_error", detail=e),
                        code="connection_error",
                        provider=self.provider,
                        request_id=None,
                        retries=attempt,
                        latency=latency,
                    )
                self._emit_connection_error(
                    e,
                    method=method,
                    path=path,
                    stream=stream,
                    attempt=attempt,
                    request_id=None,
                    status_code=None,
                    latency=latency,
                    code=err.code or "connection_error",
                )
                raise err from e
            except BaseException:
                # e.g. asyncio.CancelledError: release the response, never convert it.
                if resp is not None:
                    await resp.aclose()
                raise

            if resp.status_code < 400:
                meta = self._call_meta(method, path, stream, started, attempt, resp)
                self._emit(
                    "response",
                    {
                        "provider": self.provider,
                        "method": method,
                        "path": path,
                        "stream": stream,
                        "attempt": attempt,
                        "retries": attempt,
                        "status_code": resp.status_code,
                        "request_id": meta.request_id,
                        "latency": meta.latency,
                        "cached": False,
                    },
                )
                return resp, meta
            if (
                resp.status_code in _RETRY_STATUS or resp.status_code >= 500
            ) and attempt < self.max_retries:
                retry_after = resp.headers.get("retry-after")
                status_code = resp.status_code
                request_id = request_id_of(resp.headers)
                await resp.aclose()
                await self._emit_retry(
                    method, path, stream, attempt, "status", status_code, request_id, retry_after
                )
                attempt += 1
                continue
            try:
                err_status = self._make_error(resp)
                err_status.retries = attempt
                err_status.latency = time.monotonic() - started
                self._emit(
                    "http_error",
                    {
                        "provider": self.provider,
                        "method": method,
                        "path": path,
                        "stream": stream,
                        "attempt": attempt,
                        "retries": attempt,
                        "status_code": resp.status_code,
                        "request_id": err_status.request_id,
                        "latency": err_status.latency,
                    },
                )
                raise err_status
            finally:
                await resp.aclose()

    def _make_error(self, resp: httpx.Response) -> APIStatusError:
        try:
            body: Any = resp.json()
        except ValueError:
            body = resp.text
        msg = error_message(body)
        message = self._t("api_error", provider=self.provider, status=resp.status_code)
        if msg:
            message += ": " + msg  # the API's own message is not translated
        hint = self._hint(resp.status_code)
        if hint:
            message += "\n" + hint
        return status_error_class(resp.status_code)(
            message,
            status_code=resp.status_code,
            body=body,
            provider=self.provider,
            request_id=request_id_of(resp.headers),
            headers=dict(resp.headers),
        )


# The loop keeps only weak references to tasks; hold finalizer closes until they finish.
_PENDING_CLOSES: set = set()


def _schedule_close(resp: Any) -> None:
    """Run `resp.aclose()` as a task on the current loop (called via `call_soon_threadsafe`)."""
    # A task whose loop was closed before it finished never runs its done
    # callback; prune such entries so they are not retained until process exit.
    for old in list(_PENDING_CLOSES):
        try:
            if old.done() or old.get_loop().is_closed():
                _PENDING_CLOSES.discard(old)
        except Exception:
            _PENDING_CLOSES.discard(old)
    task = asyncio.ensure_future(_close_quietly(resp))
    _PENDING_CLOSES.add(task)
    task.add_done_callback(_PENDING_CLOSES.discard)


class _AsyncEventStream:
    """SSE events of one streaming response. Closes the response when done or closed.

    Callers should `aclose()` a stream they stop early. As a last resort, a stream
    garbage-collected while still open schedules `resp.aclose()` on the event loop it
    was created on, or emits a `ResourceWarning` if that loop is gone.

    `request_id` and `retries` are available as soon as the stream is returned.
    `aclose()` after a terminal SSE event emits `stream_end`. The garbage-collection
    path only closes the response; it does not emit (it cannot await listeners).
    """

    def __init__(self, client: _AsyncBaseClient, resp: httpx.Response, meta: _CallMeta) -> None:
        self._client = client
        self._resp = resp
        self._lines = resp.aiter_lines()
        self._events = aiter_sse(self._lines, client.lang)
        self._meta = meta
        self.request_id = meta.request_id
        self.retries = meta.retries
        self.started = meta.started
        self.method = meta.method
        self.path = meta.path
        self.status_code = meta.status_code
        self._closed = False
        self._terminal = False
        self._errored = False
        self._end_emitted = False
        try:
            self._loop: Optional[asyncio.AbstractEventLoop] = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def __aiter__(self) -> "_AsyncEventStream":
        return self

    async def __anext__(self) -> SSEEvent:
        if self._closed:
            raise StopAsyncIteration
        try:
            ev = await self._events.__anext__()
        except StopAsyncIteration:
            await self.aclose()
            raise
        except httpx.RequestError as e:
            await self._fail_read(e)
        except LLMError as e:
            self._errored = True
            await self.aclose()
            note_request_error(self._client, self, e.code)
            raise
        except BaseException:
            # Includes asyncio.CancelledError: close the response, then propagate.
            self._errored = True
            await self.aclose()
            raise
        if _is_terminal_event(ev):
            self._terminal = True
        return ev

    async def _fail_read(self, exc: httpx.RequestError) -> None:
        self._errored = True
        latency = time.monotonic() - self.started
        await self.aclose()
        if isinstance(exc, httpx.TimeoutException):
            err: APIConnectionError = APITimeoutError(
                self._client._t("stream_timeout"),
                code="timeout",
                provider=self._client.provider,
                request_id=self.request_id,
                retries=self.retries,
                latency=latency,
            )
        else:
            err = APIConnectionError(
                self._client._t("stream_connection_error", detail=exc),
                code="connection_error",
                provider=self._client.provider,
                request_id=self.request_id,
                retries=self.retries,
                latency=latency,
            )
        self._client._emit_connection_error(
            exc,
            method=self.method,
            path=self.path,
            stream=True,
            attempt=self.retries,
            request_id=self.request_id,
            status_code=self.status_code,
            latency=latency,
            code=err.code or "connection_error",
        )
        raise err from exc

    async def aclose(self) -> None:
        """Close the stream and the response. Safe to call more than once.

        After a terminal SSE event, the first close emits `stream_end`.
        """
        if self._closed:
            return
        self._closed = True
        # Attempt every close even if an earlier one is cancelled, so the
        # response is not left open.
        try:
            await _close_quietly(self._events)
        finally:
            try:
                await _close_quietly(self._lines)
            finally:
                await _close_quietly(self._resp)
        if self._terminal and not self._errored and not self._end_emitted:
            self._end_emitted = True
            self._client._emit(
                "stream_end",
                {
                    "provider": self._client.provider,
                    "request_id": self.request_id,
                    "retries": self.retries,
                    "latency": time.monotonic() - self.started,
                    "stream": True,
                    "complete": True,
                },
            )

    def __del__(self) -> None:
        # Safety net for a stream dropped without aclose(). Never raise from here.
        if getattr(self, "_closed", True):
            return
        self._closed = True
        try:
            loop = getattr(self, "_loop", None)
            if loop is not None and not loop.is_closed():
                loop.call_soon_threadsafe(_schedule_close, self._resp)
                return
        except Exception:
            pass
        try:
            client = getattr(self, "_client", None)
            lang = getattr(client, "lang", None)
            warnings.warn(t("unclosed_stream", lang), ResourceWarning, source=self)
        except Exception:
            pass


class _ReplayEvents:
    """Events replayed from the cache. Exposes the stored call metadata."""

    def __init__(self, events: List[SSEEvent], request_id: Optional[str], retries: int) -> None:
        self._it = iter(events)
        self.request_id = request_id
        self.retries = retries
        self.started = None
        self.method = None
        self.path = None
        self.status_code = None

    def __aiter__(self) -> "_ReplayEvents":
        return self

    async def __anext__(self) -> SSEEvent:
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration from None

    async def aclose(self) -> None:
        pass


class _AsyncRecordedEvents:
    """Pass events through and store the stream in the cache once it is complete.

    Complete means a terminal event (`[DONE]` / `message_stop`) was received:
    parsers stop there and close the stream early. EOF without a terminal event,
    errors, cancellation and early `aclose()` are not stored.
    """

    def __init__(self, client: _AsyncBaseClient, events: Any, body: Dict[str, Any]) -> None:
        self._client = client
        self._events = events
        self._body = body
        self._recorded: List[Dict[str, Any]] = []
        self._stored = False
        self.request_id = getattr(events, "request_id", None)
        self.retries = getattr(events, "retries", 0) or 0
        self.started = getattr(events, "started", None)
        self.method = getattr(events, "method", None)
        self.path = getattr(events, "path", None)
        self.status_code = getattr(events, "status_code", None)
        self._size = 0
        self._recording = True

    def __aiter__(self) -> "_AsyncRecordedEvents":
        return self

    async def _store(self) -> None:
        if self._stored:
            return
        self._stored = True
        stored = ChatResult("", None, None, None, {"events": self._recorded})
        stored.request_id = self.request_id
        stored.retries = self.retries
        stored.latency = None if self.started is None else time.monotonic() - self.started
        await self._client._acache_store(self._body, stored)

    async def __anext__(self) -> SSEEvent:
        try:
            ev = await self._events.__anext__()
        except StopAsyncIteration:
            raise
        except BaseException:
            await _close_quietly(self._events)
            raise
        if self._recording:
            item = {"event": ev.event, "data": ev.data}
            self._size += _http._stream_item_size(item)
            if self._size > _http._STREAM_BUFFER_LIMIT:
                self._recorded.clear()
                self._recording = False
            else:
                self._recorded.append(item)
        if self._recording and _is_terminal_event(ev):
            await self._store()
        return ev

    async def aclose(self) -> None:
        await _close_quietly(self._events)


class _AsyncChunks:
    """Turn events into `ChatChunk`s with `parse(ev) -> (chunk or None, terminal)`."""

    def __init__(
        self,
        events: Any,
        parse: Callable[[SSEEvent], Tuple[Optional[ChatChunk], bool]],
        client: _AsyncBaseClient,
    ) -> None:
        self._events = events
        self._parse = parse
        self._client = client
        self._done = False
        self.request_id = getattr(events, "request_id", None)
        self.retries = getattr(events, "retries", 0) or 0

    def __aiter__(self) -> "_AsyncChunks":
        return self

    async def __anext__(self) -> ChatChunk:
        while True:
            if self._done:
                raise StopAsyncIteration
            try:
                ev = await self._events.__anext__()
            except StopAsyncIteration:
                self._done = True
                error = APIStreamError(
                    self._client._t("stream_incomplete", provider=self._client.provider),
                    code="stream_incomplete",
                )
                note_stream_error(self._client, error, self._events)
                await _close_quietly(self._events)
                raise error
            except BaseException:
                # Transport errors and size limits are already reported by the event stream.
                self._done = True
                await _close_quietly(self._events)
                raise
            try:
                chunk, terminal = self._parse(ev)
            except APIStreamError as e:
                self._done = True
                note_stream_error(self._client, e, self._events)
                await _close_quietly(self._events)
                raise
            except LLMError as e:
                self._done = True
                note_request_error(self._client, self._events, e.code)
                await _close_quietly(self._events)
                raise
            except BaseException:
                self._done = True
                await _close_quietly(self._events)
                raise
            if terminal:
                self._done = True
                await _close_quietly(self._events)
                raise StopAsyncIteration
            if chunk is not None:
                chunk.request_id = self.request_id
                return chunk

    async def aclose(self) -> None:
        self._done = True
        await _close_quietly(self._events)


class _AsyncLoggedChunks:
    """Pass chunks through and log the whole stream once it has been read to the end.

    Errors, cancellation and early `aclose()` are not logged.
    """

    def __init__(
        self, client: _AsyncBaseClient, chunks: Any, body: Dict[str, Any], cached: bool
    ) -> None:
        self._client = client
        self._chunks = chunks
        self._body = body
        self._cached = cached
        self._texts: List[str] = []
        self._raws: List[Any] = []
        self._done = False
        self.request_id = getattr(chunks, "request_id", None)
        self.retries = getattr(chunks, "retries", 0) or 0
        self._size = 0
        self._recording = True

    def __aiter__(self) -> "_AsyncLoggedChunks":
        return self

    async def __anext__(self) -> ChatChunk:
        if self._done:
            raise StopAsyncIteration
        try:
            chunk = await self._chunks.__anext__()
        except StopAsyncIteration:
            self._done = True
            response = (
                {"text": "".join(self._texts), "chunks": self._raws}
                if self._recording else
                {"text": None, "chunks": None, "truncated": True}
            )
            await self._client._alog_call(
                self._body, response, stream=True, cached=self._cached,
            )
            raise
        except BaseException:
            self._done = True
            await _close_quietly(self._chunks)
            raise
        if self._client.log is not None and self._recording:
            self._size += _http._stream_item_size([chunk.text or "", chunk.raw])
            if self._size > _http._STREAM_BUFFER_LIMIT:
                self._texts.clear()
                self._raws.clear()
                self._recording = False
            else:
                self._texts.append(chunk.text or "")
                self._raws.append(chunk.raw)
        return chunk

    async def aclose(self) -> None:
        self._done = True
        await _close_quietly(self._chunks)
