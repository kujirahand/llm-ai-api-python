"""register_provider(): declared providers, validation, and the sync/async twin (#141)."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest import mock

import httpx

from llm_ai_api import (
    JSONLLog,
    LLMConfigError,
    SQLiteCache,
    llm,
    register_provider,
)
from llm_ai_api._providers import (
    _DECLARED,
    _forget,
    _make_async,
    lookup,
    provider_names,
)

from .helpers import FreshRecorder, Recorder, json_response, sse_response

parse_model_spec = sys.modules["llm_ai_api.llm"].parse_model_spec

OPENAI_REPLY = {
    "model": "m",
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 2},
}
CLAUDE_REPLY = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}
OPENAI_SSE = (
    'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
    "data: [DONE]\n\n"
)
CLAUDE_SSE = (
    'event: content_block_delta\ndata: {"type":"content_block_delta",'
    '"delta":{"type":"text_delta","text":"hi"}}\n\n'
    'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)
BASE = "https://llm.example.test/v1"


def _declared(cls):
    """The declared attributes a class has (the Anthropic classes have no max_tokens_field)."""
    return {name: getattr(cls, name) for name in _DECLARED if hasattr(cls, name)}


class RegistryTestCase(unittest.TestCase):
    """Forget every provider a test registered, so tests do not leak into each other."""

    registered = ()

    def setUp(self):
        self._before = set(provider_names())
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        for name in set(provider_names()) - self._before:
            _forget(name)
        self.assertEqual(set(provider_names()), self._before)


class DeclaredOpenAITest(RegistryTestCase):
    def test_ask_sends_to_declared_url_with_bearer_key(self):
        register_provider("deepseek", base_url=BASE + "/", api_key_env="DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "env-key"
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("deepseek:chat-1", transport=rec.transport) as m:
            self.assertEqual(m.ask("hi", max_tokens=5, temperature=0.2), "ok")
            self.assertEqual(m.provider, "deepseek")
        req = rec.requests[0]
        self.assertEqual(str(req.url), BASE + "/chat/completions")
        self.assertEqual(req.headers["authorization"], "Bearer env-key")
        # Defaults match a plain OpenAI-compatible provider: max_tokens, no stream_options.
        self.assertEqual(rec.body(), {
            "model": "chat-1",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 5,
            "temperature": 0.2,
        })

    def test_rules_of_other_providers_do_not_apply(self):
        register_provider("custom", base_url=BASE, api_key_default="k")
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("custom:gpt-6-astra", transport=rec.transport) as m:
            m.ask("hi", temperature=0.5)
        self.assertEqual(rec.body()["temperature"], 0.5)  # the openai table is not applied

    def test_max_tokens_field_and_stream_usage(self):
        register_provider(
            "fieldy",
            base_url=BASE,
            api_key_default="k",
            max_tokens_field="max_completion_tokens",
            stream_include_usage=True,
        )
        rec = Recorder(json_response(OPENAI_REPLY), sse_response(OPENAI_SSE))
        with llm("fieldy:m", transport=rec.transport) as m:
            m.ask("hi", max_tokens=7)
            self.assertEqual(rec.body()["max_completion_tokens"], 7)
            self.assertNotIn("max_tokens", rec.body())
            self.assertEqual("".join(m.ask_stream("hi")), "hello")
        self.assertEqual(rec.body()["stream_options"], {"include_usage": True})

    def test_base_url_env_and_explicit_base_url(self):
        register_provider("envy", base_url=BASE, api_key_default="k", base_url_env="ENVY_BASE_URL")
        os.environ["ENVY_BASE_URL"] = "https://other.example.test/v1"
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("envy:m", transport=rec.transport) as m:
            m.ask("hi")
            self.assertEqual(str(rec.requests[-1].url), "https://other.example.test/v1/chat/completions")
        with llm("envy:m", transport=rec.transport, base_url="https://third.example.test/v1") as m:
            m.ask("hi")
        self.assertEqual(str(rec.requests[-1].url), "https://third.example.test/v1/chat/completions")

    def test_api_key_env_tuple_first_has_priority(self):
        register_provider("multi", base_url=BASE, api_key_env=("MULTI_A", "MULTI_B"))
        os.environ["MULTI_B"] = "from-b"
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("multi:m", transport=rec.transport) as m:
            m.ask("hi")
        self.assertEqual(rec.requests[0].headers["authorization"], "Bearer from-b")
        os.environ["MULTI_A"] = "from-a"
        with llm("multi:m", transport=rec.transport) as m:
            m.ask("hi")
        self.assertEqual(rec.requests[1].headers["authorization"], "Bearer from-a")

    def test_missing_key_is_reported_at_creation(self):
        register_provider("needkey", base_url=BASE, api_key_env="NEEDKEY_API_KEY")
        with self.assertRaises(LLMConfigError) as ctx:
            llm("needkey:m", lang="en")
        self.assertEqual(ctx.exception.code, "missing_api_key")
        self.assertIn("NEEDKEY_API_KEY", str(ctx.exception))

    def test_missing_key_without_env_name(self):
        register_provider("noenv", base_url=BASE)
        with self.assertRaises(LLMConfigError) as ctx:
            llm("noenv:m", lang="en")
        self.assertEqual(ctx.exception.code, "missing_api_key")
        self.assertIn("api_key=", str(ctx.exception))

    def test_optional_key(self):
        register_provider("open", base_url=BASE, api_key_required=False)
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("open:m", transport=rec.transport) as m:
            m.ask("hi")
        self.assertNotIn("authorization", rec.requests[0].headers)
        with llm("open:m", transport=rec.transport, api_key="given") as m:
            m.ask("hi")
        self.assertEqual(rec.requests[1].headers["authorization"], "Bearer given")

    def test_api_key_default(self):
        register_provider("localbox", base_url="http://127.0.0.1:8080/v1", api_key_default="local")
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("localbox:m", transport=rec.transport) as m:
            m.ask("hi")
        self.assertEqual(rec.requests[0].headers["authorization"], "Bearer local")

    def test_api_key_header_auth(self):
        register_provider(
            "corp", base_url=BASE, api_key_env="CORP_KEY", auth_header="api-key", auth_scheme=""
        )
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("corp:m", transport=rec.transport, api_key="secret") as m:
            m.ask("hi")
        headers = rec.requests[0].headers
        self.assertEqual(headers["api-key"], "secret")
        self.assertNotIn("authorization", headers)

    def test_custom_scheme(self):
        register_provider("tokeny", base_url=BASE, api_key_default="k", auth_scheme="Token")
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("tokeny:m", transport=rec.transport) as m:
            m.ask("hi")
        self.assertEqual(rec.requests[0].headers["authorization"], "Token k")

    def test_fixed_headers_and_caller_override(self):
        register_provider(
            "hdr", base_url=BASE, api_key_default="k", headers={"X-Org": "acme", "X-Tag": "a"}
        )
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("hdr:m", transport=rec.transport, headers={"x-tag": "mine"}) as m:
            m.ask("hi")
        headers = rec.requests[0].headers
        self.assertEqual(headers["x-org"], "acme")
        self.assertEqual(headers["x-tag"], "mine")

    def test_header_cannot_replace_auth(self):
        register_provider("hdr2", base_url=BASE, api_key_default="k", headers={"Authorization": "fixed"})
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("hdr2:m", transport=rec.transport) as m:
            m.ask("hi")
        self.assertEqual(rec.requests[0].headers["authorization"], "Bearer k")

    def test_raw_layer_works(self):
        register_provider("rawy", base_url=BASE, api_key_default="k")
        rec = Recorder(json_response({"x": 1}))
        with llm("rawy:m", transport=rec.transport) as m:
            self.assertEqual(m.client.request("/embeddings", {"input": "a"}), {"x": 1})
        self.assertEqual(str(rec.requests[0].url), BASE + "/embeddings")

    def test_openrouter_style_options_are_rejected_for_registered(self):
        register_provider("plain", base_url=BASE, api_key_default="k")
        with self.assertRaises(TypeError):
            llm("plain:m", app_url="https://x.test")


class DeclaredAnthropicTest(RegistryTestCase):
    def test_anthropic_format(self):
        register_provider(
            "claude-proxy",
            api_format="anthropic",
            base_url="https://proxy.example.test",
            api_key_env="PROXY_KEY",
        )
        os.environ["PROXY_KEY"] = "pk"
        rec = Recorder(json_response(CLAUDE_REPLY))
        with llm("claude-proxy:some-model", transport=rec.transport) as m:
            self.assertEqual(m.ask("hi", system="be brief", temperature=0.3), "ok")
            self.assertEqual(m.provider, "claude-proxy")
        req = rec.requests[0]
        self.assertEqual(str(req.url), "https://proxy.example.test/v1/messages")
        self.assertEqual(req.headers["x-api-key"], "pk")
        self.assertEqual(req.headers["anthropic-version"], "2026-10-21")
        body = rec.body()
        self.assertEqual(body["system"], "be brief")
        self.assertEqual(body["max_tokens"], 16000)
        # The version-dependent rule of the Anthropic format applies to the registration too.
        self.assertNotIn("temperature", body)

    def test_anthropic_version_override_keeps_temperature(self):
        register_provider(
            "claude-old", api_format="anthropic", base_url="https://p.example.test", api_key_default="k"
        )
        rec = Recorder(json_response(CLAUDE_REPLY))
        with llm("claude-old:m", transport=rec.transport, anthropic_version="2023-06-01") as m:
            m.ask("hi", temperature=0.3)
        self.assertEqual(rec.body()["temperature"], 0.3)
        self.assertEqual(rec.requests[0].headers["anthropic-version"], "2023-06-01")

    def test_anthropic_stream_images_and_schema_follow_format(self):
        register_provider(
            "claude-fmt", api_format="anthropic", base_url="https://p.example.test", api_key_default="k"
        )
        rec = Recorder(sse_response(CLAUDE_SSE), json_response(CLAUDE_REPLY), json_response(
            {"content": [{"type": "text", "text": "{\"a\": 1}"}], "stop_reason": "end_turn"}
        ))
        with llm("claude-fmt:m", transport=rec.transport) as m:
            self.assertEqual("".join(m.ask_stream("hi")), "hi")
            m.ask("look", images=["https://img.example.test/a.png"])
            self.assertEqual(
                rec.body()["messages"][0]["content"][1],
                {"type": "image", "source": {"type": "url", "url": "https://img.example.test/a.png"}},
            )
            result = m.chat(
                [{"role": "user", "content": "q"}],
                schema={"type": "object", "properties": {"a": {"type": "integer"}}},
            )
            self.assertEqual(result.parsed, {"a": 1})
            self.assertIn("output_config", rec.body())

    def test_auth_header_override_and_optional_key(self):
        register_provider(
            "claude-bearer",
            api_format="anthropic",
            base_url="https://p.example.test",
            api_key_required=False,
            auth_header="Authorization",
            auth_scheme="Bearer",
        )
        rec = Recorder(json_response(CLAUDE_REPLY))
        with llm("claude-bearer:m", transport=rec.transport, api_key="t") as m:
            m.ask("hi")
        headers = rec.requests[0].headers
        self.assertEqual(headers["authorization"], "Bearer t")
        self.assertNotIn("x-api-key", headers)
        with llm("claude-bearer:m", transport=rec.transport) as m:
            m.ask("hi")
        self.assertNotIn("authorization", rec.requests[1].headers)
        self.assertEqual(rec.requests[1].headers["anthropic-version"], "2026-10-21")

    def test_models_list_uses_anthropic_path(self):
        register_provider(
            "claude-list", api_format="anthropic", base_url="https://p.example.test", api_key_default="k"
        )
        rec = Recorder(json_response({"data": [{"id": "a"}, {"id": "b"}], "has_more": False}))
        with llm("claude-list:m", transport=rec.transport) as m:
            self.assertEqual(m.models(), ["a", "b"])
        self.assertEqual(str(rec.requests[0].url), "https://p.example.test/v1/models")

    def test_openai_only_fields_are_rejected(self):
        for kwargs in ({"max_tokens_field": "max_tokens"}, {"stream_include_usage": False}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(LLMConfigError) as ctx:
                    register_provider(
                        "mixed", api_format="anthropic", base_url=BASE, api_key_default="k", **kwargs
                    )
                self.assertEqual(ctx.exception.code, "invalid_provider")
        self.assertIsNone(lookup("mixed"))


class SharedMachineryTest(RegistryTestCase):
    def test_models_openai_format(self):
        register_provider("lister", base_url=BASE, api_key_default="k")
        rec = Recorder(json_response({"data": [{"id": "m1"}, {"id": "m2"}]}))
        with llm("lister:x", transport=rec.transport) as m:
            self.assertEqual(m.models(), ["m1", "m2"])
        self.assertEqual(str(rec.requests[0].url), BASE + "/models")

    def test_models_follows_the_created_client_after_replace(self):
        register_provider("swap", base_url=BASE, api_key_default="k", models=True)
        rec = Recorder(json_response({"data": [{"id": "m1"}]}))
        old = llm("swap:x", transport=rec.transport)
        register_provider("swap", base_url=BASE, api_key_default="k", models=False, replace=True)
        with old as m:
            self.assertEqual(m.models(), ["m1"])
        with llm("swap:x", transport=rec.transport) as m:
            with self.assertRaises(LLMConfigError) as ctx:
                m.models()
        self.assertEqual(ctx.exception.code, "unsupported_models")

    def test_cache_context_includes_fixed_headers_only_when_set(self):
        register_provider("fh1", base_url=BASE, api_key_default="k", headers={"X-A": "1"})
        register_provider("fh2", base_url=BASE, api_key_default="k", headers={"X-A": "2"})
        register_provider("fh0", base_url=BASE, api_key_default="k")
        with llm("fh1:m") as a, llm("fh2:m") as b, llm("fh0:m") as c:
            self.assertNotEqual(a.client._cache_context(), b.client._cache_context())
            self.assertNotIn("fixed_headers", c.client._cache_context())
        # Built-ins have no fixed headers, so their cache keys stay as they were.
        for spec in ("openai:m", "anthropic:m", "openrouter:m"):
            with llm(spec, api_key="k") as m:
                self.assertNotIn("fixed_headers", m.client._cache_context())

    def test_replacing_fixed_headers_misses_the_cache(self):
        register_provider("fhc", base_url=BASE, api_key_default="k", headers={"X-Tenant": "a"})
        with tempfile.TemporaryDirectory() as tmp:
            cache = SQLiteCache(os.path.join(tmp, "cache.db"))
            rec = Recorder(json_response(OPENAI_REPLY))
            with llm("fhc:m", transport=rec.transport, cache=cache, log=False) as m:
                m.ask("same")
                m.ask("same")
            self.assertEqual(len(rec.requests), 1)  # same definition: the second call hits
            register_provider(
                "fhc", base_url=BASE, api_key_default="k", headers={"X-Tenant": "b"}, replace=True
            )
            with llm("fhc:m", transport=rec.transport, cache=cache, log=False) as m:
                m.ask("same")
            self.assertEqual(len(rec.requests), 2)  # the new fixed header is a new key
            self.assertEqual(rec.requests[1].headers["x-tenant"], "b")

    def test_models_false_is_unsupported(self):
        register_provider("nolist", base_url=BASE, api_key_default="k", models=False)
        with llm("nolist:x", transport=Recorder(json_response({})).transport) as m:
            with self.assertRaises(LLMConfigError) as ctx:
                m.models()
        self.assertEqual(ctx.exception.code, "unsupported_models")

    def test_transcribe_is_not_supported(self):
        register_provider("noaudio", base_url=BASE, api_key_default="k")
        with llm("noaudio:x", transport=Recorder(json_response({})).transport) as m:
            with self.assertRaises(LLMConfigError) as ctx:
                m.transcribe(b"RIFF....WAVE")
        self.assertEqual(ctx.exception.code, "unsupported_modality")

    def test_images_use_openai_parts(self):
        register_provider("vision", base_url=BASE, api_key_default="k")
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("vision:m", transport=rec.transport) as m:
            m.ask("look", images=["https://img.example.test/a.png"])
        self.assertEqual(
            rec.body()["messages"][0]["content"][1],
            {"type": "image_url", "image_url": {"url": "https://img.example.test/a.png"}},
        )

    def test_cache_and_log(self):
        register_provider("cachey", base_url=BASE, api_key_default="k")
        with tempfile.TemporaryDirectory() as tmp:
            log_path = os.path.join(tmp, "log.jsonl")
            rec = Recorder(json_response(OPENAI_REPLY))
            cache = SQLiteCache(os.path.join(tmp, "cache.db"))
            with llm(
                "cachey:m", transport=rec.transport, cache=cache, log=JSONLLog(log_path)
            ) as m:
                self.assertEqual(m.ask("same"), "ok")
                self.assertEqual(m.ask("same"), "ok")
            self.assertEqual(len(rec.requests), 1)  # the second call came from the cache
            with open(log_path, encoding="utf-8") as f:
                lines = f.read().splitlines()
            self.assertEqual(len(lines), 2)
            self.assertIn('"provider": "cachey"', lines[0])
            self.assertIn('"cached": true', lines[1])

    def test_cache_key_depends_on_provider_name(self):
        register_provider("twin-a", base_url=BASE, api_key_default="k")
        register_provider("twin-b", base_url=BASE, api_key_default="k")
        with tempfile.TemporaryDirectory() as tmp:
            cache = SQLiteCache(os.path.join(tmp, "cache.db"))
            rec = Recorder(json_response(OPENAI_REPLY))
            for spec in ("twin-a:m", "twin-b:m"):
                with llm(spec, transport=rec.transport, cache=cache, log=False) as m:
                    m.ask("same")
            self.assertEqual(len(rec.requests), 2)

    def test_events(self):
        register_provider("evt", base_url=BASE, api_key_default="k")
        rec = Recorder(json_response(OPENAI_REPLY, headers={"x-request-id": "req-1"}))
        seen = []
        with llm("evt:m", transport=rec.transport, cache=False, log=False) as m:
            m.add_event_listener("response", lambda event, payload: seen.append(payload))
            m.ask("hi")
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["provider"], "evt")
        self.assertEqual(seen[0]["request_id"], "req-1")

    def test_http_error_names_the_registered_provider(self):
        register_provider("errs", base_url=BASE, api_key_default="k")
        rec = Recorder(json_response({"error": {"message": "nope"}}, status=401))
        with llm("errs:m", transport=rec.transport, lang="en") as m:
            with self.assertRaises(Exception) as ctx:
                m.ask("hi")
        self.assertEqual(ctx.exception.provider, "errs")
        self.assertEqual(ctx.exception.status_code, 401)

    def test_repr_masks_userinfo(self):
        register_provider("masked", base_url="https://user:pw@llm.example.test/v1", api_key_default="k")
        with llm("masked:m", transport=Recorder(json_response({})).transport) as m:
            self.assertNotIn("pw", repr(m.client))
            self.assertIn("***@llm.example.test", repr(m.client))


class AsyncTwinTest(RegistryTestCase, unittest.IsolatedAsyncioTestCase):
    async def test_aask_and_stream_openai_format(self):
        register_provider("asy", base_url=BASE, api_key_env="ASY_KEY", auth_header="api-key", auth_scheme="")
        rec = FreshRecorder(lambda: json_response(OPENAI_REPLY), lambda: sse_response(OPENAI_SSE))
        m = llm("asy:m", transport=rec.transport, api_key="k", cache=False, log=False)
        try:
            self.assertEqual(await m.aask("hi", max_tokens=3), "ok")
            pieces = [p async for p in m.aask_stream("hi")]
            self.assertEqual("".join(pieces), "hello")
        finally:
            await m.aclose()
        self.assertEqual(rec.requests[0].headers["api-key"], "k")
        self.assertEqual(rec.requests[1].headers["api-key"], "k")
        self.assertEqual(str(rec.requests[0].url), BASE + "/chat/completions")
        self.assertEqual(rec.body(0)["max_tokens"], 3)

    async def test_aask_anthropic_format(self):
        register_provider(
            "asy-claude", api_format="anthropic", base_url="https://p.example.test", api_key_default="k"
        )
        rec = FreshRecorder(lambda: json_response(CLAUDE_REPLY), lambda: sse_response(CLAUDE_SSE))
        m = llm("asy-claude:m", transport=rec.transport, cache=False, log=False)
        try:
            self.assertEqual(await m.aask("hi", temperature=0.4), "ok")
            self.assertEqual("".join([p async for p in m.aask_stream("hi")]), "hi")
        finally:
            await m.aclose()
        self.assertNotIn("temperature", rec.body(0))
        self.assertEqual(rec.requests[0].headers["x-api-key"], "k")

    async def test_amodels_and_unsupported(self):
        register_provider("amod", base_url=BASE, api_key_default="k")
        register_provider("amod-off", base_url=BASE, api_key_default="k", models=False)
        rec = FreshRecorder(lambda: json_response({"data": [{"id": "z"}]}))
        m = llm("amod:m", transport=rec.transport)
        try:
            self.assertEqual(await m.amodels(), ["z"])
        finally:
            await m.aclose()
        m = llm("amod-off:m", transport=rec.transport)
        try:
            with self.assertRaises(LLMConfigError) as ctx:
                await m.amodels()
        finally:
            await m.aclose()
        self.assertEqual(ctx.exception.code, "unsupported_models")

    async def test_amodels_follows_the_created_llm_after_replace(self):
        register_provider("aswap", base_url=BASE, api_key_default="k", models=True)
        rec = FreshRecorder(lambda: json_response({"data": [{"id": "z"}]}))
        old = llm("aswap:m", transport=rec.transport)
        register_provider("aswap", base_url=BASE, api_key_default="k", models=False, replace=True)
        try:
            self.assertEqual(await old.amodels(), ["z"])
        finally:
            await old.aclose()
        new = llm("aswap:m", transport=rec.transport)
        try:
            with self.assertRaises(LLMConfigError) as ctx:
                await new.amodels()
        finally:
            await new.aclose()
        self.assertEqual(ctx.exception.code, "unsupported_models")

    async def test_replacing_fixed_headers_misses_the_async_cache(self):
        register_provider("afhc", base_url=BASE, api_key_default="k", headers={"X-Tenant": "a"})
        with tempfile.TemporaryDirectory() as tmp:
            cache = SQLiteCache(os.path.join(tmp, "cache.db"))
            rec = FreshRecorder(lambda: json_response(OPENAI_REPLY))
            with llm("afhc:m", transport=rec.transport, cache=cache, log=False) as m:
                m.ask("same")  # stored by the sync client
            m = llm("afhc:m", transport=rec.transport, cache=cache, log=False)
            try:
                await m.aask("same")  # same definition: the async client hits the same key
            finally:
                await m.aclose()
            self.assertEqual(len(rec.requests), 1)
            register_provider(
                "afhc", base_url=BASE, api_key_default="k", headers={"X-Tenant": "b"}, replace=True
            )
            m = llm("afhc:m", transport=rec.transport, cache=cache, log=False)
            try:
                await m.aask("same")
            finally:
                await m.aclose()
            self.assertEqual(len(rec.requests), 2)
            self.assertEqual(rec.requests[1].headers["x-tenant"], "b")

    async def test_async_client_shares_listeners_and_resolved_settings(self):
        register_provider("shr", base_url=BASE, api_key_default="k")
        rec = FreshRecorder(lambda: json_response(OPENAI_REPLY))
        m = llm("shr:m", transport=rec.transport, cache=False, log=False)
        seen = []
        m.add_event_listener("response", lambda event, payload: seen.append(payload["provider"]))
        try:
            await m.aask("hi")
            self.assertEqual(seen, ["shr"])
            self.assertEqual(m._async_client_instance.base_url, m.client.base_url)
        finally:
            await m.aclose()

    def test_sync_and_async_declared_attributes_match(self):
        register_provider(
            "twin",
            base_url=BASE,
            api_key_env=("TWIN_A", "TWIN_B"),
            base_url_env="TWIN_URL",
            api_key_default="d",
            auth_header="x-key",
            auth_scheme="Key",
            headers={"X-A": "1"},
            max_tokens_field="max_completion_tokens",
            stream_include_usage=True,
            models=False,
        )
        entry = lookup("twin")
        self.assertEqual(_declared(entry.sync), _declared(entry.async_))
        self.assertEqual(_declared(entry.async_)["auth_header"], "x-key")
        self.assertEqual(entry.async_.__name__, "_Async" + entry.sync.__name__)
        # Literal names, independent of _DECLARED: dropping an attribute from
        # the copy list must fail here, not silently shrink both sides.
        for attr in (
            "provider", "default_base_url", "api_key_env", "api_key_env_fallbacks",
            "base_url_env", "api_key_default", "api_key_optional", "api_format",
            "auth_header", "auth_scheme", "fixed_headers", "header_options",
            "supports_models", "supports_audio", "models_style", "rules_provider",
            "max_tokens_field", "stream_include_usage",
        ):
            self.assertEqual(getattr(entry.sync, attr), getattr(entry.async_, attr), attr)
        self.assertEqual(entry.async_.max_tokens_field, "max_completion_tokens")

    def test_builtins_match_their_async_twins(self):
        for name in provider_names():
            entry = lookup(name)
            if not entry.builtin:
                continue
            with self.subTest(name=name):
                self.assertEqual(_declared(entry.sync), _declared(entry.async_))
                # Generating the twin again gives the same declared shape.
                self.assertEqual(_declared(_make_async(entry.sync)), _declared(entry.async_))


class AliasAndReplaceTest(RegistryTestCase):
    def test_alias_resolves_to_canonical_name(self):
        register_provider("deepseek", base_url=BASE, api_key_default="k", aliases=("ds", "deep-seek"))
        rec = Recorder(json_response(OPENAI_REPLY))
        for spec in ("ds:m", "deep-seek:m", "DS:m", "deepseek:m"):
            with llm(spec, transport=rec.transport) as m:
                self.assertEqual(m.provider, "deepseek")
                m.ask("hi")
        self.assertEqual(parse_model_spec("ds:m"), ("ds", "m"))

    def test_single_string_alias(self):
        register_provider("longname", base_url=BASE, api_key_default="k", aliases="ln")
        self.assertIs(lookup("ln"), lookup("longname"))

    def test_unknown_provider_lists_registered_names(self):
        register_provider("listed", base_url=BASE, api_key_default="k", aliases=("lst",))
        with self.assertRaises(LLMConfigError) as ctx:
            parse_model_spec("nothere:m", "en")
        self.assertEqual(ctx.exception.code, "unknown_provider")
        message = str(ctx.exception)
        self.assertIn("'nothere'", message)
        for name in ("openai", "claude", "listed", "lst"):
            self.assertIn(name, message)

    def test_unregistered_name_stays_unknown(self):
        with self.assertRaises(LLMConfigError) as ctx:
            llm("never-registered:m", api_key="k")
        self.assertEqual(ctx.exception.code, "unknown_provider")

    def test_duplicate_without_replace(self):
        register_provider("dup", base_url=BASE, api_key_default="k")
        with self.assertRaises(LLMConfigError) as ctx:
            register_provider("dup", base_url=BASE, api_key_default="k")
        self.assertEqual(ctx.exception.code, "provider_exists")

    def test_replace_own_provider(self):
        register_provider("swap", base_url=BASE, api_key_default="k", aliases=("sw",))
        register_provider(
            "swap", base_url="https://new.example.test/v1", api_key_default="k", replace=True
        )
        self.assertIsNone(lookup("sw"))  # the old alias went away with the old definition
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("swap:m", transport=rec.transport) as m:
            m.ask("hi")
        self.assertEqual(str(rec.requests[0].url), "https://new.example.test/v1/chat/completions")

    def test_existing_llm_keeps_its_classes_after_replace(self):
        register_provider("keep", base_url=BASE, api_key_default="old")
        rec = FreshRecorder(lambda: json_response(OPENAI_REPLY))
        m = llm("keep:m", transport=rec.transport, cache=False, log=False)
        old_async = m._async_class
        register_provider(
            "keep", base_url="https://new.example.test/v1", api_key_default="new", replace=True
        )
        self.assertIsNot(lookup("keep").async_, old_async)
        self.assertIs(m._async_class, old_async)
        import asyncio

        async def run():
            try:
                return await m.aask("hi")
            finally:
                await m.aclose()

        self.assertEqual(asyncio.run(run()), "ok")
        self.assertEqual(str(rec.requests[0].url), BASE + "/chat/completions")

    def test_builtin_names_cannot_be_taken_even_with_replace(self):
        for name in ("openai", "anthropic", "claude", "ollama", "google"):
            for replace in (False, True):
                with self.subTest(name=name, replace=replace):
                    with self.assertRaises(LLMConfigError) as ctx:
                        register_provider(name, base_url=BASE, api_key_default="k", replace=replace)
                    self.assertEqual(ctx.exception.code, "provider_exists")
        # The built-ins are untouched.
        self.assertTrue(lookup("openai").builtin)
        self.assertEqual(lookup("claude").name, "anthropic")

    def test_alias_colliding_with_builtin_is_rejected_and_nothing_is_registered(self):
        with self.assertRaises(LLMConfigError) as ctx:
            register_provider("fresh", base_url=BASE, api_key_default="k", aliases=("claude",))
        self.assertEqual(ctx.exception.code, "provider_exists")
        self.assertIsNone(lookup("fresh"))

    def test_alias_colliding_with_another_registration(self):
        register_provider("first", base_url=BASE, api_key_default="k", aliases=("one",))
        for replace in (False, True):
            with self.subTest(replace=replace):
                with self.assertRaises(LLMConfigError) as ctx:
                    register_provider(
                        "second", base_url=BASE, api_key_default="k", aliases=("one",), replace=replace
                    )
                self.assertEqual(ctx.exception.code, "provider_exists")
                self.assertIsNone(lookup("second"))
        with self.assertRaises(LLMConfigError):
            register_provider("one", base_url=BASE, api_key_default="k", replace=True)

    def test_replace_does_not_take_over_another_registration(self):
        register_provider("owner", base_url=BASE, api_key_default="k")
        with self.assertRaises(LLMConfigError) as ctx:
            register_provider("other", base_url=BASE, api_key_default="k", aliases=("owner",), replace=True)
        self.assertEqual(ctx.exception.code, "provider_exists")

    def test_builtin_pairs_view_includes_registered(self):
        from llm_ai_api.llm import _ASYNC_PROVIDERS, _PROVIDER_PAIRS, _PROVIDERS

        register_provider("viewed", base_url=BASE, api_key_default="k")
        self.assertIn("viewed", _PROVIDER_PAIRS)
        self.assertIs(_PROVIDERS["viewed"], lookup("viewed").sync)
        self.assertIs(_ASYNC_PROVIDERS["viewed"], lookup("viewed").async_)


class ValidationTest(RegistryTestCase):
    def assertInvalid(self, *args, **kwargs):
        with self.assertRaises(LLMConfigError) as ctx:
            register_provider(*args, **kwargs)
        self.assertEqual(ctx.exception.code, "invalid_provider")
        return ctx.exception

    def test_bad_names(self):
        for name in ("", "Upper", "1abc", "has space", "a" * 33, "dot.ted", "-dash", None, 5, "日本語"):
            with self.subTest(name=name):
                self.assertInvalid(name, base_url=BASE, api_key_default="k")

    def test_name_length_limit_is_32(self):
        register_provider("a" * 32, base_url=BASE, api_key_default="k")
        self.assertIsNotNone(lookup("a" * 32))

    def test_good_names(self):
        for name in ("a", "my-box", "my_box", "x1"):
            with self.subTest(name=name):
                register_provider(name, base_url=BASE, api_key_default="k")
                self.assertIsNotNone(lookup(name))

    def test_base_url_is_required(self):
        self.assertInvalid("nourl")
        self.assertInvalid("nourl", base_url="")
        self.assertInvalid("nourl", base_url="   ")
        self.assertInvalid("nourl", base_url=None)
        self.assertInvalid("nourl", base_url=123)
        self.assertIsNone(lookup("nourl"))

    def test_unknown_api_format(self):
        self.assertInvalid("fmt", base_url=BASE, api_format="gemini")
        self.assertInvalid("fmt", base_url=BASE, api_format=None)

    def test_type_errors(self):
        cases = (
            {"api_key_env": 5},
            {"api_key_env": ""},
            {"api_key_env": ("OK", 5)},
            {"api_key_env": "A=B"},
            {"base_url_env": 5},
            {"api_key_default": 5},
            {"api_key_required": "yes"},
            {"models": 1},
            {"replace": "no"},
            {"auth_header": "bad header"},
            {"auth_header": ""},
            {"auth_scheme": 5},
            {"headers": "X: y"},
            {"headers": {"bad name": "v"}},
            {"headers": {"X-A": 5}},
            {"headers": {"X-A": "a\r\nInjected: 1"}},
            {"max_tokens_field": 5},
            {"stream_include_usage": "yes"},
            {"aliases": 5},
            {"aliases": ("Bad",)},
            {"aliases": ("dup", "dup")},
            {"aliases": ("same",)},  # registered below as "same": an alias equal to the name
        )
        for extra in cases:
            kwargs = {"base_url": BASE, "api_key_default": "k"}
            kwargs.update(extra)
            name = "same" if extra.get("aliases") == ("same",) else "bad"
            with self.subTest(extra=extra):
                self.assertInvalid(name, **kwargs)
            self.assertIsNone(lookup(name))

    def test_unknown_keyword_is_a_type_error(self):
        with self.assertRaises(TypeError):
            register_provider("typo", base_url=BASE, api_key_defualt="k")

    def test_error_message_does_not_echo_the_base_url(self):
        with mock.patch.dict(os.environ, {"LLM_AI_API_LANG": "ja"}):
            exc = self.assertInvalid(
                "okname", base_url="https://u:secret@h.example.test/v1", api_format="nope"
            )
        self.assertIn("register_provider", str(exc))
        self.assertNotIn("secret", str(exc))

    def test_header_values_must_be_strings(self):
        for value in (None, 5):
            with self.subTest(value=value):
                self.assertInvalid("hdr", base_url=BASE, api_key_default="k", headers={"X-A": value})
        register_provider("hdr", base_url=BASE, api_key_default="k", headers={"X-A": ""})  # empty is fine

    def test_secret_values_are_not_echoed(self):
        exc = self.assertInvalid("sec", base_url=BASE, api_key_default=b"sk-topsecret")
        self.assertNotIn("topsecret", str(exc))
        self.assertIn("bytes", str(exc))
        exc = self.assertInvalid("sec", base_url=BASE, api_key_default="k", headers={"X-A": b"sk-topsecret"})
        self.assertNotIn("topsecret", str(exc))
        self.assertIn("bytes", str(exc))
        exc = self.assertInvalid("sec", base_url=BASE, api_key_default="k", headers={"X-A": None})
        self.assertIn("NoneType", str(exc))
        exc = self.assertInvalid("sec", base_url=BASE, api_key_default="k\nsk-topsecret")
        self.assertNotIn("topsecret", str(exc))
        exc = self.assertInvalid("sec", base_url=BASE, api_key_default="k", headers={"X-A": "sk-topsecret\r\n"})
        self.assertNotIn("topsecret", str(exc))

    def test_header_values_must_be_ascii(self):
        # httpx would raise a bare UnicodeEncodeError at request time; reject at registration.
        cases = (
            {"headers": {"X-Org": "株式会社"}},
            {"api_key_default": "キー"},
            {"auth_scheme": "Bearér"},
        )
        for extra in cases:
            kwargs = {"base_url": BASE, "api_key_default": "k"}
            kwargs.update(extra)
            with self.subTest(extra=extra):
                exc = self.assertInvalid("nonascii", **kwargs)
                self.assertNotIn("株式会社", str(exc))
                self.assertNotIn("キー", str(exc))
            self.assertIsNone(lookup("nonascii"))

    def test_base_url_env_must_be_a_variable_name(self):
        self.assertInvalid("envname", base_url=BASE, api_key_default="k", base_url_env="URL=x")

    def test_messages_exist_in_both_languages(self):
        from llm_ai_api.lang import en, ja

        for msg_id in ("invalid_provider", "provider_exists", "missing_api_key_no_env"):
            self.assertIn(msg_id, en.MESSAGES)
            self.assertIn(msg_id, ja.MESSAGES)

    def test_nothing_is_registered_after_a_failure(self):
        before = provider_names()
        self.assertInvalid("half", base_url=BASE, aliases=("ok-alias", "Bad"))
        self.assertEqual(provider_names(), before)


class BuiltinMigrationTest(RegistryTestCase):
    """The built-ins now come from the same registry; their behaviour is unchanged."""

    def test_builtin_entries(self):
        names = {n for n in provider_names() if lookup(n).builtin}
        self.assertEqual(
            names,
            {"openai", "openrouter", "grok", "muse", "google", "lmstudio", "ollama", "strata", "anthropic", "claude"},
        )
        self.assertIs(lookup("claude"), lookup("anthropic"))

    def test_builtin_async_class_names_are_still_importable(self):
        from llm_ai_api import _async_clients

        for sync_name in ("OpenAI", "OpenRouter", "Grok", "Muse", "Google", "LMStudio", "Ollama", "Strata", "Anthropic"):
            cls = getattr(_async_clients, "_Async%sClient" % sync_name)
            self.assertEqual(cls.provider, lookup(sync_name.lower()).name)
        with self.assertRaises(AttributeError):
            getattr(_async_clients, "_AsyncNoSuchClient")

    def test_async_anthropic_base_agrees_with_sync_class(self):
        from llm_ai_api import AnthropicClient
        from llm_ai_api._async_clients import _AsyncAnthropicClient

        self.assertEqual(_declared(_AsyncAnthropicClient), _declared(AnthropicClient))

    def test_openrouter_header_options(self):
        from llm_ai_api import OpenRouterClient

        rec = Recorder(json_response(OPENAI_REPLY))
        with OpenRouterClient(
            transport=rec.transport, app_url="https://app.test", app_name="App", headers={"x-title": "mine"}
        ) as c:
            c.chat("m", [{"role": "user", "content": "q"}])
        headers = rec.requests[0].headers
        self.assertEqual(headers["http-referer"], "https://app.test")
        self.assertEqual(headers["x-title"], "mine")

    def test_transcribe_support_comes_from_the_declaration(self):
        self.assertTrue(lookup("openai").sync.supports_audio)
        for name in ("anthropic", "google", "openrouter", "grok", "muse", "ollama"):
            self.assertFalse(lookup(name).sync.supports_audio, name)

    def test_httpx_is_not_leaked(self):
        # A sanity check that registration did not change the public error type.
        register_provider("netfail", base_url=BASE, api_key_default="k")

        def boom(request):
            raise httpx.ConnectError("down", request=request)

        with llm("netfail:m", transport=httpx.MockTransport(boom), max_retries=0, lang="en") as m:
            with self.assertRaises(Exception) as ctx:
                m.ask("hi")
        self.assertNotIsInstance(ctx.exception, httpx.HTTPError)


if __name__ == "__main__":
    unittest.main()
