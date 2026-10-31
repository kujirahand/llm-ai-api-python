"""Per-instance event listeners for request lifecycle notifications.

Listeners are synchronous callables ``listener(event, payload)``. They run on the
sync client and on the async client (the async path calls them inline, on the
event loop thread). A listener that raises ``Exception`` is ignored so it cannot
fail the request, change retries, or skip later listeners. ``BaseException``
(cancellation, keyboard interrupt) is not caught.

Payloads are plain dicts of metadata. They never include the API key, auth
headers, or the request or response body.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

from .errors import APIStreamError, LLMConfigError
from .lang import t
from .types import ChatResult

# Stable names, in the order shown to users. `None` means "every event".
EVENTS: Tuple[str, ...] = (
    "retry",
    "connection_error",
    "response",
    "http_error",
    "request_error",
    "stream_error",
    "stream_end",
    "cache_hit",
    "cache_error",
    "log_error",
)
_EVENT_SET = frozenset(EVENTS)

Listener = Callable[[str, Dict[str, Any]], Any]


@dataclass
class _CallMeta:
    """Metadata for one HTTP attempt sequence. Internal; not part of the public API."""

    method: str
    path: str
    stream: bool
    started: float
    request_id: Optional[str] = None
    retries: int = 0
    status_code: Optional[int] = None
    latency: Optional[float] = None  # seconds, snapshotted when the HTTP outcome is known


def request_id_of(headers: Any) -> Optional[str]:
    """Return ``x-request-id`` or ``request-id`` from response headers, if present."""
    if headers is None:
        return None
    value = headers.get("x-request-id") or headers.get("request-id")
    if isinstance(value, str) and value:
        return value
    return None


def _elapsed(started: float) -> float:
    return time.monotonic() - started


class EventDispatcher:
    """Registration list shared by a sync client and, for ``LLM``, its async client."""

    def __init__(self) -> None:
        self._listeners: List[Tuple[Optional[str], Listener]] = []
        self._lock = threading.Lock()

    def add(self, event: Optional[str], listener: Listener, lang: Optional[str]) -> None:
        _check_event(event, lang)
        if not callable(listener):
            raise LLMConfigError(t("invalid_listener", lang), code="invalid_listener")
        with self._lock:
            self._listeners.append((event, listener))

    def remove(self, event: Optional[str], listener: Listener, lang: Optional[str]) -> None:
        """Remove one registration. Unknown events raise; a missing listener does not."""
        _check_event(event, lang)
        with self._lock:
            for i, (registered, fn) in enumerate(self._listeners):
                if registered == event and fn is listener:
                    del self._listeners[i]
                    return

    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        """Call matching listeners. ``Exception`` from a listener is discarded."""
        with self._lock:
            listeners = [fn for registered, fn in self._listeners if registered is None or registered == event]
        for fn in listeners:
            try:
                fn(event, dict(payload))
            except Exception:
                continue


def _check_event(event: Optional[str], lang: Optional[str]) -> None:
    if event is None or event in _EVENT_SET:
        return
    raise LLMConfigError(
        t("invalid_event", lang, event=event, known=", ".join(EVENTS)),
        code="invalid_event",
    )


def retry_payload(
    meta_provider: str,
    method: str,
    path: str,
    stream: bool,
    attempt: int,
    max_retries: int,
    delay: float,
    reason: str,
    status_code: Optional[int],
    request_id: Optional[str],
) -> Dict[str, Any]:
    return {
        "provider": meta_provider,
        "method": method,
        "path": path,
        "stream": stream,
        "attempt": attempt,
        "retries": attempt,
        "max_retries": max_retries,
        "delay": delay,
        "reason": reason,
        "status_code": status_code,
        "request_id": request_id,
    }


def outcome_payload(
    provider: str,
    method: str,
    path: str,
    stream: bool,
    attempt: int,
    request_id: Optional[str],
    latency: Optional[float],
    status_code: Optional[int],
    **extra: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "provider": provider,
        "method": method,
        "path": path,
        "stream": stream,
        "attempt": attempt,
        "retries": attempt,
        "status_code": status_code,
        "request_id": request_id,
        "latency": latency,
    }
    payload.update(extra)
    return payload


def cache_hit_payload(provider: str, stream: bool, model: Any, result: ChatResult) -> Dict[str, Any]:
    return {
        "provider": provider,
        "stream": stream,
        "model": model if isinstance(model, str) else None,
        "request_id": result.request_id,
        "retries": result.retries,
        "latency": result.latency,
        "cached": True,
    }


def apply_result_meta(result: ChatResult, meta: _CallMeta) -> ChatResult:
    """Copy HTTP metadata onto a parsed `ChatResult` (mutates and returns it)."""
    result.request_id = meta.request_id
    result.retries = meta.retries
    result.latency = meta.latency
    return result


def note_stream_error(client: Any, exc: APIStreamError, events: Any) -> None:
    """Fill metadata on a stream error and emit ``stream_error`` before it propagates."""
    started = getattr(events, "started", None)
    exc.provider = client.provider
    exc.request_id = getattr(events, "request_id", None)
    exc.retries = getattr(events, "retries", 0) or 0
    exc.latency = None if started is None else _elapsed(started)
    client._emit(
        "stream_error",
        {
            "provider": client.provider,
            "request_id": exc.request_id,
            "retries": exc.retries,
            "latency": exc.latency,
            "stream": True,
            "code": exc.code,
        },
    )


def note_request_error(client: Any, events: Any, code: Optional[str]) -> None:
    """Emit ``request_error`` for a failure while reading a stream (for example bad JSON)."""
    started = getattr(events, "started", None)
    client._emit(
        "request_error",
        {
            "provider": client.provider,
            "method": getattr(events, "method", None),
            "path": getattr(events, "path", None),
            "stream": True,
            "attempt": getattr(events, "retries", 0) or 0,
            "retries": getattr(events, "retries", 0) or 0,
            "status_code": getattr(events, "status_code", None),
            "request_id": getattr(events, "request_id", None),
            "latency": None if started is None else _elapsed(started),
            "code": code,
        },
    )
