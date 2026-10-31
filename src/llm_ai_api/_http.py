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


def iter_sse(lines: Iterable[str]) -> Iterator[SSEEvent]:
    """行のイテレータから SSE イベントを取り出す。

    `:` で始まる行（コメント）は無視し、空行でイベントを確定する。
    """
    event: Optional[str] = None
    data: list = []
    for line in lines:
        if line == "":
            if data or event is not None:
                yield SSEEvent(event, "\n".join(data))
            event, data = None, []
            continue
        if line.startswith(":"):
            continue
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "event":
            event = value
        elif name == "data":
            data.append(value)
    if data or event is not None:
        yield SSEEvent(event, "\n".join(data))


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
            texts.append(chunk.text)
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
                if ev.data == "[DONE]" or ev.event == "message_stop":
                    complete = True
                yield ev
            complete = True
        finally:
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
    ) -> Iterator[SSEEvent]:
        """JSON を送り、SSE イベントを順に返す。HTTP エラーはこの呼び出しで送出される。"""
        resp = self._open("POST", path, body, headers, timeout, stream=True)
        return self._iter_events(resp)

    # --- 内部 -----------------------------------------------------------------

    def _iter_events(self, resp: httpx.Response) -> Iterator[SSEEvent]:
        try:
            for ev in iter_sse(resp.iter_lines()):
                yield ev
        except httpx.TimeoutException as e:
            raise APITimeoutError(self._t("stream_timeout"), code="timeout") from e
        except httpx.TransportError as e:
            raise APIConnectionError(
                self._t("stream_connection_error", detail=e), code="connection_error"
            ) from e
        finally:
            resp.close()

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
            req = self._client.build_request(
                method, url, content=content, headers=self._headers(stream, headers), **kwargs
            )
            resp = None
            try:
                resp = self._client.send(req, stream=stream)
                if resp.status_code >= 400:
                    # With stream=True the error body has not been read yet, and reading
                    # it can fail too, so it has to be inside this try (conversion + retry).
                    resp.read()
            except httpx.TimeoutException as e:
                if resp is not None:
                    resp.close()
                if attempt < self.max_retries:
                    self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise APITimeoutError(self._t("timeout"), code="timeout") from e
            except httpx.TransportError as e:
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
