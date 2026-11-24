"""Examples from docs/api.md «Testing application code» / docs/api-ja.md «アプリのテスト»."""

from __future__ import annotations

import unittest
from typing import Any, AsyncIterator, Iterator, Protocol

from llm_ai_api.errors import RateLimitError
from llm_ai_api.types import ChatResult


class AppLLM(Protocol):
    def ask(self, prompt: str | list[dict], **kwargs: Any) -> str: ...


class ScriptedLLM:
    def __init__(self, replies: list[str | ChatResult | BaseException]):
        self._replies = list(replies)

    def ask(self, prompt: str | list[dict], **kwargs: Any) -> str:
        if not self._replies:
            raise AssertionError("no scripted replies left")
        item = self._replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ChatResult):
            return item.text
        return item


def summarize(client: AppLLM, text: str) -> str:
    return client.ask("Summarize:\n" + text)


class ScriptedStream:
    def __init__(self, text: str):
        self.request_id = None
        self.retries = 0
        self._chunks = [text]
        self._index = 0

    def __iter__(self) -> Iterator[str]:
        return self

    def __next__(self) -> str:
        if self._index >= len(self._chunks):
            raise StopIteration
        chunk = self._chunks[self._index]
        self._index += 1
        return chunk


class ScriptedAsyncLLM:
    def __init__(self, replies: list[str | ChatResult | BaseException]):
        self._replies = list(replies)

    def _next(self) -> str | ChatResult:
        if not self._replies:
            raise AssertionError("no scripted replies left")
        item = self._replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    async def aask(self, prompt: str | list[dict], **kwargs: Any) -> str:
        item = self._next()
        return item.text if isinstance(item, ChatResult) else item

    async def aask_stream(self, prompt: str | list[dict], **kwargs: Any) -> AsyncIterator[str]:
        item = self._next()
        text = item.text if isinstance(item, ChatResult) else item

        class Stream:
            def __init__(self, chunks: list[str]):
                self.request_id = None
                self.retries = 0
                self._chunks = chunks
                self._index = 0

            def __aiter__(self):
                return self

            async def __anext__(self) -> str:
                if self._index >= len(self._chunks):
                    raise StopAsyncIteration
                chunk = self._chunks[self._index]
                self._index += 1
                return chunk

        return Stream([text])


async def asummarize(client: ScriptedAsyncLLM, text: str) -> str:
    return await client.aask("Summarize:\n" + text)


class TestingAppsDocsTest(unittest.TestCase):
    def test_scripted_ask_returns_text(self):
        client = ScriptedLLM(["a short summary"])
        self.assertEqual(summarize(client, "a long article"), "a short summary")

    def test_scripted_ask_accepts_chat_result(self):
        client = ScriptedLLM([ChatResult(text="from result")])
        self.assertEqual(summarize(client, "article"), "from result")

    def test_scripted_rate_limit(self):
        client = ScriptedLLM([RateLimitError("slow down", status_code=429)])
        with self.assertRaises(RateLimitError):
            summarize(client, "a long article")

    def test_scripted_stream_has_public_attributes(self):
        stream = ScriptedStream("hello")
        self.assertIsNone(stream.request_id)
        self.assertEqual(stream.retries, 0)
        self.assertEqual(list(stream), ["hello"])


class TestingAppsDocsAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_scripted_aask(self):
        client = ScriptedAsyncLLM(["a short summary"])
        self.assertEqual(await asummarize(client, "a long article"), "a short summary")

    async def test_scripted_aask_stream(self):
        client = ScriptedAsyncLLM(["chunk"])
        stream = await client.aask_stream("q")
        self.assertIsNone(stream.request_id)
        self.assertEqual(stream.retries, 0)
        chunks = [chunk async for chunk in stream]
        self.assertEqual(chunks, ["chunk"])

    async def test_scripted_aask_rate_limit(self):
        client = ScriptedAsyncLLM([RateLimitError("slow down", status_code=429)])
        with self.assertRaises(RateLimitError):
            await asummarize(client, "article")
