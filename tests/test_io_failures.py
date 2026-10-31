"""Runtime cache and log failures remain non-fatal and observable."""
import asyncio
import tempfile
import threading
import unittest
from unittest.mock import patch

from llm_ai_api import llm
from llm_ai_api.cache import SQLiteCache
from llm_ai_api.log import JSONLLog
from .helpers import FreshRecorder, json_response

OK = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "model": "x"}


class IOFailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_sync_and_async_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            cache = SQLiteCache(directory + "/cache")
            log = JSONLLog(directory + "/log")
            model = llm("openai:x", api_key="key", cache=cache, log=log,
                        transport=FreshRecorder(lambda: json_response(OK)).transport)
            seen = []
            model.add_event_listener(None, lambda event, payload: seen.append((event, payload, threading.get_ident())))
            def fail(*args, **kwargs):
                raise OSError("secret prompt and key")
            with patch.object(cache, "get", side_effect=fail), patch.object(cache, "put", side_effect=fail), patch.object(log, "write", side_effect=fail):
                with self.assertLogs("llm_ai_api", level="WARNING") as warnings:
                    self.assertEqual(model.ask("hello"), "ok")
                    self.assertEqual(await model.aask("hello"), "ok")
                self.assertEqual(cache.failure_count, 4)
                self.assertEqual(log.failure_count, 2)
                errors = [(event, payload, thread) for event, payload, thread in seen if event.endswith("_error")]
                self.assertEqual([p["operation"] for _, p, _ in errors], ["lookup", "store", "write"] * 2)
                self.assertTrue(all(t == threading.get_ident() for _, _, t in errors))
                self.assertTrue(all(p["error_type"] == "OSError" for _, p, _ in errors))
                self.assertNotIn("secret", str(errors) + str(warnings.output))
            await model.aclose()

    async def test_custom_objects_need_no_counter(self):
        class Broken:
            def get(self, key):
                raise ValueError("private")
            def put(self, *args):
                raise ValueError("private")
            def write(self, *args, **kwargs):
                raise ValueError("private")
        model = llm("openai:x", api_key="key", cache=Broken(), log=Broken(),
                    transport=FreshRecorder(lambda: json_response(OK)).transport)
        with self.assertLogs("llm_ai_api", level="WARNING"):
            self.assertEqual(await model.aask("hello"), "ok")
        await model.aclose()
