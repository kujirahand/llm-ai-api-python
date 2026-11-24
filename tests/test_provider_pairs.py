"""Built-in providers are registered as sync/async pairs from one table."""

from __future__ import annotations

import sys
import unittest

from llm_ai_api import LLMConfigError, llm
from llm_ai_api.llm import _ASYNC_PROVIDERS, _PROVIDER_PAIRS, _PROVIDERS

from .helpers import FreshRecorder, json_response

parse_model_spec = sys.modules["llm_ai_api.llm"].parse_model_spec

OPENAI_REPLY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
CLAUDE_REPLY = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}


def _reply_for(name: str) -> dict:
    return CLAUDE_REPLY if name in ("anthropic", "claude") else OPENAI_REPLY


class ProviderPairsTest(unittest.TestCase):
    def test_derived_maps_match_pairs(self):
        self.assertEqual(set(_PROVIDER_PAIRS), set(_PROVIDERS))
        self.assertEqual(set(_PROVIDER_PAIRS), set(_ASYNC_PROVIDERS))
        for name, (sync, async_client) in _PROVIDER_PAIRS.items():
            self.assertIs(_PROVIDERS[name], sync, name)
            self.assertIs(_ASYNC_PROVIDERS[name], async_client, name)

    def test_claude_is_alias_of_anthropic(self):
        self.assertIs(_PROVIDER_PAIRS["claude"][0], _PROVIDER_PAIRS["anthropic"][0])
        self.assertIs(_PROVIDER_PAIRS["claude"][1], _PROVIDER_PAIRS["anthropic"][1])

    def test_parse_model_spec_accepts_every_builtin_name(self):
        for name in _PROVIDER_PAIRS:
            provider, model = parse_model_spec("%s:demo-model" % name)
            self.assertEqual(provider, name)
            self.assertEqual(model, "demo-model")

    def test_parse_model_spec_splits_at_first_colon(self):
        self.assertEqual(
            parse_model_spec("openrouter:meta/llama:free"),
            ("openrouter", "meta/llama:free"),
        )

    def test_unknown_provider(self):
        with self.assertRaises(LLMConfigError) as ctx:
            parse_model_spec("unknown:x")
        self.assertEqual(ctx.exception.code, "unknown_provider")


class ProviderPairsAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_lazy_async_client_uses_registered_pair(self):
        for name, (sync, async_client) in _PROVIDER_PAIRS.items():
            rec = FreshRecorder(lambda reply=_reply_for(name): json_response(reply))
            m = llm("%s:demo-model" % name, api_key="k", transport=rec.transport)
            self.assertIsInstance(m.client, sync)
            self.assertIsNone(m._async_client_instance)
            text = await m.aask("q")
            self.assertEqual(text, "ok")
            self.assertIsInstance(m._async_client_instance, async_client)
            self.assertIs(type(m._async_client_instance), async_client)
            await m.aclose()

    async def test_async_client_inherits_resolved_settings(self):
        rec = FreshRecorder(lambda: json_response(OPENAI_REPLY))
        m = llm(
            "openai:demo-model",
            api_key="k",
            base_url="https://example.test/v1",
            max_retries=2,
            transport=rec.transport,
        )
        m.set_config(max_retries=0)
        self.assertIsNone(m._async_client_instance)
        await m.aask("q")
        async_client = m._async_client_instance
        self.assertEqual(async_client.base_url, m.client.base_url)
        self.assertEqual(async_client.base_url, "https://example.test/v1")
        self.assertEqual(async_client.max_retries, 0)
        self.assertIs(async_client.cache, m.client.cache)
        self.assertIs(async_client.log, m.client.log)
        self.assertEqual(async_client.connection, m.client.connection)
        self.assertEqual(async_client._api_key, m.client._api_key)
        await m.aclose()
