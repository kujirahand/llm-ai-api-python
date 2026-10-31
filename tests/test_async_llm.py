"""Tests for the public async API: LLM.aask() / achat() / aask_stream() / achat_stream() / aclose()."""

import asyncio
import json
import os
import tempfile
import unittest

import httpx

from llm_ai_api import (
    LLM,
    APIConnectionError,
    APIStreamError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    ChatResult,
    InternalServerError,
    NotFoundError,
    SQLiteCache,
    llm,
    set_cache,
    set_log,
)

from .helpers import (
    AsyncFailingStream,
    BlockingAsyncStream,
    FreshRecorder,
    Recorder,
    json_response,
    sse_response,
)

OPENAI_REPLY = {
    "choices": [{"message": {"content": "ポチ"}, "finish_reason": "stop"}],
    "model": "gpt-x",
}
CLAUDE_REPLY = {"content": [{"type": "text", "text": "ポチ"}], "stop_reason": "end_turn"}
OPENAI_STREAM = (
    'data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'
    'data: {"choices":[],"usage":{}}\n\n'
    'data: {"choices":[{"delta":{"content":"チ"}}]}\n\n'
    "data: [DONE]\n\n"
)
CLAUDE_STREAM = (
    "event: message_start\n"
    'data: {"type":"message_start","message":{}}\n\n'
    "event: ping\n"
    'data: {"type":"ping"}\n\n'
    "event: content_block_delta\n"
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ポ"}}\n\n'
    "event: content_block_delta\n"
    'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"チ"}}\n\n'
    "event: message_stop\n"
    'data: {"type":"message_stop"}\n\n'
)

# (spec, reply, url, auth header, auth value)
PROVIDERS = [
    ("openai:gpt-x", OPENAI_REPLY,
     "https://api.openai.com/v1/chat/completions", "authorization", "Bearer k"),
    ("openrouter:meta/llama:free", OPENAI_REPLY,
     "https://openrouter.ai/api/v1/chat/completions", "authorization", "Bearer k"),
    ("google:gemini-x", OPENAI_REPLY,
     "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
     "authorization", "Bearer k"),
    ("anthropic:claude-x", CLAUDE_REPLY,
     "https://api.anthropic.com/v1/messages", "x-api-key", "k"),
    ("claude:claude-x", CLAUDE_REPLY,
     "https://api.anthropic.com/v1/messages", "x-api-key", "k"),
]


class AsyncLLMTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.db = os.path.join(self.dir, "cache.db")
        self.log_path = os.path.join(self.dir, "log.jsonl")

    def make(self, rec, spec="openai:gpt-x", **kw):
        m = llm(spec, api_key="k", transport=rec.transport, **kw)
        self.addAsyncCleanup(m.aclose)
        return m

    def records(self):
        with open(self.log_path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]


class AsyncLLMBasicsTest(AsyncLLMTestBase):
    async def test_aask_all_providers_match_sync(self):
        for spec, reply, url, header, value in PROVIDERS:
            with self.subTest(spec=spec):
                rec = FreshRecorder(lambda reply=reply: json_response(reply))
                m = self.make(rec, spec, system="S", max_tokens=7)
                self.assertEqual(await m.aask("可愛い犬の名前を考えて"), "ポチ")
                self.assertEqual(m.ask("可愛い犬の名前を考えて"), "ポチ")
                async_req, sync_req = rec.requests
                self.assertEqual(str(async_req.url), url)
                self.assertEqual(async_req.headers[header], value)
                self.assertEqual(json.loads(async_req.content), json.loads(sync_req.content))
                for name in (header, "content-type", "accept", "user-agent"):
                    self.assertEqual(async_req.headers[name], sync_req.headers[name])
                if header == "x-api-key":
                    self.assertEqual(async_req.headers["anthropic-version"], "2026-10-21")

    async def test_body_conversions(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec)
        await m.aask("q")
        self.assertEqual(rec.body(), {"model": "gpt-x", "messages": [{"role": "user", "content": "q"}]})
        await m.aask("q", max_tokens=5)
        self.assertEqual(rec.body()["max_completion_tokens"], 5)
        self.assertNotIn("max_tokens", rec.body())

        rec = Recorder(json_response(CLAUDE_REPLY))
        m = self.make(rec, "anthropic:claude-x")
        await m.aask("q")
        b = rec.body()
        self.assertEqual(b["max_tokens"], 16000)
        self.assertNotIn("temperature", b)

    async def test_async_client_is_created_lazily(self):
        rec = FreshRecorder(lambda: json_response(OPENAI_REPLY))
        m = self.make(rec)
        m.ask("q")
        self.assertIsNone(m._async_client_instance)
        await m.aask("q")
        client = m._async_client_instance
        self.assertIsNotNone(client)
        await m.aask("q")
        self.assertIs(m._async_client_instance, client)

    async def test_achat_returns_result(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec)
        r = await m.achat([{"role": "user", "content": "q"}])
        self.assertIsInstance(r, ChatResult)
        self.assertEqual((r.text, r.stop_reason, r.model), ("ポチ", "stop", "gpt-x"))
        self.assertEqual(r.raw, OPENAI_REPLY)

    async def test_astream_openai_compatible(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        m = self.make(rec, "openrouter:a/b")
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        self.assertTrue(rec.body()["stream"])

    async def test_achat_stream_sends_messages_and_old_astream_is_an_alias(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        m = self.make(rec, "openrouter:a/b")
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        self.assertEqual(
            [p async for p in m.achat_stream(messages, system="S")], ["ポ", "チ"]
        )
        b = rec.body()
        self.assertTrue(b["stream"])
        self.assertEqual(b["messages"], [{"role": "system", "content": "S"}] + messages)
        self.assertEqual(len(messages), 3)  # the caller's list is not modified

        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        ask_body = rec.body()
        self.assertEqual(ask_body["messages"], [{"role": "user", "content": "q"}])

        # The deprecated name still works and sends the same request.
        self.assertEqual([p async for p in m.astream("q")], ["ポ", "チ"])
        self.assertEqual(rec.body(), ask_body)

    async def test_astream_anthropic(self):
        rec = Recorder(sse_response(CLAUDE_STREAM))
        m = self.make(rec, "claude:claude-x")
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])

    async def test_astream_is_lazy_and_raises_http_error_on_first_iteration(self):
        rec = Recorder(json_response({"error": {"message": "bad key"}}, status=401))
        m = self.make(rec)
        stream = m.aask_stream("q")
        self.assertEqual(rec.requests, [])
        with self.assertRaises(AuthenticationError) as cm:
            await stream.__anext__()
        self.assertIn("bad key", str(cm.exception))
        self.assertEqual(len(rec.requests), 1)


class AsyncLLMOverridesTest(AsyncLLMTestBase):
    CASES = [
        {},
        {"system": None, "max_tokens": None, "temperature": None, "extra": None},
        {"temperature": None},
        {"extra": None},
        {"system": None},
        {"extra": {"b": 2}},
        {"extra": {"a": 9}},
        {"system": "X", "max_tokens": 1, "temperature": 0.9},
    ]

    async def test_unset_none_and_extra_match_sync(self):
        for spec, reply in (("openai:m", OPENAI_REPLY), ("claude:m", CLAUDE_REPLY)):
            rec = FreshRecorder(lambda reply=reply: json_response(reply))
            m = self.make(rec, spec, system="S", max_tokens=5, temperature=0.4, extra={"a": 1})
            for kw in self.CASES:
                with self.subTest(spec=spec, kw=kw):
                    await m.aask("q", **kw)
                    async_body = rec.body()
                    m.ask("q", **kw)
                    self.assertEqual(async_body, rec.body())
                    await m.achat([{"role": "user", "content": "q"}], **kw)
                    self.assertEqual(async_body, rec.body())

    async def test_explicit_none_turns_off_defaults(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec, "openai:m", system="S", max_tokens=5, temperature=0.4, extra={"a": 1})
        await m.aask("q")
        b = rec.body()
        self.assertEqual((b["messages"][0], b["max_completion_tokens"], b["temperature"], b["a"]),
                         ({"role": "system", "content": "S"}, 5, 0.4, 1))
        await m.aask("q", system=None, max_tokens=None, temperature=None, extra=None)
        self.assertEqual(rec.body(), {"model": "m", "messages": [{"role": "user", "content": "q"}]})
        await m.aask("q", extra={"b": 2})
        self.assertEqual((rec.body()["a"], rec.body()["b"]), (1, 2))

    async def test_astream_overrides(self):
        rec = Recorder(sse_response("data: [DONE]\n\n"))
        m = self.make(rec, "openai:m", temperature=0.4)
        self.assertEqual([p async for p in m.aask_stream("q", temperature=None)], [])
        self.assertNotIn("temperature", rec.body())
        self.assertEqual([p async for p in m.aask_stream("q")], [])
        self.assertEqual(rec.body()["temperature"], 0.4)


class AsyncLLMLifecycleTest(AsyncLLMTestBase):
    async def test_gather_shares_one_llm(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        async with llm("openai:gpt-x", api_key="k", transport=rec.transport) as m:
            answers = await asyncio.gather(m.aask("a"), m.aask("b"), m.aask("c"))
        self.assertEqual(answers, ["ポチ", "ポチ", "ポチ"])
        prompts = sorted(json.loads(r.content)["messages"][0]["content"] for r in rec.requests)
        self.assertEqual(prompts, ["a", "b", "c"])

    async def test_async_with_and_aclose_is_idempotent(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        async with llm("openai:gpt-x", api_key="k", transport=rec.transport) as m:
            self.assertIsInstance(m, LLM)
            self.assertEqual(await m.aask("q"), "ポチ")
        self.assertTrue(m._async_client_instance._client.is_closed)
        self.assertTrue(m.client._client.is_closed)
        await m.aclose()
        await m.aclose()

    async def test_aclose_without_async_use(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm("openai:gpt-x", api_key="k", transport=rec.transport)
        await m.aclose()
        self.assertIsNone(m._async_client_instance)
        self.assertTrue(m.client._client.is_closed)
        await m.aclose()

    async def test_aask_cancel_closes_response(self):
        stream = BlockingAsyncStream(b'{"choices":')
        rec = Recorder(httpx.Response(200, stream=stream, headers={"content-type": "application/json"}))
        m = self.make(rec, log=self.log_path)
        task = asyncio.ensure_future(m.aask("q"))
        await stream.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stream.closed)
        self.assertEqual(self.records(), [])

    async def test_astream_cancel_closes_response(self):
        stream = BlockingAsyncStream('data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'.encode("utf-8"))
        rec = Recorder(httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream"}))
        m = self.make(rec, cache=self.db, log=self.log_path)
        it = m.aask_stream("q")
        self.assertEqual(await it.__anext__(), "ポ")
        task = asyncio.ensure_future(it.__anext__())
        await stream.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(stream.closed)
        self.assertEqual(len(SQLiteCache(self.db)), 0)
        self.assertEqual(self.records(), [])

    async def test_astream_aclose_closes_response(self):
        stream = BlockingAsyncStream('data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'.encode("utf-8"))
        rec = Recorder(httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream"}))
        m = self.make(rec)
        it = m.aask_stream("q")
        self.assertEqual(await it.__anext__(), "ポ")
        await it.aclose()
        self.assertTrue(stream.closed)
        await it.aclose()
        with self.assertRaises(StopAsyncIteration):
            await it.__anext__()


class AsyncLLMErrorsTest(AsyncLLMTestBase):
    async def test_status_errors(self):
        for status, cls in [(401, AuthenticationError), (404, NotFoundError), (500, InternalServerError)]:
            with self.subTest(status=status):
                rec = Recorder(json_response({"error": {"message": "nope"}}, status=status,
                                             headers={"x-request-id": "req-1"}))
                m = self.make(rec, max_retries=0)
                with self.assertRaises(cls) as cm:
                    await m.aask("q")
                e = cm.exception
                self.assertIsInstance(e, APIStatusError)
                self.assertEqual((e.status_code, e.code, e.request_id), (status, "api_error", "req-1"))
                self.assertIn("nope", str(e))

    async def test_httpx_errors_do_not_leak(self):
        cases = [
            (httpx.ConnectError("down"), APIConnectionError, "connection_error"),
            (httpx.ReadTimeout("slow"), APITimeoutError, "timeout"),
        ]
        for exc, cls, code in cases:
            with self.subTest(exc=type(exc).__name__):
                m = self.make(Recorder(exc), max_retries=0)
                with self.assertRaises(cls) as cm:
                    await m.aask("q")
                self.assertEqual(cm.exception.code, code)
                with self.assertRaises(cls):
                    async for _ in m.aask_stream("q"):
                        pass

    async def test_astream_failure_mid_body(self):
        rec = Recorder(httpx.Response(
            200, stream=AsyncFailingStream(httpx.ReadError("cut")),
            headers={"content-type": "text/event-stream"},
        ))
        m = self.make(rec)
        with self.assertRaises(APIConnectionError) as cm:
            async for _ in m.aask_stream("q"):
                pass
        self.assertNotIsInstance(cm.exception, httpx.HTTPError)


class AsyncLLMCacheTest(AsyncLLMTestBase):
    async def test_second_aask_hits_cache(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec, cache=self.db)
        self.assertEqual(await m.aask("q"), "ポチ")
        self.assertEqual(await m.aask("q"), "ポチ")
        self.assertEqual(len(rec.requests), 1)
        r = await m.achat([{"role": "user", "content": "q"}])
        self.assertEqual(r.raw, OPENAI_REPLY)
        self.assertEqual(len(rec.requests), 1)

    async def test_sync_and_async_share_entries(self):
        rec = FreshRecorder(lambda: json_response(CLAUDE_REPLY))
        m = self.make(rec, "anthropic:claude-x", cache=self.db)
        m.ask("q")  # stored by the sync client
        self.assertEqual(await m.aask("q"), "ポチ")
        self.assertEqual(len(rec.requests), 1)
        await m.aask("r")  # stored by the async client
        self.assertEqual(m.ask("r"), "ポチ")
        self.assertEqual(len(rec.requests), 2)

    async def test_completed_stream_is_cached_and_replayed(self):
        rec = FreshRecorder(lambda: sse_response(OPENAI_STREAM))
        m = self.make(rec, cache=self.db)
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        self.assertEqual(len(rec.requests), 1)
        # a stream stored by the sync API is replayed by the async API
        self.assertEqual(list(m.ask_stream("r")), ["ポ", "チ"])
        self.assertEqual([p async for p in m.aask_stream("r")], ["ポ", "チ"])
        self.assertEqual(len(rec.requests), 2)

    async def test_stream_without_terminal_event_is_not_cached(self):
        eof = OPENAI_STREAM.replace("data: [DONE]\n\n", "")
        rec = Recorder(sse_response(eof))
        m = self.make(rec, cache=self.db)
        with self.assertRaises(APIStreamError):
            [p async for p in m.aask_stream("q")]
        self.assertEqual(len(SQLiteCache(self.db)), 0)
        with self.assertRaises(APIStreamError):
            [p async for p in m.aask_stream("q")]
        self.assertEqual(len(rec.requests), 2)

    async def test_anthropic_stream_with_message_stop_is_cached(self):
        rec = Recorder(sse_response(CLAUDE_STREAM))
        m = llm("anthropic:claude-x", api_key="k", transport=rec.transport, cache=self.db)
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        self.assertEqual(len(rec.requests), 1)
        await m.aclose()

    async def test_stream_closed_early_is_not_cached(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        m = self.make(rec, cache=self.db)
        it = m.aask_stream("q")
        self.assertEqual(await it.__anext__(), "ポ")
        await it.aclose()
        self.assertEqual(len(SQLiteCache(self.db)), 0)
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        self.assertEqual(len(rec.requests), 2)
        self.assertEqual(len(SQLiteCache(self.db)), 1)


class AsyncLLMLogTest(AsyncLLMTestBase):
    async def test_aask_logs_one_line(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm("openai:gpt-x", api_key="sk-secret", transport=rec.transport,
                cache=self.db, log=self.log_path)
        self.addAsyncCleanup(m.aclose)
        await m.aask("可愛い犬の名前を考えて")
        (r,) = self.records()
        self.assertEqual((r["provider"], r["model"], r["stream"], r["cached"]),
                         ("openai", "gpt-x", False, False))
        self.assertEqual(r["request"]["messages"][0]["content"], "可愛い犬の名前を考えて")
        self.assertEqual(r["response"], OPENAI_REPLY)
        with open(self.log_path, encoding="utf-8") as f:
            self.assertNotIn("sk-secret", f.read())
        await m.aask("可愛い犬の名前を考えて")  # cache hit: logged as cached
        self.assertEqual([r["cached"] for r in self.records()], [False, True])
        self.assertEqual(len(rec.requests), 1)

    async def test_astream_logs_stream_and_cached(self):
        m = self.make(Recorder(sse_response(OPENAI_STREAM)), cache=self.db, log=self.log_path)
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        self.assertEqual([p async for p in m.aask_stream("q")], ["ポ", "チ"])
        recs = self.records()
        self.assertEqual([(r["stream"], r["cached"]) for r in recs], [(True, False), (True, True)])
        for r in recs:
            self.assertEqual(r["response"]["text"], "ポチ")
            self.assertEqual(len(r["response"]["chunks"]), 3)

    async def test_stream_closed_early_is_not_logged(self):
        m = self.make(Recorder(sse_response(OPENAI_STREAM)), log=self.log_path)
        it = m.aask_stream("q")
        await it.__anext__()
        await it.aclose()
        self.assertEqual(self.records(), [])


if __name__ == "__main__":
    unittest.main()
