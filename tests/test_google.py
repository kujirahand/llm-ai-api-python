import os
import unittest
from unittest import mock

from llm_ai_api import GoogleClient, LLMConfigError, llm, models

from .helpers import Recorder, json_response

REPLY = {"choices": [{"message": {"content": "ポチ"}, "finish_reason": "stop"}]}
MSGS = [{"role": "user", "content": "q"}]


class GoogleTest(unittest.TestCase):
    def test_request_shape(self):
        rec = Recorder(json_response(REPLY))
        c = GoogleClient(api_key="k", transport=rec.transport)
        r = c.chat("gemini-x", MSGS, max_tokens=9)
        req = rec.requests[0]
        self.assertEqual(
            str(req.url),
            "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        )
        self.assertEqual(req.headers["authorization"], "Bearer k")
        self.assertEqual(rec.body(), {"model": "gemini-x", "messages": MSGS, "max_tokens": 9})
        self.assertEqual(r.text, "ポチ")

    def test_key_env_and_fallback(self):
        for env, ok in (
            ({"GEMINI_API_KEY": "a"}, "a"),
            ({"GOOGLE_API_KEY": "b"}, "b"),
            ({"GEMINI_API_KEY": "a", "GOOGLE_API_KEY": "b"}, "a"),
        ):
            with mock.patch.dict(os.environ, env, clear=True):
                rec = Recorder(json_response(REPLY))
                GoogleClient(transport=rec.transport).chat("m", MSGS)
                self.assertEqual(rec.requests[0].headers["authorization"], "Bearer " + ok)

    def test_missing_key_names_gemini_env(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(LLMConfigError) as cm:
                GoogleClient(lang="en")
        self.assertIn("GEMINI_API_KEY", str(cm.exception))

    def test_llm_interface(self):
        rec = Recorder(json_response(REPLY))
        m = llm(models.GOOGLE_GEMINI_3_8_FLASH, api_key="k", transport=rec.transport)
        self.assertEqual(m.provider, "google")
        self.assertEqual(m.ask("q"), "ポチ")
        self.assertEqual(rec.body()["model"], "gemini-3.8-flash")


if __name__ == "__main__":
    unittest.main()
