"""Optional SQLite cache for chat() responses (model + input -> output). Off by default.

Key:   HMAC-SHA256("{provider}:{model}>>>{input}") keyed with a scrypt-derived key of the API
       key; `input` = canonical JSON of the request body and the client settings that can
       change a response. The API key itself is never part of the hashed message. Keys differ
       from the old sha256 format, so entries written by earlier versions simply miss.
Value: the whole ChatResult as JSON, encrypted with a key derived from the API key.
       Without an API key (providers that need none) a fixed default secret is used instead,
       so values are never stored in plain text; the per-file random salt still makes the
       derived key differ from file to file.

Only the standard library is available, so the cipher is built from HMAC-SHA256
(counter-mode keystream + encrypt-then-MAC) with a scrypt-derived key. It keeps cached
responses from sitting in plain text; it is not a substitute for protecting the API key.
With the default secret, anyone who knows it (it is public) and can read the file can decrypt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import stat
import threading
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, Optional

from .errors import LLMConfigError
from .lang import t
from .types import ChatResult, Usage, _optional_int

DEFAULT_CACHE_PATH = "llm_ai_api_cache.db"
CACHE_DIR_ENV = "LLM_AI_API_CACHE_DIR"
DB_NAME = "cache.db"  # file name inside the directory given by CACHE_DIR_ENV
DEFAULT_MAX_SIZE = 100 * 1024 * 1024  # bytes; above this the oldest third of the rows is dropped
_NONCE = 16
_MAC = 32
_PLAIN, _ENCRYPTED = b"P", b"E"  # first byte of a stored value
# Used in place of an API key when there is none. A domain-separation constant, not a secret.
_NO_KEY_SECRET = "llm-ai-api:no-api-key"
_chmod_warned_paths: set = set()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, stream: bytes) -> bytes:
    """XOR `data` with an equally long `stream` in bulk (integer arithmetic, not per byte)."""
    n = len(data)
    if n == 0:
        return b""
    return (int.from_bytes(data, "big") ^ int.from_bytes(stream, "big")).to_bytes(n, "big")


def _mac(mac_key: bytes, aad: bytes, nonce: bytes, ct: bytes) -> bytes:
    # `aad` (the cache key) is authenticated too, so a ciphertext cannot be moved to
    # another row. Its length is included to keep the field boundaries unambiguous.
    data = len(aad).to_bytes(4, "big") + aad + nonce + ct
    return hmac.new(mac_key, data, hashlib.sha256).digest()


def encrypt(enc_key: bytes, mac_key: bytes, plain: bytes, aad: bytes = b"") -> bytes:
    """Encrypt-then-MAC. Layout: nonce(16) + ciphertext + mac(32).

    `aad` is authenticated but not stored; pass the same value to `decrypt()`.
    """
    nonce = os.urandom(_NONCE)
    ct = _xor(plain, _keystream(enc_key, nonce, len(plain)))
    return nonce + ct + _mac(mac_key, aad, nonce, ct)


def decrypt(enc_key: bytes, mac_key: bytes, blob: bytes, aad: bytes = b"") -> Optional[bytes]:
    """Return the plain text, or None if the blob is malformed or fails authentication."""
    if len(blob) < _NONCE + _MAC:
        return None
    nonce, ct, mac = blob[:_NONCE], blob[_NONCE:-_MAC], blob[-_MAC:]
    if not hmac.compare_digest(mac, _mac(mac_key, aad, nonce, ct)):
        return None
    return _xor(ct, _keystream(enc_key, nonce, len(ct)))


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


def _cached_request_id(value: Any) -> Optional[str]:
    """Request id stored with a cache row. Missing or non-string values become None."""
    return value if isinstance(value, str) and value else None


def _cached_latency(value: Any) -> Optional[float]:
    """Latency in seconds. Missing or non-numeric values (including bool) become None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _cached_retries(value: Any) -> int:
    """Retry count. Missing or invalid values become 0 so older rows still load."""
    if type(value) is int and value >= 0:
        return value
    return 0


# Fixed salt: a domain-separation constant, not a secret. The API key supplies the entropy.
_KEY_SALT = b"llm-ai-api:cache-key:v2"
_KEY_MEMO_MAX = 128  # bound the memo below; a process normally uses a handful of API keys
_key_hmac_keys: Dict[str, bytes] = {}  # api_key -> derived HMAC key (bounded, like SQLiteCache._keys)
_key_hmac_lock = threading.Lock()


def _key_hmac_key(api_key: str) -> bytes:
    """Derive (and memoize) the per-API-key HMAC key; scrypt is slow and cache_key() is hot.

    The derivation runs outside the lock (it is deterministic, so two threads racing on a
    first use derive the same value); the lock only guards the memo dict itself.
    """
    with _key_hmac_lock:
        derived = _key_hmac_keys.get(api_key)
    if derived is None:
        derived = hashlib.scrypt(
            api_key.encode("utf-8"), salt=_KEY_SALT, n=2**14, r=8, p=1, dklen=32
        )
        with _key_hmac_lock:
            if len(_key_hmac_keys) >= _KEY_MEMO_MAX:
                _key_hmac_keys.clear()
            _key_hmac_keys[api_key] = derived
    return derived


def cache_key(
    provider: str,
    body: Dict[str, Any],
    context: Optional[Dict[str, Any]] = None,
    api_key: Optional[str] = "",
) -> str:
    """Return the cache key: HMAC-SHA256 of "{provider}:{model}>>>{input}" (64 hex chars).

    The HMAC key is derived from the API key with scrypt, so the API key is not hashed
    directly and is not part of the message. Different API keys give different cache keys.
    When `api_key` is None (a provider without a key) a fixed default secret is used, so the
    key is still derived and no exception is raised. Keys differ from the earlier sha256 format; existing cache entries simply miss.

    `input` is the canonical JSON of the request body and `context`. `context` carries
    client settings that can change the response for the same body (base URL, extra
    headers, the Anthropic API version), so entries are not shared across different
    endpoints or configurations.
    """
    model = body.get("model", "") if isinstance(body, dict) else ""
    canonical = json.dumps(
        {"body": body, "context": context or {}},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    raw = "%s:%s>>>%s" % (provider, model, canonical)
    if api_key is None:
        api_key = _NO_KEY_SECRET
    return hmac.new(_key_hmac_key(api_key), raw.encode("utf-8"), hashlib.sha256).hexdigest()


from ._io_errors import FailureCounter

class SQLiteCache(FailureCounter):
    """Stores ChatResult objects in an SQLite file, keyed by `cache_key()`.

    `max_size` (bytes) caps the file: when a `put()` leaves the file larger than that, the
    oldest third of the rows (by creation time) is deleted and the file is vacuumed. One
    trim per `put()`. None means unlimited.
    """

    def __init__(
        self,
        path: Any = DEFAULT_CACHE_PATH,
        *,
        max_size: Optional[int] = DEFAULT_MAX_SIZE,
        lang: Optional[str] = None,
    ) -> None:
        """Open (and create if needed) the cache file.

        An unusable path or a `max_size` that is not a positive int (or None) raises
        LLMConfigError.
        """
        self._init_failure_counter()
        self.path = str(path)
        if max_size is not None and (
            isinstance(max_size, bool) or not isinstance(max_size, int) or max_size <= 0
        ):
            raise LLMConfigError(
                t("invalid_cache", lang, detail="max_size=%r" % (max_size,)),
                code="invalid_cache",
            )
        self.max_size = max_size
        self._lock = threading.Lock()
        self._keys: Dict[str, tuple] = {}  # secret -> (enc_key, mac_key)
        try:
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, mode=0o700, exist_ok=True)
            if not os.path.exists(self.path):
                # Create the file owner-only from the start, so it is never readable by
                # others (even briefly) as it would be if SQLite created it with the umask.
                try:
                    fd = os.open(self.path, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
                except FileExistsError:
                    pass  # created concurrently by another process
                else:
                    os.close(fd)
            # Windows uses its own access controls; do not inspect Unix modes there.
            if os.name == "posix":
                for path in (self.path, self.path + "-wal", self.path + "-shm"):
                    try:
                        file_mode = os.lstat(path).st_mode
                    except OSError:
                        continue  # missing side files, or unreadable; SQLite still decides if the DB is usable
                    if stat.S_ISLNK(file_mode):
                        continue
                    mode = stat.S_IMODE(file_mode)
                    if mode & 0o077:
                        try:
                            os.chmod(path, 0o600)
                        except OSError:
                            if path not in _chmod_warned_paths:
                                _chmod_warned_paths.add(path)
                                logging.getLogger("llm_ai_api").warning(
                                    "Could not tighten cache file permissions: %s (mode %04o)",
                                    path, mode,
                                )
            with self._connect() as conn:
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS llm_cache ("
                    "key TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT, "
                    "response BLOB NOT NULL, created_at REAL NOT NULL)"
                )
                conn.execute("CREATE TABLE IF NOT EXISTS llm_cache_meta (name TEXT PRIMARY KEY, value BLOB)")
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
            try:
                # WAL lets several processes share one file without writers blocking readers.
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                pass  # best effort (read-only or network file systems): keep the default
            with conn:
                yield conn
        finally:
            conn.close()

    def _derive(self, secret: str) -> tuple:
        """Derive (enc_key, mac_key) from `secret` with scrypt and a per-file random salt."""
        if secret not in self._keys:
            with self._lock, self._connect() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO llm_cache_meta VALUES ('salt', ?)", (os.urandom(16),)
                )
                salt = conn.execute(
                    "SELECT value FROM llm_cache_meta WHERE name = 'salt'"
                ).fetchone()[0]
            dk = hashlib.scrypt(secret.encode("utf-8"), salt=bytes(salt), n=2**14, r=8, p=1, dklen=64)
            self._keys[secret] = (dk[:32], dk[32:])
        return self._keys[secret]

    def get(self, key: str, secret: Optional[str] = None) -> Optional[ChatResult]:
        """Return the stored result for `key`, or None on a miss.

        `secret` (the API key) decrypts entries written with it. Without `secret`, encrypted
        entries are decrypted with the default secret (as `put()` writes them), and plain
        entries written by older versions are still read. A corrupted or tampered
        row (bad MAC, invalid JSON, or not the shape `put` writes) is deleted and treated
        as a miss instead of raising.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT response FROM llm_cache WHERE key = ?", (key,)).fetchone()
        if row is None:
            return None
        try:
            if not isinstance(row[0], (bytes, bytearray)) or not row[0]:
                raise ValueError("cached response has an unexpected shape")
            blob = bytes(row[0])
            if secret is not None:
                # With a secret only authenticated, encrypted values are accepted; a
                # plain-text value here could have been planted by someone else.
                if blob[:1] != _ENCRYPTED:
                    raise ValueError("cached response is not encrypted")
                plain = decrypt(*self._derive(secret), blob[1:], key.encode("utf-8"))
                if plain is None:
                    raise ValueError("cached response failed authentication")
            elif blob[:1] == _PLAIN:
                plain = blob[1:]  # legacy row written before the default secret existed
            elif blob[:1] == _ENCRYPTED:
                plain = decrypt(*self._derive(_NO_KEY_SECRET), blob[1:], key.encode("utf-8"))
                if plain is None:
                    raise ValueError("cached response failed authentication")
            else:
                raise ValueError("cached response cannot be read")
            data = json.loads(plain.decode("utf-8"))
            if not isinstance(data, dict) or not isinstance(data.get("text"), str):
                raise ValueError("cached response has an unexpected shape")
            if not isinstance(data.get("raw"), dict):
                raise ValueError("cached response has an unexpected shape")
            u = data.get("usage")
            if u is None:
                usage = None
            elif isinstance(u, dict):
                usage = Usage(
                    u.get("input_tokens"),
                    u.get("output_tokens"),
                    cache_read_tokens=_optional_int(u.get("cache_read_tokens")),
                    cache_creation_tokens=_optional_int(u.get("cache_creation_tokens")),
                    reasoning_tokens=_optional_int(u.get("reasoning_tokens")),
                )
            else:
                raise ValueError("cached response has an unexpected shape")
            return ChatResult(
                text=data["text"],
                model=data.get("model"),
                stop_reason=data.get("stop_reason"),
                usage=usage,
                raw=data["raw"],
                request_id=_cached_request_id(data.get("request_id")),
                latency=_cached_latency(data.get("latency")),
                retries=_cached_retries(data.get("retries")),
            )
        except (ValueError, TypeError, KeyError):
            with self._lock, self._connect() as conn:
                conn.execute("DELETE FROM llm_cache WHERE key = ?", (key,))
            return None

    def put(
        self, key: str, provider: str, result: ChatResult, secret: Optional[str] = None
    ) -> None:
        """Store `result` under `key`, replacing any existing entry.

        The value is always encrypted: with `secret` (the API key), or with a fixed default
        secret when none is given. Either way the key also depends on the file's random salt.
        """
        usage = None
        if result.usage is not None:
            usage = {
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
            }
            for field in ("cache_read_tokens", "cache_creation_tokens", "reasoning_tokens"):
                value = getattr(result.usage, field)
                if value is not None:
                    usage[field] = value
        plain = json.dumps(
            {
                "text": result.text,
                "model": result.model,
                "stop_reason": result.stop_reason,
                "usage": usage,
                "raw": result.raw,
                "request_id": result.request_id,
                "latency": result.latency,
                "retries": result.retries,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        if secret is None:
            secret = _NO_KEY_SECRET
        value = _ENCRYPTED + encrypt(*self._derive(secret), plain, key.encode("utf-8"))
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO llm_cache (key, provider, model, response, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (key, provider, result.model, value, time.time()),
            )
        self._trim()

    def _trim(self) -> None:
        """Delete the oldest third of the rows and vacuum if the file exceeds `max_size`.

        Takes the lock itself (after the insert was committed). Best effort: a failure
        must not break the caller.
        """
        if self.max_size is None:
            return
        try:
            with self._lock:
                if os.path.getsize(self.path) <= self.max_size:
                    return
                # VACUUM cannot run inside a transaction, hence autocommit mode.
                conn = sqlite3.connect(self.path, timeout=30.0, isolation_level=None)
                try:
                    count = conn.execute("SELECT COUNT(*) FROM llm_cache").fetchone()[0]
                    if count > 1:  # always keep the newest row
                        conn.execute(
                            "DELETE FROM llm_cache WHERE key IN ("
                            "SELECT key FROM llm_cache ORDER BY created_at, rowid LIMIT ?)",
                            (max(1, count // 3),),
                        )
                    conn.execute("VACUUM")
                finally:
                    conn.close()
        except (sqlite3.Error, OSError):
            pass

    def clear(self, days: Optional[float] = None) -> int:
        """Delete entries older than `days` days (all of them when None); return the count."""
        cutoff = float("inf") if days is None else time.time() - days * 86400
        with self._lock, self._connect() as conn:
            return conn.execute("DELETE FROM llm_cache WHERE created_at <= ?", (cutoff,)).rowcount

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
_global_set = False  # True once set_cache() was called (even with None = explicitly off)
_env_cache: Any = None  # cache opened from LLM_AI_API_CACHE_DIR, created on first use


def _resolve(value: Any, lang: Optional[str], max_size: Optional[int] = DEFAULT_MAX_SIZE) -> Any:
    if value is None or value is False:
        return None
    if value is True:
        return SQLiteCache(DEFAULT_CACHE_PATH, max_size=max_size, lang=lang)
    if isinstance(value, (str, os.PathLike)):
        return SQLiteCache(value, max_size=max_size, lang=lang)
    if isinstance(value, SQLiteCache) or (
        callable(getattr(value, "get", None)) and callable(getattr(value, "put", None))
    ):
        return value
    raise LLMConfigError(
        t("invalid_cache", lang, detail=repr(value)),
        code="invalid_cache",
    )


def set_cache(
    cache: Any = None, *, max_size: Optional[int] = DEFAULT_MAX_SIZE, lang: Optional[str] = None
) -> Any:
    """Set the process-wide cache (None/False: off, True: default file, path, or cache object).

    `max_size` (bytes, None = unlimited) is used when the cache is created here from True
    or a path. A ready-made cache object keeps its own `max_size`; this argument is ignored.

    Once called, it takes precedence over the LLM_AI_API_CACHE_DIR environment variable.
    """
    global _global_cache, _global_set
    _global_cache = _resolve(cache, lang, max_size)
    _global_set = True
    return _global_cache


def get_cache() -> Any:
    """Return the process-wide cache object, or None when it is off.

    Unless set_cache() was called, the cache is `<LLM_AI_API_CACHE_DIR>/cache.db` when
    that environment variable is set, and off otherwise.
    """
    global _env_cache
    if _global_set:
        return _global_cache
    directory = os.environ.get(CACHE_DIR_ENV)
    if not directory:
        return None
    path = os.path.join(directory, DB_NAME)
    if _env_cache is None or _env_cache.path != path:
        _env_cache = SQLiteCache(path)
    return _env_cache


def clear_cache(days: float = 0, cache_dir: Optional[str] = None, *, lang: Optional[str] = None) -> int:
    """Delete cache entries older than `days` days and return how many were deleted.

    `days=0` deletes everything. The cache is `<cache_dir>/cache.db`; `cache_dir` defaults
    to the LLM_AI_API_CACHE_DIR environment variable, then to the process-wide cache.
    """
    directory = cache_dir or os.environ.get(CACHE_DIR_ENV)
    if directory:
        path = os.path.join(directory, DB_NAME)
        if not os.path.exists(path):
            return 0
        return SQLiteCache(path, lang=lang).clear(days)
    cache = get_cache()
    if isinstance(cache, SQLiteCache):
        return cache.clear(days)
    raise LLMConfigError(t("cache_dir_not_set", lang), code="cache_dir_not_set")


def resolve_cache(value: Any, *, lang: Optional[str] = None) -> Any:
    """Resolve a per-instance `cache=` argument; CACHE_NOT_SET falls back to the global cache."""
    if value is CACHE_NOT_SET:
        return get_cache()
    return _resolve(value, lang)
