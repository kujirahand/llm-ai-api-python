import unittest

from llm_ai_api import APIStreamError, AnthropicClient

from .helpers import Recorder, json_response, sse_response

REPLY = {
    "model": "claude-x",
    "content": [
        {"type": "thinking", "thinking": "..."},
        {"type": "text", "text": "ポ"},
        {"type": "text", "text": "チ"},
    ],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 4, "output_tokens": 6},
}
MSGS = [
    {"role": "system", "content": "s1"},
    {"role": "user", "content": "q"},
    {"role": "system", "content": "s2"},
]


def client(rec):
    return AnthropicClient(api_key="k", transport=rec.transport)


class AnthropicTest(unittest.TestCase):
    def test_chat(self):
        rec = Recorder(json_response(REPLY))
        r = client(rec).chat("claude-x", MSGS)
        req = rec.requests[0]
        self.assertEqual(str(req.url), "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.headers["x-api-key"], "k")
        self.assertEqual(req.headers["anthropic-version"], "2026-10-21")
        self.assertNotIn("authorization", req.headers)
        self.assertEqual(
            rec.body(),
            {
                "model": "claude-x",
                "system": "s1\n\ns2",
                "messages": [{"role": "user", "content": "q"}],
                "max_tokens": 16000,
            },
        )
        self.assertEqual(r.text, "ポチ")
        self.assertEqual(r.stop_reason, "end_turn")
        self.assertEqual((r.usage.input_tokens, r.usage.output_tokens), (4, 6))

    def test_no_temperature_unless_given_and_extra_last(self):
        rec = Recorder(json_response(REPLY))
        c = client(rec)
        c.chat("m", [{"role": "user", "content": "q"}])
        self.assertNotIn("temperature", rec.body())
        self.assertNotIn("system", rec.body())
        c.chat("m", [{"role": "user", "content": "q"}], max_tokens=5, temperature=0.2,
               extra={"max_tokens": 9, "top_k": 1})
        self.assertEqual(rec.body()["max_tokens"], 9)
        self.assertEqual(rec.body()["temperature"], 0.2)
        self.assertEqual(rec.body()["top_k"], 1)

    def test_custom_version(self):
        rec = Recorder(json_response(REPLY))
        AnthropicClient(api_key="k", anthropic_version="2099-01-01", transport=rec.transport).chat(
            "m", MSGS
        )
        self.assertEqual(rec.requests[0].headers["anthropic-version"], "2099-01-01")

    def test_system_blocks(self):
        rec = Recorder(json_response(REPLY))
        blocks = [{"type": "text", "text": "b", "cache_control": {"type": "ephemeral"}}]
        client(rec).chat("m", [{"role": "system", "content": "a"},
                               {"role": "system", "content": blocks},
                               {"role": "user", "content": "q"}])
        self.assertEqual(rec.body()["system"], [{"type": "text", "text": "a"}] + blocks)

    def test_stream(self):
        text = (
            'event: message_start\ndata: {"type":"message_start"}\n\n'
            "event: ping\ndata: {\"type\": \"ping\"}\n\n"
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":"he"}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"input_json_delta","partial_json":"{"}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":"llo"}}\n\n'
            'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        )
        rec = Recorder(sse_response(text))
        chunks = list(client(rec).stream_chat("m", MSGS))
        self.assertEqual("".join(c.text for c in chunks), "hello")
        self.assertTrue(rec.body()["stream"])

    def test_stream_error_event(self):
        text = (
            'event: error\ndata: {"type":"error","error":{"type":"overloaded_error",'
            '"message":"Overloaded"}}\n\n'
        )
        rec = Recorder(sse_response(text))
        with self.assertRaises(APIStreamError) as cm:
            list(client(rec).stream_chat("m", MSGS))
        self.assertIn("Overloaded", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
