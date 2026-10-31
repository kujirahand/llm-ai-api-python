import os
import sys
import unittest
from unittest import mock

from llm_ai_api import LLM, LLMConfigError, llm

from .helpers import Recorder, json_response, sse_response

parse_model_spec = sys.modules["llm_ai_api.llm"].parse_model_spec

OPENAI_REPLY = {"choices": [{"message": {"content": "ポチ"}}]}
CLAUDE_REPLY = {"content": [{"type": "text", "text": "ポチ"}]}


class LLMTest(unittest.TestCase):
    def test_parse_spec(self):
        self.assertEqual(parse_model_spec("openai:gpt-6-luna"), ("openai", "gpt-6-luna"))
        self.assertEqual(
            parse_model_spec("OpenRouter:meta/llama:free"), ("openrouter", "meta/llama:free")
        )
        self.assertEqual(parse_model_spec("claude:x"), ("claude", "x"))

    def test_parse_spec_errors(self):
        for bad in ["gpt-6", "openai:", ":x", "unknown:x", ""]:
            with self.assertRaises(LLMConfigError, msg=bad):
                parse_model_spec(bad)

    def test_ask_openai(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm("openai:gpt-6-luna", api_key="k", transport=rec.transport)
        self.assertEqual(m.ask("可愛い犬の名前を考えて"), "ポチ")
        self.assertEqual(
            rec.body(),
            {"model": "gpt-6-luna", "messages": [{"role": "user", "content": "可愛い犬の名前を考えて"}]},
        )
        self.assertEqual((m.provider, m.model), ("openai", "gpt-6-luna"))

    def test_ask_claude_alias_and_defaults(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        m = llm("claude:claude-x", api_key="k", system="常に犬の名前で答えて", max_tokens=100,
                extra={"a": 1}, transport=rec.transport)
        self.assertEqual(m.provider, "anthropic")
        self.assertEqual(m.ask("q"), "ポチ")
        b = rec.body()
        self.assertEqual((b["system"], b["max_tokens"], b["a"]), ("常に犬の名前で答えて", 100, 1))
        self.assertNotIn("temperature", b)
        # 呼び出しごとの上書き。extra は浅くマージされる
        m.ask("q", system="別", max_tokens=5, extra={"b": 2})
        b = rec.body()
        self.assertEqual((b["system"], b["max_tokens"], b["a"], b["b"]), ("別", 5, 1, 2))

    def test_explicit_none_turns_off_a_default_for_one_call(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm("openai:m", api_key="k", system="S", max_tokens=5, temperature=0.4,
                extra={"a": 1}, transport=rec.transport)

        m.ask("q")  # not passed: the defaults apply
        b = rec.body()
        self.assertEqual((b["messages"][0], b["max_completion_tokens"], b["temperature"], b["a"]),
                         ({"role": "system", "content": "S"}, 5, 0.4, 1))

        m.ask("q", system=None, max_tokens=None, temperature=None, extra=None)
        self.assertEqual(rec.body(), {"model": "m", "messages": [{"role": "user", "content": "q"}]})

        # each argument is independent
        m.ask("q", temperature=None)
        b = rec.body()
        self.assertNotIn("temperature", b)
        self.assertEqual((b["max_completion_tokens"], b["a"], len(b["messages"])), (5, 1, 2))
        m.ask("q", extra=None)
        self.assertNotIn("a", rec.body())
        self.assertEqual(rec.body()["temperature"], 0.4)
        m.ask("q", system=None)
        self.assertEqual(len(rec.body()["messages"]), 1)

    def test_explicit_none_applies_to_chat_and_stream_too(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm("openai:m", api_key="k", temperature=0.4, transport=rec.transport)
        m.chat([{"role": "user", "content": "q"}], temperature=None)
        self.assertNotIn("temperature", rec.body())
        rec = Recorder(sse_response("data: [DONE]\n\n"))
        m = llm("openai:m", api_key="k", temperature=0.4, transport=rec.transport)
        list(m.ask_stream("q", temperature=None))
        self.assertNotIn("temperature", rec.body())
        list(m.ask_stream("q"))
        self.assertEqual(rec.body()["temperature"], 0.4)

    def test_known_rejection_is_dropped_through_the_common_interface(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm("openai:gpt-6-astra", api_key="k", temperature=0.4, extra={"logprobs": True},
                transport=rec.transport)
        m.ask("q")
        self.assertNotIn("temperature", rec.body())
        self.assertNotIn("logprobs", rec.body())
        rec = Recorder(json_response(CLAUDE_REPLY))
        m = llm("claude:claude-x", api_key="k", temperature=0.4, extra={"top_k": 2},
                transport=rec.transport)
        m.ask("q")
        self.assertNotIn("temperature", rec.body())
        self.assertNotIn("top_k", rec.body())
        self.assertEqual(rec.body()["max_tokens"], 16000)

    def test_explicit_none_on_claude_keeps_required_max_tokens(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        m = llm("claude:m", api_key="k", max_tokens=100, system="S", transport=rec.transport)
        m.ask("q", max_tokens=None, system=None)
        b = rec.body()
        self.assertEqual(b["max_tokens"], 16000)  # Claude requires it: the library's own default
        self.assertNotIn("system", b)

    def test_stream(self):
        rec = Recorder(sse_response(
            'data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'
            'data: {"choices":[],"usage":{}}\n\n'
            'data: {"choices":[{"delta":{"content":"チ"}}]}\n\n'
            "data: [DONE]\n\n"))
        m = llm("openrouter:a/b", api_key="k", transport=rec.transport)
        self.assertEqual(list(m.ask_stream("q")), ["ポ", "チ"])

    def test_chat_stream_sends_messages_and_old_stream_is_an_alias(self):
        body = (
            'data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"チ"}}]}\n\n'
            "data: [DONE]\n\n"
        )
        rec = Recorder(sse_response(body))
        m = llm("openrouter:a/b", api_key="k", transport=rec.transport)
        messages = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
        ]
        self.assertEqual(list(m.chat_stream(messages, system="S")), ["ポ", "チ"])
        b = rec.body()
        self.assertTrue(b["stream"])
        self.assertEqual(b["messages"], [{"role": "system", "content": "S"}] + messages)
        self.assertEqual(len(messages), 3)  # the caller's list is not modified

        # ask_stream() is chat_stream() with one user message.
        list(m.ask_stream("q"))
        ask_body = rec.body()
        self.assertEqual(ask_body["messages"], [{"role": "user", "content": "q"}])

        # The deprecated name still works and sends the same request.
        self.assertEqual(list(m.stream("q")), ["ポ", "チ"])
        self.assertEqual(rec.body(), ask_body)

    def test_chat_returns_result_and_context_manager(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        with llm("openai:m", api_key="k", transport=rec.transport) as m:
            self.assertIsInstance(m, LLM)
            r = m.chat([{"role": "user", "content": "q"}])
            self.assertEqual(r.raw, OPENAI_REPLY)

    def test_api_key_from_env(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "envkey"}):
            rec = Recorder(json_response(CLAUDE_REPLY))
            llm("anthropic:m", transport=rec.transport).ask("q")
            self.assertEqual(rec.requests[0].headers["x-api-key"], "envkey")


if __name__ == "__main__":
    unittest.main()
