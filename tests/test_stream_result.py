"""Tests for #136: `stream.result` holds a `ChatResult` once a stream is read to its end.

- Sync and async, OpenAI-style and Anthropic, through `llm()` and the provider layer.
- `result` is None before the terminal event, after an error, and after an early close.
- Usage is taken from the stream (OpenAI: the last one; Anthropic: merged field by field).
- A cache replay also gives a result (with `latency=None`).
"""

import asyncio
import json
import os
import tempfile
import unittest

from llm_ai_api import APIStreamError, AnthropicClient, ChatResult, OpenAIClient, Usage, llm
from llm_ai_api.openai import _OpenAIStreamResult
from llm_ai_api.types import ChatChunk

from .helpers import Recorder, sse_response


def sse(*events):
    return "".join("data: %s\n\n" % (e if isinstance(e, str) else json.dumps(e)) for e in events)


def anthropic_sse(*events):
    return "".join("event: %s\ndata: %s\n\n" % (e["type"], json.dumps(e)) for e in events)


OPENAI_USAGE = {
    "prompt_tokens": 7,
    "completion_tokens": 3,
    "prompt_tokens_details": {"cached_tokens": 2},
    "completion_tokens_details": {"reasoning_tokens": 1},
}
OPENAI_EVENTS = [
    {"model": "gpt-x-1", "choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]},
    {"model": "gpt-x-1", "choices": [{"delta": {"content": "Hel"}, "finish_reason": None}]},
    {"model": "gpt-x-1", "choices": [{"delta": {"content": "lo"}, "finish_reason": None}]},
    {"model": "gpt-x-1", "choices": [{"delta": {}, "finish_reason": "stop"}]},
    {"model": "gpt-x-1", "choices": [], "usage": OPENAI_USAGE},
]
OPENAI_STREAM = sse(*OPENAI_EVENTS, "[DONE]")

ANTHROPIC_EVENTS = [
    {
        "type": "message_start",
        "message": {
            "model": "claude-x-1",
            "usage": {
                "input_tokens": 11,
                "output_tokens": 1,
                "cache_read_input_tokens": 4,
                "cache_creation_input_tokens": 5,
            },
        },
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "ping"},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 9}},
]
ANTHROPIC_STREAM = anthropic_sse(*ANTHROPIC_EVENTS, {"type": "message_stop"})
# Every non-terminal event is recorded in `raw["events"]`, including `ping`
# (which the parser skips as a chunk). Only `message_stop` is left out.
ANTHROPIC_RECORDED = ANTHROPIC_EVENTS

HEADERS = {"x-request-id": "req-1", "content-type": "text/event-stream"}


def response(text, headers=None):
    r = sse_response(text)
    r.headers.update(headers or {})
    return r


def openai_llm(rec, **kw):
    return llm("openai:gpt-x", api_key="k", transport=rec.transport, **kw)


def anthropic_llm(rec, **kw):
    return llm("anthropic:claude-x", api_key="k", transport=rec.transport, **kw)


class OpenAIResultMixin:
    def check(self, result):
        self.assertIsInstance(result, ChatResult)
        self.assertEqual(result.text, "Hello")
        self.assertEqual(result.model, "gpt-x-1")
        self.assertEqual(result.stop_reason, "stop")
        self.assertEqual(
            result.usage,
            Usage(7, 3, cache_read_tokens=2, reasoning_tokens=1),
        )
        self.assertEqual(result.raw, {"events": OPENAI_EVENTS})


class SyncOpenAITest(OpenAIResultMixin, unittest.TestCase):
    def test_llm_chat_stream(self):
        rec = Recorder(response(OPENAI_STREAM, {"x-request-id": "req-1"}))
        with openai_llm(rec) as m:
            stream = m.chat_stream([{"role": "user", "content": "hi"}])
            self.assertIsNone(stream.result)
            self.assertEqual("".join(stream), "Hello")
            self.check(stream.result)
            self.assertEqual(stream.result.request_id, "req-1")
            self.assertEqual(stream.result.retries, 0)
            self.assertIsNotNone(stream.result.latency)
            self.assertIs(stream.result, stream.result)

    def test_ask_stream(self):
        rec = Recorder(response(OPENAI_STREAM))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            list(stream)
            self.check(stream.result)

    def test_over_limit_still_delivers_chunks_but_no_result(self):
        from unittest import mock

        from llm_ai_api._http import _StreamAccumulator

        rec = Recorder(response(OPENAI_STREAM))
        with mock.patch.object(_StreamAccumulator, "max_retained_bytes", 10):
            with openai_llm(rec) as m:
                stream = m.ask_stream("hi")
                self.assertEqual("".join(stream), "Hello")
                self.assertIsNone(stream.result)

    def test_provider_layer(self):
        rec = Recorder(response(OPENAI_STREAM))
        client = OpenAIClient(api_key="k", transport=rec.transport)
        self.addCleanup(client.close)
        stream = client.stream_chat("gpt-x", [{"role": "user", "content": "hi"}])
        self.assertIsNone(stream.result)
        list(stream)
        self.check(stream.result)

    def test_none_before_the_end(self):
        rec = Recorder(response(OPENAI_STREAM))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            next(stream)
            self.assertIsNone(stream.result)

    def test_none_when_closed_early(self):
        rec = Recorder(response(OPENAI_STREAM))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            next(stream)
            stream.close()
            self.assertIsNone(stream.result)

    def test_none_on_error(self):
        text = sse(OPENAI_EVENTS[1], {"error": {"message": "boom"}})
        rec = Recorder(response(text))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            with self.assertRaises(APIStreamError):
                list(stream)
            self.assertIsNone(stream.result)

    def test_none_when_the_stream_is_cut_off(self):
        rec = Recorder(response(sse(OPENAI_EVENTS[1])))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            with self.assertRaises(APIStreamError):
                list(stream)
            self.assertIsNone(stream.result)

    def test_no_usage_is_none(self):
        events = OPENAI_EVENTS[:4]
        rec = Recorder(response(sse(*events, "[DONE]")))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            list(stream)
            self.assertEqual(stream.result.text, "Hello")
            self.assertIsNone(stream.result.usage)

    def test_stop_reason_max_tokens(self):
        events = [
            {"model": "gpt-x-1", "choices": [{"delta": {"content": "Hi"}, "finish_reason": None}]},
            {"model": "gpt-x-1", "choices": [{"delta": {}, "finish_reason": "length"}]},
        ]
        rec = Recorder(response(sse(*events, "[DONE]")))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi", max_tokens=1)
            list(stream)
            self.assertEqual(stream.result.stop_reason, "length")

    def test_stop_reason_none_when_never_sent(self):
        events = [{"model": "gpt-x-1", "choices": [{"delta": {"content": "Hi"}}]}]
        rec = Recorder(response(sse(*events, "[DONE]")))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            list(stream)
            self.assertIsNone(stream.result.stop_reason)

    def test_the_last_usage_wins(self):
        events = [
            {"model": "gpt-x-1", "choices": [{"delta": {"content": "Hi"}, "finish_reason": None}],
             "usage": {"prompt_tokens": 1, "completion_tokens": 1}},
            {"model": "gpt-x-1", "choices": [{"delta": {}, "finish_reason": "stop"}],
             "usage": {"prompt_tokens": 7, "completion_tokens": 3}},
        ]
        rec = Recorder(response(sse(*events, "[DONE]")))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            list(stream)
            self.assertEqual(stream.result.usage, Usage(7, 3))

    def test_terminal_only_stream_has_an_empty_result(self):
        rec = Recorder(response(sse("[DONE]")))
        with openai_llm(rec) as m:
            stream = m.ask_stream("hi")
            self.assertEqual(list(stream), [])
            self.assertIsNotNone(stream.result)
            self.assertEqual(stream.result.text, "")
            self.assertIsNone(stream.result.usage)


class SyncAnthropicTest(unittest.TestCase):
    def check(self, result):
        self.assertIsInstance(result, ChatResult)
        self.assertEqual(result.text, "Hello")
        self.assertEqual(result.model, "claude-x-1")
        self.assertEqual(result.stop_reason, "end_turn")
        # message_start gives input and cache values; message_delta overrides the output.
        self.assertEqual(
            result.usage,
            Usage(11, 9, cache_read_tokens=4, cache_creation_tokens=5),
        )
        self.assertEqual(result.raw, {"events": ANTHROPIC_RECORDED})

    def test_llm_chat_stream(self):
        rec = Recorder(response(ANTHROPIC_STREAM, {"request-id": "req-a"}))
        with anthropic_llm(rec) as m:
            stream = m.chat_stream([{"role": "user", "content": "hi"}])
            self.assertIsNone(stream.result)
            self.assertEqual("".join(stream), "Hello")
            self.check(stream.result)
            self.assertEqual(stream.result.request_id, "req-a")

    def test_provider_layer(self):
        rec = Recorder(response(ANTHROPIC_STREAM))
        client = AnthropicClient(api_key="k", transport=rec.transport)
        self.addCleanup(client.close)
        stream = client.stream_chat("claude-x", [{"role": "user", "content": "hi"}])
        self.assertIsNone(stream.result)
        list(stream)
        self.check(stream.result)

    def test_none_before_the_end_and_after_close(self):
        rec = Recorder(response(ANTHROPIC_STREAM))
        with anthropic_llm(rec) as m:
            stream = m.ask_stream("hi")
            next(stream)
            self.assertIsNone(stream.result)
            stream.close()
            self.assertIsNone(stream.result)

    def test_none_on_error(self):
        text = anthropic_sse(
            ANTHROPIC_EVENTS[0], {"type": "error", "error": {"message": "overloaded"}}
        )
        rec = Recorder(response(text))
        with anthropic_llm(rec) as m:
            stream = m.ask_stream("hi")
            with self.assertRaises(APIStreamError):
                list(stream)
            self.assertIsNone(stream.result)

    def test_no_usage_is_none(self):
        events = [
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
        ]
        rec = Recorder(response(anthropic_sse(*events, {"type": "message_stop"})))
        with anthropic_llm(rec) as m:
            stream = m.ask_stream("hi")
            list(stream)
            self.assertEqual(stream.result.text, "Hi")
            self.assertIsNone(stream.result.usage)

    def test_stop_reason_max_tokens(self):
        events = [
            ANTHROPIC_EVENTS[0],
            {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hi"}},
            {
                "type": "message_delta",
                "delta": {"stop_reason": "max_tokens"},
                "usage": {"output_tokens": 1},
            },
        ]
        rec = Recorder(response(anthropic_sse(*events, {"type": "message_stop"})))
        with anthropic_llm(rec) as m:
            stream = m.ask_stream("hi", max_tokens=1)
            list(stream)
            self.assertEqual(stream.result.stop_reason, "max_tokens")
            self.assertEqual(stream.result.usage.output_tokens, 1)


class AsyncOpenAITest(OpenAIResultMixin, unittest.TestCase):
    def test_llm_achat_stream(self):
        async def run():
            rec = Recorder(response(OPENAI_STREAM, {"x-request-id": "req-1"}))
            async with openai_llm(rec) as m:
                stream = m.achat_stream([{"role": "user", "content": "hi"}])
                self.assertIsNone(stream.result)
                pieces = [p async for p in stream]
                self.assertEqual("".join(pieces), "Hello")
                self.check(stream.result)
                self.assertEqual(stream.result.request_id, "req-1")
                self.assertIsNotNone(stream.result.latency)
                self.assertIs(stream.result, stream.result)

        asyncio.run(run())

    def test_aask_stream(self):
        async def run():
            rec = Recorder(response(OPENAI_STREAM))
            async with openai_llm(rec) as m:
                stream = m.aask_stream("hi")
                async for _ in stream:
                    pass
                self.check(stream.result)

        asyncio.run(run())

    def test_none_before_the_end_and_after_aclose(self):
        async def run():
            rec = Recorder(response(OPENAI_STREAM))
            async with openai_llm(rec) as m:
                stream = m.aask_stream("hi")
                await stream.__anext__()
                self.assertIsNone(stream.result)
                await stream.aclose()
                self.assertIsNone(stream.result)

        asyncio.run(run())

    def test_none_on_error(self):
        async def run():
            text = sse(OPENAI_EVENTS[1], {"error": {"message": "boom"}})
            rec = Recorder(response(text))
            async with openai_llm(rec) as m:
                stream = m.aask_stream("hi")
                with self.assertRaises(APIStreamError):
                    async for _ in stream:
                        pass
                self.assertIsNone(stream.result)

        asyncio.run(run())

    def test_no_usage_is_none(self):
        async def run():
            rec = Recorder(response(sse(*OPENAI_EVENTS[:4], "[DONE]")))
            async with openai_llm(rec) as m:
                stream = m.aask_stream("hi")
                async for _ in stream:
                    pass
                self.assertEqual(stream.result.text, "Hello")
                self.assertIsNone(stream.result.usage)

        asyncio.run(run())


class AsyncAnthropicTest(unittest.TestCase):
    def test_achat_stream(self):
        async def run():
            rec = Recorder(response(ANTHROPIC_STREAM, {"request-id": "req-a"}))
            async with anthropic_llm(rec) as m:
                stream = m.achat_stream([{"role": "user", "content": "hi"}])
                self.assertIsNone(stream.result)
                async for _ in stream:
                    pass
                result = stream.result
                self.assertEqual(result.text, "Hello")
                self.assertEqual(result.model, "claude-x-1")
                self.assertEqual(result.stop_reason, "end_turn")
                self.assertEqual(
                    result.usage, Usage(11, 9, cache_read_tokens=4, cache_creation_tokens=5)
                )
                self.assertEqual(result.raw, {"events": ANTHROPIC_RECORDED})
                self.assertEqual(result.request_id, "req-a")

        asyncio.run(run())

    def test_none_on_error(self):
        async def run():
            text = anthropic_sse(
                ANTHROPIC_EVENTS[0], {"type": "error", "error": {"message": "overloaded"}}
            )
            rec = Recorder(response(text))
            async with anthropic_llm(rec) as m:
                stream = m.aask_stream("hi")
                with self.assertRaises(APIStreamError):
                    async for _ in stream:
                        pass
                self.assertIsNone(stream.result)

        asyncio.run(run())

    def test_none_after_aclose(self):
        async def run():
            rec = Recorder(response(ANTHROPIC_STREAM))
            async with anthropic_llm(rec) as m:
                stream = m.aask_stream("hi")
                self.assertEqual(await stream.__anext__(), "Hel")
                await stream.aclose()
                self.assertIsNone(stream.result)

        asyncio.run(run())


class CacheReplayTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.db = os.path.join(self.dir.name, "cache.db")

    def test_sync_replay_has_result_without_latency(self):
        rec = Recorder(response(OPENAI_STREAM, {"x-request-id": "req-1"}))
        with openai_llm(rec, cache=self.db) as m:
            live = m.ask_stream("hi")
            list(live)
            self.assertIsNotNone(live.result.latency)
        with openai_llm(rec, cache=self.db) as m:
            replay = m.ask_stream("hi")
            self.assertEqual("".join(replay), "Hello")
        self.assertEqual(len(rec.requests), 1)
        result = replay.result
        self.assertEqual(result.text, "Hello")
        self.assertEqual(result.stop_reason, "stop")
        self.assertEqual(result.usage, live.result.usage)
        self.assertEqual(result.raw, live.result.raw)
        self.assertIsNone(result.latency)

    def test_async_replay_has_result_without_latency(self):
        async def run():
            rec = Recorder(response(ANTHROPIC_STREAM))
            async with anthropic_llm(rec, cache=self.db) as m:
                live = m.aask_stream("hi")
                async for _ in live:
                    pass
            async with anthropic_llm(rec, cache=self.db) as m:
                replay = m.aask_stream("hi")
                async for _ in replay:
                    pass
            self.assertEqual(len(rec.requests), 1)
            self.assertEqual(replay.result.text, "Hello")
            self.assertEqual(replay.result.usage, live.result.usage)
            self.assertEqual(replay.result.raw, live.result.raw)
            self.assertIsNone(replay.result.latency)

        asyncio.run(run())


class AccumulatorLimitTests(unittest.TestCase):
    def feed(self, acc, pieces):
        for piece in pieces:
            acc.add(ChatChunk(text=piece, raw={"choices": [{"delta": {"content": piece}}]}))
        acc.complete()

    def test_under_limit_builds_result(self):
        acc = _OpenAIStreamResult()
        self.feed(acc, ["Hel", "lo"])
        result = acc.build(None, 0)
        self.assertEqual(result.text, "Hello")
        self.assertEqual(len(result.raw["events"]), 2)

    def test_over_limit_gives_no_result(self):
        acc = _OpenAIStreamResult()
        acc.max_retained_bytes = 100
        self.feed(acc, ["x" * 60, "y" * 60])
        self.assertIsNone(acc.build(None, 0))
        self.assertEqual(acc._texts, [])
        self.assertEqual(acc._events, [])

    def test_multibyte_text_is_counted_in_utf8_bytes(self):
        acc = _OpenAIStreamResult()
        acc.max_retained_bytes = 200
        self.feed(acc, ["あ" * 40])  # 120 bytes of text plus the event JSON
        self.assertIsNone(acc.build(None, 0))


if __name__ == "__main__":
    unittest.main()
