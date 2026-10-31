import unittest

import httpx

from llm_ai_api import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    LLMConfigError,
    OpenAIClient,
    RateLimitError,
)

from .helpers import FailingStream, Recorder, json_response


def make(rec, **kw):
    c = OpenAIClient(api_key="sk-test", transport=rec.transport, **kw)
    c.sleeps = []
    c._sleep = c.sleeps.append
    return c


class HttpTest(unittest.TestCase):
    def test_missing_key(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMConfigError):
                OpenAIClient()

    def test_key_not_in_repr(self):
        c = make(Recorder(json_response({})))
        self.assertNotIn("sk-test", repr(c))

    def test_base_url_credentials_masked_in_repr(self):
        c = OpenAIClient(
            api_key="k",
            base_url="https://user:p4ssw0rd@example.example/v1?token=abc",
            transport=Recorder(json_response({})).transport,
        )
        r = repr(c)
        self.assertNotIn("p4ssw0rd", r)
        self.assertNotIn("token", r)
        self.assertIn("***", r)
        plain = OpenAIClient(
            api_key="k",
            base_url="https://example.example/v1",
            transport=Recorder(json_response({})).transport,
        )
        self.assertIn("https://example.example/v1", repr(plain))
        self.assertNotIn("***", repr(plain))

    def test_headers_and_raw_passthrough(self):
        rec = Recorder(json_response({"x": 1}))
        c = make(rec, headers={"X-Foo": "bar"})
        out = c.request("/anything", {"日本語": "あ", "unknown": [1]})
        self.assertEqual(out, {"x": 1})
        req = rec.requests[0]
        self.assertEqual(str(req.url), "https://api.openai.com/v1/anything")
        self.assertEqual(req.headers["authorization"], "Bearer sk-test")
        self.assertEqual(req.headers["x-foo"], "bar")
        self.assertTrue(req.headers["user-agent"].startswith("llm-ai-api-python/"))
        self.assertEqual(rec.body(), {"日本語": "あ", "unknown": [1]})
        self.assertIn("あ".encode("utf-8"), req.content)

    def test_status_errors(self):
        cases = [(400, BadRequestError), (401, AuthenticationError)]
        for status, cls in cases:
            rec = Recorder(
                json_response({"error": {"message": "bad"}}, status, {"x-request-id": "req_1"})
            )
            with self.assertRaises(cls) as cm:
                make(rec).request("/x", {})
            e = cm.exception
            self.assertEqual(e.status_code, status)
            self.assertEqual(e.request_id, "req_1")
            self.assertEqual(e.body, {"error": {"message": "bad"}})
            self.assertIn("bad", str(e))
            self.assertEqual(len(rec.requests), 1)  # リトライしない

    def test_non_json_error_body(self):
        rec = Recorder(httpx.Response(400, text="plain text"))
        with self.assertRaises(BadRequestError) as cm:
            make(rec).request("/x", {})
        self.assertEqual(cm.exception.body, "plain text")

    def test_retry_with_retry_after(self):
        rec = Recorder(
            json_response({}, 429, {"retry-after": "3"}), json_response({"ok": True})
        )
        c = make(rec)
        self.assertEqual(c.request("/x", {}), {"ok": True})
        self.assertEqual(c.sleeps, [3.0])
        self.assertEqual(len(rec.requests), 2)

    def test_retry_exhausted(self):
        rec = Recorder(json_response({}, 500))
        c = make(rec, max_retries=2)
        with self.assertRaises(InternalServerError):
            c.request("/x", {})
        self.assertEqual(len(rec.requests), 3)
        self.assertEqual(len(c.sleeps), 2)

    def test_rate_limit_error_class(self):
        with self.assertRaises(RateLimitError):
            make(Recorder(json_response({}, 429)), max_retries=0).request("/x", {})

    def test_connection_and_timeout_errors(self):
        c = make(Recorder(httpx.ConnectError("no")), max_retries=1)
        with self.assertRaises(APIConnectionError):
            c.request("/x", {})
        c = make(Recorder(httpx.ReadTimeout("slow")), max_retries=0)
        with self.assertRaises(APITimeoutError):
            c.request("/x", {})

    # --- the error body itself can fail to be read ---------------------------------

    def failing(self, exc, status=500):
        return httpx.Response(status, stream=FailingStream(exc))

    def test_stream_error_body_timeout_is_converted(self):
        # one response object per attempt: a consumed stream cannot be read again
        rec = Recorder(self.failing(httpx.ReadTimeout("slow")), self.failing(httpx.ReadTimeout("slow")))
        c = make(rec, max_retries=1)
        with self.assertRaises(APITimeoutError):
            c.request_stream("/x", {})
        self.assertEqual(len(rec.requests), 2)  # retried once

    def test_stream_error_body_disconnect_is_converted(self):
        c = make(Recorder(self.failing(httpx.ReadError("reset"), 400)), max_retries=0)
        with self.assertRaises(APIConnectionError):
            c.request_stream("/x", {})

    def test_stream_error_body_failure_then_success_is_retried(self):
        from .helpers import sse_response

        rec = Recorder(self.failing(httpx.ReadTimeout("slow")), sse_response("data: ok\n\n"))
        c = make(rec)
        self.assertEqual([e.data for e in c.request_stream("/x", {})], ["ok"])
        self.assertEqual(len(c.sleeps), 1)

    def test_non_stream_error_body_failure_is_converted(self):
        c = make(Recorder(self.failing(httpx.ReadTimeout("slow"))), max_retries=0)
        with self.assertRaises(APITimeoutError):
            c.request("/x", {})


if __name__ == "__main__":
    unittest.main()
