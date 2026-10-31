import json
import unittest

from llm_ai_api import APIStreamError, LLMError, OpenAIClient, OpenRouterClient, llm

from .helpers import Recorder, json_response, sse_response

REPLY = {
    "model": "m",
    "choices": [{"message": {"content": "ポチ"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 3, "completion_tokens": 5},
}
MSGS = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]


class OpenAITest(unittest.TestCase):
    def test_chat_minimal_body_and_result(self):
        rec = Recorder(json_response(REPLY))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        r = c.chat("m", MSGS)
        self.assertEqual(rec.body(), {"model": "m", "messages": MSGS})
        self.assertEqual(r.text, "ポチ")
        self.assertEqual(r.stop_reason, "stop")
        self.assertEqual((r.usage.input_tokens, r.usage.output_tokens), (3, 5))
        self.assertEqual(r.raw, REPLY)

    def test_params_and_extra(self):
        rec = Recorder(json_response(REPLY))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        c.chat("m", MSGS, max_tokens=10, temperature=0.5, extra={"temperature": 1, "n": 2})
        self.assertEqual(
            rec.body(),
            {
                "model": "m",
                "messages": MSGS,
                "max_completion_tokens": 10,
                "temperature": 1,
                "n": 2,
            },
        )

    def test_null_content(self):
        rec = Recorder(json_response({"choices": [{"message": {"content": None}}]}))
        self.assertEqual(OpenAIClient(api_key="k", transport=rec.transport).chat("m", MSGS).text, "")

    def test_stream(self):
        text = (
            'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
            'data: {"choices":[{"delta":{"content":"he"}}]}\n\r\n'
            'data: {"choices":[{"delta":{"content":"llo"}}]}\n\n'
            'data: {"choices":[],"usage":{"prompt_tokens":1}}\n\n'
            "data: [DONE]\n\n"
            'data: {"choices":[{"delta":{"content":"IGNORED"}}]}\n\n'
        )
        rec = Recorder(sse_response(text))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        chunks = list(c.stream_chat("m", MSGS))
        self.assertEqual("".join(x.text for x in chunks), "hello")
        self.assertEqual(
            rec.body(), {"model": "m", "messages": MSGS, "stream": True,
                         "stream_options": {"include_usage": True}},
        )
        self.assertEqual(rec.requests[0].headers["accept"], "text/event-stream")

    def test_error_event_in_stream_raises(self):
        err = {"error": {"code": 502, "message": "upstream failed"}}
        text = (
            'data: {"choices":[{"delta":{"content":"par"}}]}\n\n'
            "data: " + json.dumps(err) + "\n\n"
            'data: {"choices":[{"delta":{"content":"IGNORED"}}]}\n\n'
        )
        rec = Recorder(sse_response(text))
        m = llm("openai:m", api_key="k", lang="en", transport=rec.transport)
        got = []
        with self.assertRaises(APIStreamError) as cm:
            for piece in m.stream("q"):
                got.append(piece)
        self.assertEqual(got, ["par"])  # partial text was delivered before the failure
        self.assertIn("upstream failed", str(cm.exception))
        self.assertEqual(cm.exception.body, err)
        self.assertEqual(cm.exception.code, "stream_error")

    def test_invalid_json_in_stream_raises_library_error(self):
        rec = Recorder(sse_response("data: {not json}\n\n"))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        with self.assertRaises(LLMError) as cm:
            list(c.stream_chat("m", MSGS))
        self.assertEqual(cm.exception.code, "invalid_json_response")

    def test_string_error_in_stream_raises(self):
        rec = Recorder(sse_response('data: {"error": "boom"}\n\n'))
        c = OpenRouterClient(api_key="k", transport=rec.transport)
        with self.assertRaises(APIStreamError) as cm:
            list(c.stream_chat("m", MSGS))
        self.assertIn("boom", str(cm.exception))


class OpenRouterTest(unittest.TestCase):
    def test_headers_and_max_tokens_name(self):
        rec = Recorder(json_response(REPLY), sse_response('data: [DONE]\n\n'))
        c = OpenRouterClient(
            api_key="k", app_url="https://x.example", app_name="App", transport=rec.transport
        )
        c.chat("a/b:free", MSGS, max_tokens=7)
        req = rec.requests[0]
        self.assertEqual(str(req.url), "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(req.headers["http-referer"], "https://x.example")
        self.assertEqual(req.headers["x-title"], "App")
        self.assertEqual(rec.body()["max_tokens"], 7)
        list(c.stream_chat("a/b:free", MSGS))
        self.assertNotIn("stream_options", rec.body())


if __name__ == "__main__":
    unittest.main()
