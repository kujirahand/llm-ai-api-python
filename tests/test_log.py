import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from llm_ai_api import JSONLLog, LLMConfigError, get_log, llm, set_cache, set_log

from .helpers import FreshRecorder, Recorder, json_response, sse_response

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
        with open(self.path, encoding="utf-8") as f:
            self.assertNotIn("sk-secret", f.read())

    def test_logged_request_is_the_body_after_drops(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm(
            "openai:gpt-6-astra",
            api_key="k",
            transport=rec.transport,
            log=self.path,
            temperature=0.4,
            extra={"logprobs": True, "n": 1},
        )
        m.ask("q")
        (r,) = self.records()
        self.assertEqual(r["request"], rec.body())
        self.assertNotIn("temperature", r["request"])
        self.assertNotIn("logprobs", r["request"])
        self.assertEqual(r["request"]["n"], 1)

    def test_stream_logged_after_complete_read(self):
        m = self.make(Recorder(sse_response(OPENAI_STREAM)), log=self.path)
        it = m.ask_stream("q")
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
        list(m.ask_stream("q"))
        list(m.ask_stream("q"))
        first, second = self.records()
        self.assertEqual((first["stream"], first["cached"]), (True, False))
        self.assertEqual((second["stream"], second["cached"]), (True, True))
        self.assertEqual(first["response"]["text"], "ポチ")
        self.assertEqual(second["response"]["text"], "ポチ")

    def test_stream_abandoned_not_logged(self):
        m = self.make(Recorder(sse_response(OPENAI_STREAM)), log=self.path)
        it = m.ask_stream("q")
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
        self.assertEqual("".join(m.ask_stream("q")), "ポチ")
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


class LogSecurityTest(unittest.TestCase):
    def test_redact_sync_and_async_without_changing_results(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "log")

            def redact(record):
                record["request"].pop("messages")
                record["response"].clear()
                return record

            log = JSONLLog(path, redact=redact)
            m = llm("openai:gpt-x", api_key="k",
                    transport=FreshRecorder(lambda: json_response(OPENAI_REPLY)).transport, log=log)
            self.assertEqual(m.ask("secret"), "ポチ")
            async def run_async():
                try:
                    return await m.aask("secret")
                finally:
                    await m.aclose()
            self.assertEqual(asyncio.run(run_async()), "ポチ")
            with open(path, encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            self.assertEqual(len(records), 2)
            for record in records:
                self.assertNotIn("messages", record["request"])
                self.assertEqual(record["response"], {})

    def test_redact_skip_and_failure_do_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "log")
            log = JSONLLog(path, redact=lambda record: None)
            log.write("openai", "m", {}, {})
            def fail(record):
                raise ValueError("failed")
            log.redact = fail
            m = llm("openai:gpt-x", api_key="k",
                    transport=Recorder(json_response(OPENAI_REPLY)).transport, log=log)
            self.assertEqual(m.ask("secret"), "ポチ")
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "")

    @unittest.skipUnless(os.name == "posix", "POSIX permissions")
    def test_existing_permissions_and_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "log")
            with open(path, "w") as f:
                f.write("old\n")
            os.chmod(path, 0o644)
            log = JSONLLog(path)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            os.chmod(path, 0o644)
            with patch("llm_ai_api.log.os.fchmod", side_effect=OSError("denied")):
                with self.assertRaises(OSError):
                    log.write("openai", "m", {}, {})
            with open(path) as f:
                self.assertEqual(f.read(), "old\n")
            log.write("openai", "m", {}, {})
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

class ConcurrentLogTest(unittest.TestCase):
    def test_shared_path_serializes_append_and_trim(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "log")
            first = JSONLLog(path, max_size=1)
            second = JSONLLog(os.path.join(directory, ".", "log"), max_size=1)
            entered = threading.Event()
            release = threading.Event()
            original = first._trim
            started = threading.Event()
            finished = threading.Event()

            def second_write():
                started.set()
                second.write("p", "m", {}, {"id": 2})
                finished.set()

            def paused_trim():
                entered.set()
                self.assertTrue(release.wait(5))
                original()

            first._trim = paused_trim
            with ThreadPoolExecutor(max_workers=2) as pool:
                a = pool.submit(first.write, "p", "m", {}, {"id": 1})
                self.assertTrue(entered.wait(5))
                b = pool.submit(second_write)
                self.assertTrue(started.wait(5))
                try:
                    self.assertFalse(finished.wait(0.1))
                    with open(path, encoding="utf-8") as f:
                        self.assertEqual(len(f.readlines()), 1)
                finally:
                    release.set()
                a.result(timeout=5)
                b.result(timeout=5)
            with open(path, encoding="utf-8") as f:
                self.assertEqual(json.loads(f.readlines()[-1])["response"]["id"], 2)
            self.assertEqual(os.listdir(directory), ["log"])

    def test_async_clients_share_path_lock(self):
        async def run(path):
            clients = [llm("openai:gpt-x", api_key="k", log=path,
                           transport=FreshRecorder(lambda: json_response(OPENAI_REPLY)).transport,
                           cache=False)
                       for _ in range(12)]
            try:
                await asyncio.gather(*(client.aask(str(i)) for i, client in enumerate(clients)))
            finally:
                await asyncio.gather(*(client.aclose() for client in clients))

        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "log")
            asyncio.run(run(path))
            with open(path, encoding="utf-8") as f:
                records = [json.loads(line) for line in f]
            self.assertEqual(len(records), 12)
            self.assertEqual({r["request"]["messages"][0]["content"] for r in records},
                             {str(i) for i in range(12)})
