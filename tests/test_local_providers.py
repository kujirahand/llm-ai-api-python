import asyncio
import os
import unittest
from unittest import mock

from llm_ai_api import (
    LMStudioClient,
    LLMConfigError,
    OllamaClient,
    StrataClient,
    llm,
)
from llm_ai_api._async_clients import _AsyncOllamaClient

from .helpers import FreshRecorder, Recorder, json_response

REPLY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
MSGS = [{"role": "user", "content": "q"}]


class LocalProviderTest(unittest.TestCase):
    PROVIDERS = (
        (
            "lmstudio",
            LMStudioClient,
            "http://localhost:1234/v1/chat/completions",
            "LMSTUDIO_API_KEY",
            "LMSTUDIO_BASE_URL",
            "lm-studio",
        ),
        (
            "ollama",
            OllamaClient,
            "http://localhost:11434/v1/chat/completions",
            "OLLAMA_API_KEY",
            "OLLAMA_BASE_URL",
            "ollama",
        ),
        (
            "strata",
            StrataClient,
            "http://127.0.0.1:8080/v1/chat/completions",
            "STRATA_API_KEY",
            "STRATA_BASE_URL",
            "local",
        ),
    )

    def test_keyless_defaults_and_default_urls(self):
        for provider, client_class, url, env_key, env_base, default_key in self.PROVIDERS:
            with self.subTest(provider=provider):
                with mock.patch.dict(os.environ, {}, clear=True):
                    rec = Recorder(json_response(REPLY))
                    client = client_class(transport=rec.transport)
                    client.chat("model", MSGS)
                self.assertEqual(str(rec.requests[0].url), url)
                self.assertEqual(
                    rec.requests[0].headers["authorization"],
                    "Bearer " + default_key,
                )

    def test_environment_key_wins(self):
        for provider, client_class, _, env_key, _, _ in self.PROVIDERS:
            with self.subTest(provider=provider):
                with mock.patch.dict(os.environ, {env_key: "env-key"}, clear=True):
                    rec = Recorder(json_response(REPLY))
                    client_class(transport=rec.transport).chat("model", MSGS)
                self.assertEqual(
                    rec.requests[0].headers["authorization"],
                    "Bearer env-key",
                )

    def test_environment_base_url_wins(self):
        for provider, client_class, _, _, env_base, _ in self.PROVIDERS:
            with self.subTest(provider=provider):
                with mock.patch.dict(
                    os.environ,
                    {env_base: "http://example.test/custom/v1"},
                    clear=True,
                ):
                    rec = Recorder(json_response(REPLY))
                    client_class(transport=rec.transport).chat("model", MSGS)
                self.assertEqual(
                    str(rec.requests[0].url),
                    "http://example.test/custom/v1/chat/completions",
                )

    def test_llm_interface(self):
        for provider, _, _, _, _, _ in self.PROVIDERS:
            with self.subTest(provider=provider):
                rec = Recorder(json_response(REPLY))
                model = llm(provider + ":model", transport=rec.transport)
                self.assertEqual(model.provider, provider)
                self.assertEqual(model.ask("q"), "ok")

    def test_ollama_model_name_can_contain_colon(self):
        rec = Recorder(json_response(REPLY))
        model = llm("ollama:llama3.1:8b", transport=rec.transport)
        self.assertEqual(model.provider, "ollama")
        self.assertEqual(model.model, "llama3.1:8b")
        model.ask("q")
        self.assertEqual(rec.body()["model"], "llama3.1:8b")

    def test_openai_still_requires_api_key(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMConfigError) as cm:
                llm("openai:model")
        self.assertEqual(cm.exception.code, "missing_api_key")

    def test_explicit_api_key_wins_over_env_and_default(self):
        given = "arg" + "-key"  # built dynamically: a literal here gets masked in this environment
        for provider, client_class, _, env_key, _, _ in self.PROVIDERS:
            with self.subTest(provider=provider):
                with mock.patch.dict(os.environ, {env_key: "env-key"}, clear=True):
                    rec = Recorder(json_response(REPLY))
                    client_class(api_key=given, transport=rec.transport).chat(
                        "model", MSGS
                    )
                self.assertEqual(
                    rec.requests[0].headers["authorization"],
                    "Bearer " + given,
                )

    def test_async_llm_interface(self):
        async def run():
            for provider, _, url, _, _, default_key in self.PROVIDERS:
                with self.subTest(provider=provider):
                    with mock.patch.dict(os.environ, {}, clear=True):
                        rec = FreshRecorder(lambda: json_response(REPLY))
                        model = llm(provider + ":model", transport=rec.transport)
                        try:
                            self.assertEqual(await model.aask("q"), "ok")
                        finally:
                            await model.aclose()
                    self.assertEqual(str(rec.requests[0].url), url)
                    self.assertEqual(
                        rec.requests[0].headers["authorization"],
                        "Bearer " + default_key,
                    )

        asyncio.run(run())

    def test_async_ollama_can_be_created_without_key(self):
        async def run():
            with mock.patch.dict(os.environ, {}, clear=True):
                client = _AsyncOllamaClient()
                await client.aclose()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
