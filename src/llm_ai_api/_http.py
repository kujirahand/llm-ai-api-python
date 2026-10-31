"""httpx による送受信、SSE パーサー、リトライ。

httpx の例外は、ここで自前の例外に変換して外に出さない。
"""

from __future__ import annotations

import json
import math
import os
import random
import time
import urllib.parse
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional, Tuple

import httpx

from .cache import CACHE_NOT_SET, SQLiteCache, cache_key, resolve_cache
from ._connection import build_httpx_kwargs, resolve_connection
from ._events import (
    EventDispatcher,
    _CallMeta,
    cache_hit_payload,
    note_request_error,
    note_stream_error,
    request_id_of,
    retry_payload,
)
from .log import LOG_NOT_SET, resolve_log
from .errors import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    LLMConfigError,
    LLMError,
    status_error_class,
)
from .lang import t
from .types import ChatChunk, ChatResult, SSEEvent

_RETRY_STATUS = {408, 409, 429}
_DEFAULT_RETRY_AFTER_MAX = 60.0
# Independent budgets for cache events and log chunks.
_STREAM_BUFFER_LIMIT = 16 * 1024 * 1024


def _stream_item_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    except UnicodeEncodeError:
        return len(json.dumps(value, ensure_ascii=True).encode("utf-8"))


_MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # largest non-stream response body that is accepted
_MAX_SSE_LINE_BYTES = 16 * 1024 * 1024  # longest single SSE line that is accepted

# Transport errors raised before the request reached the server: always safe to retry.
_CONNECT_STAGE_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)


def _transport_reason(exc: BaseException) -> str:
    """Short reason tag for a transport failure. Not a translated message."""
    if isinstance(exc, httpx.ReadTimeout):
        return "read_timeout"
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout)):
        return "connect"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return "transport"


def _is_retryable_transport_error(exc: Exception, retry_read_timeout: bool) -> bool:
    """Whether a transport error may be retried without risking a duplicate request.

    Generation requests are not idempotent, so by default only connection-stage
    failures (the request provably never reached the server) are retried. A read
    timeout is retried only when `retry_read_timeout` is on; other errors after the
    request was sent (write errors, read errors, protocol errors, ...) never are.
    """
    if isinstance(exc, _CONNECT_STAGE_ERRORS):
        return True
    return retry_read_timeout and isinstance(exc, httpx.ReadTimeout)


def _check_retry_after_max(value: Any, lang: Optional[str]) -> float:
    """Validate `retry_after_max` at configuration time: a finite number >= 0.

    A negative or NaN cap would otherwise reach `time.sleep()` / `asyncio.sleep()` on
    the first `retry-after` response and fail there instead of at setup.
    """
    try:
        ok = math.isfinite(value) and value >= 0
    except TypeError:
        ok = False
    if not ok:
        raise LLMConfigError(
            t("invalid_option", lang, name="retry_after_max", value=value),
            code="invalid_option",
        )
    return value


def _retry_after_delay(retry_after: Optional[str], cap: float) -> Optional[float]:
    """Parse a `retry-after` header (seconds) and cap it; None if absent or invalid."""
    if not retry_after:
        return None
    try:
        return min(max(float(retry_after), 0.0), cap)
    except ValueError:
        return None


def _declared_too_large(resp: httpx.Response) -> bool:
    """True if the Content-Length header parses to an int over the response cap."""
    try:
        return int(resp.headers.get("content-length", "")) > _MAX_RESPONSE_BYTES
    except ValueError:
        return False


def _too_large(limit: int, lang: Optional[str]) -> LLMError:
    return LLMError(t("response_too_large", lang, limit=limit), code="response_too_large")


class _ResponseBuffer:
    """Collect decoded response bytes up to the shared response limit."""

    def __init__(self, lang: Optional[str]) -> None:
        self.lang = lang
        self.buffer = bytearray()

    def add(self, chunk: bytes) -> None:
        if len(self.buffer) + len(chunk) > _MAX_RESPONSE_BYTES:
            raise _too_large(_MAX_RESPONSE_BYTES, self.lang)
        self.buffer.extend(chunk)

    def content(self) -> bytes:
        return bytes(self.buffer)


class _SSEDecoder:
    """Line-by-line SSE state machine, shared by the sync and async readers.

    Lines starting with `:` (comments) are ignored; an empty line completes an event.
    """

    def __init__(self, lang: Optional[str] = None) -> None:
        self._lang = lang
        self._event: Optional[str] = None
        self._data: list = []

    def feed(self, line: str) -> Optional[SSEEvent]:
        """Consume one line; return the event it completes, if any."""
        if len(line.encode("utf-8")) > _MAX_SSE_LINE_BYTES:
            raise _too_large(_MAX_SSE_LINE_BYTES, self._lang)
        if line == "":
            return self.flush()
        if line.startswith(":"):
            return None
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "event":
            self._event = value
        elif name == "data":
            self._data.append(value)
        return None

    def flush(self) -> Optional[SSEEvent]:
        """Return the pending event (if any) and reset the state."""
        ev = None
        if self._data or self._event is not None:
            ev = SSEEvent(self._event, "\n".join(self._data))
        self._event, self._data = None, []
        return ev


def iter_sse(lines: Iterable[str], lang: Optional[str] = None) -> Iterator[SSEEvent]:
    """行のイテレータから SSE イベントを取り出す。

    `:` で始まる行（コメント）は無視し、空行でイベントを確定する。
    """
    decoder = _SSEDecoder(lang)
    for line in lines:
        ev = decoder.feed(line)
        if ev is not None:
            yield ev
    ev = decoder.flush()
    if ev is not None:
        yield ev


def _is_terminal_event(ev: SSEEvent) -> bool:
    """Whether `ev` successfully ends a stream, as the provider parsers see it.

    `[DONE]` (OpenAI style) is unambiguous. For Anthropic the parser decides by
    the payload's `type`, falling back to the event name: a stream can end with
    `data: {"type": "message_stop"}` and no `event:` line at all, while a
    `message_stop` event whose payload is invalid JSON or an error is a failure,
    not a successful end. Only a successful end may mark a recorded stream as
    complete (a failed stream is never stored in the cache).
    """
    if ev.data.strip() == "[DONE]":  # the OpenAI-style parser strips too
        return True
    if not ev.data:
        # No payload: the parser falls back to the event name.
        return ev.event == "message_stop"
    try:
        raw = ev.json()
    except LLMError:
        return False
    if not isinstance(raw, dict):
        return False
    return (raw.get("type") or ev.event) == "message_stop"


def _mask_url(url: str) -> str:
    """Return `url` safe for display: userinfo becomes `***`, query and fragment are dropped.

    The API key is never part of the URL; this protects credentials a user may have
    embedded in a custom base URL. If the URL cannot be parsed, returns `"***"`.
    """
    try:
        parts = urllib.parse.urlsplit(url)
        netloc = parts.netloc
        if "@" in netloc:
            netloc = "***@" + netloc.rpartition("@")[2]
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))
    except ValueError:
        return "***"


def _user_agent() -> str:
    from . import __version__

    return "llm-ai-api-python/" + __version__


def error_message(body: Any) -> Optional[str]:
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            msg = err.get("message")
            if isinstance(msg, str):
                return msg
        if isinstance(err, str):
            return err
        msg = body.get("message")
        if isinstance(msg, str):
            return msg
    elif isinstance(body, str) and body:
        return body
    return None


class _TaggedIter:
    """Iterator wrapper that exposes call metadata and forwards ``close()``.

    Generators cannot carry attributes, and a ``for`` loop does not call
    ``close()`` on a class iterator, so this wrapper is what ``stream_chat``
    returns and what recording iterators are wrapped in.
    """

    def __init__(
        self,
        inner: Iterator[Any],
        *,
        request_id: Optional[str],
        retries: int,
        started: Optional[float],
        method: Optional[str] = None,
        path: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self._inner = inner
        self.request_id = request_id
        self.retries = retries
        self.started = started
        self.method = method
        self.path = path
        self.status_code = status_code
        self._closed = False

    def __iter__(self) -> "_TaggedIter":
        return self

    def __next__(self) -> Any:
        return next(self._inner)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        close = getattr(self._inner, "close", None)
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


class _ReplayEvents:
    """SSE events replayed from the cache. Exposes the stored call metadata."""

    def __init__(self, events: list, request_id: Optional[str], retries: int) -> None:
        self._it = iter(events)
        self.request_id = request_id
        self.retries = retries
        self.started = None
        self.method = None
        self.path = None
        self.status_code = None

    def __iter__(self) -> "_ReplayEvents":
        return self

    def __next__(self) -> SSEEvent:
        return next(self._it)

    def close(self) -> None:
        pass


class BaseClient:
    """Shared raw HTTP layer for the provider clients."""

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
        transport: Optional[httpx.BaseTransport] = None,
        connection: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """`lang` はエラーメッセージの言語（`"ja"` / `"en"`）。None なら環境から判定する。

        `max_retries` はリトライ回数。通信エラーは、既定では接続段階の失敗（リクエストが
        サーバーに届いていないもの）だけをリトライする。`retry_read_timeout=True` にすると
        読み取りタイムアウトもリトライする（サーバーが生成を始めていれば二重課金になりうる）。
        `retry_after_max` は `retry-after` ヘッダーに従って待つ秒数の上限。

        `cache` は chat() の応答キャッシュ（True / パス / SQLiteCache / False / None。
        未指定なら `set_cache()` のグローバル設定に従う）。

        `log` は chat() の入出力ログ（True / パス / ログオブジェクト / False / None。
        未指定なら `set_log()` のグローバル設定に従う）。

        `transport` はテスト用（`httpx.MockTransport` を渡す）。

        `connection` は接続設定の dict（`set_connection()` の全体設定をキー単位で上書きする。
        `transport` 指定時は検証のみで httpx には適用しない）。
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
            self._client = httpx.Client(
                transport=transport,
                timeout=httpx.Timeout(timeout, connect=self._connect_timeout),
            )
        else:
            self._client = httpx.Client(
                timeout=httpx.Timeout(timeout, connect=self._connect_timeout),
                **build_httpx_kwargs(self.connection, lang=lang),
            )

    def add_event_listener(self, event: Optional[str], listener: Any) -> None:
        """Register ``listener`` for ``event``, or for every event when ``event`` is None.

        ``listener(event, payload)`` is called synchronously with a plain dict.
        ``Exception`` raised by a listener is discarded and does not affect the
        request or later listeners. ``BaseException`` is not caught. The same
        function can be registered more than once; each registration is called.
        Listeners run in registration order.

        Unknown event names raise ``LLMConfigError`` (``code="invalid_event"``).
        See the package docs for event names and payload keys. Payloads never
        include the API key, authorization headers, or request/response bodies.
        """
        self._events.add(event, listener, self.lang)

    def remove_event_listener(self, event: Optional[str], listener: Any) -> None:
        """Remove one registration of ``listener`` for ``event``.

        The ``event`` argument must match the one passed to ``add_event_listener``
        (``None`` only removes an all-events registration). An unknown event name
        raises ``LLMConfigError`` (``code="invalid_event"``). Removing a listener
        that was not registered does nothing.
        """
        self._events.remove(event, listener, self.lang)

    def _emit(self, event: str, payload: Dict[str, Any]) -> None:
        self._events.emit(event, payload)

    def __repr__(self) -> str:
        return "%s(base_url=%r)" % (type(self).__name__, _mask_url(self.base_url))

    def close(self) -> None:
        """内部の HTTP クライアントを閉じる。"""
        self._client.close()

    def _cache_context(self) -> Dict[str, Any]:
        """Return the client settings that can change a response for the same body.

        Part of the cache key, so cached entries are not shared across different
        endpoints, API keys or header configurations. Providers add their own settings.
        The API key is mixed into the key hash separately (see `cache_key`) and is never
        stored.
        """
        return {
            "base_url": self.base_url,
            "headers": dict(self._extra_headers),
        }

    def _cache_lookup(self, body: Dict[str, Any]) -> Optional[ChatResult]:
        """Return the cached result for this request body, or None (miss or cache failure)."""
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
        """Store a result in the cache, ignoring cache failures."""
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

    def _lookup_chat_cache(self, body: Dict[str, Any]) -> Optional[ChatResult]:
        """Return a cached chat result and emit ``cache_hit``, or None on a miss."""
        cached = self._cache_lookup(body)
        if cached is None:
            return None
        self._emit("cache_hit", cache_hit_payload(self.provider, False, body.get("model"), cached))
        return cached

    def _log_call(
        self, body: Dict[str, Any], response: Any, *, stream: bool = False, cached: bool = False
    ) -> None:
        """Write one record to the log, ignoring log failures."""
        if self.log is None:
            return
        try:
            self.log.write(
                self.provider, body.get("model"), body, response, stream=stream, cached=cached
            )
        except Exception:
            # A log failure must not lose an API response the caller already paid for.
            pass

    def _log_chunks(
        self, body: Dict[str, Any], chunks: Iterator[ChatChunk], cached: bool
    ) -> Iterator[ChatChunk]:
        """Pass chunks through and log the whole stream once it has been read to the end."""
        if self.log is None:
            yield from chunks
            return
        texts: list = []
        raws: list = []
        size = 0
        recording = True
        for chunk in chunks:
            if recording:
                size += _stream_item_size([chunk.text or "", chunk.raw])
                if size > _STREAM_BUFFER_LIMIT:
                    texts.clear()
                    raws.clear()
                    recording = False
                else:
                    texts.append(chunk.text or "")
                    raws.append(chunk.raw)
            yield chunk
        response = ({"text": "".join(texts), "chunks": raws} if recording else
                    {"text": None, "chunks": None, "truncated": True})
        self._log_call(body, response, stream=True, cached=cached)

    def _stream_events(
        self, path: str, body: Dict[str, Any], timeout: Optional[float] = None
    ) -> Tuple[Iterator[SSEEvent], bool]:
        """`request_stream()` with the response cache: replay a hit, record a miss.

        A stream is stored only when it was read to the end (or up to its terminal event),
        as a `ChatResult` whose `raw["events"]` holds the SSE events.
        Returns the events and whether they were replayed from the cache.
        The iterator exposes `request_id` and `retries` (and `started` for a live stream).
        """
        cached = self._cache_lookup(body)
        if cached is not None and isinstance(cached.raw.get("events"), list):
            replay = [SSEEvent(e.get("event"), e.get("data", "")) for e in cached.raw["events"]]
            self._emit(
                "cache_hit", cache_hit_payload(self.provider, True, body.get("model"), cached)
            )
            return _ReplayEvents(replay, cached.request_id, cached.retries), True
        events = self.request_stream(path, body, timeout=timeout)
        if self.cache is None:
            return events, False
        recorded = self._record_events(events, body)
        return (
            _TaggedIter(
                recorded,
                request_id=events.request_id,
                retries=events.retries,
                started=events.started,
                method=events.method,
                path=events.path,
                status_code=events.status_code,
            ),
            False,
        )

    def _record_events(self, events: "_EventStream", body: Dict[str, Any]) -> Iterator[SSEEvent]:
        # Parsers stop at the terminal event and close this generator early, so only
        # a terminal event marks the stream complete. EOF without one (a cut-off
        # stream), errors and early stops are not stored.
        recorded: list = []
        complete = False
        size = 0
        recording = True
        try:
            for ev in events:
                if recording:
                    item = {"event": ev.event, "data": ev.data}
                    size += _stream_item_size(item)
                    if size > _STREAM_BUFFER_LIMIT:
                        recorded.clear()
                        recording = False
                    else:
                        recorded.append(item)
                if _is_terminal_event(ev):
                    complete = True
                yield ev
        finally:
            # Close even when the caller stops early, so the response is released now.
            started = events.started
            latency = time.monotonic() - started
            close = getattr(events, "close", None)
            if close is not None:
                close()
            if complete and recording:
                stored = ChatResult("", None, None, None, {"events": recorded})
                stored.request_id = events.request_id
                stored.retries = events.retries
                stored.latency = latency
                self._cache_store(body, stored)

    def __enter__(self) -> "BaseClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # --- サブクラスが実装する -------------------------------------------------

    def _auth_headers(self) -> Dict[str, str]:
        raise NotImplementedError

    # --- 生レイヤー -----------------------------------------------------------

    def request(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Send JSON and return the response JSON (dict) unchanged.

        Response headers are not part of the return value. Listen for the
        ``response`` event, or use ``chat()``, to read ``request_id``.
        """
        value, _meta = self._read_json(path, body, method=method, headers=headers, timeout=timeout)
        return value

    def _read_json(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        method: str = "POST",
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> Tuple[Dict[str, Any], _CallMeta]:
        """Like ``request()``, but also return call metadata for ``chat()``."""
        resp, meta = self._open(method, path, body, headers, timeout, stream=False)
        try:
            if len(resp.content) > _MAX_RESPONSE_BYTES:
                self._emit_request_error(meta, "response_too_large")
                raise _too_large(_MAX_RESPONSE_BYTES, self.lang)
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
            resp.close()

    def request_stream(
        self,
        path: str,
        body: Optional[Dict[str, Any]] = None,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> "_EventStream":
        """Send JSON and yield SSE events. HTTP errors are raised by this call.

        The returned stream has ``request_id`` and ``retries`` as soon as this
        returns (response headers have been received). It closes the response
        when read to the end, on error, or on ``close()``. Call ``close()`` to
        stop early (a stream that is dropped without ``close()`` is also closed
        when it is garbage-collected).
        """
        resp, meta = self._open("POST", path, body, headers, timeout, stream=True)
        return _EventStream(self, resp, meta)

    # --- 内部 -----------------------------------------------------------------

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

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _retry_delay(self, attempt: int, retry_after: Optional[str]) -> float:
        delay = _retry_after_delay(retry_after, self.retry_after_max)
        if delay is None:
            delay = min(8.0, 0.5 * (2 ** attempt)) * (0.75 + random.random() / 2)
        return delay

    def _emit_retry(
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
        """Tell listeners, then sleep. The delay in the payload is what we sleep."""
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
        self._sleep(delay)

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

    def _open(
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
                resp = self._client.send(req, stream=True)
                if resp.status_code >= 400 or not stream:
                    try:
                        if _declared_too_large(resp):
                            raise _too_large(_MAX_RESPONSE_BYTES, self.lang)
                        buffer = _ResponseBuffer(self.lang)
                        for chunk in resp.iter_bytes():
                            buffer.add(chunk)
                        resp._content = buffer.content()
                    except LLMError:
                        meta = self._call_meta(method, path, stream, started, attempt, resp)
                        resp.close()
                        self._emit_request_error(meta, "response_too_large")
                        raise
            except httpx.RequestError as e:
                if resp is not None:
                    resp.close()
                if attempt < self.max_retries and _is_retryable_transport_error(
                    e, self.retry_read_timeout
                ):
                    self._emit_retry(method, path, stream, attempt, _transport_reason(e), None, None)
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
            try:
                if (
                    resp.status_code in _RETRY_STATUS or resp.status_code >= 500
                ) and attempt < self.max_retries:
                    self._emit_retry(
                        method,
                        path,
                        stream,
                        attempt,
                        "status",
                        resp.status_code,
                        request_id_of(resp.headers),
                        resp.headers.get("retry-after"),
                    )
                    attempt += 1
                    continue
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
                resp.close()

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


class _EventStream:
    """SSE events of one streaming response. Owns the `httpx.Response`.

    Closes the response when read to the end, on error, or on `close()`. Also closes
    it from `__del__`, for streams dropped without ever being read (a plain
    generator's `finally` would not run then).

    `request_id` and `retries` are available as soon as the stream is returned.
    A terminal SSE event followed by `close()` emits `stream_end`.
    """

    def __init__(self, client: BaseClient, resp: httpx.Response, meta: _CallMeta) -> None:
        self._client = client
        self._resp = resp
        self._sse = iter_sse(resp.iter_lines(), client.lang)
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

    def __iter__(self) -> "_EventStream":
        return self

    def __next__(self) -> SSEEvent:
        if self._closed:
            raise StopIteration
        try:
            ev = next(self._sse)
        except StopIteration:
            self.close()
            raise
        except httpx.RequestError as e:
            self._fail_read(e)
        except LLMError as e:
            self._errored = True
            self.close()
            note_request_error(self._client, self, e.code)
            raise
        except BaseException:
            self._errored = True
            self.close()
            raise
        if _is_terminal_event(ev):
            self._terminal = True
        return ev

    def _fail_read(self, exc: httpx.RequestError) -> None:
        """Convert a mid-stream transport error, emit `connection_error`, and raise."""
        self._errored = True
        latency = time.monotonic() - self.started
        self.close()
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

    def close(self) -> None:
        """Close the stream and the response. Safe to call more than once.

        Best-effort cleanup: errors from closing are suppressed so httpx exceptions
        never leak and never mask the error that triggered the close. After a
        terminal SSE event, the first close emits `stream_end`.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._sse.close()
        except Exception:
            pass
        try:
            self._resp.close()
        except Exception:
            pass
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
        # Last resort for a stream dropped without close(). Never raise from __del__.
        if getattr(self, "_closed", True):
            return
        try:
            self.close()
        except Exception:
            pass
