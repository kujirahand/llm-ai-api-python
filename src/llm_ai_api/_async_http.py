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
import warnings
from typing import Any, AsyncIterable, AsyncIterator, Callable, Dict, List, Optional, Tuple

import httpx

from ._http import (
    _MAX_RETRY_AFTER,
    _RETRY_STATUS,
    _mask_url,
    _is_terminal_event,
    _SSEDecoder,
    _user_agent,
    error_message,
)
from .cache import CACHE_NOT_SET, SQLiteCache, cache_key, resolve_cache
from .errors import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    LLMConfigError,
    LLMError,
    status_error_class,
)
from .lang import t
from .log import LOG_NOT_SET, resolve_log
from .types import ChatChunk, ChatResult, SSEEvent


async def aiter_sse(lines: AsyncIterable[str]) -> AsyncIterator[SSEEvent]:
    """Async version of `iter_sse()`: yield SSE events from an async iterable of lines."""
    decoder = _SSEDecoder()
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
        lang: Optional[str] = None,
        cache: Any = CACHE_NOT_SET,
        log: Any = LOG_NOT_SET,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        """Same arguments as `BaseClient`; `transport` is for tests (`httpx.MockTransport`)."""
        self.lang = lang
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
        self._extra_headers = dict(headers or {})
        self._client = httpx.AsyncClient(
            transport=transport, timeout=httpx.Timeout(timeout, connect=10.0)
        )

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

    async def _astream_events(self, path: str, body: Dict[str, Any]) -> Tuple[Any, bool]:
        """`request_stream()` with the response cache: replay a hit, record a miss.

        Returns the events (an async iterator with `aclose()`) and whether they were
        replayed from the cache.
        """
        cached = await self._acache_lookup(body)
        if cached is not None and isinstance(cached.raw.get("events"), list):
            replay = [SSEEvent(e.get("event"), e.get("data", "")) for e in cached.raw["events"]]
            return _ReplayEvents(replay), True
        events = await self.request_stream(path, body)
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
        resp = await self._aopen(method, path, body, headers, timeout, stream=False)
        try:
            return resp.json()
        except ValueError as e:
            raise LLMError(
                self._t("invalid_json_response", preview=resp.text[:200]),
                code="invalid_json_response",
            ) from e
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
        """Send JSON and return the SSE events. HTTP errors are raised by this call."""
        resp = await self._aopen("POST", path, body, headers, timeout, stream=True)
        return _AsyncEventStream(self, resp)

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

    async def _backoff(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = None
        if retry_after:
            try:
                delay = min(max(float(retry_after), 0.0), _MAX_RETRY_AFTER)
            except ValueError:
                delay = None
        if delay is None:
            delay = min(8.0, 0.5 * (2 ** attempt)) * (0.75 + random.random() / 2)
        await self._sleep(delay)

    async def _aopen(
        self,
        method: str,
        path: str,
        body: Optional[Dict[str, Any]],
        headers: Optional[Dict[str, str]],
        timeout: Optional[float],
        stream: bool,
    ) -> httpx.Response:
        url = self.base_url + "/" + path.lstrip("/")
        content = (
            None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        )
        kwargs: Dict[str, Any] = {}
        if timeout is not None:
            kwargs["timeout"] = httpx.Timeout(timeout, connect=10.0)
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
                resp = await self._client.send(req, stream=stream)
                if resp.status_code >= 400:
                    # With stream=True the error body has not been read yet, and reading
                    # it can fail too, so it has to be inside this try (conversion + retry).
                    await resp.aread()
            except httpx.TimeoutException as e:
                if resp is not None:
                    await resp.aclose()
                if attempt < self.max_retries:
                    await self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise APITimeoutError(self._t("timeout"), code="timeout") from e
            except httpx.RequestError as e:
                if resp is not None:
                    await resp.aclose()
                if attempt < self.max_retries:
                    await self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise APIConnectionError(
                    self._t("connection_error", detail=e), code="connection_error"
                ) from e
            except BaseException:
                # e.g. asyncio.CancelledError: release the response, never convert it.
                if resp is not None:
                    await resp.aclose()
                raise

            if resp.status_code < 400:
                return resp
            if (
                resp.status_code in _RETRY_STATUS or resp.status_code >= 500
            ) and attempt < self.max_retries:
                retry_after = resp.headers.get("retry-after")
                await resp.aclose()
                await self._backoff(attempt, retry_after)
                attempt += 1
                continue
            try:
                raise self._make_error(resp)
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
        request_id = resp.headers.get("x-request-id") or resp.headers.get("request-id")
        return status_error_class(resp.status_code)(
            message,
            status_code=resp.status_code,
            body=body,
            provider=self.provider,
            request_id=request_id,
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
    """

    def __init__(self, client: _AsyncBaseClient, resp: httpx.Response) -> None:
        self._client = client
        self._resp = resp
        self._lines = resp.aiter_lines()
        self._events = aiter_sse(self._lines)
        self._closed = False
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
            return await self._events.__anext__()
        except StopAsyncIteration:
            await self.aclose()
            raise
        except httpx.TimeoutException as e:
            await self.aclose()
            raise APITimeoutError(self._client._t("stream_timeout"), code="timeout") from e
        except httpx.RequestError as e:
            await self.aclose()
            raise APIConnectionError(
                self._client._t("stream_connection_error", detail=e), code="connection_error"
            ) from e
        except BaseException:
            # Includes asyncio.CancelledError: close the response, then propagate.
            await self.aclose()
            raise

    async def aclose(self) -> None:
        """Close the stream and the response. Safe to call more than once."""
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
    """Events replayed from the cache."""

    def __init__(self, events: List[SSEEvent]) -> None:
        self._it = iter(events)

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

    Complete means read to the end or up to the terminal event (`[DONE]` /
    `message_stop`): parsers stop there and close the stream early. Errors,
    cancellation and early `aclose()` are not stored.
    """

    def __init__(self, client: _AsyncBaseClient, events: Any, body: Dict[str, Any]) -> None:
        self._client = client
        self._events = events
        self._body = body
        self._recorded: List[Dict[str, Any]] = []
        self._stored = False

    def __aiter__(self) -> "_AsyncRecordedEvents":
        return self

    async def _store(self) -> None:
        if self._stored:
            return
        self._stored = True
        await self._client._acache_store(
            self._body, ChatResult("", None, None, None, {"events": self._recorded})
        )

    async def __anext__(self) -> SSEEvent:
        try:
            ev = await self._events.__anext__()
        except StopAsyncIteration:
            await self._store()
            raise
        except BaseException:
            await _close_quietly(self._events)
            raise
        self._recorded.append({"event": ev.event, "data": ev.data})
        if _is_terminal_event(ev):
            await self._store()
        return ev

    async def aclose(self) -> None:
        await _close_quietly(self._events)


class _AsyncChunks:
    """Turn events into `ChatChunk`s with `parse(ev) -> (chunk or None, terminal)`."""

    def __init__(
        self, events: Any, parse: Callable[[SSEEvent], Tuple[Optional[ChatChunk], bool]]
    ) -> None:
        self._events = events
        self._parse = parse
        self._done = False

    def __aiter__(self) -> "_AsyncChunks":
        return self

    async def __anext__(self) -> ChatChunk:
        while True:
            if self._done:
                raise StopAsyncIteration
            try:
                ev = await self._events.__anext__()
                chunk, terminal = self._parse(ev)
            except StopAsyncIteration:
                self._done = True
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

    def __aiter__(self) -> "_AsyncLoggedChunks":
        return self

    async def __anext__(self) -> ChatChunk:
        if self._done:
            raise StopAsyncIteration
        try:
            chunk = await self._chunks.__anext__()
        except StopAsyncIteration:
            self._done = True
            await self._client._alog_call(
                self._body,
                {"text": "".join(self._texts), "chunks": self._raws},
                stream=True,
                cached=self._cached,
            )
            raise
        except BaseException:
            self._done = True
            await _close_quietly(self._chunks)
            raise
        if self._client.log is not None:
            self._texts.append(chunk.text or "")
            self._raws.append(chunk.raw)
        return chunk

    async def aclose(self) -> None:
        self._done = True
        await _close_quietly(self._chunks)
