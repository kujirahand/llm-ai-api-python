import asyncio
import os
import unittest
from unittest import mock

from llm_ai_api import LLMConfigError, MuseClient, llm, models
from llm_ai_api.llm import _ASYNC_PROVIDERS, _PROVIDERS
from llm_ai_api._async_clients import _AsyncMuseClient

from .helpers import FreshRecorder, Recorder, json_response

REPLY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
MSGS = [{"role": "user", "content": "q"}]


class MuseTest(unittest.TestCase):
    def test_llm_creates_muse_client(self):
        rec = Recorder(json_response(REPLY))
        model = llm("muse:muse-wonder-1.0", api_key="k", transport=rec.transport)
        self.assertIsInstance(model.client, MuseClient)
        self.assertEqual(model.provider, "muse")
        self.assertEqual(model.model, "muse-wonder-1.0")

    def test_model_constant(self):
        self.assertEqual(models.MUSE_MUSE_WONDER_1_0, "muse:muse-wonder-1.0")

    def test_default_base_url(self):
        rec = Recorder(json_response(REPLY))
        MuseClient(api_key="k", transport=rec.transport).chat("m", MSGS)
        self.assertEqual(
            str(rec.requests[0].url), "https://api.meta.ai/v1/chat/completions"
        )

    def test_base_url_from_environment(self):
        with mock.patch.dict(
            os.environ, {"MUSE_BASE_URL": "http://example.test/v1"}, clear=True
        ):
            rec = Recorder(json_response(REPLY))
            MuseClient(api_key="k", transport=rec.transport).chat("m", MSGS)
        self.assertEqual(
            str(rec.requests[0].url), "http://example.test/v1/chat/completions"
        )

    def test_api_key_from_model_api_key(self):
        with mock.patch.dict(os.environ, {"MODEL_API_KEY": "env-key"}, clear=True):
            rec = Recorder(json_response(REPLY))
            MuseClient(transport=rec.transport).chat("m", MSGS)
        self.assertEqual(rec.requests[0].headers["authorization"], "Bearer env-key")

    def test_missing_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMConfigError) as cm:
                llm("muse:muse-wonder-1.0")
        self.assertEqual(cm.exception.code, "missing_api_key")

    def test_ask_round_trip(self):
        rec = Recorder(json_response(REPLY))
        model = llm("muse:muse-wonder-1.0", api_key="k", transport=rec.transport)
        self.assertEqual(model.ask("q"), "ok")
        body = rec.body()
        self.assertEqual(body["model"], "muse-wonder-1.0")
        self.assertEqual(body["messages"], MSGS)
        self.assertNotIn("temperature", body)

    def test_async_client_registered(self):
        self.assertIs(_PROVIDERS["muse"], MuseClient)
        self.assertIs(_ASYNC_PROVIDERS["muse"], _AsyncMuseClient)
        self.assertEqual(_AsyncMuseClient.provider, "muse")
        self.assertEqual(_AsyncMuseClient.api_key_env, "MODEL_API_KEY")
        self.assertEqual(_AsyncMuseClient.base_url_env, "MUSE_BASE_URL")
        self.assertEqual(_AsyncMuseClient.default_base_url, "https://api.meta.ai/v1")

    def test_async_round_trip(self):
        async def run():
            with mock.patch.dict(os.environ, {"MODEL_API_KEY": "k"}, clear=True):
                rec = FreshRecorder(lambda: json_response(REPLY))
                m = llm("muse:muse-wonder-1.0", transport=rec.transport)
                try:
                    self.assertEqual(await m.aask("q"), "ok")
                finally:
                    await m.aclose()
            self.assertEqual(
                str(rec.requests[0].url), "https://api.meta.ai/v1/chat/completions"
            )

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
