"""Regression tests for #25: streaming responses must not leak.

- A sync stream dropped without being iterated still closes its response.
- A sync stream dropped after partial iteration closes its response.
- An async stream left with `break` and dropped without `aclose()` schedules
  the close on its event loop; with the loop gone it emits a ResourceWarning.
- Full iteration closes exactly once; `close()` / `aclose()` are idempotent.
- A sync `close()` never leaks httpx exceptions or masks the converted error.
- Finalizer close tasks whose loop died are pruned from `_PENDING_CLOSES`.
"""

import asyncio
import gc
import os
import tempfile
import threading
import unittest
import warnings

import httpx

from llm_ai_api import APITimeoutError, OpenAIClient, llm
from llm_ai_api import _async_http
from llm_ai_api._async_http import _AsyncEventStream
from llm_ai_api.lang import t

from .helpers import Recorder

EVENTS = b"".join(
    b'data: {"choices":[{"delta":{"content":"%d"}}]}\n\n' % i for i in range(5)
) + b"data: [DONE]\n\n"


class CountingStream(httpx.SyncByteStream):
    """A response body that counts `close()` calls."""

    def __init__(self, data=EVENTS):
        self.data = data
        self.closes = 0

    def __iter__(self):
        for line in self.data.splitlines(keepends=True):
            yield line

    def close(self):
        self.closes += 1


class AsyncCountingStream(httpx.AsyncByteStream):
    """Async version of CountingStream: counts `aclose()` calls."""

    def __init__(self, data=EVENTS):
        self.data = data
        self.closes = 0

    async def __aiter__(self):
        for line in self.data.splitlines(keepends=True):
            yield line

    async def aclose(self):
        self.closes += 1


class FailingCloseStream(CountingStream):
    """Counts `close()` calls, then raises an httpx error from it."""

    def close(self):
        super().close()
        raise httpx.ConnectError("close failed")


class TimeoutThenFailingCloseStream(FailingCloseStream):
    """Yields one event, then times out mid-stream; `close()` also fails."""

    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"0"}}]}\n\n'
        raise httpx.ReadTimeout("read timed out")


def sse(stream):
    return httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream"})


class SyncStreamCloseTest(unittest.TestCase):
    def setUp(self):
        self.body = CountingStream()
        self.rec = Recorder(sse(self.body))

    def make(self, **options):
        options.setdefault("cache", False)
        options.setdefault("log", False)
        m = llm("openai:gpt-x", api_key="k", transport=self.rec.transport, **options)
        self.addCleanup(m.close)
        return m

    def test_llm_stream_dropped_without_iteration_closes_response(self):
        s = self.make().ask_stream("q")
        self.assertEqual(self.body.closes, 0)
        del s
        gc.collect()
        self.assertEqual(self.body.closes, 1)

    def test_recorded_stream_dropped_without_iteration_closes_response(self):
        with tempfile.TemporaryDirectory() as d:
            s = self.make(cache=os.path.join(d, "cache.db")).ask_stream("q")
            del s
            gc.collect()
        self.assertEqual(self.body.closes, 1)

    def test_raw_request_stream_dropped_without_iteration_closes_response(self):
        client = OpenAIClient(api_key="k", transport=self.rec.transport, cache=False, log=False)
        self.addCleanup(client.close)
        events = client.request_stream("/chat/completions", {"model": "m"})
        del events
        gc.collect()
        self.assertEqual(self.body.closes, 1)

    def test_partially_consumed_then_dropped_closes_response(self):
        s = self.make().ask_stream("q")
        self.assertEqual(next(s), "0")
        del s
        gc.collect()
        self.assertEqual(self.body.closes, 1)

    def test_full_iteration_closes_once(self):
        s = self.make().ask_stream("q")
        self.assertEqual("".join(s), "01234")
        del s
        gc.collect()
        self.assertEqual(self.body.closes, 1)

    def test_explicit_close_is_idempotent(self):
        client = OpenAIClient(api_key="k", transport=self.rec.transport, cache=False, log=False)
        self.addCleanup(client.close)
        events = client.request_stream("/chat/completions", {"model": "m"})
        next(events)
        events.close()
        events.close()
        self.assertEqual(list(events), [])
        del events
        gc.collect()
        self.assertEqual(self.body.closes, 1)


class SyncStreamCloseErrorTest(unittest.TestCase):
    def open_events(self, body):
        rec = Recorder(sse(body))
        client = OpenAIClient(api_key="k", transport=rec.transport, cache=False, log=False,
                              lang="en")
        self.addCleanup(client.close)
        return client.request_stream("/chat/completions", {"model": "m"})

    def test_close_suppresses_httpx_error(self):
        body = FailingCloseStream()
        events = self.open_events(body)
        next(events)
        events.close()  # must not raise httpx.ConnectError
        self.assertEqual(body.closes, 1)
        events.close()
        self.assertEqual(body.closes, 1)

    def test_failing_close_does_not_mask_converted_timeout(self):
        body = TimeoutThenFailingCloseStream()
        events = self.open_events(body)
        next(events)
        with self.assertRaises(APITimeoutError):
            next(events)
        self.assertEqual(body.closes, 1)


class AsyncStreamCloseTest(unittest.IsolatedAsyncioTestCase):
    def make(self, body, **options):
        options.setdefault("cache", False)
        options.setdefault("log", False)
        rec = Recorder(sse(body))
        return llm("openai:gpt-x", api_key="k", transport=rec.transport, **options)

    async def tick(self):
        for _ in range(5):
            await asyncio.sleep(0)

    async def test_break_without_aclose_schedules_close(self):
        body = AsyncCountingStream()
        async with self.make(body) as m:
            s = m.aask_stream("q")
            async for piece in s:
                self.assertEqual(piece, "0")
                break
            self.assertEqual(body.closes, 0)
            del s, piece
            gc.collect()
            await self.tick()
            self.assertEqual(body.closes, 1)

    async def test_recorded_stream_break_without_aclose_schedules_close(self):
        body = AsyncCountingStream()
        with tempfile.TemporaryDirectory() as d:
            async with self.make(body, cache=os.path.join(d, "cache.db")) as m:
                s = m.aask_stream("q")
                async for _ in s:
                    break
                del s
                gc.collect()
                await self.tick()
                self.assertEqual(body.closes, 1)

    async def test_full_iteration_closes_once(self):
        body = AsyncCountingStream()
        async with self.make(body) as m:
            s = m.aask_stream("q")
            self.assertEqual("".join([p async for p in s]), "01234")
            del s
            gc.collect()
            await self.tick()
            self.assertEqual(body.closes, 1)

    async def test_explicit_aclose_is_idempotent(self):
        body = AsyncCountingStream()
        async with self.make(body) as m:
            s = m.aask_stream("q")
            await s.__anext__()
            await s.aclose()
            await s.aclose()
            del s
            gc.collect()
            await self.tick()
            self.assertEqual(body.closes, 1)

    async def test_dropped_from_other_thread_schedules_close_on_loop(self):
        body = AsyncCountingStream()
        async with self.make(body) as m:
            holder = [m.aask_stream("q")]
            async for _ in holder[0]:
                break
            self.assertEqual(body.closes, 0)

            def drop():
                # The finalizer runs here, off the loop thread, so it must go
                # through call_soon_threadsafe.
                holder.clear()
                gc.collect()

            th = threading.Thread(target=drop)
            th.start()
            th.join()
            self.assertEqual(body.closes, 0)
            await self.tick()
            self.assertEqual(body.closes, 1)


class FakeResp:
    """Stands in for an httpx.Response; `aclose()` optionally never finishes."""

    def __init__(self, hang=False):
        self.hang = hang
        self.started = False
        self.closes = 0

    async def aclose(self):
        self.started = True
        if self.hang:
            await asyncio.Event().wait()  # never set
        self.closes += 1


class PendingClosePruneTest(unittest.TestCase):
    def tick(self, loop):
        for _ in range(5):
            loop.run_until_complete(asyncio.sleep(0))

    def test_task_of_closed_loop_is_pruned(self):
        before = set(_async_http._PENDING_CLOSES)
        loop_a = asyncio.new_event_loop()
        try:
            hanging = FakeResp(hang=True)
            loop_a.call_soon(_async_http._schedule_close, hanging)
            self.tick(loop_a)
            self.assertTrue(hanging.started)
            new = set(_async_http._PENDING_CLOSES) - before
            self.assertEqual(len(new), 1)
            task_a = new.pop()
            self.assertFalse(task_a.done())
        finally:
            loop_a.close()
        # The task can never finish now; silence "Task was destroyed but it is pending".
        task_a._log_destroy_pending = False

        loop_b = asyncio.new_event_loop()
        try:
            normal = FakeResp()
            loop_b.call_soon(_async_http._schedule_close, normal)
            self.tick(loop_b)
        finally:
            loop_b.close()
        self.assertNotIn(task_a, _async_http._PENDING_CLOSES)
        self.assertEqual(normal.closes, 1)


class AsyncStreamNoLoopTest(unittest.TestCase):
    def test_dropped_after_loop_closed_warns(self):
        body = AsyncCountingStream()

        async def open_stream():
            m = llm("openai:gpt-x", api_key="k", transport=Recorder(sse(body)).transport,
                    cache=False, log=False, lang="en")
            client = m._get_async_client()
            return await client.request_stream("/chat/completions", {"model": "m"})

        loop = asyncio.new_event_loop()
        try:
            events = loop.run_until_complete(open_stream())
        finally:
            loop.close()
        self.assertIsInstance(events, _AsyncEventStream)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            del events
            gc.collect()
        expected = t("unclosed_stream", "en")
        self.assertTrue(
            any(w.category is ResourceWarning and str(w.message) == expected for w in caught)
        )
        self.assertEqual(body.closes, 0)


if __name__ == "__main__":
    unittest.main()
