"""Tests for `LLM.chat(..., schema=...)` structured output (#60).

No pydantic: the fake models only provide the two methods the library
duck-types on (`model_json_schema` / `model_validate_json`).
"""

import json
import unittest

from llm_ai_api import LLMConfigError, StructuredOutputError, llm

from .helpers import Recorder, json_response


class FakeModel:
    @classmethod
    def model_json_schema(cls):
        return {
            "type": "object",
            "properties": {
                "required": {"type": "string"},
                "optional": {"type": "integer", "default": 3},
            },
            "required": ["required"],
        }

    @classmethod
    def model_validate_json(cls, text):
        return {"validated": json.loads(text)}


class FailingModel(FakeModel):
    @classmethod
    def model_validate_json(cls, text):
        raise ValueError("bad model")


# A name with characters the API rejects, to exercise name sanitizing.
FakeModel.__name__ = "A title!"


def openai_response(text='{"required":"ok"}', finish_reason="stop", refusal=None):
    message = {"content": text}
    if refusal is not None:
        message["refusal"] = refusal
    return {"choices": [{"message": message, "finish_reason": finish_reason}], "model": "m"}


def anthropic_response(text='{"x":"yes"}', stop_reason="end_turn"):
    return {
        "content": [{"type": "text", "text": text}],
        "stop_reason": stop_reason,
        "model": "m",
    }


def make(spec, response):
    rec = Recorder(json_response(response))
    return llm(spec, api_key="test-key", transport=rec.transport), rec


class StructuredSyncTest(unittest.TestCase):
    def test_openai_model_schema_is_normalized_and_parsed(self):
        m, rec = make("openai:test", openai_response())
        result = m.chat([{"role": "user", "content": "x"}], schema=FakeModel)

        body = rec.body()
        fmt = body["response_format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertEqual(fmt["json_schema"]["name"], "A_title_")
        self.assertIs(fmt["json_schema"]["strict"], True)
        schema = fmt["json_schema"]["schema"]
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["required"], ["required", "optional"])
        self.assertNotIn("default", schema["properties"]["optional"])
        self.assertEqual(
            schema["properties"]["optional"]["anyOf"][1], {"type": "null"}
        )
        self.assertEqual(result.parsed, {"validated": {"required": "ok"}})

    def test_dict_schema_is_sent_unchanged_and_json_is_parsed(self):
        schema = {
            "title": "raw schema",
            "type": "object",
            "properties": {"x": {"type": "string"}},
        }
        m, rec = make("openai:test", openai_response('{"x":"yes"}'))
        result = m.chat([{"role": "user", "content": "x"}], schema=schema)

        sent = rec.body()["response_format"]["json_schema"]
        self.assertEqual(sent["schema"], schema)
        self.assertEqual(sent["name"], "raw_schema")
        self.assertEqual(result.parsed, {"x": "yes"})

    def test_anthropic_merges_output_config(self):
        m, rec = make("anthropic:test", anthropic_response())
        result = m.chat(
            [{"role": "user", "content": "x"}],
            schema={"type": "object"},
            extra={"output_config": {"effort": "high"}},
        )
        output_config = rec.body()["output_config"]
        self.assertEqual(output_config["effort"], "high")
        self.assertEqual(output_config["format"]["type"], "json_schema")
        self.assertEqual(output_config["format"]["schema"], {"type": "object"})
        self.assertEqual(result.parsed, {"x": "yes"})

    def test_refusal_is_structured_error(self):
        cases = [
            ("anthropic:test", anthropic_response("", stop_reason="refusal")),
            ("openai:test", openai_response(refusal="no")),
        ]
        for spec, response in cases:
            with self.subTest(spec=spec):
                m, _ = make(spec, response)
                with self.assertRaises(StructuredOutputError) as cm:
                    m.chat([{"role": "user", "content": "x"}], schema={"type": "object"})
                self.assertEqual(cm.exception.code, "output_refused")
                self.assertIsNotNone(cm.exception.result)

    def test_incomplete_is_structured_error(self):
        cases = [
            ("anthropic:test", anthropic_response("", stop_reason="max_tokens")),
            ("openai:test", openai_response(finish_reason="length")),
        ]
        for spec, response in cases:
            with self.subTest(spec=spec):
                m, _ = make(spec, response)
                with self.assertRaises(StructuredOutputError) as cm:
                    m.chat([{"role": "user", "content": "x"}], schema={"type": "object"})
                self.assertEqual(cm.exception.code, "output_incomplete")

    def test_invalid_output_and_validation_error_preserve_cause(self):
        m, _ = make("openai:test", openai_response("not json"))
        with self.assertRaises(StructuredOutputError) as cm:
            m.chat([{"role": "user", "content": "x"}], schema={"type": "object"})
        self.assertEqual(cm.exception.code, "invalid_structured_output")
        self.assertIsInstance(cm.exception.__cause__, ValueError)

        m, _ = make("openai:test", openai_response("{}"))
        with self.assertRaises(StructuredOutputError) as cm:
            m.chat([{"role": "user", "content": "x"}], schema=FailingModel)
        self.assertEqual(cm.exception.code, "invalid_structured_output")
        self.assertIsInstance(cm.exception.__cause__, ValueError)

    def test_extra_response_format_wins(self):
        m, rec = make("openai:test", openai_response("{}"))
        m.chat(
            [{"role": "user", "content": "x"}],
            schema={"type": "object"},
            extra={"response_format": {"type": "text"}},
        )
        self.assertEqual(rec.body()["response_format"], {"type": "text"})

    def test_invalid_schema_argument(self):
        class HalfModel:
            @classmethod
            def model_json_schema(cls):
                return {}

        for bad in (1, object(), HalfModel):
            with self.subTest(bad=bad):
                m, _ = make("openai:test", openai_response())
                with self.assertRaises(LLMConfigError) as cm:
                    m.chat([{"role": "user", "content": "x"}], schema=bad)
                self.assertEqual(cm.exception.code, "invalid_schema")

    def test_no_schema_keeps_parsed_none(self):
        m, _ = make("openai:test", openai_response("plain text"))
        result = m.chat([{"role": "user", "content": "x"}])
        self.assertIsNone(result.parsed)


class StructuredAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_achat_parses(self):
        m, rec = make("openai:test", openai_response("{}"))
        result = await m.achat(
            [{"role": "user", "content": "x"}], schema={"type": "object"}
        )
        self.assertEqual(result.parsed, {})
        self.assertIn("response_format", rec.body())


if __name__ == "__main__":
    unittest.main()
