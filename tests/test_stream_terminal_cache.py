"""Regression tests from the post-merge review of the async support (#12).

- A stream whose terminal-named event carries a broken or error payload is a
  failed stream: it must not be stored in the cache (sync and async alike).
- `LLM.aclose()` closes the sync client even when it is cancelled while the
  async client is being closed.
"""

import asyncio
import gc
import os
import tempfile
import unittest

import httpx  # noqa: F401  (kept for parity with other test modules)

from llm_ai_api import APIStreamError, LLMError, SQLiteCache, llm

from .helpers import Recorder, json_response, sse_response

GOOD_STREAM = (
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"x"}}\n\n'
    'event: message_stop\n'
    'data: {"type":"message_stop"}\n\n'
)
BAD_JSON_STREAM = "event: message_stop\ndata: {invalid-json\n\n"
ERROR_STREAM = (
    'event: message_stop\n'
    'data: {"type":"error","error":{"message":"failed"}}\n\n'
)


class StreamTerminalCacheSyncTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "cache.db")

    def make(self, payload):
        rec = Recorder(sse_response(payload))
        m = llm("anthropic:claude-x", api_key="k", transport=rec.transport, cache=self.db)
        self.addCleanup(m.close)
        return rec, m

    def entries(self):
        gc.collect()  # sync generators store from finally when they are closed
        return len(SQLiteCache(self.db))

    def test_good_terminal_event_is_cached(self):
        rec, m = self.make(GOOD_STREAM)
        self.assertEqual(list(m.stream("q")), ["x"])
        self.assertEqual(self.entries(), 1)
        self.assertEqual(list(m.stream("q")), ["x"])
        self.assertEqual(len(rec.requests), 1)  # second call was a cache replay

    def test_invalid_json_terminal_is_not_cached(self):
        rec, m = self.make(BAD_JSON_STREAM)
        with self.assertRaises(LLMError):
            list(m.stream("q"))
        self.assertEqual(self.entries(), 0)

    def test_error_terminal_is_not_cached(self):
        rec, m = self.make(ERROR_STREAM)
        with self.assertRaises(APIStreamError):
            list(m.stream("q"))
        self.assertEqual(self.entries(), 0)


class StreamTerminalCacheAsyncTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "cache.db")

    def make(self, payload):
        rec = Recorder(sse_response(payload))
        return llm("anthropic:claude-x", api_key="k", transport=rec.transport, cache=self.db)

    async def test_good_terminal_event_is_cached(self):
        m = self.make(GOOD_STREAM)
        self.assertEqual([p async for p in m.astream("q")], ["x"])
        self.assertEqual(len(SQLiteCache(self.db)), 1)
        await m.aclose()

    async def test_invalid_json_terminal_is_not_cached(self):
        m = self.make(BAD_JSON_STREAM)
        with self.assertRaises(LLMError):
            [p async for p in m.astream("q")]
        self.assertEqual(len(SQLiteCache(self.db)), 0)
        await m.aclose()

    async def test_error_terminal_is_not_cached(self):
        m = self.make(ERROR_STREAM)
        with self.assertRaises(APIStreamError):
            [p async for p in m.astream("q")]
        self.assertEqual(len(SQLiteCache(self.db)), 0)
        await m.aclose()

    async def test_cancelled_aclose_still_closes_sync_client(self):
        rec = Recorder(json_response({"choices": [{"message": {"content": "x"}}]}))
        m = llm("openai:gpt-x", api_key="k", transport=rec.transport)
        self.assertEqual(await m.aask("q"), "x")  # creates the async client
        started = asyncio.Event()

        async def slow_aclose():
            started.set()
            await asyncio.sleep(3600)

        m._async_client_instance._client.aclose = slow_aclose
        task = asyncio.ensure_future(m.aclose())
        await started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(m.client._client.is_closed)


if __name__ == "__main__":
    unittest.main()
