import json
import os
import tempfile
import unittest
from unittest import mock

from llm_ai_api import ChatResult, LLMConfigError, SQLiteCache, Usage, get_cache, llm, set_cache
from llm_ai_api import cache as cache_module
from llm_ai_api.cache import cache_key

from .helpers import Recorder, json_response, sse_response

OPENAI_REPLY = {
    "choices": [{"message": {"content": "ポチ"}, "finish_reason": "stop"}],
    "model": "gpt-x",
    "usage": {"prompt_tokens": 3, "completion_tokens": 4},
}
CLAUDE_REPLY = {"content": [{"type": "text", "text": "ポチ"}]}
OPENAI_STREAM = (
    'data: {"choices":[{"delta":{"content":"ポ"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"チ"}}]}\n\n'
    "data: [DONE]\n\n"
)


class CacheTestBase(unittest.TestCase):
    def setUp(self):
        set_cache(None)
        self.addCleanup(set_cache, None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.db = os.path.join(self.dir, "cache.db")


class CacheKeyTest(unittest.TestCase):
    def test_same_for_different_dict_order(self):
        a = {"model": "m", "messages": [{"role": "user", "content": "q"}], "temperature": 0.5}
        b = {"temperature": 0.5, "messages": [{"content": "q", "role": "user"}], "model": "m"}
        self.assertEqual(cache_key("openai", a), cache_key("openai", b))

    def test_differs_by_input(self):
        base = {"model": "m", "messages": [{"role": "user", "content": "q"}]}
        key = cache_key("openai", base)
        self.assertNotEqual(key, cache_key("anthropic", base))
        self.assertNotEqual(key, cache_key("openai", dict(base, model="n")))
        self.assertNotEqual(
            key, cache_key("openai", dict(base, messages=[{"role": "user", "content": "r"}]))
        )
        self.assertNotEqual(key, cache_key("openai", dict(base, temperature=0.1)))

    def test_differs_by_context(self):
        base = {"model": "m", "messages": [{"role": "user", "content": "q"}]}
        key = cache_key("openai", base, {"base_url": "https://a.example/v1"})
        self.assertNotEqual(key, cache_key("openai", base))
        self.assertNotEqual(key, cache_key("openai", base, {"base_url": "https://b.example/v1"}))
        self.assertNotEqual(
            key, cache_key("openai", base, {"base_url": "https://a.example/v1", "headers": {"x": "y"}})
        )
        self.assertEqual(key, cache_key("openai", base, {"base_url": "https://a.example/v1"}))

    def test_client_drops_rejected_keys_before_the_cache_key(self):
        from llm_ai_api import AnthropicClient

        rec = Recorder(json_response(CLAUDE_REPLY))
        c = AnthropicClient(api_key="k", transport=rec.transport)
        messages = [{"role": "user", "content": "q"}]
        c.chat("claude-x", messages)
        plain = cache_key("anthropic", rec.body())
        c.chat("claude-x", messages, temperature=0.2, extra={"top_k": 1})
        self.assertEqual(plain, cache_key("anthropic", rec.body()))
        c.chat("claude-x", messages, max_tokens=5)
        self.assertNotEqual(plain, cache_key("anthropic", rec.body()))


class SQLiteCacheTest(CacheTestBase):
    def make_result(self):
        return ChatResult(
            text="ポチ",
            model="gpt-x",
            stop_reason="stop",
            usage=Usage(3, 4),
            raw={"a": [1, 2], "b": "日本語"},
            request_id="req-1",
            latency=0.25,
            retries=2,
        )

    def test_roundtrip_and_persistence(self):
        c = SQLiteCache(self.db)
        self.assertIsNone(c.get("k"))
        c.put("k", "openai", self.make_result())
        got = c.get("k")
        self.assertEqual(got.text, "ポチ")
        self.assertEqual(got.model, "gpt-x")
        self.assertEqual(got.stop_reason, "stop")
        self.assertEqual(got.usage, Usage(3, 4))
        self.assertEqual(got.raw, {"a": [1, 2], "b": "日本語"})
        self.assertEqual(got.request_id, "req-1")
        self.assertEqual(got.latency, 0.25)
        self.assertEqual(got.retries, 2)
        self.assertEqual(len(c), 1)
        # A second instance on the same file sees the entry.
        self.assertEqual(SQLiteCache(self.db).get("k").text, "ポチ")

    def test_row_written_without_call_metadata_still_loads(self):
        import sqlite3

        from llm_ai_api.cache import _PLAIN

        c = SQLiteCache(self.db)
        plain = json.dumps(
            {"text": "old", "model": "m", "stop_reason": "stop", "usage": None, "raw": {}}
        ).encode("utf-8")
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO llm_cache (key, provider, model, response, created_at) VALUES (?, ?, ?, ?, ?)",
            ("old", "openai", "m", _PLAIN + plain, 1.0),
        )
        conn.commit()
        conn.close()
        got = c.get("old")
        self.assertEqual(got.text, "old")
        self.assertIsNone(got.request_id)
        self.assertIsNone(got.latency)
        self.assertEqual(got.retries, 0)

    def test_no_usage_and_clear(self):
        c = SQLiteCache(self.db)
        c.put("k", "openai", ChatResult("x", None, None, None, {}))
        self.assertIsNone(c.get("k").usage)
        c.clear()
        self.assertEqual(len(c), 0)
        self.assertIsNone(c.get("k"))

    def test_context_manager_and_parent_dirs(self):
        path = os.path.join(self.dir, "sub", "dir", "c.db")
        with SQLiteCache(path) as c:
            c.put("k", "openai", self.make_result())
        self.assertTrue(os.path.exists(path))

    def test_corrupted_row_is_a_miss_and_deleted(self):
        import sqlite3

        c = SQLiteCache(self.db)
        conn = sqlite3.connect(self.db)
        conn.execute(
            "INSERT INTO llm_cache (key, provider, model, response, created_at)"
            " VALUES ('bad', 'openai', NULL, 'not json', 0)"
        )
        conn.execute(
            "INSERT INTO llm_cache (key, provider, model, response, created_at)"
            " VALUES ('bad2', 'openai', NULL, '[1, 2]', 0)"
        )
        conn.commit()
        conn.close()
        self.assertIsNone(c.get("bad"))
        self.assertIsNone(c.get("bad2"))
        self.assertEqual(len(c), 0)

    @unittest.skipUnless(os.name == "posix", "POSIX file permissions only")
    def test_new_file_is_owner_only(self):
        SQLiteCache(self.db)
        self.assertEqual(os.stat(self.db).st_mode & 0o777, 0o600)

    def test_unusable_path(self):
        blocker = os.path.join(self.dir, "file")
        with open(blocker, "w") as f:
            f.write("x")
        with self.assertRaises(LLMConfigError) as cm:
            SQLiteCache(os.path.join(blocker, "c.db"), lang="en")
        self.assertEqual(cm.exception.code, "invalid_cache")


class ChatCacheTest(CacheTestBase):
    def make(self, rec, **kw):
        return llm("openai:gpt-6-luna", api_key="k", transport=rec.transport, **kw)

    def test_instance_cache_path(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec, cache=self.db)
        first = m.chat([{"role": "user", "content": "q"}])
        second = m.chat([{"role": "user", "content": "q"}])
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(first.text, second.text)
        self.assertEqual(second.usage, Usage(3, 4))
        self.assertEqual(second.raw, first.raw)
        m.chat([{"role": "user", "content": "another"}])
        self.assertEqual(len(rec.requests), 2)

    def test_ask_cached(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec, cache=self.db)
        self.assertEqual(m.ask("q"), "ポチ")
        self.assertEqual(m.ask("q"), "ポチ")
        self.assertEqual(len(rec.requests), 1)
        m.ask("different")
        self.assertEqual(len(rec.requests), 2)

    def test_default_off(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec)
        m.ask("q")
        m.ask("q")
        self.assertEqual(len(rec.requests), 2)

    def test_global_and_override(self):
        set_cache(self.db)
        self.assertIsInstance(get_cache(), SQLiteCache)
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec)
        m.ask("q")
        m.ask("q")
        self.assertEqual(len(rec.requests), 1)

        rec2 = Recorder(json_response(OPENAI_REPLY))
        off = self.make(rec2, cache=False)
        off.ask("q")
        off.ask("q")
        self.assertEqual(len(rec2.requests), 2)

        set_cache(None)
        self.assertIsNone(get_cache())
        rec3 = Recorder(json_response(OPENAI_REPLY))
        m3 = self.make(rec3)
        m3.ask("q")
        m3.ask("q")
        self.assertEqual(len(rec3.requests), 2)

    def test_cache_object(self):
        c = SQLiteCache(self.db)
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec, cache=c)
        m.ask("q")
        m.ask("q")
        self.assertEqual(len(rec.requests), 1)
        self.assertEqual(len(c), 1)
        m.close()  # must not break the shared cache
        self.assertEqual(len(c), 1)

    def test_cache_true_uses_default_path(self):
        default = os.path.join(self.dir, "default.db")
        with mock.patch.object(cache_module, "DEFAULT_CACHE_PATH", default):
            rec = Recorder(json_response(OPENAI_REPLY))
            m = self.make(rec, cache=True)
        m.ask("q")
        m.ask("q")
        self.assertEqual(len(rec.requests), 1)
        self.assertTrue(os.path.exists(default))

    def test_base_url_separates_entries(self):
        rec_a = Recorder(json_response(OPENAI_REPLY))
        a = llm("openai:m", api_key="k", base_url="https://a.example/v1",
                transport=rec_a.transport, cache=self.db)
        rec_b = Recorder(json_response(OPENAI_REPLY))
        b = llm("openai:m", api_key="k", base_url="https://b.example/v1",
                transport=rec_b.transport, cache=self.db)
        a.ask("q")
        b.ask("q")  # same provider/model/prompt, different endpoint: no cache hit
        self.assertEqual((len(rec_a.requests), len(rec_b.requests)), (1, 1))
        a.ask("q")
        self.assertEqual(len(rec_a.requests), 1)

    def test_api_key_separates_entries(self):
        rec_a = Recorder(json_response(OPENAI_REPLY))
        a = llm("openai:m", api_key="key-a", transport=rec_a.transport, cache=self.db)
        rec_b = Recorder(json_response(OPENAI_REPLY))
        b = llm("openai:m", api_key="key-b", transport=rec_b.transport, cache=self.db)
        a.ask("q")
        b.ask("q")  # same prompt, different API key: no cache hit
        self.assertEqual((len(rec_a.requests), len(rec_b.requests)), (1, 1))
        rec_c = Recorder(json_response(OPENAI_REPLY))
        c = llm("openai:m", api_key="key-a", transport=rec_c.transport, cache=self.db)
        c.ask("q")  # reuses the first key: served from the cache
        self.assertEqual(len(rec_c.requests), 0)

    def test_extra_changes_the_key(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec, cache=self.db)
        m.ask("q")
        m.ask("q", extra={"seed_hint": 1})
        self.assertEqual(len(rec.requests), 2)
        m.ask("q", extra={"seed_hint": 1})
        self.assertEqual(len(rec.requests), 2)

    def test_openrouter(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm("openrouter:openai/gpt-x", api_key="k", transport=rec.transport, cache=self.db)
        m.ask("q")
        m.ask("q")
        self.assertEqual(len(rec.requests), 1)

    def test_anthropic(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        m = llm("claude:claude-opus-5-5", api_key="k", transport=rec.transport, cache=self.db)
        self.assertEqual(m.ask("q"), "ポチ")
        self.assertEqual(m.ask("q"), "ポチ")
        self.assertEqual(len(rec.requests), 1)

    def test_dropped_keys_share_one_cache_entry(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        m = llm("claude:claude-x", api_key="k", transport=rec.transport, cache=self.db)
        m.ask("q")
        m.ask("q", temperature=0.2, extra={"top_k": 1})
        self.assertEqual(len(rec.requests), 1)
        m.ask("q", max_tokens=5)
        self.assertEqual(len(rec.requests), 2)

    def test_streaming_is_cached(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        m = self.make(rec, cache=self.db)
        self.assertEqual("".join(m.stream("q")), "ポチ")
        self.assertEqual("".join(m.stream("q")), "ポチ")
        self.assertEqual(len(rec.requests), 1)

    def test_stream_without_terminal_event_is_not_cached(self):
        eof = OPENAI_STREAM.replace("data: [DONE]\n\n", "")
        rec = Recorder(sse_response(eof))
        m = self.make(rec, cache=self.db)
        self.assertEqual("".join(m.stream("q")), "ポチ")  # the caller still gets the chunks
        self.assertEqual(len(SQLiteCache(self.db)), 0)
        self.assertEqual("".join(m.stream("q")), "ポチ")
        self.assertEqual(len(rec.requests), 2)

    def test_google_stream_with_done_is_cached(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        m = llm("google:gemini-x", api_key="k", transport=rec.transport, cache=self.db)
        self.addCleanup(m.close)
        self.assertEqual("".join(m.stream("q")), "ポチ")
        self.assertEqual("".join(m.stream("q")), "ポチ")
        self.assertEqual(len(rec.requests), 1)

    def test_partial_stream_is_not_cached(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        m = self.make(rec, cache=self.db)
        it = m.stream("q")
        next(it)
        it.close()
        self.assertEqual("".join(m.stream("q")), "ポチ")
        self.assertEqual(len(rec.requests), 2)

    def test_stream_and_chat_do_not_share_entries(self):
        rec = Recorder(sse_response(OPENAI_STREAM), json_response(OPENAI_REPLY))
        m = self.make(rec, cache=self.db)
        list(m.stream("q"))
        m.ask("q")
        self.assertEqual(len(rec.requests), 2)

    def test_broken_cache_is_best_effort(self):
        class Broken:
            def get(self, key):
                raise RuntimeError("boom")

            def put(self, key, provider, result):
                raise RuntimeError("boom")

        rec = Recorder(json_response(OPENAI_REPLY))
        m = self.make(rec, cache=Broken())
        self.assertEqual(m.ask("q"), "ポチ")
        self.assertEqual(len(rec.requests), 1)

    def test_invalid_cache_setting(self):
        with self.assertRaises(LLMConfigError) as cm:
            llm("openai:m", api_key="k", cache=123, lang="en")
        self.assertEqual(cm.exception.code, "invalid_cache")
        with self.assertRaises(LLMConfigError):
            set_cache(123)


if __name__ == "__main__":
    unittest.main()
