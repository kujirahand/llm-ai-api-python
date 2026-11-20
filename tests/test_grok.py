import asyncio
import os
import unittest
from unittest import mock

from llm_ai_api import GrokClient, LLMConfigError, llm, models
from llm_ai_api._async_clients import _AsyncGrokClient
from llm_ai_api.llm import _ASYNC_PROVIDERS

from .helpers import FreshRecorder, Recorder, json_response

REPLY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
MSGS = [{"role": "user", "content": "q"}]
URL = "https://api.x.ai/v1/chat/completions"


class GrokTest(unittest.TestCase):
    def test_llm_creates_grok_client(self):
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "k"}, clear=True):
            m = llm("grok:grok-4.7")
        self.assertIsInstance(m.client, GrokClient)
        self.assertEqual(m.provider, "grok")
        self.assertEqual(m.model, "grok-4.7")

    def test_missing_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMConfigError) as cm:
                llm("grok:grok-4.7")
        self.assertEqual(cm.exception.code, "missing_api_key")

    def test_default_base_url_and_environment_key(self):
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "env-key"}, clear=True):
            rec = Recorder(json_response(REPLY))
            GrokClient(transport=rec.transport).chat("grok-4.7", MSGS)
        self.assertEqual(str(rec.requests[0].url), URL)
        self.assertEqual(rec.requests[0].headers["authorization"], "Bearer env-key")

    def test_environment_base_url_wins(self):
        env = {"XAI_API_KEY": "k", "XAI_BASE_URL": "http://example.test/v1"}
        with mock.patch.dict(os.environ, env, clear=True):
            rec = Recorder(json_response(REPLY))
            GrokClient(transport=rec.transport).chat("grok-4.7", MSGS)
        self.assertEqual(
            str(rec.requests[0].url), "http://example.test/v1/chat/completions"
        )

    def test_ask_round_trip(self):
        with mock.patch.dict(os.environ, {"XAI_API_KEY": "k"}, clear=True):
            rec = Recorder(json_response(REPLY))
            m = llm("grok:grok-4.7", transport=rec.transport)
            self.assertEqual(m.ask("q"), "ok")
        self.assertEqual(rec.body()["model"], "grok-4.7")
        self.assertEqual(rec.body()["messages"], MSGS)

    def test_async_client_registered(self):
        self.assertIs(_ASYNC_PROVIDERS["grok"], _AsyncGrokClient)

        async def run():
            with mock.patch.dict(os.environ, {"XAI_API_KEY": "k"}, clear=True):
                rec = FreshRecorder(lambda: json_response(REPLY))
                m = llm("grok:grok-4.7", transport=rec.transport)
                try:
                    self.assertEqual(await m.aask("q"), "ok")
                finally:
                    await m.aclose()
            self.assertEqual(str(rec.requests[0].url), URL)

        asyncio.run(run())

    def test_model_constant(self):
        self.assertEqual(models.GROK_GROK_4_7, "grok:grok-4.7")


if __name__ == "__main__":
    unittest.main()
