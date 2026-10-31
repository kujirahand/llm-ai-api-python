import unittest

from llm_ai_api import APIStreamError, llm
from .helpers import Recorder
from .test_events import sse


class IncompleteStreamTest(unittest.TestCase):
    def test_sync_providers(self):
        for provider, payload in (
            ("openai", 'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'),
            ("anthropic", 'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"x"}}\n\n'),
        ):
            with self.subTest(provider=provider):
                rec = Recorder(sse(payload, "req"))
                m = llm(provider + ":model", api_key="k", lang="ja", transport=rec.transport, cache=False, log=False)
                self.addCleanup(m.close)
                seen = []
                m.add_event_listener(None, lambda event, data: seen.append((event, data)))
                stream = m.ask_stream("q")
                self.assertEqual(next(stream), "x")
                with self.assertRaises(APIStreamError) as raised:
                    next(stream)
                error = raised.exception
                self.assertEqual((error.code, error.provider, error.request_id, error.retries), ("stream_incomplete", provider, "req", 0))
                self.assertIsNotNone(error.latency)
                self.assertIn("終端", str(error))
                self.assertEqual([e for e, _ in seen], ["response", "stream_error"])
                self.assertEqual(seen[-1][1]["code"], error.code)


class AsyncIncompleteStreamTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_providers(self):
        for provider, payload in (
            ("openai", 'data: {"choices":[{"delta":{"content":"x"}}]}\n\n'),
            ("anthropic", 'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"x"}}\n\n'),
        ):
            with self.subTest(provider=provider):
                rec = Recorder(sse(payload, "req"))
                m = llm(provider + ":model", api_key="k", lang="en", transport=rec.transport, cache=False, log=False)
                seen = []
                m.add_event_listener(None, lambda event, data: seen.append((event, data)))
                stream = m.aask_stream("q")
                self.assertEqual(await stream.__anext__(), "x")
                with self.assertRaises(APIStreamError) as raised:
                    await stream.__anext__()
                error = raised.exception
                self.assertEqual((error.code, error.provider, error.request_id, error.retries), ("stream_incomplete", provider, "req", 0))
                self.assertIsNotNone(error.latency)
                self.assertIn("terminal", str(error))
                self.assertEqual([e for e, _ in seen], ["response", "stream_error"])
                self.assertEqual(seen[-1][1]["code"], error.code)
                await m.aclose()
