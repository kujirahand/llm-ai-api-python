"""Concurrent cache misses share successful non-streaming calls."""

import asyncio
import concurrent.futures
import threading
import unittest
from unittest import mock

import httpx

from llm_ai_api import OpenAIClient, AnthropicClient
from llm_ai_api._async_clients import _AsyncOpenAIClient, _AsyncAnthropicClient


class MemoryCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def put(self, key, provider, result):
        self.values[key] = result


def reply(anthropic):
    if anthropic:
        return {"content": [{"type": "text", "text": "ok"}]}
    return {"choices": [{"message": {"content": "ok"}}]}


class SyncSingleFlightTests(unittest.TestCase):
    def test_concurrent_calls_and_failure(self):
        for cls in (OpenAIClient, AnthropicClient):
            for fail in (False, True):
                with self.subTest(cls=cls, fail=fail):
                    entered, release = threading.Event(), threading.Event()
                    calls = []
                    def handler(request):
                        calls.append(1)
                        if len(calls) == 1:
                            entered.set()
                            self.assertTrue(release.wait(5))
                            if fail:
                                return httpx.Response(400, json={"error": {"message": "bad"}})
                        return httpx.Response(200, json=reply(cls is AnthropicClient))
                    client = cls(api_key="k", cache=MemoryCache(), transport=httpx.MockTransport(handler))
                    self.addCleanup(client.close)
                    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                        first = pool.submit(client.chat, "model", [])
                        self.assertTrue(entered.wait(5))
                        others = [pool.submit(client.chat, "model", []) for _ in range(3)]
                        release.set()
                        if fail:
                            with self.assertRaises(Exception):
                                first.result(5)
                        else:
                            self.assertEqual(first.result(5).text, "ok")
                        self.assertEqual([f.result(5).text for f in others], ["ok"] * 3)
                    self.assertEqual(len(calls), 2 if fail else 1)


class AsyncSingleFlightTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_calls_and_cancellation(self):
        async def immediate(func, *args, **kwargs):
            return func(*args, **kwargs)

        patcher = mock.patch("llm_ai_api._async_http.asyncio.to_thread", immediate)
        patcher.start()
        self.addCleanup(patcher.stop)
        for cls in (_AsyncOpenAIClient, _AsyncAnthropicClient):
            for cancel in (False, True):
                with self.subTest(cls=cls, cancel=cancel):
                    entered, release = asyncio.Event(), asyncio.Event()
                    calls = []
                    async def handler(request):
                        calls.append(1)
                        if len(calls) == 1:
                            entered.set()
                            await release.wait()
                        return httpx.Response(200, json=reply(cls is _AsyncAnthropicClient))
                    client = cls(api_key="k", cache=MemoryCache(), transport=httpx.MockTransport(handler))
                    self.addAsyncCleanup(client.aclose)
                    first = asyncio.create_task(client.achat("model", []))
                    await asyncio.wait_for(entered.wait(), 5)
                    others = [asyncio.create_task(client.achat("model", [])) for _ in range(3)]
                    await asyncio.sleep(0.05)
                    if cancel:
                        first.cancel()
                        with self.assertRaises(asyncio.CancelledError):
                            await first
                    else:
                        release.set()
                        self.assertEqual((await first).text, "ok")
                    results = await asyncio.wait_for(asyncio.gather(*others), 5)
                    self.assertEqual([r.text for r in results], ["ok"] * 3)
                    self.assertEqual(len(calls), 2 if cancel else 1)
