"""Examples from docs/api.md «Testing application code» / docs/api-ja.md «アプリのテスト».

The sync example is extracted from the docs and executed, so editing the
example in the docs breaks this test. The async stub below mirrors the
real LLM shape: aask() is a coroutine, while aask_stream() is a plain
method returning an async iterator (no await at the call site).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, AsyncIterator, Iterator, Protocol

from llm_ai_api.errors import RateLimitError
from llm_ai_api.types import ChatResult

_DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"


def _extract_example(filename: str, heading: str) -> str:
    text = (_DOCS_DIR / filename).read_text(encoding="utf-8")
    section = text.split(heading, 1)[1]
    return section.split("```python\n", 1)[1].split("\n```", 1)[0]


def _load_sync_example() -> dict:
    namespace: dict = {}
    code = _extract_example("api.md", "## Testing application code")
    exec(compile(code, "docs/api.md", "exec"), namespace)
    return namespace


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


class AsyncAppLLM(Protocol):
    async def aask(self, prompt: str | list[dict], **kwargs: Any) -> str: ...

    def aask_stream(
        self, prompt: str | list[dict], **kwargs: Any
    ) -> AsyncIterator[str]: ...


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

    def aask_stream(self, prompt: str | list[dict], **kwargs: Any):
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


async def asummarize(client: AsyncAppLLM, text: str) -> str:
    return await client.aask("Summarize:\n" + text)


class TestingAppsDocsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = _load_sync_example()

    def test_doc_examples_match_between_languages(self):
        en = _extract_example("api.md", "## Testing application code")
        ja = _extract_example("api-ja.md", "## アプリのテスト")
        self.assertEqual(en, ja)

    def test_scripted_ask_returns_text(self):
        client = self.example["ScriptedLLM"](["a short summary"])
        summarize = self.example["summarize"]
        self.assertEqual(summarize(client, "a long article"), "a short summary")

    def test_scripted_ask_accepts_chat_result(self):
        client = self.example["ScriptedLLM"]([ChatResult(text="from result")])
        summarize = self.example["summarize"]
        self.assertEqual(summarize(client, "article"), "from result")

    def test_scripted_rate_limit(self):
        client = self.example["ScriptedLLM"](
            [RateLimitError("slow down", status_code=429)]
        )
        summarize = self.example["summarize"]
        with self.assertRaises(RateLimitError):
            summarize(client, "a long article")

    def test_scripted_exhaustion_is_an_error(self):
        client = self.example["ScriptedLLM"]([])
        summarize = self.example["summarize"]
        with self.assertRaises(AssertionError):
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
        stream = client.aask_stream("q")
        self.assertIsNone(stream.request_id)
        self.assertEqual(stream.retries, 0)
        chunks = [chunk async for chunk in stream]
        self.assertEqual(chunks, ["chunk"])

    async def test_scripted_aask_rate_limit(self):
        client = ScriptedAsyncLLM([RateLimitError("slow down", status_code=429)])
        with self.assertRaises(RateLimitError):
            await asummarize(client, "article")
