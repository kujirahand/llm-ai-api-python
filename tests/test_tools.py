"""Tests for tool-call / thinking extraction and `tools=` / `tool_results()` (#135)."""

import copy
import tempfile
import unittest

from llm_ai_api import LLMConfigError, SQLiteCache, ToolCall, llm
from llm_ai_api._tools import _parse_arguments

from .helpers import FreshRecorder, Recorder, json_response

USER = {"role": "user", "content": "weather in Tokyo?"}
TOOLS = [
    {
        "name": "get_weather",
        "description": "Get the weather",
        "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
    }
]


def oa_response(message, finish_reason="tool_calls"):
    return {"choices": [{"message": message, "finish_reason": finish_reason}], "model": "m"}


def oa_call(arguments='{"city": "Tokyo"}', id="call_1", name="get_weather"):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": arguments}}


def an_response(content, stop_reason="tool_use"):
    return {"content": content, "model": "m", "stop_reason": stop_reason, "role": "assistant"}


def make(spec, *responses, **kw):
    rec = Recorder(*[json_response(r) for r in responses])
    return llm(spec, api_key="test-key", transport=rec.transport, **kw), rec


class ParseArgumentsTest(unittest.TestCase):
    def test_cases(self):
        self.assertEqual(_parse_arguments('{"a": 1}'), ({"a": 1}, '{"a": 1}'))
        self.assertEqual(_parse_arguments(""), ({}, ""))
        self.assertEqual(_parse_arguments("  "), ({}, "  "))
        self.assertEqual(_parse_arguments("[1]"), (None, "[1]"))
        self.assertEqual(_parse_arguments("{bad"), (None, "{bad"))
        self.assertEqual(_parse_arguments({"a": "日本"}), ({"a": "日本"}, '{"a": "日本"}'))
        self.assertEqual(_parse_arguments(None), (None, ""))
        self.assertEqual(_parse_arguments(3), (None, "3"))
        self.assertEqual(_parse_arguments(object()), (None, ""))


class OpenAIExtractionTest(unittest.TestCase):
    def chat(self, message):
        m, _ = make("openai:test", oa_response(message))
        return m.chat([USER])

    def test_function_call(self):
        call_raw = oa_call()
        result = self.chat({"content": None, "tool_calls": [call_raw]})
        self.assertEqual(len(result.tool_calls), 1)
        c = result.tool_calls[0]
        self.assertIsInstance(c, ToolCall)
        self.assertEqual(
            (c.id, c.name, c.arguments, c.arguments_raw, c.type),
            ("call_1", "get_weather", {"city": "Tokyo"}, '{"city": "Tokyo"}', "function"),
        )
        self.assertEqual(c.raw, call_raw)
        self.assertEqual(result.text, "")

    def test_broken_json_does_not_raise(self):
        c = self.chat({"tool_calls": [oa_call("{oops")]}).tool_calls[0]
        self.assertIsNone(c.arguments)
        self.assertEqual(c.arguments_raw, "{oops")

    def test_empty_arguments(self):
        self.assertEqual(self.chat({"tool_calls": [oa_call("")]}).tool_calls[0].arguments, {})

    def test_dict_arguments(self):
        c = self.chat({"tool_calls": [oa_call({"city": "Oslo"})]}).tool_calls[0]
        self.assertEqual(c.arguments, {"city": "Oslo"})
        self.assertEqual(c.arguments_raw, '{"city": "Oslo"}')

    def test_custom_type(self):
        element = {"id": "c1", "type": "custom", "custom": {"name": "run", "input": "ls -la"}}
        c = self.chat({"tool_calls": [element]}).tool_calls[0]
        self.assertEqual((c.id, c.name, c.type), ("c1", "run", "custom"))
        self.assertEqual(c.arguments_raw, "ls -la")
        self.assertIsNone(c.arguments)

    def test_flat_element_and_skipped_elements(self):
        calls = [
            "junk",
            {"type": "function", "function": {"arguments": "{}"}},  # no name
            {"id": "x", "type": "other", "name": "flat", "arguments": '{"a": 1}'},
        ]
        result = self.chat({"tool_calls": calls})
        self.assertEqual([c.name for c in result.tool_calls], ["flat"])
        self.assertEqual(result.tool_calls[0].arguments, {"a": 1})

    def test_no_id(self):
        element = {"type": "function", "function": {"name": "f", "arguments": "{}"}}
        self.assertIsNone(self.chat({"tool_calls": [element]}).tool_calls[0].id)

    def test_thinking(self):
        self.assertEqual(self.chat({"content": "x", "reasoning_content": "why"}).thinking, "why")
        self.assertEqual(self.chat({"content": "x", "reasoning": "because"}).thinking, "because")
        self.assertEqual(
            self.chat({"content": "x", "reasoning_content": "", "reasoning": "r"}).thinking, "r"
        )
        self.assertIsNone(self.chat({"content": "x"}).thinking)

    def test_message_is_a_copy(self):
        result = self.chat({"content": "x", "tool_calls": [oa_call()]})
        self.assertEqual(result.message, result.raw["choices"][0]["message"])
        result.message["content"] = "changed"
        result.message["tool_calls"][0]["id"] = "other"
        self.assertEqual(result.raw["choices"][0]["message"]["content"], "x")
        self.assertEqual(result.raw["choices"][0]["message"]["tool_calls"][0]["id"], "call_1")

    def test_no_message(self):
        m, _ = make("openai:test", {"choices": [], "model": "m"})
        result = m.chat([USER])
        self.assertEqual((result.tool_calls, result.thinking, result.message), ([], None, None))


class AnthropicExtractionTest(unittest.TestCase):
    def chat(self, content):
        m, rec = make("anthropic:test", an_response(content))
        return m.chat([USER]), rec

    def test_tool_use(self):
        block = {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "Tokyo"}}
        result, _ = self.chat([{"type": "text", "text": "ok"}, block])
        self.assertEqual(result.text, "ok")
        c = result.tool_calls[0]
        self.assertEqual(
            (c.id, c.name, c.arguments, c.type), ("tu_1", "get_weather", {"city": "Tokyo"}, "tool_use")
        )
        self.assertEqual(c.arguments_raw, '{"city": "Tokyo"}')
        self.assertEqual(c.raw, block)

    def test_skips_nameless_and_server_tool_use(self):
        result, _ = self.chat(
            [
                {"type": "tool_use", "id": "a", "input": {}},
                {"type": "server_tool_use", "id": "b", "name": "web_search", "input": {}},
            ]
        )
        self.assertEqual(result.tool_calls, [])

    def test_thinking_joined_and_redacted_excluded(self):
        result, _ = self.chat(
            [
                {"type": "thinking", "thinking": "first", "signature": "sig1"},
                {"type": "redacted_thinking", "data": "xxx"},
                {"type": "thinking", "thinking": "second", "signature": "sig2"},
                {"type": "text", "text": "hi"},
            ]
        )
        self.assertEqual(result.thinking, "first\n\nsecond")
        self.assertNotIn("xxx", result.thinking)
        self.assertEqual(result.text, "hi")

    def test_no_thinking(self):
        result, _ = self.chat([{"type": "text", "text": "hi"}])
        self.assertIsNone(result.thinking)

    def test_empty_thinking_is_none(self):
        result, _ = self.chat(
            [
                {"type": "thinking", "thinking": "", "signature": "s"},
                {"type": "text", "text": "hi"},
            ]
        )
        self.assertIsNone(result.thinking)

    def test_arguments_is_a_copy(self):
        block = {"type": "tool_use", "id": "tu_1", "name": "f", "input": {"opt": {"x": 1}}}
        result, _ = self.chat([block])
        result.tool_calls[0].arguments["opt"]["x"] = 2
        self.assertEqual(result.raw["content"][0]["input"]["opt"]["x"], 1)

    def test_message_roundtrip_keeps_signature(self):
        content = [
            {"type": "thinking", "thinking": "hmm", "signature": "SIG"},
            {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "Tokyo"}},
        ]
        m, rec = make("anthropic:test", an_response(content), an_response([{"type": "text", "text": "done"}], "end_turn"))
        first = m.chat([USER], tools=TOOLS)
        self.assertEqual(first.message, {"role": "assistant", "content": content})
        history = [USER, first.message] + m.tool_results([(first.tool_calls[0], {"temp": 20})])
        second = m.chat(history, tools=TOOLS)
        self.assertEqual(second.text, "done")
        sent = rec.body(1)["messages"]
        self.assertEqual(sent[1]["content"][0], {"type": "thinking", "thinking": "hmm", "signature": "SIG"})
        self.assertEqual(sent[2]["content"][0]["tool_use_id"], "tu_1")

    def test_message_is_a_copy(self):
        content = [
            {"type": "thinking", "thinking": "hmm", "signature": "SIG"},
            {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "Tokyo"}},
        ]
        result, _ = self.chat(content)
        self.assertEqual(result.message, {"role": "assistant", "content": content})
        result.message["content"][0]["signature"] = "changed"
        result.message["content"][1]["input"]["city"] = "Osaka"
        self.assertEqual(result.raw["content"][0]["signature"], "SIG")
        self.assertEqual(result.raw["content"][1]["input"]["city"], "Tokyo")

    def test_non_list_content(self):
        m, _ = make("anthropic:test", {"content": "str", "model": "m"})
        result = m.chat([USER])
        self.assertEqual((result.tool_calls, result.thinking, result.message), ([], None, None))


class ToolsArgumentTest(unittest.TestCase):
    def test_openai_body(self):
        m, rec = make("openai:test", oa_response({"content": "x"}))
        m.chat([USER], tools=TOOLS)
        self.assertEqual(
            rec.body()["tools"],
            [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the weather",
                        "parameters": TOOLS[0]["parameters"],
                    },
                }
            ],
        )

    def test_anthropic_body(self):
        m, rec = make("anthropic:test", an_response([]))
        m.chat([USER], tools=TOOLS)
        self.assertEqual(
            rec.body()["tools"],
            [
                {
                    "name": "get_weather",
                    "description": "Get the weather",
                    "input_schema": TOOLS[0]["parameters"],
                }
            ],
        )

    def test_defaults_without_description_and_parameters(self):
        m, rec = make("openai:test", oa_response({"content": "x"}))
        m.chat([USER], tools=[{"name": "ping"}])
        self.assertEqual(
            rec.body()["tools"],
            [{"type": "function", "function": {"name": "ping", "parameters": {"type": "object", "properties": {}}}}],
        )
        m, rec = make("anthropic:test", an_response([]))
        m.chat([USER], tools=[{"name": "ping"}])
        self.assertEqual(
            rec.body()["tools"], [{"name": "ping", "input_schema": {"type": "object", "properties": {}}}]
        )

    def test_user_extra_wins(self):
        for spec, resp in (("openai:test", oa_response({"content": "x"})), ("anthropic:test", an_response([]))):
            m, rec = make(spec, resp)
            mine = [{"custom": True}]
            m.chat([USER], tools=TOOLS, extra={"tools": mine})
            self.assertEqual(rec.body()["tools"], mine)

    def test_invalid_tools(self):
        m, rec = make("openai:test", oa_response({"content": "x"}))
        bad = [
            "x",
            {"name": "a"},
            [("a",)],
            [{"name": ""}],
            [{}],
            [{"name": "a", "extra": 1}],
            [{"name": "a", "description": 1}],
            [{"name": "a", "parameters": []}],
        ]
        for tools in bad:
            with self.subTest(tools=tools):
                with self.assertRaises(LLMConfigError) as cm:
                    m.chat([USER], tools=tools)
                self.assertEqual(cm.exception.code, "invalid_tools")
        self.assertEqual(rec.requests, [])

    def test_empty_tools_not_sent(self):
        for spec, resp in (("openai:test", oa_response({"content": "x"})), ("anthropic:test", an_response([]))):
            m, rec = make(spec, resp)
            m.chat([USER], tools=[])
            self.assertNotIn("tools", rec.body())

    def test_ask_unaffected(self):
        m, rec = make("openai:test", oa_response({"content": "x"}, "stop"))
        self.assertEqual(m.ask("q"), "x")
        self.assertNotIn("tools", rec.body())
        with self.assertRaises(TypeError):
            m.ask("q", tools=TOOLS)


class ToolResultsTest(unittest.TestCase):
    def test_openai(self):
        m, _ = make("openai:test", oa_response({}))
        call = ToolCall(id="c1", name="f")
        out = m.tool_results([(call, {"a": "日本"}), ("c2", "plain", True), (None, "x")])
        self.assertEqual(
            out,
            [
                {"role": "tool", "tool_call_id": "c1", "content": '{"a": "日本"}'},
                {"role": "tool", "tool_call_id": "c2", "content": "plain"},
                {"role": "tool", "content": "x"},
            ],
        )

    def test_anthropic(self):
        m, _ = make("anthropic:test", an_response([]))
        call = ToolCall(id="t1", name="f")
        out = m.tool_results([(call, [1, 2]), ["t2", "boom", True], ("t3", "ok", False), (None, "x")])
        self.assertEqual(
            out,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "content": "[1, 2]"},
                        {"type": "tool_result", "tool_use_id": "t2", "content": "boom", "is_error": True},
                        {"type": "tool_result", "tool_use_id": "t3", "content": "ok"},
                        {"type": "tool_result", "content": "x"},
                    ],
                }
            ],
        )

    def test_invalid(self):
        m, _ = make("openai:test", oa_response({}))
        bad = [None, "abc", [], (), [("a",)], [("a", "b", True, 1)], ["ab"], [(5, "x")], [("a", object())]]
        for outputs in bad:
            with self.subTest(outputs=outputs):
                with self.assertRaises(LLMConfigError) as cm:
                    m.tool_results(outputs)
                self.assertEqual(cm.exception.code, "invalid_tools")


class RoundTripTest(unittest.TestCase):
    def test_openai(self):
        message = {"role": "assistant", "content": None, "tool_calls": [oa_call()]}
        m, rec = make("openai:test", oa_response(message), oa_response({"content": "20C"}, "stop"))
        first = m.chat([USER], tools=TOOLS)
        self.assertEqual(first.stop_reason, "tool_calls")
        history = [USER, first.message] + m.tool_results([(first.tool_calls[0], {"temp": 20})])
        second = m.chat(history, tools=TOOLS)
        self.assertEqual(second.text, "20C")
        sent = rec.body(1)["messages"]
        self.assertEqual(sent[1], message)
        self.assertEqual(sent[2], {"role": "tool", "tool_call_id": "call_1", "content": '{"temp": 20}'})

    def test_anthropic(self):
        content = [{"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "Tokyo"}}]
        m, rec = make(
            "anthropic:test", an_response(content), an_response([{"type": "text", "text": "20C"}], "end_turn")
        )
        first = m.chat([USER], tools=TOOLS)
        history = [USER, first.message] + m.tool_results([(first.tool_calls[0], {"temp": 20}, False)])
        second = m.chat(history, tools=TOOLS)
        self.assertEqual(second.text, "20C")
        sent = rec.body(1)["messages"]
        self.assertEqual(sent[1], {"role": "assistant", "content": content})
        self.assertEqual(
            sent[2],
            {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "tu_1", "content": '{"temp": 20}'}]},
        )


class CacheTest(unittest.TestCase):
    def check(self, spec, response, expect_thinking):
        with tempfile.TemporaryDirectory() as d:
            cache = SQLiteCache(d + "/cache.db")
            m, rec = make(spec, response, cache=cache)
            first = m.chat([USER], tools=TOOLS)
            second = m.chat([USER], tools=TOOLS)
            self.assertEqual(len(rec.requests), 1)
            self.assertEqual(len(second.tool_calls), 1)
            self.assertEqual(second.tool_calls[0].name, "get_weather")
            self.assertEqual(second.tool_calls[0].arguments, {"city": "Tokyo"})
            self.assertEqual(second.thinking, expect_thinking)
            self.assertEqual(second.message, first.message)
            self.assertIsNotNone(second.message)

    def test_openai_hit(self):
        message = {"content": None, "reasoning_content": "think", "tool_calls": [oa_call()]}
        self.check("openai:test", oa_response(message), "think")

    def test_anthropic_hit(self):
        content = [
            {"type": "thinking", "thinking": "think", "signature": "s"},
            {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "Tokyo"}},
        ]
        self.check("anthropic:test", an_response(content), "think")


class SchemaWithToolsTest(unittest.TestCase):
    def test_tool_calls_skip_validation(self):
        schema = {"type": "object"}
        m, _ = make("openai:test", oa_response({"content": None, "tool_calls": [oa_call()]}))
        result = m.chat([USER], schema=schema, tools=TOOLS)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertIsNone(result.parsed)

        m, _ = make("anthropic:test", an_response([{"type": "tool_use", "id": "t", "name": "f", "input": {}}]))
        result = m.chat([USER], schema=schema, tools=TOOLS)
        self.assertEqual(len(result.tool_calls), 1)
        self.assertIsNone(result.parsed)

    def test_text_answer_still_validated(self):
        m, _ = make("openai:test", oa_response({"content": '{"a": 1}'}, "stop"))
        result = m.chat([USER], schema={"type": "object"}, tools=TOOLS)
        self.assertEqual(result.parsed, {"a": 1})


class AsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_same_extraction_as_sync(self):
        cases = (
            ("openai:test", oa_response({"content": None, "reasoning": "r", "tool_calls": [oa_call()]})),
            (
                "anthropic:test",
                an_response(
                    [
                        {"type": "thinking", "thinking": "r", "signature": "s"},
                        {"type": "tool_use", "id": "call_1", "name": "get_weather", "input": {"city": "Tokyo"}},
                    ]
                ),
            ),
        )
        for spec, response in cases:
            with self.subTest(spec=spec):
                rec = FreshRecorder(lambda r=response: json_response(copy.deepcopy(r)))
                m = llm(spec, api_key="test-key", transport=rec.transport)
                sync = m.chat([USER], tools=TOOLS)
                result = await m.achat([USER], tools=TOOLS)
                self.assertEqual(result.tool_calls, sync.tool_calls)
                self.assertEqual(result.thinking, sync.thinking)
                self.assertEqual(result.message, sync.message)
                self.assertEqual(rec.body(0)["tools"], rec.body(1)["tools"])
                await m.aclose()

    async def test_async_schema_with_tool_calls_and_cache(self):
        with tempfile.TemporaryDirectory() as d:
            cache = SQLiteCache(d + "/cache.db")
            rec = Recorder(json_response(oa_response({"content": None, "tool_calls": [oa_call()]})))
            m = llm("openai:test", api_key="test-key", transport=rec.transport, cache=cache)
            first = await m.achat([USER], schema={"type": "object"}, tools=TOOLS)
            second = await m.achat([USER], schema={"type": "object"}, tools=TOOLS)
            self.assertEqual(len(rec.requests), 1)
            self.assertIsNone(first.parsed)
            self.assertEqual(second.tool_calls[0].name, "get_weather")
            self.assertEqual(second.message, first.message)
            await m.aclose()

    async def test_async_anthropic_cache_hit(self):
        with tempfile.TemporaryDirectory() as d:
            cache = SQLiteCache(d + "/cache.db")
            content = [
                {"type": "thinking", "thinking": "think", "signature": "s"},
                {"type": "tool_use", "id": "tu_1", "name": "get_weather", "input": {"city": "Tokyo"}},
            ]
            rec = Recorder(json_response(an_response(content)))
            m = llm("anthropic:test", api_key="test-key", transport=rec.transport, cache=cache)
            first = await m.achat([USER], tools=TOOLS)
            second = await m.achat([USER], tools=TOOLS)
            self.assertEqual(len(rec.requests), 1)
            self.assertEqual(second.tool_calls[0].name, "get_weather")
            self.assertEqual(second.thinking, "think")
            self.assertEqual(second.message, first.message)
            await m.aclose()

    async def test_async_invalid_tools(self):
        m, _ = make("openai:test", oa_response({"content": "x"}))
        with self.assertRaises(LLMConfigError):
            await m.achat([USER], tools="bad")


if __name__ == "__main__":
    unittest.main()
