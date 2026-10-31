"""httpx.RequestError subclasses (e.g. DecodingError) and InvalidURL must not leak."""

import unittest
from unittest import mock

import httpx

from llm_ai_api import APIConnectionError, LLMConfigError, llm, set_cache, set_log
from llm_ai_api._async_http import _AsyncBaseClient
from llm_ai_api._http import BaseClient

from .helpers import AsyncFailingStream, FailingStream, Recorder

# Carries userinfo, a query and a fragment so the tests can check URL masking.
BAD_URL = "http://user:pass@host:badport/v1?token=secret#frag"


def _assert_url_masked(test, exc):
    """The error text must hide userinfo, query and fragment, and show `***`."""
    text = str(exc)
    for leaked in ("pass", "secret", "frag"):
        test.assertNotIn(leaked, text)
    test.assertIn("***", text)


class _Base(unittest.TestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)


class SyncRequestErrorTest(_Base):
    def make(self, rec, **kw):
        m = llm("openai:gpt-x", api_key="k", transport=rec.transport, lang="en", **kw)
        self.addCleanup(m.close)
        return m

    def test_decoding_error_becomes_connection_error_without_retries(self):
        rec = Recorder(httpx.DecodingError("bad gzip"))
        m = self.make(rec)
        with mock.patch.object(BaseClient, "_sleep", lambda self, seconds: None):
            with self.assertRaises(APIConnectionError) as cm:
                m.ask("q")
        self.assertEqual(cm.exception.code, "connection_error")
        self.assertNotIsInstance(cm.exception, httpx.HTTPError)
        # The response was already received: not a connection-stage failure (#26).
        self.assertEqual(len(rec.requests), 1)

    def test_decoding_error_while_streaming(self):
        rec = Recorder(httpx.Response(
            200, stream=FailingStream(httpx.DecodingError("bad gzip")),
            headers={"content-type": "text/event-stream"},
        ))
        m = self.make(rec)
        with self.assertRaises(APIConnectionError) as cm:
            list(m.stream("q"))
        self.assertEqual(cm.exception.code, "connection_error")
        self.assertNotIsInstance(cm.exception, httpx.HTTPError)
        # Once the body has started streaming, there is no retry.
        self.assertEqual(len(rec.requests), 1)

    def test_invalid_url_becomes_config_error(self):
        rec = Recorder(httpx.Response(200, json={}))
        m = llm(
            "openai:gpt-x", api_key="k", base_url=BAD_URL, lang="en",
            transport=rec.transport,
        )
        self.addCleanup(m.close)
        with self.assertRaises(LLMConfigError) as cm:
            m.ask("q")
        self.assertEqual(cm.exception.code, "invalid_url")
        self.assertIn("Invalid URL", str(cm.exception))
        _assert_url_masked(self, cm.exception)
        self.assertNotIsInstance(cm.exception, httpx.InvalidURL)


class AsyncRequestErrorTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)

    def make(self, rec=None, **kw):
        if rec is not None:
            kw["transport"] = rec.transport
        m = llm("openai:gpt-x", api_key="k", lang="en", **kw)
        self.addAsyncCleanup(m.aclose)
        return m

    async def test_decoding_error_becomes_connection_error_without_retries(self):
        rec = Recorder(httpx.DecodingError("bad gzip"))
        m = self.make(rec)

        async def no_sleep(self, seconds):
            return None

        with mock.patch.object(_AsyncBaseClient, "_sleep", no_sleep):
            with self.assertRaises(APIConnectionError) as cm:
                await m.aask("q")
        self.assertEqual(cm.exception.code, "connection_error")
        self.assertNotIsInstance(cm.exception, httpx.HTTPError)
        # The response was already received: not a connection-stage failure (#26).
        self.assertEqual(len(rec.requests), 1)

    async def test_decoding_error_while_streaming(self):
        rec = Recorder(httpx.Response(
            200, stream=AsyncFailingStream(httpx.DecodingError("bad gzip")),
            headers={"content-type": "text/event-stream"},
        ))
        m = self.make(rec)
        with self.assertRaises(APIConnectionError) as cm:
            async for _ in m.astream("q"):
                pass
        self.assertEqual(cm.exception.code, "connection_error")
        self.assertNotIsInstance(cm.exception, httpx.HTTPError)
        # Once the body has started streaming, there is no retry.
        self.assertEqual(len(rec.requests), 1)

    async def test_invalid_url_becomes_config_error(self):
        rec = Recorder(httpx.Response(200, json={}))
        m = self.make(rec, base_url=BAD_URL)
        with self.assertRaises(LLMConfigError) as cm:
            await m.aask("q")
        self.assertEqual(cm.exception.code, "invalid_url")
        self.assertIn("Invalid URL", str(cm.exception))
        _assert_url_masked(self, cm.exception)
        self.assertNotIsInstance(cm.exception, httpx.InvalidURL)


if __name__ == "__main__":
    unittest.main()
