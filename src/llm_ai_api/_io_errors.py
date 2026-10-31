"""Best-effort reporting for runtime cache and log failures."""

import logging
import threading


class FailureCounter:
    """Thread-safe count of failed operations performed through a client."""

    def _init_failure_counter(self):
        self._failure_count = 0
        self._failure_lock = threading.Lock()

    @property
    def failure_count(self):
        with self._failure_lock:
            return self._failure_count

    def _record_failure(self):
        with self._failure_lock:
            self._failure_count += 1


def report_io_error(client, target, kind, operation, exc):
    # Custom implementations need not support mutation or the counter interface.
    if isinstance(target, FailureCounter):
        target._record_failure()
    payload = {"provider": client.provider, "operation": operation,
               "error_type": type(exc).__name__, "message": "Details omitted"}
    try:
        logging.getLogger("llm_ai_api").warning(
            "%s %s failed (%s); details omitted", kind, operation, payload["error_type"]
        )
    except Exception:
        pass  # A broken logging handler must not affect the request.
    client._emit(kind + "_error", payload)
