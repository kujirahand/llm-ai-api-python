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

    def test_key_format(self):
        import hashlib
        import json

        body = {"model": "m", "messages": MSGS}
        canonical = json.dumps(
            {"body": body, "context": {}}, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        want = hashlib.sha256(("openai:m@KEY>>>" + canonical).encode()).hexdigest()
        self.assertEqual(cache_key("openai", body, None, "KEY"), want)
        self.assertNotEqual(cache_key("openai", body, None, "OTHER"), want)

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
