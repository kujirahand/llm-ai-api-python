"""Tests for the internal async clients (_async_http.py / _async_clients.py)."""

import asyncio
import unittest

import httpx

from llm_ai_api import (
    APIConnectionError,
    APIStreamError,
    APITimeoutError,
    BadRequestError,
    ChatResult,
    LLMError,
    RateLimitError,
    Usage,
    set_cache,
    set_log,
)
from llm_ai_api._async_clients import (
    _AsyncAnthropicClient,
    _AsyncGoogleClient,
    _AsyncOpenAIClient,
    _AsyncOpenRouterClient,
)
from llm_ai_api._async_http import aiter_sse

from .helpers import AsyncFailingStream, Recorder, json_response, sse_response

OPENAI_REPLY = {
    "choices": [{"message": {"content": "ポチ"}, "finish_reason": "stop"}],
    "model": "gpt-x",
    "usage": {"prompt_tokens": 3, "completion_tokens": 4},
}
CLAUDE_REPLY = {
    "content": [
        {"type": "thinking", "thinking": "..."},
        {"type": "text", "text": "ポ"},
        {"type": "text", "text": "チ"},
    ],
    "model": "claude-x",
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 5, "output_tokens": 6},
}
OPENAI_STREAM = (
    ": OPENROUTER PROCESSING\n\n"
    'data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'
    'data: {"choices":[],"usage":{"prompt_tokens":1}}\n\n'
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
MESSAGES = [{"role": "system", "content": "S"}, {"role": "user", "content": "q"}]


class AsyncClientTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)
        self.sleeps = []

    def make(self, rec, cls=_AsyncOpenAIClient, **kw):
        c = cls(api_key="k", transport=rec.transport, **kw)

        async def record_sleep(seconds):
            self.sleeps.append(seconds)

        c._sleep = record_sleep
        self.addAsyncCleanup(c.aclose)
        return c


class AsyncSSETest(unittest.IsolatedAsyncioTestCase):
    async def test_aiter_sse_matches_sync_parser(self):
        async def lines():
            for line in ["event: a", "data: 1", "data: 2", "", ": comment", "data: x", ""]:
                yield line
            yield "data: tail"

        events = [(e.event, e.data) async for e in aiter_sse(lines())]
        self.assertEqual(events, [("a", "1\n2"), (None, "x"), (None, "tail")])


class AsyncRawLayerTest(AsyncClientTestBase):
    async def test_request_returns_dict(self):
        rec = Recorder(json_response({"x": 1}))
        c = self.make(rec)
        self.assertEqual(await c.request("/anything", {"a": "日本語"}), {"x": 1})
        req = rec.requests[0]
        self.assertEqual(str(req.url), "https://api.openai.com/v1/anything")
        self.assertEqual(rec.body(), {"a": "日本語"})
        self.assertEqual(req.headers["authorization"], "Bearer k")
        self.assertEqual(req.headers["accept"], "application/json")
        self.assertTrue(req.headers["user-agent"].startswith("llm-ai-api-python/"))

    async def test_request_stream_raises_http_error_on_await(self):
        rec = Recorder(json_response({"error": {"message": "bad"}}, status=400))
        c = self.make(rec)
        with self.assertRaises(BadRequestError) as cm:
            await c.request_stream("/chat/completions", {})
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("bad", str(cm.exception))
        self.assertEqual(cm.exception.body, {"error": {"message": "bad"}})

    async def test_invalid_json_response(self):
        rec = Recorder(httpx.Response(200, content=b"not json"))
        c = self.make(rec)
        with self.assertRaises(LLMError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.code, "invalid_json_response")

    async def test_request_non_object_response(self):
        for payload in (b'["x"]', b"42", b'"str"', b"null"):
            rec = Recorder(httpx.Response(200, content=payload))
            c = self.make(rec)
            with self.assertRaises(LLMError) as cm:
                await c.request("/x", {})
            self.assertEqual(cm.exception.code, "invalid_json_response")

    async def test_non_object_response(self):
        for payload in (b'["x"]', b"42", b"null"):
            rec = Recorder(httpx.Response(200, content=payload))
            c = self.make(rec)
            with self.assertRaises(LLMError) as cm:
                await c.achat("gpt-x", MESSAGES)
            self.assertEqual(cm.exception.code, "invalid_json_response")

    async def test_stream_non_object_event(self):
        for data in ('["just","an","array"]', "42"):
            rec = Recorder(sse_response("data: %s\n\n" % data))
            c = self.make(rec)
            chunks = await c.stream_chat("gpt-x", MESSAGES)
            with self.assertRaises(LLMError) as cm:
                await chunks.__anext__()
            self.assertEqual(cm.exception.code, "invalid_json_response")

    async def test_retry_then_success(self):
        rec = Recorder(json_response({}, status=429), json_response({"ok": True}))
        c = self.make(rec)
        self.assertEqual(await c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)
        self.assertEqual(len(self.sleeps), 1)

    async def test_retry_after(self):
        rec = Recorder(json_response({}, 503, headers={"retry-after": "3"}), json_response({}))
        c = self.make(rec)
        await c.request("/x", {})
        self.assertEqual(self.sleeps, [3.0])

        rec = Recorder(json_response({}, 429, headers={"retry-after": "1000"}), json_response({}))
        c = self.make(rec)
        self.sleeps = []
        await c.request("/x", {})
        self.assertEqual(self.sleeps, [60.0])

    async def test_retries_exhausted(self):
        rec = Recorder(json_response({"error": {"message": "slow down"}}, status=429))
        c = self.make(rec)
        with self.assertRaises(RateLimitError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.code, "api_error")
        self.assertEqual(len(rec.requests), 3)
        self.assertEqual(len(self.sleeps), 2)

    async def test_no_retry_for_400(self):
        rec = Recorder(json_response({}, status=400))
        c = self.make(rec)
        with self.assertRaises(BadRequestError):
            await c.request("/x", {})
        self.assertEqual((len(rec.requests), self.sleeps), (1, []))

    async def test_cancel_during_retry_wait(self):
        rec = Recorder(json_response({}, status=500), json_response({"ok": True}))
        c = _AsyncOpenAIClient(api_key="k", transport=rec.transport)
        self.addAsyncCleanup(c.aclose)
        sleeping = asyncio.Event()

        async def slow_sleep(seconds):
            sleeping.set()
            await asyncio.sleep(3600)

        c._sleep = slow_sleep
        task = asyncio.ensure_future(c.request("/x", {}))
        await sleeping.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(rec.requests), 1)

    async def test_transport_errors_are_converted(self):
        rec = Recorder(httpx.ConnectError("down"))
        c = self.make(rec)
        with self.assertRaises(APIConnectionError) as cm:
            await c.request("/x", {})
        self.assertNotIsInstance(cm.exception, APITimeoutError)
        self.assertEqual(cm.exception.code, "connection_error")
        self.assertEqual(len(rec.requests), 3)

        rec = Recorder(httpx.ReadTimeout("slow"))
        c = self.make(rec, max_retries=0)
        with self.assertRaises(APITimeoutError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.code, "timeout")

    async def test_body_read_failure_is_converted(self):
        rec = Recorder(httpx.Response(200, stream=AsyncFailingStream(httpx.ReadTimeout("slow"))))
        c = self.make(rec, max_retries=0)
        with self.assertRaises(APITimeoutError):
            await c.request("/x", {})

    async def test_stream_failure_mid_body_is_converted(self):
        for exc, cls, code in [
            (httpx.ReadTimeout("slow"), APITimeoutError, "timeout"),
            (httpx.ReadError("cut"), APIConnectionError, "connection_error"),
        ]:
            with self.subTest(exc=type(exc).__name__):
                rec = Recorder(httpx.Response(
                    200,
                    stream=AsyncFailingStream(exc),
                    headers={"content-type": "text/event-stream"},
                ))
                c = self.make(rec)
                events = await c.request_stream("/x", {})
                with self.assertRaises(cls) as cm:
                    async for _ in events:
                        pass
                self.assertEqual(cm.exception.code, code)
                self.assertNotIsInstance(cm.exception, httpx.HTTPError)


class AsyncOpenAICompatTest(AsyncClientTestBase):
    async def test_achat(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        c = self.make(rec)
        r = await c.achat("gpt-x", MESSAGES, max_tokens=5)
        self.assertIsInstance(r, ChatResult)
        self.assertEqual((r.text, r.model, r.stop_reason), ("ポチ", "gpt-x", "stop"))
        self.assertEqual(r.usage, Usage(3, 4))
        self.assertEqual(r.raw, OPENAI_REPLY)
        self.assertEqual(str(rec.requests[0].url), "https://api.openai.com/v1/chat/completions")
        self.assertEqual(
            rec.body(), {"model": "gpt-x", "messages": MESSAGES, "max_completion_tokens": 5}
        )

    async def test_known_model_drops_rejected_fields(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        c = self.make(rec)
        await c.achat("gpt-6.1-sol", MESSAGES, temperature=0.2, extra={"top_logprobs": 2, "n": 1})
        body = rec.body()
        self.assertNotIn("temperature", body)
        self.assertNotIn("top_logprobs", body)
        self.assertEqual(body["n"], 1)

    async def test_openrouter_and_google_settings(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        c = self.make(rec, cls=_AsyncOpenRouterClient, app_url="https://e.x", app_name="App")
        await c.achat("a/b:free", MESSAGES, max_tokens=5, temperature=0.2, extra={"top_k": 3})
        req = rec.requests[0]
        self.assertEqual(str(req.url), "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual((req.headers["http-referer"], req.headers["x-title"]), ("https://e.x", "App"))
        self.assertEqual(
            rec.body(),
            {"model": "a/b:free", "messages": MESSAGES, "max_tokens": 5, "temperature": 0.2,
             "top_k": 3},
        )

        rec = Recorder(json_response(OPENAI_REPLY))
        c = self.make(rec, cls=_AsyncGoogleClient)
        await c.achat("gemini-x", MESSAGES)
        self.assertEqual(
            str(rec.requests[0].url),
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        self.assertEqual(rec.body(), {"model": "gemini-x", "messages": MESSAGES})

    async def test_stream_chat(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        c = self.make(rec)
        chunks = await c.stream_chat("gpt-x", MESSAGES)
        texts = [ch.text async for ch in chunks]
        self.assertEqual(texts, ["ポ", "", "チ"])
        self.assertEqual(rec.requests[0].headers["accept"], "text/event-stream")
        b = rec.body()
        self.assertTrue(b["stream"])
        self.assertEqual(b["stream_options"], {"include_usage": True})

    async def test_stream_error_event(self):
        rec = Recorder(sse_response(
            'data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'
            'data: {"error":{"message":"overloaded"}}\n\n'
        ))
        c = self.make(rec, cls=_AsyncOpenRouterClient)
        chunks = await c.stream_chat("a/b", MESSAGES)
        self.assertEqual((await chunks.__anext__()).text, "ポ")
        with self.assertRaises(APIStreamError) as cm:
            await chunks.__anext__()
        self.assertEqual(cm.exception.code, "stream_error")
        self.assertIn("overloaded", str(cm.exception))
        self.assertEqual(cm.exception.body, {"error": {"message": "overloaded"}})

    async def test_stream_invalid_json(self):
        rec = Recorder(sse_response("data: {bad\n\n"))
        c = self.make(rec)
        chunks = await c.stream_chat("gpt-x", MESSAGES)
        with self.assertRaises(LLMError) as cm:
            await chunks.__anext__()
        self.assertEqual(cm.exception.code, "invalid_json_response")


class AsyncAnthropicTest(AsyncClientTestBase):
    async def test_achat(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        c = self.make(rec, cls=_AsyncAnthropicClient)
        r = await c.achat("claude-x", MESSAGES)
        self.assertEqual((r.text, r.model, r.stop_reason), ("ポチ", "claude-x", "end_turn"))
        self.assertEqual(r.usage, Usage(5, 6))
        req = rec.requests[0]
        self.assertEqual(str(req.url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.headers["x-api-key"], "k")
        self.assertEqual(req.headers["anthropic-version"], "2026-10-21")
        self.assertNotIn("authorization", req.headers)
        self.assertEqual(
            rec.body(),
            {"model": "claude-x", "messages": [{"role": "user", "content": "q"}],
             "max_tokens": 16000, "system": "S"},
        )

    async def test_anthropic_version_and_headers(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        c = self.make(rec, cls=_AsyncAnthropicClient, anthropic_version="2099-01-01",
                      headers={"anthropic-beta": "x"})
        await c.achat("claude-x", MESSAGES, max_tokens=10, temperature=0.2, extra={"top_k": 1})
        req = rec.requests[0]
        self.assertEqual((req.headers["anthropic-version"], req.headers["anthropic-beta"]),
                         ("2099-01-01", "x"))
        self.assertEqual(rec.body()["max_tokens"], 10)
        self.assertEqual(rec.body()["temperature"], 0.2)
        self.assertEqual(rec.body()["top_k"], 1)

    async def test_default_version_drops_sampling_params(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        c = self.make(rec, cls=_AsyncAnthropicClient)
        await c.achat("claude-x", MESSAGES, temperature=0.2, extra={"top_k": 4, "top_p": 0.3})
        body = rec.body()
        self.assertEqual(body["max_tokens"], 16000)
        self.assertNotIn("temperature", body)
        self.assertNotIn("top_k", body)
        self.assertNotIn("top_p", body)

    async def test_header_override_selects_the_version_used_for_drops(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        c = self.make(rec, cls=_AsyncAnthropicClient, headers={"anthropic-version": "2023-06-01"})
        await c.achat("claude-x", MESSAGES, temperature=0.2, extra={"top_k": 4})
        self.assertEqual(rec.requests[0].headers["anthropic-version"], "2023-06-01")
        self.assertEqual(rec.body()["temperature"], 0.2)
        self.assertEqual(rec.body()["top_k"], 4)
        rec = Recorder(json_response(CLAUDE_REPLY))
        c = self.make(
            rec,
            cls=_AsyncAnthropicClient,
            anthropic_version="2023-06-01",
            headers={"anthropic-version": "2026-10-21"},
        )
        await c.achat("claude-x", MESSAGES, temperature=0.2, extra={"top_p": 0.3})
        self.assertEqual(rec.requests[0].headers["anthropic-version"], "2026-10-21")
        self.assertNotIn("temperature", rec.body())
        self.assertNotIn("top_p", rec.body())

    async def test_stream_chat(self):
        rec = Recorder(sse_response(CLAUDE_STREAM))
        c = self.make(rec, cls=_AsyncAnthropicClient)
        chunks = await c.stream_chat("claude-x", MESSAGES)
        got = [ch async for ch in chunks]
        self.assertEqual([ch.text for ch in got], ["", "ポ", "チ"])
        self.assertEqual([ch.raw["type"] for ch in got],
                         ["message_start", "content_block_delta", "content_block_delta"])
        self.assertTrue(rec.body()["stream"])

    async def test_stream_error_event(self):
        rec = Recorder(sse_response(
            "event: error\n"
            'data: {"type":"error","error":{"type":"overloaded_error","message":"Overloaded"}}\n\n'
        ))
        c = self.make(rec, cls=_AsyncAnthropicClient)
        chunks = await c.stream_chat("claude-x", MESSAGES)
        with self.assertRaises(APIStreamError) as cm:
            await chunks.__anext__()
        self.assertIn("Overloaded", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
