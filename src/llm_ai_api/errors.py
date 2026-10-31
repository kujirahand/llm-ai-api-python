"""例外クラス。httpx の例外は外に出さず、ここの例外に包んで送出する。"""

from __future__ import annotations

from typing import Any, Dict, Optional


class LLMError(Exception):
    """このパッケージの例外の基底クラス。"""


class LLMConfigError(LLMError):
    """API キー未設定、モデル指定文字列の誤りなど、設定の問題。"""


class APIConnectionError(LLMError):
    """API に接続できなかった。"""


class APITimeoutError(APIConnectionError):
    """リクエストがタイムアウトした。"""


class APIStatusError(LLMError):
    """HTTP 4xx / 5xx が返った。"""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: Any = None,
        provider: Optional[str] = None,
        request_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body
        self.provider = provider
        self.request_id = request_id
        self.headers = headers or {}


class BadRequestError(APIStatusError):
    """400"""


class AuthenticationError(APIStatusError):
    """401"""


class PermissionDeniedError(APIStatusError):
    """403"""


class NotFoundError(APIStatusError):
    """404"""


class RateLimitError(APIStatusError):
    """429"""


class InternalServerError(APIStatusError):
    """500 以上"""


class APIStreamError(LLMError):
    """ストリームの途中で error イベントを受け取った。"""

    def __init__(self, message: str, *, body: Any = None) -> None:
        super().__init__(message)
        self.body = body


def status_error_class(status_code: int) -> type:
    """HTTP ステータスコードに対応する例外クラスを返す。"""
    if status_code == 400:
        return BadRequestError
    if status_code == 401:
        return AuthenticationError
    if status_code == 403:
        return PermissionDeniedError
    if status_code == 404:
        return NotFoundError
    if status_code == 429:
        return RateLimitError
    if status_code >= 500:
        return InternalServerError
    return APIStatusError
