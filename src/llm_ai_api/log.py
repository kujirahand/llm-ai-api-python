"""Optional JSON Lines log of chat() inputs and outputs. Off by default.

One line per call: time, provider, model, stream, cached, the request body and the raw
response (for a stream: the concatenated text and the raw chunks). The API key and the
auth headers are never recorded. The file is plain text, so it contains your prompts
and the answers; protect it accordingly.
"""

from __future__ import annotations

import copy
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from .errors import LLMConfigError
from .lang import t

DEFAULT_LOG_PATH = "llm_ai_api_log.jsonl"
LOG_DIR_ENV = "LLM_AI_API_LOG_DIR"
LOG_NAME = "llm.jsonl"  # file name inside the directory given by LOG_DIR_ENV
DEFAULT_MAX_SIZE = 100 * 1024 * 1024  # bytes; above this the oldest third of the records is dropped


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
    """Append-only JSON Lines log file.

    `max_size` (bytes) caps the file: when a `write()` leaves the file larger than that,
    the oldest third of the lines is dropped and the rest is rewritten. If the file is
    still over the limit, the next write trims again. The newest record is always kept.
    None means unlimited.

    `redact` receives a deep copy of each record and returns a dict to write, or None
    to skip it. It must be thread-safe when used by async calls.

    Threads of one process are serialized by a lock. Several processes writing to the
    same file are not fully supported while a trim runs: the trim abandons itself if the
    file changed since it was read (the next write retries), but a record appended by
    another process in the tiny window between that check and the final rename can
    still be lost.
    """

    def __init__(
        self,
        path: "str | os.PathLike[str]",
        *,
        max_size: Optional[int] = DEFAULT_MAX_SIZE,
        lang: Optional[str] = None,
        redact: Optional[Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]] = None,
    ) -> None:
        self.path = os.fspath(path)
        if max_size is not None and (
            isinstance(max_size, bool) or not isinstance(max_size, int) or max_size <= 0
        ):
            raise LLMConfigError(
                t("invalid_log", lang, detail="max_size=%r" % (max_size,)), code="invalid_log"
            )
        if redact is not None and not callable(redact):
            raise LLMConfigError(t("invalid_log", lang, detail="redact"), code="invalid_log")
        self.redact = redact
        self.max_size = max_size
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
        try:
            if os.name == "posix":
                os.fchmod(fd, 0o600)
            return os.fdopen(fd, "a", encoding="utf-8")
        except BaseException:
            os.close(fd)
            raise

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
        if self.redact is not None:
            record = self.redact(copy.deepcopy(record))
            if record is None:
                return
            if not isinstance(record, dict):
                raise TypeError("redact must return a dict or None")
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._lock, self._open() as f:
            f.write(line + "\n")
        with self._lock:
            self._trim()

    def _trim(self) -> None:
        """Drop the oldest third of the records if the file exceeds `max_size`.

        Called with the lock held. Best effort: a failure must not break the caller.
        """
        if self.max_size is None:
            return
        tmp = self.path + ".tmp"
        try:
            before = os.stat(self.path)
            if before.st_size <= self.max_size:
                return
            with open(self.path, "rb") as f:
                lines = f.read().splitlines(keepends=True)
            if len(lines) < 2:  # keep the newest record even if it alone exceeds max_size
                return
            keep = lines[max(1, len(lines) // 3):]
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                if os.name == "posix":
                    os.fchmod(fd, 0o600)
                with os.fdopen(fd, "wb") as f:
                    fd = -1
                    f.writelines(keep)
            finally:
                if fd != -1:
                    os.close(fd)
            after = os.stat(self.path)
            if (after.st_ino, after.st_size, after.st_mtime_ns) != (
                before.st_ino, before.st_size, before.st_mtime_ns
            ):
                # Another process appended while we worked: give up, retry on the next write.
                os.remove(tmp)
                return
            os.replace(tmp, self.path)
        except OSError:
            try:
                os.remove(tmp)
            except OSError:
                pass

    def close(self) -> None:
        """No-op (the file is opened per write); kept for API symmetry."""


_global_log: Any = None
_global_set = False  # True once set_log() was called (even with None = explicitly off)
_env_log: Any = None  # log opened from LLM_AI_API_LOG_DIR, created on first use


def _resolve(value: Any, lang: Optional[str], max_size: Optional[int] = DEFAULT_MAX_SIZE) -> Any:
    if value is None or value is False:
        return None
    if value is True:
        return JSONLLog(DEFAULT_LOG_PATH, max_size=max_size, lang=lang)
    if isinstance(value, (str, os.PathLike)):
        return JSONLLog(value, max_size=max_size, lang=lang)
    if isinstance(value, JSONLLog) or callable(getattr(value, "write", None)):
        return value
    raise LLMConfigError(t("invalid_log", lang, detail=repr(value)), code="invalid_log")


def set_log(
    log: Any = None, *, max_size: Optional[int] = DEFAULT_MAX_SIZE, lang: Optional[str] = None
) -> Any:
    """Set the process-wide log (None/False: off, True: default file, path, or log object).

    `max_size` (bytes, None = unlimited) is used when the log is created here from True or
    a path. A ready-made log object keeps its own `max_size`; this argument is ignored.

    Once called, it takes precedence over the LLM_AI_API_LOG_DIR environment variable.
    A log object needs `write(provider, model, request, response, *, stream, cached)`.
    """
    global _global_log, _global_set
    _global_log = _resolve(log, lang, max_size)
    _global_set = True
    return _global_log


def get_log(lang: Optional[str] = None) -> Any:
    """Return the process-wide log object, or None when it is off.

    Unless set_log() was called, the log is `<LLM_AI_API_LOG_DIR>/llm.jsonl` when that
    environment variable is set, and off otherwise.
    `lang` is the language of the error message if that log file cannot be opened.
    """
    global _env_log
    if _global_set:
        return _global_log
    directory = os.environ.get(LOG_DIR_ENV)
    if not directory:
        return None
    path = os.path.join(directory, LOG_NAME)
    if _env_log is None or _env_log.path != path:
        _env_log = JSONLLog(path, lang=lang)
    return _env_log


def resolve_log(value: Any, *, lang: Optional[str] = None) -> Any:
    """Resolve a per-instance `log=` argument; LOG_NOT_SET falls back to the global log."""
    if value is LOG_NOT_SET:
        return get_log(lang=lang)
    return _resolve(value, lang)
