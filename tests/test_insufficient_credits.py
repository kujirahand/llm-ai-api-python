"""InsufficientCreditsError (#120): detection, hints, and no-retry behavior."""

import unittest

from llm_ai_api import (
    APIStatusError,
    InsufficientCreditsError,
    OpenAIClient,
    PermissionDeniedError,
    RateLimitError,
    set_cache,
    set_log,
)
from llm_ai_api._async_clients import _AsyncOpenAIClient
from llm_ai_api.errors import is_insufficient_credits, status_error_class

from .helpers import Recorder, json_response, sse_response

XAI_NO_CREDITS = {
    "code": "permission-denied",
    "error": (
        "Your team doesn't have any credits or licenses. "
        "Please purchase credits at https://console.x.ai."
    ),
}
XAI_NO_CREDITS_NESTED = {
    "error": {
        "code": "permission-denied",
        "message": "The team does not have any credits or licenses.",
    }
}
MUSE_BILLING = {
    "error": {
        "type": "billing_error",
        "code": "billing_not_configured",
        "message": "Billing is not configured for this workspace.",
    }
}
OPENAI_QUOTA = {
    "error": {
        "message": "You exceeded your current quota, please check your plan and billing details.",
        "type": "insufficient_quota",
        "code": "insufficient_quota",
    }
}
NORMAL_403 = {
    "error": {
        "code": "permission-denied",
        "message": "This API key cannot use this model.",
    }
}
NORMAL_429 = {
    "error": {
        "message": "Rate limit reached for requests.",
        "type": "rate_limit_exceeded",
        "code": "rate_limit_exceeded",
    }
}


def make_sync(rec, **kw):
    c = OpenAIClient(api_key="k", transport=rec.transport, **kw)
    c.sleeps = []
    c._sleep = c.sleeps.append
    return c


class DetectTest(unittest.TestCase):
    def test_http_402_always_matches(self):
        for body in (None, {}, "plain", MUSE_BILLING):
            self.assertTrue(is_insufficient_credits(402, body))
            self.assertIs(status_error_class(402, body), InsufficientCreditsError)

    def test_xai_403_credits_message(self):
        for body in (XAI_NO_CREDITS, XAI_NO_CREDITS_NESTED):
            self.assertTrue(is_insufficient_credits(403, body))
            self.assertIs(status_error_class(403, body), InsufficientCreditsError)

    def test_openai_429_insufficient_quota(self):
        self.assertTrue(is_insufficient_credits(429, OPENAI_QUOTA))
        self.assertIs(status_error_class(429, OPENAI_QUOTA), InsufficientCreditsError)
        # The code/type alone is enough, even on an unusual status.
        self.assertTrue(
            is_insufficient_credits(403, {"error": {"code": "insufficient_quota"}})
        )

    def test_normal_403_and_429_are_unchanged(self):
        self.assertFalse(is_insufficient_credits(403, NORMAL_403))
        self.assertIs(status_error_class(403, NORMAL_403), PermissionDeniedError)
        self.assertFalse(is_insufficient_credits(429, NORMAL_429))
        self.assertIs(status_error_class(429, NORMAL_429), RateLimitError)
        self.assertFalse(is_insufficient_credits(429, {}))
        self.assertIs(status_error_class(429), RateLimitError)

    def test_403_needs_both_code_and_phrase(self):
        only_code = {"code": "permission-denied", "error": "Access denied."}
        only_phrase = {
            "error": "Your team doesn't have any credits or licenses."
        }
        self.assertFalse(is_insufficient_credits(403, only_code))
        self.assertFalse(is_insufficient_credits(403, only_phrase))

    def test_unrelated_status_does_not_match_on_message_alone(self):
        body = {"error": {"message": "out of credits"}}
        self.assertFalse(is_insufficient_credits(400, body))
        self.assertFalse(is_insufficient_credits(500, body))


class SyncRequestTest(unittest.TestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)

    def _assert_credits_error(self, rec, status, body, lang="en"):
        c = make_sync(rec, max_retries=2, lang=lang)
        with self.assertRaises(InsufficientCreditsError) as cm:
            c.request("/x", {})
        e = cm.exception
        self.assertIsInstance(e, APIStatusError)
        self.assertEqual(e.status_code, status)
        self.assertEqual(e.body, body)
        self.assertEqual(e.code, "api_error")
        self.assertEqual(e.retries, 0)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(c.sleeps, [])
        self.assertIs(type(e), InsufficientCreditsError)
        return e

    def test_http_402(self):
        rec = Recorder(json_response(MUSE_BILLING, 402))
        e = self._assert_credits_error(rec, 402, MUSE_BILLING)
        self.assertIn("Billing is not configured", str(e))
        self.assertIn("Hint: check your billing and credit settings.", str(e))
        self.assertNotIn("rate limit", str(e).lower())

    def test_http_402_japanese_hint(self):
        rec = Recorder(json_response(MUSE_BILLING, 402))
        e = self._assert_credits_error(rec, 402, MUSE_BILLING, lang="ja")
        self.assertIn("ヒント: 課金・クレジット設定を確認してください。", str(e))

    def test_xai_403_credits(self):
        rec = Recorder(json_response(XAI_NO_CREDITS, 403))
        e = self._assert_credits_error(rec, 403, XAI_NO_CREDITS)
        self.assertIn("doesn't have any credits or licenses", str(e))
        self.assertIn("Hint: check your billing and credit settings.", str(e))
        self.assertNotIn("may not have permission", str(e))

    def test_openai_429_insufficient_quota_is_not_retried(self):
        rec = Recorder(json_response(OPENAI_QUOTA, 429, {"retry-after": "3"}))
        e = self._assert_credits_error(rec, 429, OPENAI_QUOTA)
        self.assertIn("exceeded your current quota", str(e))
        self.assertIn("Hint: check your billing and credit settings.", str(e))
        self.assertNotIn("Wait a while and retry", str(e))

    def test_normal_403_stays_permission_denied(self):
        rec = Recorder(json_response(NORMAL_403, 403))
        c = make_sync(rec, max_retries=2)
        with self.assertRaises(PermissionDeniedError) as cm:
            c.request("/x", {})
        self.assertNotIsInstance(cm.exception, InsufficientCreditsError)
        self.assertEqual(len(rec.requests), 1)
        self.assertIn("may not have permission", str(cm.exception))
        self.assertNotIn("billing and credit settings", str(cm.exception))

    def test_normal_429_is_still_retried(self):
        rec = Recorder(
            json_response(NORMAL_429, 429, {"retry-after": "3"}),
            json_response({"ok": True}),
        )
        c = make_sync(rec, max_retries=2)
        self.assertEqual(c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)
        self.assertEqual(c.sleeps, [3.0])

    def test_normal_429_exhausted_stays_rate_limit_error(self):
        rec = Recorder(json_response(NORMAL_429, 429))
        c = make_sync(rec, max_retries=1)
        with self.assertRaises(RateLimitError) as cm:
            c.request("/x", {})
        self.assertNotIsInstance(cm.exception, InsufficientCreditsError)
        self.assertEqual(len(rec.requests), 2)
        self.assertIn("Wait a while and retry", str(cm.exception))

    def test_stream_open_raises_credits_error(self):
        cases = (
            (402, MUSE_BILLING),
            (403, XAI_NO_CREDITS),
            (429, OPENAI_QUOTA),
        )
        for status, body in cases:
            with self.subTest(status=status):
                rec = Recorder(json_response(body, status))
                c = make_sync(rec, max_retries=2)
                with self.assertRaises(InsufficientCreditsError) as cm:
                    c.request_stream("/x", {})
                self.assertEqual(cm.exception.status_code, status)
                self.assertEqual(len(rec.requests), 1)
                self.assertEqual(c.sleeps, [])

    def test_stream_open_normal_429_is_retried(self):
        rec = Recorder(
            json_response(NORMAL_429, 429),
            sse_response("data: ok\n\n"),
        )
        c = make_sync(rec, max_retries=2)
        events = list(c.request_stream("/x", {}))
        self.assertEqual([e.data for e in events], ["ok"])
        self.assertEqual(len(rec.requests), 2)


class AsyncRequestTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)
        self.sleeps = []

    def make(self, rec, **kw):
        c = _AsyncOpenAIClient(api_key="k", transport=rec.transport, **kw)

        async def record_sleep(seconds):
            self.sleeps.append(seconds)

        c._sleep = record_sleep
        self.addAsyncCleanup(c.aclose)
        return c

    async def test_http_402(self):
        rec = Recorder(json_response(MUSE_BILLING, 402))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.status_code, 402)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])
        self.assertIn("billing and credit settings", str(cm.exception))

    async def test_xai_403_credits(self):
        rec = Recorder(json_response(XAI_NO_CREDITS, 403))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.status_code, 403)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])

    async def test_openai_429_insufficient_quota_is_not_retried(self):
        rec = Recorder(json_response(OPENAI_QUOTA, 429, {"retry-after": "3"}))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError) as cm:
            await c.request("/x", {})
        self.assertEqual(cm.exception.status_code, 429)
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])

    async def test_normal_429_is_still_retried(self):
        rec = Recorder(
            json_response(NORMAL_429, 429, {"retry-after": "3"}),
            json_response({"ok": True}),
        )
        c = self.make(rec, max_retries=2)
        self.assertEqual(await c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)
        self.assertEqual(self.sleeps, [3.0])

    async def test_stream_open_raises_credits_error(self):
        rec = Recorder(json_response(OPENAI_QUOTA, 429))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(InsufficientCreditsError):
            await c.request_stream("/x", {})
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(self.sleeps, [])


class ExportTest(unittest.TestCase):
    def test_exported_from_package(self):
        import llm_ai_api

        self.assertIs(llm_ai_api.InsufficientCreditsError, InsufficientCreditsError)
        self.assertIn("InsufficientCreditsError", llm_ai_api.__all__)
        self.assertTrue(issubclass(InsufficientCreditsError, APIStatusError))


if __name__ == "__main__":
    unittest.main()
