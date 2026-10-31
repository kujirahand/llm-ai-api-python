"""Optional SQLite cache for chat() responses (model + input -> output). Off by default."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from .errors import LLMConfigError
from .lang import t
from .types import ChatResult, Usage

DEFAULT_CACHE_PATH = "llm_ai_api_cache.db"


class _Unset:
    """Type of `CACHE_NOT_SET`: "the cache argument was not passed" (as opposed to None/False)."""

    _instance: "Optional[_Unset]" = None

    def __new__(cls) -> "_Unset":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "CACHE_NOT_SET"

    def __bool__(self) -> bool:
        return False


CACHE_NOT_SET: Any = _Unset()


def cache_key(provider: str, body: Dict[str, Any]) -> str:
    """Return the cache key: sha256 of the canonical JSON of the provider and request body."""
    canonical = json.dumps(
        {"provider": provider, "body": body},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class SQLiteCache:
    """Stores ChatResult objects in an SQLite file, keyed by `cache_key()`."""

    def __init__(self, path: Any = DEFAULT_CACHE_PATH, *, lang: Optional[str] = None) -> None:
        """Open (and create if needed) the cache file. An unusable path raises LLMConfigError."""
        self.path = str(path)
        self._lock = threading.Lock()
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            with self._connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS llm_cache ("
                    "key TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT, "
                    "response TEXT NOT NULL, created_at REAL NOT NULL)"
                )
        except (sqlite3.Error, OSError) as e:
            raise LLMConfigError(
                t("invalid_cache", lang, detail="%s: %s" % (self.path, e)),
                code="invalid_cache",
            ) from e

    def __repr__(self) -> str:
        return "SQLiteCache(path=%r)" % self.path

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Open a fresh connection for one operation, commit, and always close it."""
        conn = sqlite3.connect(self.path, timeout=30.0)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def get(self, key: str) -> Optional[ChatResult]:
        """Return the stored result for `key`, or None on a miss."""
        with self._connect() as conn:
            row = conn.execute("SELECT response FROM llm_cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        data = json.loads(row[0])
        u = data.get("usage")
        usage = Usage(u.get("input_tokens"), u.get("output_tokens")) if isinstance(u, dict) else None
        return ChatResult(
            text=data.get("text", ""),
            model=data.get("model"),
            stop_reason=data.get("stop_reason"),
            usage=usage,
            raw=data.get("raw") or {},
        )

    def put(self, key: str, provider: str, result: ChatResult) -> None:
        """Store `result` under `key`, replacing any existing entry."""
        usage = (
            {"input_tokens": result.usage.input_tokens, "output_tokens": result.usage.output_tokens}
            if result.usage is not None
            else None
        )
        response = json.dumps(
            {
                "text": result.text,
                "model": result.model,
                "stop_reason": result.stop_reason,
                "usage": usage,
                "raw": result.raw,
            },
            ensure_ascii=False,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, provider, model, response, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, provider, result.model, response, time.time()),
            )

    def clear(self) -> None:
        """Delete all entries."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM llm_cache")

    def __len__(self) -> int:
        with self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]

    def close(self) -> None:
        """No-op (connections are per operation); kept for API symmetry."""

    def __enter__(self) -> "SQLiteCache":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


_global_cache: Any = None


def _resolve(value: Any, lang: Optional[str]) -> Any:
    if value is None or value is False:
        return None
    if value is True:
        return SQLiteCache(DEFAULT_CACHE_PATH, lang=lang)
    if isinstance(value, (str, os.PathLike)):
        return SQLiteCache(value, lang=lang)
    if isinstance(value, SQLiteCache) or (
        callable(getattr(value, "get", None)) and callable(getattr(value, "put", None))
    ):
        return value
    raise LLMConfigError(
        t("invalid_cache", lang, detail=repr(value)),
        code="invalid_cache",
    )


def set_cache(cache: Any = None, *, lang: Optional[str] = None) -> Any:
    """Set the process-wide cache (None/False: off, True: default file, path, or cache object)."""
    global _global_cache
    _global_cache = _resolve(cache, lang)
    return _global_cache


def get_cache() -> Any:
    """Return the process-wide cache object, or None when it is off."""
    return _global_cache


def resolve_cache(value: Any, *, lang: Optional[str] = None) -> Any:
    """Resolve a per-instance `cache=` argument; CACHE_NOT_SET falls back to the global cache."""
    if value is CACHE_NOT_SET:
        return get_cache()
    return _resolve(value, lang)
