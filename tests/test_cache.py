import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from llm_ai_api import LLMConfigError, OpenAIClient, clear_cache
from llm_ai_api.cache import decrypt, encrypt

from helpers import Recorder, json_response, sse_response

REPLY = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}
MSGS = [{"role": "user", "content": "q"}]
STREAM = (
    'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
    "data: [DONE]\n\n"
)


class CacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name

    def client(self, rec, **kw):
        return OpenAIClient(api_key="k", transport=rec.transport, **kw)

    def test_disabled_by_default(self):
        rec = Recorder(json_response(REPLY))
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_AI_API_CACHE_DIR", None)
            c = self.client(rec)
            c.chat("m", MSGS)
            c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 2)

    def test_second_call_is_served_from_cache(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache_dir=self.dir)
        self.assertEqual(c.chat("m", MSGS).text, "hi")
        self.assertEqual(c.chat("m", MSGS).text, "hi")
        self.assertEqual(len(rec.requests), 1)

    def test_env_var(self):
        rec = Recorder(json_response(REPLY))
        with mock.patch.dict(os.environ, {"LLM_AI_API_CACHE_DIR": self.dir}):
            c = self.client(rec)
            c.chat("m", MSGS)
            c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 1)

    def test_different_request_misses(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache_dir=self.dir)
        c.chat("m", MSGS)
        c.chat("m", [{"role": "user", "content": "other"}])
        c.chat("m2", MSGS)
        self.assertEqual(len(rec.requests), 3)

    def test_errors_are_not_cached(self):
        rec = Recorder(json_response({"error": {"message": "x"}}, status=400), json_response(REPLY))
        c = self.client(rec, cache_dir=self.dir)
        with self.assertRaises(Exception):
            c.chat("m", MSGS)
        self.assertEqual(c.chat("m", MSGS).text, "hi")

    def test_corrupt_db_is_a_miss(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache_dir=self.dir)
        c.chat("m", MSGS)
        with open(os.path.join(self.dir, "cache.db"), "wb") as f:
            f.write(b"not a database")
        self.assertEqual(c.chat("m", MSGS).text, "hi")
        self.assertEqual(len(rec.requests), 2)

    def test_tampered_value_is_a_miss(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache_dir=self.dir)
        c.chat("m", MSGS)
        db = sqlite3.connect(os.path.join(self.dir, "cache.db"))
        blob = bytearray(db.execute("SELECT value FROM cache").fetchone()[0])
        blob[20] ^= 1
        db.execute("UPDATE cache SET value = ?", (bytes(blob),))
        db.commit()
        db.close()
        c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 2)

    def test_params_are_part_of_the_key(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache_dir=self.dir)
        c.chat("m", MSGS)
        c.chat("m", MSGS, temperature=0.5)
        self.assertEqual(len(rec.requests), 2)

    def test_stored_data_is_encrypted(self):
        rec = Recorder(json_response(REPLY))
        self.client(rec, cache_dir=self.dir).chat("m", MSGS)
        with open(os.path.join(self.dir, "cache.db"), "rb") as f:
            raw = f.read()
        self.assertNotIn(b"finish_reason", raw)
        self.assertNotIn(b"stop", raw.replace(b"stop_", b""))

    def test_clear_cache(self):
        rec = Recorder(json_response(REPLY))
        c = self.client(rec, cache_dir=self.dir)
        c.chat("m", MSGS)
        self.assertEqual(clear_cache(1, self.dir), 0)  # younger than 1 day
        c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(clear_cache(0, self.dir), 1)
        c.chat("m", MSGS)
        self.assertEqual(len(rec.requests), 2)

    def test_clear_cache_needs_dir(self):
        with mock.patch.dict(os.environ, {}):
            os.environ.pop("LLM_AI_API_CACHE_DIR", None)
            with self.assertRaises(LLMConfigError) as cm:
                clear_cache(1, lang="en")
        self.assertEqual(cm.exception.code, "cache_dir_not_set")

    def test_stream_is_cached_after_full_read(self):
        rec = Recorder(sse_response(STREAM))
        c = self.client(rec, cache_dir=self.dir)
        first = "".join(ch.text for ch in c.stream_chat("m", MSGS))
        second = "".join(ch.text for ch in c.stream_chat("m", MSGS))
        self.assertEqual((first, second), ("hello", "hello"))
        self.assertEqual(len(rec.requests), 1)

    def test_partial_stream_is_not_cached(self):
        rec = Recorder(sse_response(STREAM))
        c = self.client(rec, cache_dir=self.dir)
        it = c.stream_chat("m", MSGS)
        next(it)
        it.close()
        list(c.stream_chat("m", MSGS))
        self.assertEqual(len(rec.requests), 2)

    def test_other_api_key_does_not_share_entries(self):
        rec = Recorder(json_response(REPLY))
        self.client(rec, cache_dir=self.dir).chat("m", MSGS)
        rec2 = Recorder(json_response(REPLY))
        OpenAIClient(api_key="other", transport=rec2.transport, cache_dir=self.dir).chat("m", MSGS)
        self.assertEqual(len(rec2.requests), 1)

    def test_cipher_roundtrip(self):
        blob = encrypt(b"e" * 32, b"m" * 32, b"hello" * 100)
        self.assertEqual(decrypt(b"e" * 32, b"m" * 32, blob), b"hello" * 100)
        self.assertIsNone(decrypt(b"e" * 32, b"x" * 32, blob))


if __name__ == "__main__":
    unittest.main()
