"""Request lifecycle events and call metadata on results and errors (#30)."""

import os
import tempfile
import unittest

import httpx

from llm_ai_api import (
    APIConnectionError,
    APIStreamError,
    APITimeoutError,
    LLMConfigError,
    LLMError,
    OpenAIClient,
    RateLimitError,
    llm,
)
from llm_ai_api._async_clients import _AsyncOpenAIClient

from .helpers import FailingStream, FreshRecorder, Recorder, json_response

OK = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "model": "gpt-x",
}
CLAUDE = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn", "model": "c"}
STREAM = (
    'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"B"}}]}\n\n'
    "data: [DONE]\n\n"
)


def sse(text, request_id="req-s", status=200):
    return httpx.Response(
        status,
        content=text.encode("utf-8"),
        headers={"content-type": "text/event-stream", "x-request-id": request_id},
    )


def listen(box):
    def fn(event, payload):
        box.append((event, payload))

    return fn


class ListenerRegistrationTest(unittest.TestCase):
    def make(self, lang="en"):
        c = OpenAIClient(api_key="k", lang=lang, transport=Recorder(json_response(OK)).transport)
        self.addCleanup(c.close)
        return c

    def test_unknown_event_and_non_callable(self):
        c = self.make()
        with self.assertRaises(LLMConfigError) as cm:
            c.add_event_listener("retrie", lambda e, p: None)
        self.assertEqual(cm.exception.code, "invalid_event")
        self.assertIn("retry", str(cm.exception))
        with self.assertRaises(LLMConfigError) as cm:
            c.add_event_listener("response", None)
        self.assertEqual(cm.exception.code, "invalid_listener")

        c = self.make(lang="ja")
        with self.assertRaises(LLMConfigError) as cm:
            c.add_event_listener("nope", lambda e, p: None)
        self.assertIn("未知のイベント", str(cm.exception))

    def test_remove_one_registration_and_identity(self):
        c = self.make()
        seen = []
        fn = listen(seen)
        c.add_event_listener("response", fn)
        c.add_event_listener("response", fn)
        c.remove_event_listener("response", fn)  # one of the two
        c.request("/x", {})
        self.assertEqual(len(seen), 1)
        c.remove_event_listener("response", fn)
        c.remove_event_listener("response", fn)  # missing listener is fine
        seen.clear()
        c.request("/x", {})
        self.assertEqual(seen, [])

    def test_remove_all_events_registration_does_not_remove_a_named_one(self):
        c = self.make()
        seen = []
        fn = listen(seen)
        c.add_event_listener("response", fn)
        c.remove_event_listener(None, fn)
        c.request("/x", {})
        self.assertEqual([event for event, _ in seen], ["response"])

    def test_listener_exception_is_ignored(self):
        rec = Recorder(json_response(OK, headers={"x-request-id": "r1"}))
        c = OpenAIClient(api_key="k", transport=rec.transport, cache=False, log=False)
        self.addCleanup(c.close)
        seen = []

        def boom(event, payload):
            raise RuntimeError("listener failed")

        c.add_event_listener("response", boom)
        c.add_event_listener("response", listen(seen))
        self.assertEqual(c.request("/x", {}), OK)
        self.assertEqual(seen[0][1]["request_id"], "r1")


class SyncMetadataTest(unittest.TestCase):
    def client(self, rec, **kw):
        kw.setdefault("cache", False)
        kw.setdefault("log", False)
        c = OpenAIClient(api_key="k", transport=rec.transport, **kw)
        c.sleeps = []
        c._sleep = c.sleeps.append
        self.addCleanup(c.close)
        return c

    def test_success_metadata_and_payloads_omit_secrets(self):
        rec = Recorder(
            json_response({}, 500, {"x-request-id": "old", "retry-after": "0"}),
            json_response(OK, headers={"x-request-id": "new"}),
        )
        c = self.client(rec)
        seen = []
        c.add_event_listener(None, listen(seen))
        result = c.chat("m", [{"role": "user", "content": "secret-prompt"}])
        self.assertEqual(result.text, "ok")
        self.assertEqual(result.request_id, "new")
        self.assertEqual(result.retries, 1)
        self.assertIsInstance(result.latency, float)
        self.assertGreaterEqual(result.latency, 0)
        kinds = [event for event, _ in seen]
        self.assertEqual(kinds, ["retry", "response"])
        retry = seen[0][1]
        self.assertEqual(retry["attempt"], 0)
        self.assertEqual(retry["retries"], 0)
        self.assertEqual(retry["reason"], "status")
        self.assertEqual(retry["status_code"], 500)
        self.assertEqual(retry["request_id"], "old")
        self.assertEqual(retry["delay"], c.sleeps[0])
        self.assertEqual(retry["provider"], "openai")
        self.assertEqual(retry["path"], "/chat/completions")
        self.assertFalse(retry["stream"])
        response = seen[1][1]
        self.assertEqual(response["request_id"], "new")
        self.assertEqual(response["retries"], 1)
        self.assertEqual(response["status_code"], 200)
        self.assertFalse(response["cached"])
        blob = str(seen)
        self.assertNotIn("secret-prompt", blob)
        self.assertNotIn("Authorization", blob)
        self.assertNotIn("Bearer", blob)
        for _, payload in seen:
            self.assertNotIn("k", payload.values())

    def test_http_error_metadata(self):
        rec = Recorder(json_response({"error": {"message": "no"}}, 429, {"x-request-id": "lim"}))
        c = self.client(rec, max_retries=0)
        seen = []
        c.add_event_listener("http_error", listen(seen))
        with self.assertRaises(RateLimitError) as cm:
            c.chat("m", [{"role": "user", "content": "q"}])
        self.assertEqual(cm.exception.request_id, "lim")
        self.assertEqual(cm.exception.provider, "openai")
        self.assertEqual(cm.exception.retries, 0)
        self.assertIsInstance(cm.exception.latency, float)
        self.assertEqual(seen[0][1]["status_code"], 429)
        self.assertEqual(seen[0][1]["request_id"], "lim")

    def test_connection_error_metadata(self):
        rec = Recorder(httpx.ConnectError("down"))
        c = self.client(rec, max_retries=2)
        seen = []
        c.add_event_listener(None, listen(seen))
        with self.assertRaises(APIConnectionError) as cm:
            c.request("/x", {})
        err = cm.exception
        self.assertEqual(err.provider, "openai")
        self.assertIsNone(err.request_id)
        self.assertEqual(err.retries, 2)
        self.assertEqual(err.code, "connection_error")
        self.assertIsInstance(err.latency, float)
        self.assertEqual([event for event, _ in seen], ["retry", "retry", "connection_error"])
        self.assertEqual(seen[0][1]["reason"], "connect")
        self.assertEqual(seen[-1][1]["code"], "connection_error")
        self.assertEqual(seen[-1][1]["attempt"], 2)

    def test_timeout_reason(self):
        rec = Recorder(httpx.ReadTimeout("slow"))
        c = self.client(rec, max_retries=0)
        seen = []
        c.add_event_listener("connection_error", listen(seen))
        with self.assertRaises(APITimeoutError) as cm:
            c.request("/x", {})
        self.assertEqual(cm.exception.code, "timeout")
        self.assertEqual(seen[0][1]["reason"], "read_timeout")

    def test_anthropic_request_id_header(self):
        rec = Recorder(json_response(CLAUDE, headers={"request-id": "ant-1"}))
        from llm_ai_api import AnthropicClient

        c = AnthropicClient(api_key="k", transport=rec.transport, cache=False, log=False)
        self.addCleanup(c.close)
        result = c.chat("claude-x", [{"role": "user", "content": "q"}])
        self.assertEqual(result.request_id, "ant-1")
        self.assertEqual(result.retries, 0)

    def test_invalid_json_emits_request_error_after_response(self):
        rec = Recorder(httpx.Response(200, text="nope", headers={"x-request-id": "j"}))
        c = self.client(rec)
        seen = []
        c.add_event_listener(None, listen(seen))
        with self.assertRaises(LLMError) as cm:
            c.request("/x", {})
        self.assertEqual(cm.exception.code, "invalid_json_response")
        self.assertEqual([event for event, _ in seen], ["response", "request_error"])
        self.assertEqual(seen[1][1]["code"], "invalid_json_response")
        self.assertEqual(seen[1][1]["request_id"], "j")

    def test_stream_metadata_and_stream_end(self):
        rec = Recorder(sse(STREAM, "req-s"))
        c = self.client(rec)
        seen = []
        c.add_event_listener(None, listen(seen))
        chunks = c.stream_chat("m", [{"role": "user", "content": "q"}])
        self.assertEqual(chunks.request_id, "req-s")
        self.assertEqual(chunks.retries, 0)
        got = list(chunks)
        self.assertEqual([chunk.text for chunk in got], ["A", "B"])
        self.assertTrue(all(chunk.request_id == "req-s" for chunk in got))
        self.assertEqual([event for event, _ in seen], ["response", "stream_end"])
        self.assertTrue(seen[0][1]["stream"])
        self.assertEqual(seen[0][1]["request_id"], "req-s")
        self.assertTrue(seen[1][1]["complete"])
        self.assertGreaterEqual(seen[1][1]["latency"], seen[0][1]["latency"])

    def test_llm_stream_exposes_request_id_before_iteration(self):
        rec = Recorder(sse(STREAM, "req-s"))
        m = llm("openai:m", api_key="k", transport=rec.transport, cache=False, log=False)
        self.addCleanup(m.close)
        stream = m.stream("q")
        self.assertEqual(stream.request_id, "req-s")
        self.assertEqual("".join(stream), "AB")

    def test_partial_stream_does_not_emit_stream_end(self):
        rec = Recorder(sse(STREAM, "req-s"))
        m = llm("openai:m", api_key="k", transport=rec.transport, cache=False, log=False)
        self.addCleanup(m.close)
        seen = []
        m.add_event_listener(None, listen(seen))
        stream = m.stream("q")
        self.assertEqual(next(stream), "A")
        stream.close()
        self.assertEqual([event for event, _ in seen], ["response"])

    def test_stream_error_carries_request_id(self):
        text = (
            'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
            'data: {"error":{"message":"boom"}}\n\n'
        )
        rec = Recorder(sse(text, "req-e"))
        m = llm("openai:m", api_key="k", lang="en", transport=rec.transport, cache=False, log=False)
        self.addCleanup(m.close)
        seen = []
        m.add_event_listener(None, listen(seen))
        got = []
        with self.assertRaises(APIStreamError) as cm:
            for piece in m.stream("q"):
                got.append(piece)
        self.assertEqual(got, ["A"])
        self.assertEqual(cm.exception.provider, "openai")
        self.assertEqual(cm.exception.request_id, "req-e")
        self.assertEqual(cm.exception.retries, 0)
        self.assertEqual(cm.exception.code, "stream_error")
        self.assertIn("stream_error", [event for event, _ in seen])
        self.assertNotIn("stream_end", [event for event, _ in seen])

    def test_mid_stream_transport_error_keeps_request_id(self):
        rec = Recorder(
            httpx.Response(
                200,
                stream=FailingStream(httpx.ReadError("cut")),
                headers={"content-type": "text/event-stream", "x-request-id": "live"},
            )
        )
        c = self.client(rec)
        seen = []
        c.add_event_listener("connection_error", listen(seen))
        events = c.request_stream("/chat/completions", {"model": "m"})
        self.assertEqual(events.request_id, "live")
        with self.assertRaises(APIConnectionError) as cm:
            next(events)
        self.assertEqual(cm.exception.request_id, "live")
        self.assertEqual(cm.exception.provider, "openai")
        self.assertEqual(seen[0][1]["request_id"], "live")
        self.assertEqual(seen[0][1]["reason"], "transport")

    def test_cache_hit_restores_metadata_and_skips_response_event(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.db")
            rec = Recorder(json_response(OK, headers={"x-request-id": "stored"}))
            m = llm("openai:m", api_key="k", transport=rec.transport, cache=path, log=False)
            self.addCleanup(m.close)
            first = m.chat([{"role": "user", "content": "q"}])
            self.assertEqual(first.request_id, "stored")
            seen = []
            m.add_event_listener(None, listen(seen))
            second = m.chat([{"role": "user", "content": "q"}])
            self.assertEqual(second.request_id, "stored")
            self.assertEqual(second.retries, first.retries)
            self.assertEqual(second.latency, first.latency)
            self.assertEqual([event for event, _ in seen], ["cache_hit"])
            self.assertTrue(seen[0][1]["cached"])
            self.assertEqual(seen[0][1]["request_id"], "stored")
            self.assertEqual(len(rec.requests), 1)

    def test_cached_stream_replays_request_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "c.db")
            rec = Recorder(sse(STREAM, "req-s"))
            m = llm("openai:m", api_key="k", transport=rec.transport, cache=path, log=False)
            self.addCleanup(m.close)
            self.assertEqual("".join(m.stream("q")), "AB")
            seen = []
            m.add_event_listener(None, listen(seen))
            again = m.stream("q")
            self.assertEqual(again.request_id, "req-s")
            self.assertEqual("".join(again), "AB")
            self.assertEqual([event for event, _ in seen], ["cache_hit"])
            self.assertEqual(len(rec.requests), 1)


class AsyncMetadataTest(unittest.IsolatedAsyncioTestCase):
    async def test_achat_and_shared_listener(self):
        rec = FreshRecorder(
            lambda: json_response(OK, headers={"x-request-id": "async-1"})
        )
        m = llm("openai:m", api_key="k", transport=rec.transport, cache=False, log=False)
        seen = []
        m.add_event_listener(None, listen(seen))

        def boom(event, payload):
            if event == "response":
                raise RuntimeError("nope")

        m.add_event_listener("response", boom)
        result = await m.achat([{"role": "user", "content": "q"}])
        self.assertEqual(result.text, "ok")
        self.assertEqual(result.request_id, "async-1")
        self.assertEqual(result.retries, 0)
        self.assertIn("response", [event for event, _ in seen])
        # The same list is used for a later sync call.
        seen.clear()
        self.assertEqual(m.ask("q"), "ok")
        self.assertIn("response", [event for event, _ in seen])
        await m.aclose()

    async def test_astream_request_id_after_headers(self):
        rec = Recorder(sse(STREAM, "req-s"))
        m = llm("openai:m", api_key="k", transport=rec.transport, cache=False, log=False)
        seen = []
        m.add_event_listener(None, listen(seen))
        stream = m.astream("q")
        self.assertIsNone(stream.request_id)
        self.assertEqual(await stream.__anext__(), "A")
        self.assertEqual(stream.request_id, "req-s")
        self.assertEqual(stream.retries, 0)
        self.assertEqual(await stream.__anext__(), "B")
        with self.assertRaises(StopAsyncIteration):
            await stream.__anext__()
        self.assertEqual([event for event, _ in seen], ["response", "stream_end"])
        await m.aclose()

    async def test_async_retry_event(self):
        rec = Recorder(
            json_response({}, 429, {"retry-after": "2", "x-request-id": "a"}),
            json_response(OK, headers={"x-request-id": "b"}),
        )
        c = _AsyncOpenAIClient(api_key="k", transport=rec.transport, cache=False, log=False)
        sleeps = []

        async def record(seconds):
            sleeps.append(seconds)

        c._sleep = record
        seen = []
        c.add_event_listener(None, listen(seen))
        result = await c.achat("m", [{"role": "user", "content": "q"}])
        self.assertEqual(result.request_id, "b")
        self.assertEqual(result.retries, 1)
        self.assertEqual(sleeps, [2.0])
        self.assertEqual(seen[0][0], "retry")
        self.assertEqual(seen[0][1]["delay"], 2.0)
        self.assertEqual(seen[0][1]["request_id"], "a")
        self.assertEqual(seen[1][0], "response")
        await c.aclose()

    async def test_async_stream_error(self):
        text = 'data: {"error":{"message":"boom"}}\n\n'
        rec = Recorder(sse(text, "req-e"))
        m = llm("openai:m", api_key="k", transport=rec.transport, cache=False, log=False)
        seen = []
        m.add_event_listener("stream_error", listen(seen))
        stream = m.astream("q")
        with self.assertRaises(APIStreamError) as cm:
            await stream.__anext__()
        self.assertEqual(cm.exception.request_id, "req-e")
        self.assertEqual(cm.exception.provider, "openai")
        self.assertEqual(seen[0][1]["request_id"], "req-e")
        await m.aclose()


if __name__ == "__main__":
    unittest.main()
