import os
import sqlite3
import tempfile
import unittest
from unittest import mock

import llm_ai_api.cache as cache_mod
from llm_ai_api import LLMConfigError, OpenAIClient, SQLiteCache, clear_cache, set_cache
from llm_ai_api.cache import cache_key, decrypt, encrypt
from llm_ai_api.types import ChatResult

from .helpers import Recorder, json_response

REPLY = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
MSGS = [{"role": "user", "content": "q"}]


class CryptoTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.db = os.path.join(self.dir, "cache.db")
        # Keep the process-wide state out of the way.
        patch = mock.patch.object(cache_mod, "_global_set", False)
        patch.start()
        self.addCleanup(patch.stop)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("LLM_AI_API_CACHE_DIR", None)

    def client(self, rec, api_key="k", **kw):
        return OpenAIClient(api_key=api_key, transport=rec.transport, **kw)

    def test_cipher_roundtrip_and_tamper(self):
        blob = encrypt(b"e" * 32, b"m" * 32, b"hello" * 100)
        self.assertEqual(decrypt(b"e" * 32, b"m" * 32, blob), b"hello" * 100)
        self.assertIsNone(decrypt(b"e" * 32, b"x" * 32, blob))
        bad = bytearray(blob)
        bad[20] ^= 1
        self.assertIsNone(decrypt(b"e" * 32, b"m" * 32, bytes(bad)))

    def _canonical(self, body):
        import json

        return json.dumps(
            {"body": body, "context": {}}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )

    def test_key_format(self):
        import hashlib
        import hmac

        body = {"model": "m", "messages": MSGS}
        canonical = self._canonical(body)
        derived = hashlib.scrypt(
            b"KEY", salt=b"llm-ai-api:cache-key:v2", n=2**14, r=8, p=1, dklen=32
        )
        want = hmac.new(derived, ("openai:m>>>" + canonical).encode(), hashlib.sha256).hexdigest()
        self.assertEqual(cache_key("openai", body, None, "KEY"), want)
        self.assertEqual(len(want), 64)
        self.assertNotEqual(cache_key("openai", body, None, "OTHER"), want)

    def test_key_differs_from_old_format(self):
        # Old format was a plain SHA-256 digest of "provider:model@api_key>>>input".
        # Its value for these inputs is kept as a literal so this test does not
        # reintroduce the flagged construction.
        body = {"model": "m", "messages": MSGS}
        old = "dfcddbb49af89e643a2078892bda9d20056f6df0c19dcbd23b2f7a0da5a0eabc"
        self.assertNotEqual(cache_key("openai", body, None, "K"), old)

    def test_key_derivation_is_memoized_per_api_key(self):
        import hashlib

        body = {"model": "m", "messages": MSGS}
        real_scrypt = hashlib.scrypt
        with mock.patch.object(hashlib, "scrypt", wraps=real_scrypt) as scrypt:
            first = cache_key("openai", body, None, "memo-key-unique")
            second = cache_key("openai", body, None, "memo-key-unique")
        self.assertEqual(first, second)
        self.assertEqual(scrypt.call_count, 1)

    def test_key_empty_and_unicode_api_keys(self):
        body = {"model": "m", "messages": MSGS}
        self.assertEqual(cache_key("openai", body, None, ""), cache_key("openai", body, None, ""))
        self.assertNotEqual(cache_key("openai", body, None, ""), cache_key("openai", body, None, "k"))
        self.assertNotEqual(
            cache_key("openai", body, None, "キー"), cache_key("openai", body, None, "key")
        )

    def test_stored_value_is_encrypted_and_api_key_absent(self):
        rec = Recorder(json_response(REPLY))
        self.client(rec, cache=self.db).chat("m", MSGS)
        with open(self.db, "rb") as f:
            raw = f.read()
        self.assertNotIn(b"finish_reason", raw)
        self.assertNotIn(b"chat.completion", raw)
        self.assertEqual(len(rec.requests), 1)

    def test_roundtrip_through_client(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache=self.db)
        self.assertEqual(c.chat("m", MSGS).text, "hi")
        self.assertEqual(c.chat("m", MSGS).text, "hi")
        self.assertEqual(len(rec.requests), 1)

    def test_other_api_key_does_not_share_entries(self):
        rec = Recorder(json_response(REPLY))
        self.client(rec, cache=self.db).chat("m", MSGS)
        self.client(rec, api_key="other", cache=self.db).chat("m", MSGS)
        self.assertEqual(len(rec.requests), 2)

    def test_tampered_value_is_a_miss(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache=self.db)
        c.chat("m", MSGS)
        conn = sqlite3.connect(self.db)
        blob = bytearray(conn.execute("SELECT response FROM llm_cache").fetchone()[0])
        blob[25] ^= 1
        conn.execute("UPDATE llm_cache SET response = ?", (bytes(blob),))
        conn.commit()
        conn.close()
        self.assertEqual(c.chat("m", MSGS).text, "hi")
        self.assertEqual(len(rec.requests), 2)

    def test_plain_value_is_rejected_when_a_secret_is_used(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache=self.db)
        c.chat("m", MSGS)
        conn = sqlite3.connect(self.db)
        forged = b'P{"text":"forged","raw":{}}'
        conn.execute("UPDATE llm_cache SET response = ?", (forged,))
        conn.commit()
        conn.close()
        self.assertEqual(c.chat("m", MSGS).text, "hi")
        self.assertEqual(len(rec.requests), 2)

    def test_ciphertext_cannot_be_moved_to_another_row(self):
        rec = Recorder(json_response(REPLY), json_response({"choices": [{"message": {"content": "other"}}]}))
        c = self.client(rec, cache=self.db)
        c.chat("m", MSGS)
        c.chat("m", [{"role": "user", "content": "q2"}])
        conn = sqlite3.connect(self.db)
        rows = conn.execute("SELECT key, response FROM llm_cache ORDER BY created_at").fetchall()
        conn.execute("UPDATE llm_cache SET response = ? WHERE key = ?", (rows[0][1], rows[1][0]))
        conn.commit()
        conn.close()
        self.assertEqual(c.chat("m", [{"role": "user", "content": "q2"}]).text, "other")
        self.assertEqual(len(rec.requests), 3)

    def test_aad_is_authenticated(self):
        blob = encrypt(b"e" * 32, b"m" * 32, b"x", b"key1")
        self.assertEqual(decrypt(b"e" * 32, b"m" * 32, blob, b"key1"), b"x")
        self.assertIsNone(decrypt(b"e" * 32, b"m" * 32, blob, b"key2"))

    def test_env_var_enables_cache(self):
        os.environ["LLM_AI_API_CACHE_DIR"] = self.dir
        rec = Recorder(json_response(REPLY))
        c = self.client(rec)
        c.chat("m", MSGS)
        c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 1)
        self.assertTrue(os.path.exists(self.db))

    def test_set_cache_none_overrides_env_var(self):
        os.environ["LLM_AI_API_CACHE_DIR"] = self.dir
        with mock.patch.object(cache_mod, "_global_cache", None):
            set_cache(None)
            rec = Recorder(json_response(REPLY))
            c = self.client(rec)
            c.chat("m", MSGS)
            c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 2)

    def test_clear_cache_by_days(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache=self.db)
        c.chat("m", MSGS)
        self.assertEqual(clear_cache(1, self.dir), 0)  # younger than 1 day
        c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(clear_cache(0, self.dir), 1)
        c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 2)

    def test_clear_cache_via_env_and_missing_dir(self):
        self.assertEqual(clear_cache(0, os.path.join(self.dir, "none")), 0)
        with self.assertRaises(LLMConfigError) as cm:
            clear_cache(1, lang="en")
        self.assertEqual(cm.exception.code, "cache_dir_not_set")
        os.environ["LLM_AI_API_CACHE_DIR"] = self.dir
        SQLiteCache(self.db).put("k", "openai", ChatResult("x", None, None, None, {}))
        self.assertEqual(clear_cache(0), 1)

    def test_plain_entries_without_secret_still_work(self):
        c = SQLiteCache(self.db)
        c.put("k", "openai", ChatResult("x", None, None, None, {}))
        self.assertEqual(c.get("k").text, "x")


if __name__ == "__main__":
    unittest.main()
