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

    def test_stream(self):
        rec = Recorder(sse_response(
            'data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'
            'data: {"choices":[],"usage":{}}\n\n'
            'data: {"choices":[{"delta":{"content":"チ"}}]}\n\n'
            "data: [DONE]\n\n"))
        m = llm("openrouter:a/b", api_key="k", transport=rec.transport)
        self.assertEqual(list(m.stream("q")), ["ポ", "チ"])

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
