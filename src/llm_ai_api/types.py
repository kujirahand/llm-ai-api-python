"""Return types."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .errors import LLMError
from .lang import t


def _optional_int(value: Any) -> Optional[int]:
    """Return ``value`` when it is an ``int`` (not ``bool``); otherwise ``None``."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


@dataclass
class Usage:
    """Token usage reported by the provider.

    ``input_tokens`` and ``output_tokens`` keep the provider's existing totals
    and are not adjusted for cache or reasoning tokens. The optional fields
    are ``None`` when the provider omitted them; an explicit zero is stored
    as ``0``. This library does not estimate missing values or compute cost.
    """

    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    cache_read_tokens: Optional[int] = None
    cache_creation_tokens: Optional[int] = None
    reasoning_tokens: Optional[int] = None


@dataclass
class ChatResult:
    """Result of one chat call. `raw` is the response JSON.

    `request_id` comes from the `x-request-id` header (OpenAI-style) or the
    `request-id` header (Anthropic), and is None when the response had neither.
    `latency` is seconds from the start of the call until the body was read,
    including time spent waiting to retry. `retries` is how many retries ran
    before this response (0 when the first attempt succeeded).

    A cache hit returns the `request_id`, `latency`, and `retries` stored with
    the original response. Entries written before those fields existed load as
    None, None, and 0.

    `parsed` holds the decoded or validated structured output when the call
    used `LLM.chat(..., schema=...)` / `LLM.achat(..., schema=...)`; it is
    None otherwise.
    """

    text: str
    model: Optional[str] = None
    stop_reason: Optional[str] = None
    usage: Optional[Usage] = None
    raw: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None
    latency: Optional[float] = None
    retries: int = 0
    parsed: Any = None


@dataclass
class ChatChunk:
    """One streaming event. `text` is the text delta (empty when there is none).

    `request_id` is the same value on every chunk of the call. It is None when
    the response had no request id.
    """

    text: str
    raw: Dict[str, Any] = field(default_factory=dict)
    request_id: Optional[str] = None


@dataclass
class SSEEvent:
    """One Server-Sent Event. `data` is the raw string."""

    event: Optional[str]
    data: str

    def json(self) -> Dict[str, Any]:
        """Parse `data` as a JSON object and return it."""
        try:
            value = json.loads(self.data)
        except ValueError as e:
            raise LLMError(
                t("invalid_json_response", preview=self.data[:200]),
                code="invalid_json_response",
            ) from e
        if not isinstance(value, dict):
            # Valid JSON but not an object (array, scalar, null).
            raise LLMError(
                t("invalid_json_response", preview=self.data[:200]),
                code="invalid_json_response",
            )
        return value
