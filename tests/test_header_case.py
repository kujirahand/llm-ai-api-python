"""Case-insensitive header precedence for sync and async requests."""
import unittest

from llm_ai_api import AnthropicClient, OpenAIClient, OpenRouterClient
from llm_ai_api._async_clients import _AsyncAnthropicClient, _AsyncOpenAIClient, _AsyncOpenRouterClient
from .helpers import Recorder, json_response

REPLY = {"content": [{"type": "text", "text": "ok"}]}
MESSAGES = [{"role": "user", "content": "hello"}]


class HeaderCaseTest(unittest.TestCase):
    def test_request_headers_and_openrouter_precedence(self):
        rec = Recorder(json_response({}))
        with OpenAIClient(api_key="key", headers={"authorization": "one", "AUTHORIZATION": "two"}, transport=rec.transport) as c:
            c.request("/test", {}, headers={"Authorization": "three"})
        self.assertEqual(rec.requests[0].headers.get_list("authorization"), ["three"])
        with OpenRouterClient(api_key="key", headers={"http-referer": "custom"}, app_url="default", transport=rec.transport) as c:
            self.assertEqual(c._headers(False, None)["http-referer"], "custom")

    def test_version_and_cache_context(self):
        rec = Recorder(json_response(REPLY))
        with AnthropicClient(api_key="key", headers={"Anthropic-Version": "old"}, transport=rec.transport) as c:
            c.chat("model", MESSAGES, temperature=0.2)
            self.assertEqual(rec.requests[0].headers.get_list("anthropic-version"), ["old"])
            self.assertEqual(rec.body()["temperature"], 0.2)
            context = c._cache_context()
        with AnthropicClient(api_key="key", anthropic_version="other", headers={"anthropic-version": "old"}, transport=rec.transport) as c:
            self.assertEqual(context, c._cache_context())
        with AnthropicClient(api_key="key", anthropic_version="old", headers={"Anthropic-Version": "2026-10-21"}, transport=rec.transport) as c:
            c.chat("model", MESSAGES, temperature=0.2)
            self.assertNotIn("temperature", rec.body())


class AsyncHeaderCaseTest(unittest.IsolatedAsyncioTestCase):
    async def test_request_headers_and_openrouter_precedence(self):
        rec = Recorder(json_response({}))
        c = _AsyncOpenAIClient(api_key="key", headers={"authorization": "one", "AUTHORIZATION": "two"}, transport=rec.transport)
        try:
            await c.request("/test", {}, headers={"Authorization": "three"})
            self.assertEqual(rec.requests[0].headers.get_list("authorization"), ["three"])
        finally:
            await c.aclose()
        c = _AsyncOpenRouterClient(api_key="key", headers={"http-referer": "custom"}, app_url="default", transport=rec.transport)
        try:
            self.assertEqual(c._headers(False, None)["http-referer"], "custom")
        finally:
            await c.aclose()

    async def test_version_and_cache_context(self):
        rec = Recorder(json_response(REPLY))
        c = _AsyncAnthropicClient(api_key="key", headers={"Anthropic-Version": "old"}, transport=rec.transport)
        try:
            await c.achat("model", MESSAGES, temperature=0.2)
            self.assertEqual(rec.requests[0].headers.get_list("anthropic-version"), ["old"])
            self.assertEqual(rec.body()["temperature"], 0.2)
            context = c._cache_context()
        finally:
            await c.aclose()
        c = _AsyncAnthropicClient(api_key="key", anthropic_version="other", headers={"anthropic-version": "old"}, transport=rec.transport)
        try:
            self.assertEqual(context, c._cache_context())
        finally:
            await c.aclose()
        c = _AsyncAnthropicClient(api_key="key", anthropic_version="old", headers={"Anthropic-Version": "2026-10-21"}, transport=rec.transport)
        try:
            await c.achat("model", MESSAGES, temperature=0.2)
            self.assertNotIn("temperature", rec.body())
        finally:
            await c.aclose()
