"""Optional cache and reasoning token fields on Usage (#127)."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from llm_ai_api import AnthropicClient, ChatResult, OpenAIClient, SQLiteCache, Usage, llm
from llm_ai_api.cache import _NO_KEY_SECRET, _PLAIN, decrypt
from llm_ai_api.types import _optional_int

from .helpers import FreshRecorder, json_response

MSGS = [{"role": "user", "content": "q"}]


def openai_reply(**usage_extra):
    usage = {"prompt_tokens": 9, "completion_tokens": 3}
    usage.update(usage_extra)
    return {
        "model": "m",
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": usage,
    }


def anthropic_reply(**usage_extra):
    usage = {"input_tokens": 9, "output_tokens": 3}
    usage.update(usage_extra)
    return {
        "model": "m",
        "content": [{"type": "text", "text": "ok"}],
        "stop_reason": "end_turn",
        "usage": usage,
    }


class OptionalIntTest(unittest.TestCase):
    def test_optional_int(self):
        self.assertEqual(_optional_int(0), 0)
        self.assertEqual(_optional_int(4), 4)
        self.assertIsNone(_optional_int(None))
        self.assertIsNone(_optional_int(True))
        self.assertIsNone(_optional_int(False))
        self.assertIsNone(_optional_int("4"))
        self.assertIsNone(_optional_int(4.0))
        self.assertIsNone(_optional_int({"cached_tokens": 1}))


class UsageConstructionTest(unittest.TestCase):
    def test_two_argument_construction(self):
        usage = Usage(3, 4)
        self.assertEqual(usage.input_tokens, 3)
        self.assertEqual(usage.output_tokens, 4)
        self.assertIsNone(usage.cache_read_tokens)
        self.assertIsNone(usage.cache_creation_tokens)
        self.assertIsNone(usage.reasoning_tokens)
        self.assertEqual(usage, Usage(3, 4))


class OpenAIUsageDetailsTest(unittest.TestCase):
    def _chat(self, reply):
        rec = FreshRecorder(lambda: json_response(reply))
        client = OpenAIClient(api_key="k", transport=rec.transport)
        return client.chat("m", MSGS)

    def test_omitted_details_are_none(self):
        usage = self._chat(openai_reply()).usage
        self.assertEqual((usage.input_tokens, usage.output_tokens), (9, 3))
        self.assertIsNone(usage.cache_read_tokens)
        self.assertIsNone(usage.cache_creation_tokens)
        self.assertIsNone(usage.reasoning_tokens)

    def test_explicit_zero_and_partial_details(self):
        usage = self._chat(
            openai_reply(
                prompt_tokens_details={"cached_tokens": 0},
                completion_tokens_details={"reasoning_tokens": 2},
            )
        ).usage
        self.assertEqual(usage.cache_read_tokens, 0)
        self.assertIsNone(usage.cache_creation_tokens)
        self.assertEqual(usage.reasoning_tokens, 2)
        self.assertEqual((usage.input_tokens, usage.output_tokens), (9, 3))

    def test_unexpected_detail_types_are_none(self):
        usage = self._chat(
            openai_reply(
                prompt_tokens_details=["cached"],
                completion_tokens_details={"reasoning_tokens": "2"},
            )
        ).usage
        self.assertIsNone(usage.cache_read_tokens)
        self.assertIsNone(usage.reasoning_tokens)
        self.assertEqual((usage.input_tokens, usage.output_tokens), (9, 3))


class AnthropicUsageDetailsTest(unittest.TestCase):
    def _chat(self, reply):
        rec = FreshRecorder(lambda: json_response(reply))
        client = AnthropicClient(api_key="k", transport=rec.transport)
        return client.chat("m", MSGS)

    def test_omitted_details_are_none(self):
        usage = self._chat(anthropic_reply()).usage
        self.assertEqual((usage.input_tokens, usage.output_tokens), (9, 3))
        self.assertIsNone(usage.cache_read_tokens)
        self.assertIsNone(usage.cache_creation_tokens)
        self.assertIsNone(usage.reasoning_tokens)

    def test_explicit_zero_and_partial_details(self):
        usage = self._chat(
            anthropic_reply(cache_read_input_tokens=4, cache_creation_input_tokens=0)
        ).usage
        self.assertEqual(usage.cache_read_tokens, 4)
        self.assertEqual(usage.cache_creation_tokens, 0)
        self.assertIsNone(usage.reasoning_tokens)

    def test_unexpected_detail_types_are_none(self):
        usage = self._chat(
            anthropic_reply(cache_read_input_tokens="4", cache_creation_input_tokens=True)
        ).usage
        self.assertIsNone(usage.cache_read_tokens)
        self.assertIsNone(usage.cache_creation_tokens)


class UsageDetailsInterfaceTest(unittest.IsolatedAsyncioTestCase):
    async def test_sync_and_async_llm(self):
        reply = openai_reply(
            prompt_tokens_details={"cached_tokens": 5},
            completion_tokens_details={"reasoning_tokens": 1},
        )
        rec = FreshRecorder(lambda: json_response(reply))
        client = llm("openai:m", api_key="k", transport=rec.transport)
        sync = client.chat(MSGS)
        self.assertEqual(sync.usage.cache_read_tokens, 5)
        self.assertEqual(sync.usage.reasoning_tokens, 1)
        async_result = await client.achat(MSGS)
        self.assertEqual(async_result.usage.cache_read_tokens, 5)
        self.assertEqual(async_result.usage.reasoning_tokens, 1)
        await client.aclose()


class UsageDetailsCacheTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = os.path.join(tmp.name, "cache.db")

    def test_new_row_roundtrip_and_old_row_defaults(self):
        cache = SQLiteCache(self.db)
        result = ChatResult(
            text="ok",
            model="m",
            usage=Usage(9, 3, cache_read_tokens=5, cache_creation_tokens=0, reasoning_tokens=1),
            raw={"usage": {"prompt_tokens": 9}},
        )
        cache.put("new", "openai", result)
        got = cache.get("new")
        self.assertEqual(
            got.usage,
            Usage(9, 3, cache_read_tokens=5, cache_creation_tokens=0, reasoning_tokens=1),
        )

        # Optional keys are omitted when they are None, and still load as None.
        cache.put("plain", "openai", ChatResult(text="plain", usage=Usage(1, 2), raw={}))
        conn = sqlite3.connect(self.db)
        blob = conn.execute("SELECT response FROM llm_cache WHERE key = ?", ("plain",)).fetchone()[0]
        # Without a secret the value is encrypted with the default secret.
        stored = json.loads(decrypt(*cache._derive(_NO_KEY_SECRET), blob[1:], b"plain").decode("utf-8"))
        self.assertEqual(stored["usage"], {"input_tokens": 1, "output_tokens": 2})
        conn.close()
        self.assertEqual(cache.get("plain").usage, Usage(1, 2))

        old = json.dumps(
            {
                "text": "old",
                "model": "m",
                "stop_reason": "stop",
                "usage": {"input_tokens": 3, "output_tokens": 4},
                "raw": {},
            }
        ).encode("utf-8")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO llm_cache (key, provider, model, response, created_at) VALUES (?, ?, ?, ?, ?)",
            ("old", "openai", "m", _PLAIN + old, 1.0),
        )
        conn.commit()
        conn.close()
        loaded = cache.get("old")
        self.assertEqual(loaded.usage, Usage(3, 4))
        self.assertIsNone(loaded.usage.cache_read_tokens)
        self.assertIsNone(loaded.usage.cache_creation_tokens)
        self.assertIsNone(loaded.usage.reasoning_tokens)
