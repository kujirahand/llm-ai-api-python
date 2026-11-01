"""Conversation histories through the common sync and async interfaces."""

import copy
import os
import tempfile
import unittest

import httpx

from llm_ai_api import LLMConfigError, llm
from llm_ai_api.cache import cache_key
from .helpers import FreshRecorder, json_response

HISTORY = [{"role": "system", "content": "inner"},
           {"role": "user", "content": "question"},
           {"role": "assistant", "content": "answer"},
           {"role": "user", "content": "follow up"}]


def response(anthropic=False, stream=False):
    if stream:
        content = (b'event: content_block_delta\ndata: {"type":"content_block_delta","delta":{"type":"text_delta","text":"ok"}}\n\nevent: message_stop\ndata: {"type":"message_stop"}\n\n' if anthropic else
                   b'data: {"choices":[{"delta":{"content":"ok"}}]}\n\ndata: [DONE]\n\n')
        return httpx.Response(200, content=content, headers={"x-request-id": "rid", "request-id": "rid"})
    return json_response({"content": [{"type": "text", "text": "ok"}]} if anthropic else
                         {"choices": [{"message": {"content": "ok"}}]})


class HistoryTest(unittest.TestCase):
    def test_all_providers_match_chat_and_stream(self):
        for provider in ("openai", "openrouter", "google", "anthropic"):
            with self.subTest(provider=provider):
                anthropic = provider == "anthropic"
                rec = FreshRecorder(lambda: response(anthropic))
                m = llm(provider + ":model", api_key="k", system="outer", transport=rec.transport)
                self.addCleanup(m.close)
                history = copy.deepcopy(HISTORY)
                self.assertEqual(m.ask(history), "ok")
                m.chat(history)
                self.assertEqual(rec.body(0), rec.body(1))
                if anthropic:
                    self.assertEqual(rec.body()["system"], "outer\n\ninner")
                    self.assertEqual(rec.body()["messages"], HISTORY[1:])
                else:
                    self.assertEqual(rec.body()["messages"], [{"role": "system", "content": "outer"}] + HISTORY)
                self.assertEqual(history, HISTORY)
                rec.responses = [lambda: response(anthropic, True)]
                stream = m.ask_stream(history)
                self.assertEqual(stream.request_id, "rid")
                self.assertEqual(list(stream), ["ok"])
                self.assertEqual(list(m.stream(history)), ["ok"])
                prepared = m._prepare(history, "outer", None, None, None)
                list(m.client.stream_chat(**prepared))
                self.assertEqual(rec.body(-1), rec.body(-2))
                self.assertEqual(history, HISTORY)

    def test_cache_identity_and_string_body(self):
        rec = FreshRecorder(lambda: response())
        m = llm("openai:model", api_key="k", transport=rec.transport)
        self.addCleanup(m.close)
        m.ask("question")
        body = {"model": "model", "messages": [{"role": "user", "content": "question"}]}
        self.assertEqual(rec.body(), body)
        self.assertEqual(cache_key("openai", rec.body(), api_key="k"),
                         "d57a453b0b0e4010451b148704ecdee330335f9bc2c7f1769fdfb087cd23612b")
        m.ask(HISTORY)
        m.chat(HISTORY)
        self.assertEqual(cache_key("openai", rec.body(-1), api_key="k"),
                         cache_key("openai", rec.body(-2), api_key="k"))

    def test_history_reuses_chat_cache_and_emits_hit(self):
        with tempfile.TemporaryDirectory() as directory:
            rec = FreshRecorder(lambda: response())
            m = llm("openai:model", api_key="k", transport=rec.transport,
                    cache=os.path.join(directory, "cache.db"))
            try:
                events = []
                m.add_event_listener("cache_hit", lambda event, payload: events.append(payload))
                m.chat(HISTORY)
                self.assertEqual(m.ask(HISTORY), "ok")
                self.assertEqual(len(rec.requests), 1)
                self.assertEqual(len(events), 1)
            finally:
                m.close()

    def test_invalid(self):
        m = llm("openai:model", api_key="k", lang="en")
        self.addCleanup(m.close)
        for bad in (42, {}, [], [1]):
            for method in (m.ask, m.ask_stream, m.stream):
                with self.subTest(bad=bad, method=method.__name__):
                    with self.assertRaisesRegex(LLMConfigError, "non-empty list"):
                        method(bad)


class AsyncHistoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_history_all_providers(self):
        for provider in ("openai", "openrouter", "google", "anthropic"):
            with self.subTest(provider=provider):
                anthropic = provider == "anthropic"
                rec = FreshRecorder(lambda: response(anthropic))
                m = llm(provider + ":model", api_key="k", system="outer", transport=rec.transport)
                try:
                    history = copy.deepcopy(HISTORY)
                    self.assertEqual(await m.aask(history), "ok")
                    await m.achat(history)
                    self.assertEqual(rec.body(0), rec.body(1))
                    self.assertEqual(history, HISTORY)
                    rec.responses = [lambda: response(anthropic, True)]
                    stream = m.aask_stream(history)
                    self.assertEqual([part async for part in stream], ["ok"])
                    self.assertEqual([part async for part in m.astream(history)], ["ok"])
                    self.assertEqual(stream.request_id, "rid")
                    self.assertEqual(history, HISTORY)
                finally:
                    await m.aclose()

    async def test_invalid(self):
        m = llm("openai:model", api_key="k", lang="en")
        try:
            for bad in (42, {}, [], [1]):
                with self.assertRaises(LLMConfigError):
                    await m.aask(bad)
                with self.assertRaises(LLMConfigError):
                    m.aask_stream(bad)
                with self.assertRaises(LLMConfigError):
                    m.astream(bad)
        finally:
            await m.aclose()
