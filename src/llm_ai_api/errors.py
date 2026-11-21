"""Exception classes. httpx exceptions are wrapped here and never leak out."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


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


class InsufficientCreditsError(APIStatusError):
    """Credit, billing, or quota exhaustion.

    Raised for HTTP 402, and for 403/429 responses whose body reports a
    credit, billing, or quota failure (for example xAI ``permission-denied``
    with a credits/licenses message, or OpenAI ``insufficient_quota``).
    Ordinary permission and rate-limit errors keep their existing classes.
    """


class InternalServerError(APIStatusError):
    """500 以上"""


class APIStreamError(LLMError):
    """A stream reported an error or ended without its terminal event.

    `request_id` is taken from the response headers when the chat layer raises
    this. `retries` and `latency` describe the call that opened the stream.
    """

    def __init__(
        self,
        message: str,
        *,
        body: Any = None,
        code: str = "stream_error",
        provider: Optional[str] = None,
        request_id: Optional[str] = None,
        retries: int = 0,
        latency: Optional[float] = None,
    ) -> None:
        super().__init__(message, code=code)
        self.body = body
        self.provider = provider
        self.request_id = request_id
        self.retries = retries
        self.latency = latency


class StructuredOutputError(LLMError):
    """The response could not be used as the structured output requested with `schema=`.

    `result` is the original `ChatResult`, so the (already paid for) response
    stays available. `code` is one of `output_refused`, `output_incomplete`,
    or `invalid_structured_output`.
    """

    def __init__(
        self,
        message: str,
        *,
        code: str,
        result: Any,
        provider: Optional[str] = None,
    ) -> None:
        super().__init__(message, code=code)
        self.result = result
        self.provider = provider


# Fold "_" and "-" so "insufficient_quota" and "insufficient-quota" match.
_CREDIT_CODES = frozenset(
    {
        "insufficient-quota",
        "billing-error",
        "billing-not-configured",
    }
)
_PERMISSION_DENIED_CODES = frozenset({"permission-denied"})
_CREDIT_PHRASES = (
    "credits or licenses",
    "credit or license",
    "doesn't have any credits",
    "does not have any credits",
    "don't have any credits",
    "do not have any credits",
    "has no credits",
    "have no credits",
    "out of credits",
    "out of credit",
    "insufficient credits",
    "insufficient credit",
    "no credits or licenses",
)


def _normalized_token(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    token = value.strip().lower().replace("_", "-")
    return token or None


def _codes_and_message(body: Any) -> Tuple[set, str]:
    """Collect error code/type/status tokens and the combined message text."""
    codes: set = set()
    parts: list = []

    def add_code(value: Any) -> None:
        token = _normalized_token(value)
        if token is not None:
            codes.add(token)

    def add_message(value: Any) -> None:
        if isinstance(value, str) and value:
            parts.append(value)

    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict):
            add_code(err.get("code"))
            add_code(err.get("type"))
            add_code(err.get("status"))
            add_message(err.get("message"))
        elif isinstance(err, str):
            add_message(err)
        add_code(body.get("code"))
        add_code(body.get("type"))
        add_code(body.get("status"))
        add_message(body.get("message"))
    elif isinstance(body, str):
        add_message(body)
    return codes, " ".join(parts).lower()


def is_insufficient_credits(status_code: int, body: Any = None) -> bool:
    """Return True when the HTTP error is credit, billing, or quota exhaustion."""
    if status_code == 402:
        return True
    codes, message = _codes_and_message(body)
    if codes & _CREDIT_CODES:
        return True
    if status_code == 403 and (codes & _PERMISSION_DENIED_CODES):
        if any(phrase in message for phrase in _CREDIT_PHRASES):
            return True
    return False


def status_error_class(status_code: int, body: Any = None) -> type:
    """Return the exception class for an HTTP status code and optional error body."""
    if is_insufficient_credits(status_code, body):
        return InsufficientCreditsError
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
