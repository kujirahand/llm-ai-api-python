"""httpx による送受信、SSE パーサー、リトライ。

httpx の例外は、ここで自前の例外に変換して外に出さない。
"""

from __future__ import annotations

import json
import os
import random
import time
from typing import Any, Dict, Iterable, Iterator, Optional

import httpx

from .errors import (
    APIConnectionError,
    APITimeoutError,
    APIStatusError,
    LLMConfigError,
    LLMError,
    status_error_class,
)
from .types import SSEEvent

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


def _user_agent() -> str:
    from . import __version__

    return "llm-ai-api-python/" + __version__


def _error_message(body: Any) -> Optional[str]:
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
    base_url_env = ""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 600.0,
        max_retries: int = 2,
        headers: Optional[Dict[str, str]] = None,
        *,
        transport: Optional[httpx.BaseTransport] = None,
    ) -> None:
        """`transport` はテスト用（`httpx.MockTransport` を渡す）。"""
        key = api_key or os.environ.get(self.api_key_env)
        if not key:
            raise LLMConfigError(
                "%s の API キーがありません。api_key 引数か環境変数 %s で指定してください。"
                % (self.provider, self.api_key_env)
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
        return "%s(base_url=%r)" % (type(self).__name__, self.base_url)

    def close(self) -> None:
        """内部の HTTP クライアントを閉じる。"""
        self._client.close()

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
            raise LLMError("レスポンスが JSON ではありません: %r" % resp.text[:200]) from e
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
            raise APITimeoutError("ストリームの読み取りがタイムアウトしました") from e
        except httpx.TransportError as e:
            raise APIConnectionError("ストリームの読み取りに失敗しました: %s" % e) from e
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
            try:
                resp = self._client.send(req, stream=stream)
            except httpx.TimeoutException as e:
                if attempt < self.max_retries:
                    self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise APITimeoutError("リクエストがタイムアウトしました") from e
            except httpx.TransportError as e:
                if attempt < self.max_retries:
                    self._backoff(attempt, None)
                    attempt += 1
                    continue
                raise APIConnectionError("接続に失敗しました: %s" % e) from e

            if resp.status_code < 400:
                return resp
            try:
                resp.read()
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
        msg = _error_message(body)
        message = "%s API error (HTTP %d)" % (self.provider, resp.status_code)
        if msg:
            message += ": " + msg
        request_id = resp.headers.get("x-request-id") or resp.headers.get("request-id")
        return status_error_class(resp.status_code)(
            message,
            status_code=resp.status_code,
            body=body,
            provider=self.provider,
            request_id=request_id,
            headers=dict(resp.headers),
        )
