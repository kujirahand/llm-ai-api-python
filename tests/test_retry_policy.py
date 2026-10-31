"""Retry policy (#26): which transport errors are retried, Retry-After cap, set_config()."""

import unittest
from unittest.mock import patch

import httpx

from llm_ai_api import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    LLMConfigError,
    OpenAIClient,
    RateLimitError,
    llm,
    set_cache,
    set_log,
)
from llm_ai_api._async_clients import _AsyncOpenAIClient

from .helpers import Recorder, json_response

OK = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}

RETRY_AFTER_CASES = [
    ("Wed, 21 Oct 2015 07:28:10 GMT", 5.0),
    ("Wed, 21 Oct 2015 07:28:03 GMT", 3.0),
    ("Wed, 21 Oct 2015 07:27:59 GMT", 0.5),
    ("NaN", 0.5), ("inf", 0.5), ("-inf", 0.5),
    ("-1", 0.5), ("invalid", 0.5), ("0", 0.0),
]


def make(rec, **kw):
    c = OpenAIClient(api_key="k", transport=rec.transport, **kw)
    c.sleeps = []
    c._sleep = c.sleeps.append
    return c


class _Base(unittest.TestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)


class TransportRetryTest(_Base):
    def test_connect_stage_errors_are_retried(self):
        cases = [
            (httpx.ConnectError("down"), APIConnectionError, "connection_error"),
            (httpx.ConnectTimeout("slow connect"), APITimeoutError, "timeout"),
            (httpx.PoolTimeout("pool"), APITimeoutError, "timeout"),
        ]
        for exc, cls, code in cases:
            with self.subTest(exc=type(exc).__name__):
                rec = Recorder(exc)
                c = make(rec, max_retries=2)
                with self.assertRaises(cls) as cm:
                    c.request("/x", {})
                self.assertEqual(cm.exception.code, code)
                self.assertEqual(len(rec.requests), 3)
                self.assertEqual(len(c.sleeps), 2)

    def test_connect_error_then_success(self):
        rec = Recorder(httpx.ConnectError("down"), json_response({"ok": True}))
        c = make(rec)
        self.assertEqual(c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)

    def test_read_timeout_not_retried_by_default(self):
        rec = Recorder(httpx.ReadTimeout("slow"))
        c = make(rec, max_retries=2)
        with self.assertRaises(APITimeoutError) as cm:
            c.request("/x", {})
        self.assertEqual(cm.exception.code, "timeout")
        self.assertEqual((len(rec.requests), c.sleeps), (1, []))

    def test_read_timeout_retried_when_enabled(self):
        rec = Recorder(httpx.ReadTimeout("slow"))
        c = make(rec, max_retries=2, retry_read_timeout=True)
        with self.assertRaises(APITimeoutError):
            c.request("/x", {})
        self.assertEqual(len(rec.requests), 3)

        rec = Recorder(httpx.ReadTimeout("slow"), json_response({"ok": True}))
        c = make(rec, retry_read_timeout=True)
        self.assertEqual(c.request("/x", {}), {"ok": True})

    def test_other_post_send_errors_never_retried(self):
        cases = [
            (httpx.ReadError("reset"), APIConnectionError, "connection_error"),
            (httpx.WriteError("broken pipe"), APIConnectionError, "connection_error"),
            (httpx.RemoteProtocolError("bad"), APIConnectionError, "connection_error"),
            (httpx.DecodingError("bad gzip"), APIConnectionError, "connection_error"),
            (httpx.WriteTimeout("slow write"), APITimeoutError, "timeout"),
        ]
        for exc, cls, code in cases:
            for opt_in in (False, True):
                with self.subTest(exc=type(exc).__name__, retry_read_timeout=opt_in):
                    rec = Recorder(exc)
                    c = make(rec, max_retries=2, retry_read_timeout=opt_in)
                    with self.assertRaises(cls) as cm:
                        c.request("/x", {})
                    self.assertEqual(cm.exception.code, code)
                    self.assertEqual(len(rec.requests), 1)

    def test_streaming_uses_the_same_classification(self):
        rec = Recorder(httpx.ReadTimeout("slow"))
        c = make(rec, max_retries=2)
        with self.assertRaises(APITimeoutError):
            c.request_stream("/x", {})
        self.assertEqual(len(rec.requests), 1)

        rec = Recorder(httpx.ConnectError("down"))
        c = make(rec, max_retries=2)
        with self.assertRaises(APIConnectionError):
            c.request_stream("/x", {})
        self.assertEqual(len(rec.requests), 3)


class StatusRetryTest(_Base):
    def test_retry_after_dates_and_invalid_values(self):
        for header, expected in RETRY_AFTER_CASES:
            with self.subTest(header=header):
                rec = Recorder(json_response({}, 429, {"retry-after": header}))
                c = make(rec, retry_after_max=5, max_retries=1)
                self.addCleanup(c.close)
                with patch("llm_ai_api._http.time.time", return_value=1445412480), \
                        patch("llm_ai_api._http.random.random", return_value=0.5):
                    with self.assertRaises(RateLimitError):
                        c.request("/x", {})
                self.assertEqual(c.sleeps, [expected])

    def test_status_retries_unchanged(self):
        rec = Recorder(json_response({}, 500))
        c = make(rec, max_retries=2)
        with self.assertRaises(InternalServerError):
            c.request("/x", {})
        self.assertEqual(len(rec.requests), 3)

        rec = Recorder(json_response({}, 429), json_response({"ok": True}))
        c = make(rec)
        self.assertEqual(c.request("/x", {}), {"ok": True})
        self.assertEqual(len(rec.requests), 2)

    def test_retry_after_capped_by_retry_after_max(self):
        rec = Recorder(json_response({}, 429, {"retry-after": "120"}), json_response({}))
        c = make(rec, retry_after_max=5)
        c.request("/x", {})
        self.assertEqual(c.sleeps, [5.0])

        rec = Recorder(json_response({}, 429, {"retry-after": "3"}), json_response({}))
        c = make(rec, retry_after_max=5)
        c.request("/x", {})
        self.assertEqual(c.sleeps, [3.0])

    def test_default_retry_after_cap_is_60(self):
        rec = Recorder(json_response({}, 503, {"retry-after": "120"}), json_response({}))
        c = make(rec)
        self.assertEqual(c.retry_after_max, 60.0)
        c.request("/x", {})
        self.assertEqual(c.sleeps, [60.0])


class LLMConfigTest(_Base):
    def make(self, rec, **kw):
        m = llm("openai:gpt-x", api_key="k", transport=rec.transport, **kw)
        m.client.sleeps = []
        m.client._sleep = m.client.sleeps.append
        self.addCleanup(m.close)
        return m

    def test_constructor_options(self):
        rec = Recorder(httpx.ReadTimeout("slow"), json_response(OK))
        m = self.make(rec, retry_read_timeout=True, retry_after_max=7, max_retries=1)
        self.assertEqual(
            (m.client.max_retries, m.client.retry_read_timeout, m.client.retry_after_max),
            (1, True, 7),
        )
        self.assertEqual(m.ask("q"), "ok")
        self.assertEqual(len(rec.requests), 2)

    def test_defaults(self):
        m = self.make(Recorder(json_response(OK)))
        self.assertEqual(
            (m.client.max_retries, m.client.retry_read_timeout, m.client.retry_after_max),
            (2, False, 60.0),
        )

    def test_set_config_max_retries(self):
        rec = Recorder(json_response({}, 500))
        m = self.make(rec)
        self.assertIsNone(m.set_config(max_retries=0))
        with self.assertRaises(InternalServerError):
            m.ask("q")
        self.assertEqual(len(rec.requests), 1)

    def test_set_config_retry_read_timeout(self):
        rec = Recorder(httpx.ReadTimeout("slow"), json_response(OK))
        m = self.make(rec)
        m.set_config(retry_read_timeout=True)
        self.assertEqual(m.ask("q"), "ok")
        self.assertEqual(len(rec.requests), 2)

    def test_set_config_changes_only_given_options(self):
        m = self.make(Recorder(json_response(OK)), max_retries=5, retry_read_timeout=True)
        m.set_config(retry_after_max=1.5)
        self.assertEqual(
            (m.client.max_retries, m.client.retry_read_timeout, m.client.retry_after_max),
            (5, True, 1.5),
        )

    def test_set_config_retry_after_max(self):
        rec = Recorder(json_response({}, 429, {"retry-after": "30"}), json_response(OK))
        m = self.make(rec)
        m.set_config(retry_after_max=2)
        m.ask("q")
        self.assertEqual(m.client.sleeps, [2.0])


BAD_RETRY_AFTER_MAX = [-1, -0.5, float("nan"), float("inf"), "10", None]


class RetryAfterMaxValidationTest(_Base):
    def assert_invalid(self, fn, value):
        with self.assertRaises(LLMConfigError) as cm:
            fn(value)
        self.assertEqual(cm.exception.code, "invalid_option")
        self.assertIn("retry_after_max", str(cm.exception))

    def test_client_constructor_rejects_bad_values(self):
        for value in BAD_RETRY_AFTER_MAX:
            with self.subTest(value=value):
                self.assert_invalid(
                    lambda v: OpenAIClient(api_key="k", retry_after_max=v, lang="en"), value
                )
                self.assert_invalid(
                    lambda v: _AsyncOpenAIClient(api_key="k", retry_after_max=v, lang="en"),
                    value,
                )

    def test_llm_rejects_bad_values(self):
        for value in BAD_RETRY_AFTER_MAX:
            with self.subTest(value=value):
                self.assert_invalid(
                    lambda v: llm("openai:gpt-x", api_key="k", retry_after_max=v), value
                )

    def test_set_config_rejects_bad_values_and_changes_nothing(self):
        m = llm("openai:gpt-x", api_key="k", retry_after_max=5)
        self.addCleanup(m.close)
        for value in BAD_RETRY_AFTER_MAX:
            with self.subTest(value=value):
                self.assert_invalid(
                    lambda v: m.set_config(max_retries=7, retry_after_max=v), value
                )
                self.assertEqual((m.client.max_retries, m.client.retry_after_max), (2, 5))

    def test_valid_values_accepted(self):
        for value in (0, 0.0, 1.5, 60):
            with self.subTest(value=value):
                c = OpenAIClient(api_key="k", retry_after_max=value)
                self.addCleanup(c.close)
                m = llm("openai:gpt-x", api_key="k")
                self.addCleanup(m.close)
                m.set_config(retry_after_max=value)
                self.assertEqual(m.client.retry_after_max, value)

    def test_message_is_localized(self):
        with self.assertRaises(LLMConfigError) as cm:
            OpenAIClient(api_key="k", retry_after_max=-1, lang="ja")
        self.assertIn("0 以上", str(cm.exception))

    def test_zero_cap_with_retry_after_ends_in_status_error(self):
        # The original report: a long Retry-After must not leak ValueError from sleep().
        # The real sleep is used on purpose (sleep(0) returns immediately).
        rec = Recorder(json_response({}, 429, {"retry-after": "120"}))
        m = llm("openai:gpt-x", api_key="k", transport=rec.transport,
                retry_after_max=0, max_retries=1)
        self.addCleanup(m.close)
        with self.assertRaises(RateLimitError):
            m.ask("q")
        self.assertEqual(len(rec.requests), 2)

    def test_negative_max_retries_means_no_retry(self):
        # Not validated: the retry loop compares `attempt < max_retries`, so a negative
        # value behaves like 0 (one attempt, no retry).
        rec = Recorder(json_response({}, 500))
        c = make(rec, max_retries=-1)
        with self.assertRaises(InternalServerError):
            c.request("/x", {})
        self.assertEqual((len(rec.requests), c.sleeps), (1, []))


class AsyncRetryTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)
        self.sleeps = []

    async def record_sleep(self, seconds):
        self.sleeps.append(seconds)

    def make(self, rec, **kw):
        c = _AsyncOpenAIClient(api_key="k", transport=rec.transport, **kw)
        c._sleep = self.record_sleep
        self.addAsyncCleanup(c.aclose)
        return c

    def make_llm(self, rec, **kw):
        m = llm("openai:gpt-x", api_key="k", transport=rec.transport, **kw)
        self.addAsyncCleanup(m.aclose)
        return m

    async def test_connect_stage_errors_are_retried(self):
        for exc, cls in [
            (httpx.ConnectError("down"), APIConnectionError),
            (httpx.ConnectTimeout("slow connect"), APITimeoutError),
        ]:
            with self.subTest(exc=type(exc).__name__):
                rec = Recorder(exc)
                c = self.make(rec, max_retries=2)
                with self.assertRaises(cls):
                    await c.request("/x", {})
                self.assertEqual(len(rec.requests), 3)

    async def test_read_timeout_classification(self):
        rec = Recorder(httpx.ReadTimeout("slow"))
        c = self.make(rec, max_retries=2)
        with self.assertRaises(APITimeoutError):
            await c.request("/x", {})
        self.assertEqual(len(rec.requests), 1)

        rec = Recorder(httpx.ReadTimeout("slow"))
        c = self.make(rec, max_retries=2, retry_read_timeout=True)
        with self.assertRaises(APITimeoutError):
            await c.request("/x", {})
        self.assertEqual(len(rec.requests), 3)

    async def test_other_post_send_error_not_retried_even_with_opt_in(self):
        rec = Recorder(httpx.RemoteProtocolError("bad"))
        c = self.make(rec, max_retries=2, retry_read_timeout=True)
        with self.assertRaises(APIConnectionError):
            await c.request("/x", {})
        self.assertEqual(len(rec.requests), 1)

    async def test_retry_after_max(self):
        rec = Recorder(json_response({}, 429, headers={"retry-after": "120"}), json_response({}))
        c = self.make(rec, retry_after_max=5)
        await c.request("/x", {})
        self.assertEqual(self.sleeps, [5.0])

    async def test_retry_after_dates_and_invalid_values(self):
        for header, expected in RETRY_AFTER_CASES:
            with self.subTest(header=header):
                self.sleeps.clear()
                rec = Recorder(json_response({}, 429, {"retry-after": header}))
                c = self.make(rec, retry_after_max=5, max_retries=1)
                with patch("llm_ai_api._http.time.time", return_value=1445412480), \
                        patch("llm_ai_api._async_http.random.random", return_value=0.5):
                    with self.assertRaises(RateLimitError):
                        await c.request("/x", {})
                self.assertEqual(self.sleeps, [expected])

    async def test_llm_options_reach_async_client(self):
        rec = Recorder(json_response(OK))
        m = self.make_llm(rec, max_retries=4, retry_read_timeout=True, retry_after_max=9)
        ac = m._get_async_client()
        self.assertEqual((ac.max_retries, ac.retry_read_timeout, ac.retry_after_max), (4, True, 9))

    async def test_set_config_before_async_client_is_created(self):
        rec = Recorder(httpx.ReadTimeout("slow"), json_response(OK))
        m = self.make_llm(rec)
        m.set_config(retry_read_timeout=True, retry_after_max=3)
        ac = m._get_async_client()
        ac._sleep = self.record_sleep
        self.assertEqual((ac.retry_read_timeout, ac.retry_after_max), (True, 3))
        self.assertEqual(await m.aask("q"), "ok")
        self.assertEqual(len(rec.requests), 2)

    async def test_set_config_after_async_client_is_created(self):
        rec = Recorder(json_response({}, 500))
        m = self.make_llm(rec)
        ac = m._get_async_client()
        ac._sleep = self.record_sleep
        m.set_config(max_retries=0)
        self.assertEqual((m.client.max_retries, ac.max_retries), (0, 0))
        with self.assertRaises(InternalServerError):
            await m.aask("q")
        self.assertEqual(len(rec.requests), 1)

    async def test_zero_cap_with_retry_after_ends_in_status_error(self):
        rec = Recorder(json_response({}, 429, headers={"retry-after": "120"}))
        m = self.make_llm(rec, retry_after_max=0, max_retries=1)
        with self.assertRaises(RateLimitError):
            await m.aask("q")
        self.assertEqual(len(rec.requests), 2)

    async def test_set_config_rejects_nan_after_async_client_is_created(self):
        m = self.make_llm(Recorder(json_response(OK)), retry_after_max=5)
        ac = m._get_async_client()
        with self.assertRaises(LLMConfigError):
            m.set_config(retry_after_max=float("nan"))
        self.assertEqual((m.client.retry_after_max, ac.retry_after_max), (5, 5))

    async def test_status_retry_still_works(self):
        rec = Recorder(json_response({}, 429), json_response(OK))
        m = self.make_llm(rec)
        m._get_async_client()._sleep = self.record_sleep
        self.assertEqual(await m.aask("q"), "ok")
        self.assertEqual(len(rec.requests), 2)

        m.set_config(max_retries=0)
        rec.responses = [json_response({}, 429)]
        with self.assertRaises(RateLimitError):
            await m.aask("q2")
        self.assertEqual(len(rec.requests), 3)


if __name__ == "__main__":
    unittest.main()
