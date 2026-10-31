"""Exception classes. httpx exceptions are wrapped here and never leak out."""

from __future__ import annotations

from typing import Any, Dict, Optional


class LLMError(Exception):
    """Base class for exceptions raised by this package.

    `code` is a language-independent identifier (for example `"missing_api_key"`).
    Branch on `code`, not on the translated message.
    """

    def __init__(self, message: str = "", *, code: Optional[str] = None) -> None:
        super().__init__(message)
        self.code = code


class LLMConfigError(LLMError):
    """A configuration problem, such as a missing API key or a bad model string."""


class APIConnectionError(LLMError):
    """The API could not be reached.

    `request_id` is set when the failure happened after response headers arrived
    (a dropped stream). It is None when the connection failed before that.
    `retries` is how many retries ran before this failure. `latency` is seconds
    from the start of the call until the failure, including retry waits.
    """

    def __init__(
        self,
        message: str = "",
        *,
        code: Optional[str] = None,
        provider: Optional[str] = None,
        request_id: Optional[str] = None,
        retries: int = 0,
        latency: Optional[float] = None,
    ) -> None:
        super().__init__(message, code=code)
        self.provider = provider
        self.request_id = request_id
        self.retries = retries
        self.latency = latency


class APITimeoutError(APIConnectionError):
    """The request timed out."""


class APIStatusError(LLMError):
    """The API returned HTTP 4xx or 5xx.

    `retries` is how many retries ran before this response. `latency` is seconds
    from the start of the call until this response, including retry waits.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: Any = None,
        provider: Optional[str] = None,
        request_id: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        retries: int = 0,
        latency: Optional[float] = None,
    ) -> None:
        super().__init__(message, code="api_error")
        self.status_code = status_code
        self.body = body
        self.provider = provider
        self.request_id = request_id
        self.headers = headers or {}
        self.retries = retries
        self.latency = latency


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
    """An error event arrived in the middle of a stream.

    `request_id` is taken from the response headers when the chat layer raises
    this. `retries` and `latency` describe the call that opened the stream.
    """

    def __init__(
        self,
        message: str,
        *,
        body: Any = None,
        provider: Optional[str] = None,
        request_id: Optional[str] = None,
        retries: int = 0,
        latency: Optional[float] = None,
    ) -> None:
        super().__init__(message, code="stream_error")
        self.body = body
        self.provider = provider
        self.request_id = request_id
        self.retries = retries
        self.latency = latency


def status_error_class(status_code: int) -> type:
    """Return the exception class for an HTTP status code."""
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
