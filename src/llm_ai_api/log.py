"""Optional JSON Lines log of chat() inputs and outputs. Off by default.

One line per call: time, provider, model, stream, cached, the request body and the raw
response (for a stream: the concatenated text and the raw chunks). The API key and the
auth headers are never recorded. The file is plain text, so it contains your prompts
and the answers; protect it accordingly.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .errors import LLMConfigError
from .lang import t

DEFAULT_LOG_PATH = "llm_ai_api_log.jsonl"
LOG_DIR_ENV = "LLM_AI_API_LOG_DIR"
LOG_NAME = "llm.jsonl"  # file name inside the directory given by LOG_DIR_ENV


class _Unset:
    """Type of `LOG_NOT_SET`: "the log argument was not passed" (as opposed to None/False)."""

    _instance: "Optional[_Unset]" = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "LOG_NOT_SET"

    def __bool__(self) -> bool:
        return False


LOG_NOT_SET = _Unset()


class JSONLLog:
    """Append-only JSON Lines log file."""

    def __init__(self, path: "str | os.PathLike[str]", *, lang: Optional[str] = None) -> None:
        self.path = os.fspath(path)
        self._lock = threading.Lock()
        try:
            parent = os.path.dirname(os.path.abspath(self.path))
            os.makedirs(parent, mode=0o700, exist_ok=True)
            self._open().close()
        except OSError as e:
            raise LLMConfigError(
                t("invalid_log", lang, detail="%s: %s" % (self.path, e)), code="invalid_log"
            ) from e

    def _open(self) -> Any:
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        return os.fdopen(fd, "a", encoding="utf-8")

    def write(
        self,
        provider: str,
        model: Optional[str],
        request: Dict[str, Any],
        response: Any,
        *,
        stream: bool = False,
        cached: bool = False,
    ) -> None:
        """Append one record."""
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "provider": provider,
            "model": model,
            "stream": stream,
            "cached": cached,
            "request": request,
            "response": response,
        }
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock, self._open() as f:
            f.write(line + "\n")

    def close(self) -> None:
        """No-op (the file is opened per write); kept for API symmetry."""


_global_log: Any = None
_global_set = False  # True once set_log() was called (even with None = explicitly off)
_env_log: Any = None  # log opened from LLM_AI_API_LOG_DIR, created on first use


def _resolve(value: Any, lang: Optional[str]) -> Any:
    if value is None or value is False:
        return None
    if value is True:
        return JSONLLog(DEFAULT_LOG_PATH, lang=lang)
    if isinstance(value, (str, os.PathLike)):
        return JSONLLog(value, lang=lang)
    if isinstance(value, JSONLLog) or callable(getattr(value, "write", None)):
        return value
    raise LLMConfigError(t("invalid_log", lang, detail=repr(value)), code="invalid_log")


def set_log(log: Any = None, *, lang: Optional[str] = None) -> Any:
    """Set the process-wide log (None/False: off, True: default file, path, or log object).

    Once called, it takes precedence over the LLM_AI_API_LOG_DIR environment variable.
    A log object needs `write(provider, model, request, response, *, stream, cached)`.
    """
    global _global_log, _global_set
    _global_log = _resolve(log, lang)
    _global_set = True
    return _global_log


def get_log() -> Any:
    """Return the process-wide log object, or None when it is off.

    Unless set_log() was called, the log is `<LLM_AI_API_LOG_DIR>/llm.jsonl` when that
    environment variable is set, and off otherwise.
    """
    global _env_log
    if _global_set:
        return _global_log
    directory = os.environ.get(LOG_DIR_ENV)
    if not directory:
        return None
    path = os.path.join(directory, LOG_NAME)
    if _env_log is None or _env_log.path != path:
        _env_log = JSONLLog(path)
    return _env_log


def resolve_log(value: Any, *, lang: Optional[str] = None) -> Any:
    """Resolve a per-instance `log=` argument; LOG_NOT_SET falls back to the global log."""
    if value is LOG_NOT_SET:
        return get_log()
    return _resolve(value, lang)
