"""httpx による送受信、SSE パーサー、リトライ。

httpx の例外は、ここで自前の例外に変換して外に出さない。
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.parse
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple

import httpx

from .cache import CACHE_NOT_SET, SQLiteCache, cache_key, resolve_cache
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
_MAX_RETRY_AFTER = 60.0
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024  # largest non-stream response body that is accepted
_MAX_SSE_LINE_BYTES = 16 * 1024 * 1024  # longest single SSE line that is accepted


def _declared_too_large(resp: httpx.Response) -> bool:
    """True if the Content-Length header parses to an int over the response cap."""
    try:
        return int(resp.headers.get("content-length", "")) > _MAX_RESPONSE_BYTES
    except ValueError:
        return False


def _too_large(limit: int, lang: Optional[str]) -> LLMError:
    return LLMError(t("response_too_large", lang, limit=limit), code="response_too_large")


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
    if ev.data == "[DONE]":
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


class BaseClient:
    """各プロバイダーのクライアントの共通部分（生レイヤー）。"""

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
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        """`lang` はエラーメッセージの言語（`"ja"` / `"en"`）。None なら環境から判定する。

        `cache` は chat() の応答キャッシュ（True / パス / SQLiteCache / False / None。
        未指定なら `set_cache()` のグローバル設定に従う）。

        `log` は chat() の入出力ログ（True / パス / ログオブジェクト / False / None。
        未指定なら `set_log()` のグローバル設定に従う）。

        `transport` はテスト用（`httpx.MockTransport` を渡す）。
        """
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
        self._client = httpx.Client(
            transport=transport, timeout=httpx.Timeout(timeout, connect=10.0)
        )

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
        for chunk in chunks:
            texts.append(chunk.text or "")
            raws.append(chunk.raw)
            yield chunk
        self._log_call(body, {"text": "".join(texts), "chunks": raws}, stream=True, cached=cached)

    def _stream_events(self, path: str, body: Dict[str, Any]) -> Tuple[Iterator[SSEEvent], bool]:
        """`request_stream()` with the response cache: replay a hit, record a miss.

        A stream is stored only when it was read to the end (or up to its terminal event),
        as a `ChatResult` whose `raw["events"]` holds the SSE events.
        Returns the events and whether they were replayed from the cache.
        """
        cached = self._cache_lookup(body)
        if cached is not None and isinstance(cached.raw.get("events"), list):
            replay = [SSEEvent(e.get("event"), e.get("data", "")) for e in cached.raw["events"]]
            return iter(replay), True
        events = self.request_stream(path, body)
        if self.cache is None:
            return events, False
        return self._record_events(events, body), False

    def _record_events(self, events: Iterator[SSEEvent], body: Dict[str, Any]) -> Iterator[SSEEvent]:
        # Parsers stop at the terminal event and close this generator early, so a
        # terminal event counts as complete too. Errors and early stops are not stored.
        recorded: list = []
        complete = False
        try:
            for ev in events:
                recorded.append({"event": ev.event, "data": ev.data})
                if _is_terminal_event(ev):
                    complete = True
                yield ev
            complete = True
        finally:
            # 途中で閉じられたときも、レスポンスをすぐに解放する。
            close = getattr(events, "close", None)
            if close is not None:
                close()
            if complete:
                self._cache_store(body, ChatResult("", None, None, None, {"events": recorded}))

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
        """JSON を送り、レスポンス JSON（dict）をそのまま返す。"""
        resp = self._open(method, path, body, headers, timeout, stream=False)
        try:
            if len(resp.content) > _MAX_RESPONSE_BYTES:
                raise _too_large(_MAX_RESPONSE_BYTES, self.lang)
            return resp.json()
        except ValueError as e:
            raise LLMError(
                self._t("invalid_json_response", preview=resp.text[:200]),
                code="invalid_json_response",
            ) from e
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
        """JSON を送り、SSE イベントを順に返す。HTTP エラーはこの呼び出しで送出される。

        返すストリームは、最後まで読んだとき・エラーになったとき・`close()` を呼んだときに
        レスポンスを閉じる。途中でやめるときは `close()` を呼ぶこと
        （閉じずに捨てた場合も、回収時にレスポンスを閉じる）。
        """
        resp = self._open("POST", path, body, headers, timeout, stream=True)
        return _EventStream(self, resp)

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

    def _backoff(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = None
        if retry_after:
            try:
                delay = min(max(float(retry_after), 0.0), _MAX_RETRY_AFTER)
            except ValueError:
                delay = None
        if delay is None:
            delay = min(8.0, 0.5 * (2 ** attempt)) * (0.75 + random.random() / 2)
        self._sleep(delay)

    def _open(
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
                # Always send with stream=True so Content-Length can be checked before
                # a non-stream body is read.
                resp = self._client.send(req, stream=True)
                if resp.status_code >= 400:
                    # The error body has not been read yet, and reading
                    # it can fail too, so it has to be inside this try (conversion + retry).
                    resp.read()
                elif not stream:
                    if _declared_too_large(resp):
                        resp.close()
                        raise _too_large(_MAX_RESPONSE_BYTES, self.lang)
                    resp.read()
            except httpx.TimeoutException as e:
                if resp is not None:
                    resp.close()
                if attempt < self.max_retries:
                    self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise APITimeoutError(self._t("timeout"), code="timeout") from e
            except httpx.RequestError as e:
                if resp is not None:
                    resp.close()
                if attempt < self.max_retries:
                    self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise APIConnectionError(
                    self._t("connection_error", detail=e), code="connection_error"
                ) from e

            if resp.status_code < 400:
                return resp
            try:
                if (
                    resp.status_code in _RETRY_STATUS or resp.status_code >= 500
                ) and attempt < self.max_retries:
                    self._backoff(attempt, resp.headers.get("retry-after"))
                    attempt += 1
                    continue
                raise self._make_error(resp)
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
            message += ": " + msg  # API が返したメッセージは翻訳しない
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


class _EventStream:
    """SSE events of one streaming response. Owns the `httpx.Response`.

    Closes the response when read to the end, on error, or on `close()`. Also closes
    it from `__del__`, for streams dropped without ever being read (a plain
    generator's `finally` would not run then).
    """

    def __init__(self, client: BaseClient, resp: httpx.Response) -> None:
        self._client = client
        self._resp = resp
        self._events = iter_sse(resp.iter_lines(), client.lang)
        self._closed = False

    def __iter__(self) -> "_EventStream":
        return self

    def __next__(self) -> SSEEvent:
        if self._closed:
            raise StopIteration
        try:
            return next(self._events)
        except StopIteration:
            self.close()
            raise
        except httpx.TimeoutException as e:
            self.close()
            raise APITimeoutError(self._client._t("stream_timeout"), code="timeout") from e
        except httpx.RequestError as e:
            self.close()
            raise APIConnectionError(
                self._client._t("stream_connection_error", detail=e), code="connection_error"
            ) from e
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Close the stream and the response. Safe to call more than once.

        Best-effort cleanup: errors from closing are suppressed so httpx exceptions
        never leak and never mask the error that triggered the close.
        """
        if self._closed:
            return
        self._closed = True
        try:
            self._events.close()
        except Exception:
            pass
        try:
            self._resp.close()
        except Exception:
            pass

    def __del__(self) -> None:
        # Last resort for a stream dropped without close(). Never raise from __del__.
        if getattr(self, "_closed", True):
            return
        try:
            self.close()
        except Exception:
            pass
