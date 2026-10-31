"""Encrypted local response cache stored in a single SQLite file.

Key:   sha256("{provider}:{model}@{api_key}>>>{input}"), where `input` is the request as
       canonical JSON (method, path, stream flag and body).
Value: the whole response, encrypted with a key derived from the API key.

Only the standard library is available, so the cipher is built from HMAC-SHA256
(counter-mode keystream + encrypt-then-MAC) with a scrypt-derived key. It keeps cached
responses from sitting in plain text; it is not a substitute for protecting the API key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import time
from contextlib import closing
from typing import Any, Dict, Optional

from .errors import LLMConfigError
from .lang import t

DB_NAME = "cache.db"
_NONCE = 16
_MAC = 32


def cache_key(provider: str, model: str, api_key: str, input_json: str) -> str:
    """Return the lookup hash for one request."""
    raw = "%s:%s@%s>>>%s" % (provider, model, api_key, input_json)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest()
        counter += 1
    return bytes(out[:length])


def encrypt(enc_key: bytes, mac_key: bytes, plain: bytes) -> bytes:
    """Encrypt-then-MAC. Layout: nonce(16) + ciphertext + mac(32)."""
    nonce = os.urandom(_NONCE)
    ks = _keystream(enc_key, nonce, len(plain))
    ct = bytes(a ^ b for a, b in zip(plain, ks))
    mac = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    return nonce + ct + mac


def decrypt(enc_key: bytes, mac_key: bytes, blob: bytes) -> Optional[bytes]:
    """Return the plain text, or None if the blob is malformed or fails authentication."""
    if len(blob) < _NONCE + _MAC:
        return None
    nonce, ct, mac = blob[:_NONCE], blob[_NONCE:-_MAC], blob[-_MAC:]
    want = hmac.new(mac_key, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, want):
        return None
    ks = _keystream(enc_key, nonce, len(ct))
    return bytes(a ^ b for a, b in zip(ct, ks))


def _connect(cache_dir: str) -> sqlite3.Connection:
    os.makedirs(cache_dir, exist_ok=True)
    db = sqlite3.connect(os.path.join(cache_dir, DB_NAME), timeout=30)
    db.execute("CREATE TABLE IF NOT EXISTS meta (name TEXT PRIMARY KEY, value BLOB)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS cache ("
        "key TEXT PRIMARY KEY, value BLOB NOT NULL, created_at REAL NOT NULL)"
    )
    return db


class ResponseCache:
    """Cache for one client (one provider and API key)."""

    def __init__(self, cache_dir: str, provider: str, api_key: str) -> None:
        self.cache_dir = cache_dir
        self.provider = provider
        self._api_key = api_key
        self._keys: Optional[tuple] = None

    def _derive(self, db: sqlite3.Connection) -> tuple:
        # The scrypt salt is random per database and stored in it; deriving once per
        # client keeps lookups fast.
        if self._keys is None:
            row = db.execute("SELECT value FROM meta WHERE name = 'salt'").fetchone()
            if row is None:
                db.execute(
                    "INSERT OR IGNORE INTO meta VALUES ('salt', ?)", (os.urandom(16),)
                )
                db.commit()
                row = db.execute("SELECT value FROM meta WHERE name = 'salt'").fetchone()
            dk = hashlib.scrypt(
                self._api_key.encode("utf-8"), salt=row[0], n=2**14, r=8, p=1, dklen=64
            )
            self._keys = (dk[:32], dk[32:])
        return self._keys

    def key(self, method: str, path: str, body: Any, stream: bool) -> str:
        """Build the lookup key for a request."""
        model = body.get("model", "") if isinstance(body, dict) else ""
        input_json = json.dumps(
            {"method": method, "path": path, "stream": stream, "body": body},
            ensure_ascii=False,
            sort_keys=True,
        )
        return cache_key(self.provider, str(model), self._api_key, input_json)

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        """Return the cached response, or None on a miss or any storage/decrypt problem."""
        try:
            with closing(_connect(self.cache_dir)) as db:
                row = db.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
                if row is None:
                    return None
                enc_key, mac_key = self._derive(db)
            plain = decrypt(enc_key, mac_key, bytes(row[0]))
            data = None if plain is None else json.loads(plain.decode("utf-8"))
        except (sqlite3.Error, OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def store(self, key: str, data: Dict[str, Any]) -> None:
        """Save a response. Best effort: a failure never breaks the API call."""
        try:
            with closing(_connect(self.cache_dir)) as db:
                enc_key, mac_key = self._derive(db)
                blob = encrypt(
                    enc_key, mac_key, json.dumps(data, ensure_ascii=False).encode("utf-8")
                )
                db.execute(
                    "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)", (key, blob, time.time())
                )
                db.commit()
        except (sqlite3.Error, OSError):
            pass


def clear_cache(days: float = 0, cache_dir: Optional[str] = None, *, lang: Optional[str] = None) -> int:
    """Delete cache entries older than `days` days and return how many were deleted.

    `days=0` deletes everything. `cache_dir` defaults to env `LLM_AI_API_CACHE_DIR`.
    """
    directory = cache_dir or os.environ.get("LLM_AI_API_CACHE_DIR")
    if not directory:
        raise LLMConfigError(t("cache_dir_not_set", lang), code="cache_dir_not_set")
    if not os.path.exists(os.path.join(directory, DB_NAME)):
        return 0
    cutoff = time.time() - days * 86400
    with closing(_connect(directory)) as db:
        cur = db.execute("DELETE FROM cache WHERE created_at <= ?", (cutoff,))
        db.commit()
        return cur.rowcount
