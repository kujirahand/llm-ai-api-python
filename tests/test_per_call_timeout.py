"""Tests for the per-call `timeout` of the common interface (ask/chat/stream and async)."""

import asyncio
import os
import tempfile
import unittest

from llm_ai_api import llm

from .helpers import Recorder, json_response, sse_response

OPENAI_REPLY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
CLAUDE_REPLY = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}
OPENAI_STREAM = 'data: {"choices":[{"delta":{"content":"a"}}]}\n\ndata: [DONE]\n\n'
CLAUDE_STREAM = (
    "event: content_block_delta\n"
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"a"}}\n\n'
    "event: message_stop\n"
    'data: {"type":"message_stop"}\n\n'
)

# (spec, reply, stream)
PROVIDERS = [
    ("openai:m", OPENAI_REPLY, OPENAI_STREAM),
    ("openrouter:v/m", OPENAI_REPLY, OPENAI_STREAM),
    ("google:m", OPENAI_REPLY, OPENAI_STREAM),
    ("anthropic:m", CLAUDE_REPLY, CLAUDE_STREAM),
]


def read_timeout(request):
    """The httpx timeout that was applied to a recorded request."""
    return request.extensions["timeout"]["read"]


class PerCallTimeoutTest(unittest.TestCase):
    def make(self, spec, response, **kw):
        rec = Recorder(response)
        m = llm(spec, api_key="k", transport=rec.transport, max_retries=0, **kw)
        return m, rec

    def test_default_keeps_client_timeout(self):
        for spec, reply, stream in PROVIDERS:
            with self.subTest(spec=spec):
                m, rec = self.make(spec, json_response(reply), timeout=42.0)
                m.ask("q")
                m.chat([{"role": "user", "content": "q"}])
                self.assertEqual([read_timeout(r) for r in rec.requests], [42.0, 42.0])
                m, rec = self.make(spec, sse_response(stream), timeout=42.0)
                list(m.stream("q"))
                self.assertEqual(read_timeout(rec.requests[0]), 42.0)

    def test_sync_override(self):
        for spec, reply, stream in PROVIDERS:
            with self.subTest(spec=spec):
                m, rec = self.make(spec, json_response(reply), timeout=42.0)
                m.ask("q", timeout=3.5)
                m.chat([{"role": "user", "content": "q"}], timeout=4.5)
                self.assertEqual([read_timeout(r) for r in rec.requests], [3.5, 4.5])
                # connect timeout stays at 10 seconds (same as the raw layer)
                self.assertEqual(rec.requests[0].extensions["timeout"]["connect"], 10.0)
                m.ask("q")  # the override applies to one call only
                self.assertEqual(read_timeout(rec.requests[-1]), 42.0)
                m, rec = self.make(spec, sse_response(stream), timeout=42.0)
                self.assertEqual("".join(m.stream("q", timeout=2.5)), "a")
                self.assertEqual(read_timeout(rec.requests[0]), 2.5)

    def test_timeout_is_not_sent_in_body(self):
        for spec, reply, _ in PROVIDERS:
            with self.subTest(spec=spec):
                m, rec = self.make(spec, json_response(reply))
                m.ask("q", timeout=3.0)
                self.assertNotIn("timeout", rec.body())

    def test_async_default_and_override(self):
        for spec, reply, stream in PROVIDERS:
            with self.subTest(spec=spec):

                async def run():
                    m, rec = self.make(spec, json_response(reply), timeout=42.0)
                    async with m:
                        await m.aask("q")
                        await m.achat([{"role": "user", "content": "q"}], timeout=4.5)
                        await m.aask("q", timeout=3.5)
                    self.assertEqual(
                        [read_timeout(r) for r in rec.requests], [42.0, 4.5, 3.5]
                    )
                    m, rec = self.make(spec, sse_response(stream), timeout=42.0)
                    async with m:
                        self.assertEqual(
                            "".join([p async for p in m.astream("q", timeout=2.5)]), "a"
                        )
                    self.assertEqual(read_timeout(rec.requests[0]), 2.5)
                    m, rec = self.make(spec, sse_response(stream), timeout=42.0)
                    async with m:
                        [p async for p in m.astream("q")]
                    self.assertEqual(read_timeout(rec.requests[0]), 42.0)
                    self.assertNotIn("timeout", rec.body())

                asyncio.run(run())

    def test_cache_ignores_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.db")
            m, rec = self.make("openai:m", json_response(OPENAI_REPLY), cache=path)
            m.ask("q", timeout=1.0)
            self.assertEqual(m.ask("q", timeout=9.0), "ok")  # same key: served from cache
            self.assertEqual(len(rec.requests), 1)
            m, rec = self.make("openai:m", sse_response(OPENAI_STREAM), cache=path)
            list(m.stream("q", timeout=1.0))
            list(m.stream("q", timeout=9.0))
            self.assertEqual(len(rec.requests), 1)

    def test_async_cache_ignores_timeout(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.db")
            msgs = [{"role": "user", "content": "q2"}]

            async def run():
                m, rec = self.make("openai:m", json_response(OPENAI_REPLY), cache=path)
                async with m:
                    first = await m.aask("q", timeout=1.0)
                    second = await m.aask("q", timeout=9.0)
                    third = (await m.achat(msgs, timeout=1.0)).text
                    fourth = (await m.achat(msgs, timeout=9.0)).text
                self.assertEqual(first, second)
                self.assertEqual(third, fourth)
                self.assertEqual(len(rec.requests), 2)  # one per distinct prompt

                m, rec = self.make("openai:m", sse_response(OPENAI_STREAM), cache=path)
                async with m:
                    a = [p async for p in m.astream("s", timeout=1.0)]
                    self.assertEqual(len(rec.requests), 1)  # populated the cache
                    b = [p async for p in m.astream("s", timeout=9.0)]
                self.assertEqual(a, b)
                self.assertEqual(len(rec.requests), 1)  # replayed, no new request

            asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
