"""Tests for cache/log hardening (#33): file mode, WAL, size limits, bulk XOR."""

import asyncio
import gzip
import os
import sqlite3
import stat
import tempfile
import unittest
from unittest import mock

import httpx

import llm_ai_api._http as http_mod
from llm_ai_api import LLMError, OpenAIClient, SQLiteCache
from llm_ai_api._async_clients import _AsyncOpenAIClient
from llm_ai_api._async_http import aiter_sse
from llm_ai_api.cache import _keystream, _mac, decrypt, encrypt
from llm_ai_api.types import ChatResult

from .helpers import Recorder, json_response, sse_response

REPLY = {"choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}]}


class CacheFileTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name
        self.db = os.path.join(self.dir, "cache.db")

    def test_new_file_is_owner_only_even_with_open_umask(self):
        old = os.umask(0)
        self.addCleanup(os.umask, old)
        SQLiteCache(self.db).put("k", "openai", ChatResult("x", None, None, None, {}))
        self.assertEqual(stat.S_IMODE(os.stat(self.db).st_mode), 0o600)

    def test_existing_file_permissions_are_untouched(self):
        open(self.db, "wb").close()
        os.chmod(self.db, 0o644)
        SQLiteCache(self.db)
        self.assertEqual(stat.S_IMODE(os.stat(self.db).st_mode), 0o644)

    def test_new_cache_uses_wal_and_works(self):
        c = SQLiteCache(self.db)
        c.put("k", "openai", ChatResult("x", None, None, None, {}))
        self.assertEqual(c.get("k").text, "x")
        conn = sqlite3.connect(self.db)
        try:
            self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        finally:
            conn.close()


def _old_xor(a, b):
    return bytes(x ^ y for x, y in zip(a, b))


class BulkXorTest(unittest.TestCase):
    enc, mac = b"e" * 32, b"m" * 32

    def test_roundtrip_sizes(self):
        for plain in (b"", b"a", b"hello" * 100, os.urandom(1024 * 1024)):
            blob = encrypt(self.enc, self.mac, plain, b"aad")
            self.assertEqual(decrypt(self.enc, self.mac, blob, b"aad"), plain)

    def test_value_from_old_algorithm_still_decrypts(self):
        plain = b"\x00\xffold format" * 7
        nonce = b"n" * 16
        ct = _old_xor(plain, _keystream(self.enc, nonce, len(plain)))
        blob = nonce + ct + _mac(self.mac, b"aad", nonce, ct)
        self.assertEqual(decrypt(self.enc, self.mac, blob, b"aad"), plain)

    def test_new_encrypt_matches_old_layout(self):
        plain = b"same bytes" * 9
        blob = encrypt(self.enc, self.mac, plain, b"aad")
        nonce, ct = blob[:16], blob[16:-32]
        self.assertEqual(ct, _old_xor(plain, _keystream(self.enc, nonce, len(plain))))


class _RecordingStream(httpx.SyncByteStream):
    """Byte stream that counts how often its body is iterated and whether it was closed."""

    def __init__(self, data):
        self.data = data
        self.reads = 0
        self.closed = False

    def __iter__(self):
        self.reads += 1
        yield self.data

    def close(self):
        self.closed = True


class _RecordingAsyncStream(httpx.AsyncByteStream):
    def __init__(self, data):
        self.data = data
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        self.reads += 1
        yield self.data

    async def aclose(self):
        self.closed = True


class SizeLimitTest(unittest.TestCase):
    def test_non_stream_body_too_large(self):
        rec = Recorder(json_response({"pad": "x" * 100}))
        c = OpenAIClient(api_key="k", transport=rec.transport, lang="en")
        with mock.patch.object(http_mod, "_MAX_RESPONSE_BYTES", 50):
            with self.assertRaises(LLMError) as cm:
                c.request("/v1/chat/completions", {})
        self.assertEqual(cm.exception.code, "response_too_large")

    def test_non_stream_body_within_limit(self):
        rec = Recorder(json_response({"a": 1}))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        with mock.patch.object(http_mod, "_MAX_RESPONSE_BYTES", 50):
            self.assertEqual(c.request("/x", {}), {"a": 1})

    def test_async_non_stream_body_too_large(self):
        rec = Recorder(json_response({"pad": "x" * 100}))

        async def go():
            c = _AsyncOpenAIClient(api_key="k", transport=rec.transport, lang="en")
            try:
                await c.request("/x", {})
            finally:
                await c.aclose()

        with mock.patch.object(http_mod, "_MAX_RESPONSE_BYTES", 50):
            with self.assertRaises(LLMError) as cm:
                asyncio.run(go())
        self.assertEqual(cm.exception.code, "response_too_large")

    def test_content_length_over_cap_rejected_without_reading(self):
        stream = _RecordingStream(b"x" * 100)
        rec = Recorder(httpx.Response(200, headers={"content-length": "100"}, stream=stream))
        c = OpenAIClient(api_key="k", transport=rec.transport, lang="en")
        with mock.patch.object(http_mod, "_MAX_RESPONSE_BYTES", 50):
            with self.assertRaises(LLMError) as cm:
                c.request("/x", {})
        self.assertEqual(cm.exception.code, "response_too_large")
        self.assertEqual(stream.reads, 0)
        self.assertTrue(stream.closed)

    def test_async_content_length_over_cap_rejected_without_reading(self):
        stream = _RecordingAsyncStream(b"x" * 100)
        rec = Recorder(httpx.Response(200, headers={"content-length": "100"}, stream=stream))

        async def go():
            c = _AsyncOpenAIClient(api_key="k", transport=rec.transport, lang="en")
            try:
                await c.request("/x", {})
            finally:
                await c.aclose()

        with mock.patch.object(http_mod, "_MAX_RESPONSE_BYTES", 50):
            with self.assertRaises(LLMError) as cm:
                asyncio.run(go())
        self.assertEqual(cm.exception.code, "response_too_large")
        self.assertEqual(stream.reads, 0)
        self.assertTrue(stream.closed)

    def test_small_content_length_but_big_body_rejected_after_read(self):
        stream = _RecordingStream(b'{"pad": "' + b"x" * 100 + b'"}')
        rec = Recorder(httpx.Response(200, headers={"content-length": "10"}, stream=stream))
        c = OpenAIClient(api_key="k", transport=rec.transport, lang="en")
        with mock.patch.object(http_mod, "_MAX_RESPONSE_BYTES", 50):
            with self.assertRaises(LLMError) as cm:
                c.request("/x", {})
        self.assertEqual(cm.exception.code, "response_too_large")
        self.assertEqual(stream.reads, 1)

    def test_decoded_body_limits_sync_and_async(self):
        for compressed in (False, True):
            for status, streaming in ((200, False), (400, False), (400, True)):
                for asynchronous in (False, True):
                    with self.subTest(compressed=compressed, status=status,
                                      streaming=streaming, asynchronous=asynchronous):
                        data = b"x" * 100
                        headers = {}
                        if compressed:
                            data = gzip.compress(data)
                            headers["content-encoding"] = "gzip"
                        stream = (_RecordingAsyncStream(data) if asynchronous
                                  else _RecordingStream(data))
                        transport = httpx.MockTransport(
                            lambda request: httpx.Response(status, headers=headers, stream=stream)
                        )
                        async def run_async():
                            client = _AsyncOpenAIClient(api_key="k", transport=transport)
                            try:
                                if streaming:
                                    await client.request_stream("/x", {})
                                else:
                                    await client.request("/x", {})
                            finally:
                                await client.aclose()
                        with mock.patch.object(http_mod, "_MAX_RESPONSE_BYTES", 50):
                            with self.assertRaises(LLMError) as cm:
                                if asynchronous:
                                    asyncio.run(run_async())
                                else:
                                    client = OpenAIClient(api_key="k", transport=transport)
                                    try:
                                        if streaming:
                                            client.request_stream("/x", {})
                                        else:
                                            client.request("/x", {})
                                    finally:
                                        client.close()
                        self.assertEqual(cm.exception.code, "response_too_large")
                        self.assertTrue(stream.closed)

    def test_sse_line_cap_counts_bytes_not_characters(self):
        line = "data: " + "あ" * 10  # 16 characters, 36 bytes
        with mock.patch.object(http_mod, "_MAX_SSE_LINE_BYTES", 20):
            with self.assertRaises(LLMError) as cm:
                list(http_mod.iter_sse([line, ""]))
        self.assertEqual(cm.exception.code, "response_too_large")

    def test_async_sse_line_cap_counts_bytes_not_characters(self):
        async def lines():
            yield "data: " + "あ" * 10
            yield ""

        async def go():
            return [ev async for ev in aiter_sse(lines())]

        with mock.patch.object(http_mod, "_MAX_SSE_LINE_BYTES", 20):
            with self.assertRaises(LLMError) as cm:
                asyncio.run(go())
        self.assertEqual(cm.exception.code, "response_too_large")

    def test_sse_line_too_large(self):
        with mock.patch.object(http_mod, "_MAX_SSE_LINE_BYTES", 20):
            self.assertEqual(len(list(http_mod.iter_sse(["data: ok", ""]))), 1)
            with self.assertRaises(LLMError) as cm:
                list(http_mod.iter_sse(["data: " + "x" * 30, ""]))
        self.assertEqual(cm.exception.code, "response_too_large")

    def test_sse_line_too_large_via_stream(self):
        rec = Recorder(sse_response("data: " + "x" * 30 + "\n\n"))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        with mock.patch.object(http_mod, "_MAX_SSE_LINE_BYTES", 20):
            with self.assertRaises(LLMError) as cm:
                list(c.request_stream("/x", {}))
        self.assertEqual(cm.exception.code, "response_too_large")

    def test_async_sse_line_too_large(self):
        async def lines():
            yield "data: " + "x" * 30
            yield ""

        async def go():
            return [ev async for ev in aiter_sse(lines())]

        with mock.patch.object(http_mod, "_MAX_SSE_LINE_BYTES", 20):
            with self.assertRaises(LLMError) as cm:
                asyncio.run(go())
        self.assertEqual(cm.exception.code, "response_too_large")


if __name__ == "__main__":
    unittest.main()
