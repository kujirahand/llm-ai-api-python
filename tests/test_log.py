import json
import os
import tempfile
import unittest

from llm_ai_api import LLMConfigError, get_log, llm, set_cache, set_log

from .helpers import Recorder, json_response, sse_response

OPENAI_REPLY = {
    "choices": [{"message": {"content": "ポチ"}, "finish_reason": "stop"}],
    "model": "gpt-x",
}
OPENAI_STREAM = (
    'data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"チ"}}]}\n\n'
    "data: [DONE]\n\n"
)


class LogTest(unittest.TestCase):
    def setUp(self):
        set_log(None)
        set_cache(None)
        self.addCleanup(set_log, None)
        self.addCleanup(set_cache, None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "sub", "log.jsonl")

    def records(self):
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def make(self, rec, **kw):
        return llm("openai:gpt-x", api_key="sk-secret", transport=rec.transport, **kw)

    def test_off_by_default(self):
        self.assertIsNone(get_log())
        self.make(Recorder(json_response(OPENAI_REPLY))).ask("q")
        self.assertFalse(os.path.exists(self.path))

    def test_logs_request_and_raw_response(self):
        m = self.make(Recorder(json_response(OPENAI_REPLY)), log=self.path)
        m.ask("可愛い犬の名前を考えて")
        (r,) = self.records()
        self.assertEqual((r["provider"], r["model"]), ("openai", "gpt-x"))
        self.assertFalse(r["stream"])
        self.assertFalse(r["cached"])
        self.assertEqual(r["request"]["messages"][0]["content"], "可愛い犬の名前を考えて")
        self.assertEqual(r["response"], OPENAI_REPLY)
        self.assertNotIn("sk-secret", open(self.path, encoding="utf-8").read())

    def test_stream_logged_after_complete_read(self):
        m = self.make(Recorder(sse_response(OPENAI_STREAM)), log=self.path)
        it = m.stream("q")
        next(it)
        self.assertFalse(os.path.exists(self.path) and self.records())
        list(it)
        (r,) = self.records()
        self.assertTrue(r["stream"])
        self.assertEqual(r["response"]["text"], "ポチ")
        self.assertEqual(len(r["response"]["chunks"]), 2)

    def test_stream_cache_hit_logged(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        m = self.make(rec, log=self.path, cache=self.path + ".db")
        list(m.stream("q"))
        list(m.stream("q"))
        first, second = self.records()
        self.assertEqual((first["stream"], first["cached"]), (True, False))
        self.assertEqual((second["stream"], second["cached"]), (True, True))
        self.assertEqual(first["response"]["text"], "ポチ")
        self.assertEqual(second["response"]["text"], "ポチ")

    def test_stream_abandoned_not_logged(self):
        m = self.make(Recorder(sse_response(OPENAI_STREAM)), log=self.path)
        it = m.stream("q")
        next(it)
        close = getattr(it, "close", None)
        if close is not None:
            close()
        self.assertTrue(not os.path.exists(self.path) or len(self.records()) == 0)

    def test_anthropic_null_text_delta(self):
        text = (
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":null}}\n\n'
            'event: content_block_delta\ndata: {"type":"content_block_delta","index":0,'
            '"delta":{"type":"text_delta","text":"ポチ"}}\n\n'
            'event: message_stop\ndata: {"type":"message_stop"}\n\n'
        )
        rec = Recorder(sse_response(text))
        m = llm(
            "anthropic:claude-x", api_key="sk-ant-test", transport=rec.transport, log=self.path
        )
        self.assertEqual("".join(m.stream("q")), "ポチ")
        (r,) = self.records()
        self.assertEqual(r["response"]["text"], "ポチ")

    def test_global_log_and_disable_per_instance(self):
        set_log(self.path)
        self.make(Recorder(json_response(OPENAI_REPLY))).ask("a")
        self.make(Recorder(json_response(OPENAI_REPLY)), log=False).ask("b")
        self.assertEqual(len(self.records()), 1)

    def test_cached_flag(self):
        m = self.make(Recorder(json_response(OPENAI_REPLY)), log=self.path, cache=self.path + ".db")
        m.ask("q")
        m.ask("q")
        self.assertEqual([r["cached"] for r in self.records()], [False, True])

    def test_log_failure_does_not_lose_response(self):
        class Broken:
            def write(self, *a, **kw):
                raise OSError("disk full")

        m = self.make(Recorder(json_response(OPENAI_REPLY)), log=Broken())
        self.assertEqual(m.ask("q"), "ポチ")

    def test_invalid_log(self):
        with self.assertRaises(LLMConfigError) as cm:
            set_log(123)
        self.assertEqual(cm.exception.code, "invalid_log")

    def test_env_dir(self):
        d = os.path.dirname(self.path)
        old = os.environ.get("LLM_AI_API_LOG_DIR")
        os.environ["LLM_AI_API_LOG_DIR"] = d
        self.addCleanup(
            lambda: os.environ.pop("LLM_AI_API_LOG_DIR", None)
            if old is None
            else os.environ.__setitem__("LLM_AI_API_LOG_DIR", old)
        )
        import llm_ai_api.log as log_module

        log_module._global_set = False
        self.addCleanup(setattr, log_module, "_env_log", None)
        self.make(Recorder(json_response(OPENAI_REPLY))).ask("q")
        self.assertTrue(os.path.exists(os.path.join(d, "llm.jsonl")))
