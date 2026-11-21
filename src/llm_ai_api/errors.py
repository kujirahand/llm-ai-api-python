"""Exception classes. httpx exceptions are wrapped here and never leak out."""

from __future__ import annotations

import re
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

    Raised for HTTP 402, and for other 4xx responses whose body has a
    machine-readable billing or quota code, an OpenRouter budget
    ``limit_source``, an xAI ``permission-denied`` 403 that mentions credits,
    or a documented Anthropic credit or spend-limit sentence.
    Ordinary permission errors and temporary rate limits, including a Google
    429 ``RESOURCE_EXHAUSTED``, keep their existing classes.
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
# These are machine-readable codes, not message text. A temporary rate-limit
# code (OpenAI ``slow_down``, Google ``rate_limit_exceeded`` /
# ``too_many_requests``, Anthropic ``rate_limit_error`` with no spend-cap
# code) is intentionally absent. Google's legacy / OpenAI-compatible
# ``RESOURCE_EXHAUSTED`` is also absent: that status is used for short-lived
# rate limits and for spend-based limits the rate-limits page says to retry,
# and the body does not carry a separate quota code.
# https://developers.openai.com/api/docs/guides/error-codes
# https://platform.claude.com/docs/en/api/rate-limits
# https://ai.google.dev/gemini-api/docs/api-errors
# https://ai.google.dev/gemini-api/docs/rate-limits
# https://dev.meta.ai/docs/error-handling
_CREDIT_CODES = frozenset(
    {
        # OpenAI. ``insufficient_quota`` is the broad type; the others are error.code.
        "insufficient-quota",
        "credit-balance-exhausted",
        "organization-spend-limit-exceeded",
        "project-spend-limit-exceeded",
        "organization-usage-limit-exceeded",
        # Anthropic billing_error, and the tier spend cap's details.error_code.
        "billing-error",
        "enforced-spend-limit-reached",
        # Meta Model API.
        "billing-not-configured",
        # Google Interactions API. Not the legacy RESOURCE_EXHAUSTED status.
        "quota-exceeded",
        "payment-required",
    }
)
_PERMISSION_DENIED_CODES = frozenset({"permission-denied"})
# OpenRouter 403 budget exhaustion. ``openrouter_in_flight_budget`` is not
# here: that case is a transient HTTP 402, which is classified separately.
# Content-filter 403s have no limit_source and stay permission errors.
# https://openrouter.ai/docs/api_reference/errors-and-debugging
_CREDIT_LIMIT_SOURCES = frozenset(
    {
        "openrouter-guardrail-budget",
        "openrouter-workspace-budget",
        "openrouter-key-limit",
        "openrouter-credits",
    }
)
# 4xx message text, used only where the provider publishes no distinct code.
# Anthropic's empty balance is 400 invalid_request_error (same type as a bad
# request). A spend limit the caller set is also that type; the rate-limits
# page gives these prefixes and no error_code.
# https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers
# https://platform.claude.com/docs/en/api/rate-limits
_CREDIT_MESSAGE_PHRASES = (
    "credit balance is too low",
    "credit balance too low",
    "you have reached your specified api usage limits",
    "you have reached your specified workspace api usage limits",
)
# xAI keeps using 403 permission-denied for a team with no credits, and the
# debugging page does not publish a separate code. Match the word so a
# reworded sentence still counts, but not "accredited", a "/credits" URL
# path, or "non-credit". The code alone is a normal permission error.
_CREDIT_WORD = re.compile(r"(?<!non-)(?<![/\w])credits?\b")


def _normalized_token(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    token = value.strip().lower().replace("_", "-")
    return token or None


def _add_error_codes(obj: Any, add_code) -> None:
    """Record code/type/status, plus Anthropic's ``details.error_code``."""
    if not isinstance(obj, dict):
        return
    add_code(obj.get("code"))
    add_code(obj.get("type"))
    add_code(obj.get("status"))
    details = obj.get("details")
    if isinstance(details, dict):
        add_code(details.get("error_code"))


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
            _add_error_codes(err, add_code)
            add_message(err.get("message"))
        elif isinstance(err, str):
            add_message(err)
        _add_error_codes(body, add_code)
        add_message(body.get("message"))
    elif isinstance(body, str):
        add_message(body)
    return codes, " ".join(parts).lower()


def _limit_sources(body: Any) -> set:
    """OpenRouter ``error.metadata.limit_source`` values, normalized."""
    sources: set = set()
    if not isinstance(body, dict):
        return sources
    err = body.get("error")
    if not isinstance(err, dict):
        return sources
    meta = err.get("metadata")
    if not isinstance(meta, dict):
        return sources
    token = _normalized_token(meta.get("limit_source"))
    if token is not None:
        sources.add(token)
    return sources


def is_insufficient_credits(status_code: int, body: Any = None) -> bool:
    """Return True when the HTTP error is credit, billing, or quota exhaustion.

    HTTP 402 always matches (Meta, OpenRouter credits, Google prepay, Anthropic
    ``billing_error``). Other statuses match only on a code or limit_source
    from the tables above, an xAI ``permission-denied`` 403 whose message
    contains the word "credit(s)", or a documented Anthropic 4xx sentence.
    """
    if status_code == 402:
        return True
    codes, message = _codes_and_message(body)
    if codes & _CREDIT_CODES:
        return True
    if _limit_sources(body) & _CREDIT_LIMIT_SOURCES:
        return True
    if status_code == 403 and (codes & _PERMISSION_DENIED_CODES):
        if _CREDIT_WORD.search(message):
            return True
    if 400 <= status_code < 500 and any(
        phrase in message for phrase in _CREDIT_MESSAGE_PHRASES
    ):
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
