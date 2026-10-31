import time
import unittest
from unittest.mock import patch

from llm_ai_api import _http
from llm_ai_api._async_http import _AsyncLoggedChunks, _AsyncRecordedEvents
from llm_ai_api.types import ChatChunk, SSEEvent


class Client:
    log = True
    def __init__(self):
        self.saved = []
    def _cache_store(self, *args):
        self.saved.append(args)
    def _log_call(self, *args, **kwargs):
        self.saved.append(args)
    async def _acache_store(self, *args):
        self.saved.append(args)
    async def _alog_call(self, *args, **kwargs):
        self.saved.append(args)


class EventIterator:
    def __init__(self, items):
        self.items = iter(items)
        self.started = time.monotonic()
        self.request_id = "request-123"
        self.retries = 2
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.items)

    def close(self):
        self.closed = True


class AsyncIterator:
    def __init__(self, items):
        self.items = iter(items)
        self.started = time.monotonic()
        self.request_id = "request-123"
        self.retries = 2
    def __aiter__(self):
        return self
    async def __anext__(self):
        try:
            return next(self.items)
        except StopIteration:
            raise StopAsyncIteration
    async def aclose(self):
        pass


class StreamLimitTests(unittest.TestCase):
    def test_sync_buffers_release_and_delivery_continues(self):
        client = Client()
        events = [SSEEvent(None, 'x' * 100), SSEEvent(None, '[DONE]')]
        chunks = [ChatChunk('x' * 100, {'text': 'x' * 100}), ChatChunk('end', {})]
        with patch.object(_http, '_STREAM_BUFFER_LIMIT', 150):
            recorded = _http.BaseClient._record_events(client, EventIterator(events), {})
            self.assertEqual(list(recorded), events)
            logged = _http.BaseClient._log_chunks(client, {}, iter(chunks), False)
            self.assertEqual(list(logged), chunks)
        self.assertEqual(len(client.saved), 1)
        self.assertEqual(client.saved[0][1],
                         {'text': None, 'chunks': None, 'truncated': True})

    def test_cache_metadata_and_overflow(self):
        events = [SSEEvent(None, "data"), SSEEvent(None, "[DONE]")]
        for limit in (1000, 1):
            client = Client()
            source = EventIterator(events)
            with patch.object(_http, "_STREAM_BUFFER_LIMIT", limit):
                self.assertEqual(list(_http.BaseClient._record_events(client, source, {})), events)
            self.assertTrue(source.closed)
            if limit == 1:
                self.assertEqual(client.saved, [])
            else:
                stored = client.saved[0][1]
                self.assertEqual((stored.request_id, stored.retries), ("request-123", 2))
                self.assertGreaterEqual(stored.latency, 0)

    def test_size_and_exact_boundary(self):
        self.assertEqual(_http._STREAM_BUFFER_LIMIT, 16 * 1024 * 1024)
        self.assertEqual(_http._stream_item_size('犬'), len('"犬"'.encode('utf-8')))
        client = Client()
        chunks = [ChatChunk('犬', {'text': '犬'})]
        limit = _http._stream_item_size(['犬', {'text': '犬'}])
        with patch.object(_http, '_STREAM_BUFFER_LIMIT', limit):
            self.assertEqual(list(_http.BaseClient._log_chunks(client, {}, iter(chunks), False)), chunks)
        self.assertEqual(client.saved[0][1], {'text': '犬', 'chunks': [{'text': '犬'}]})

    def test_early_close_does_not_log_truncation(self):
        client = Client()
        with patch.object(_http, '_STREAM_BUFFER_LIMIT', 1):
            stream = _http.BaseClient._log_chunks(client, {}, iter([ChatChunk('x', {})]), False)
            next(stream)
            stream.close()
        self.assertEqual(client.saved, [])


class AsyncStreamLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_buffers_release_and_delivery_continues(self):
        client = Client()
        events = [SSEEvent(None, 'x' * 100), SSEEvent(None, '[DONE]')]
        chunks = [ChatChunk('x' * 100, {'text': 'x' * 100}), ChatChunk('end', {})]
        with patch.object(_http, '_STREAM_BUFFER_LIMIT', 150):
            recorded = _AsyncRecordedEvents(client, AsyncIterator(events), {})
            self.assertEqual([e async for e in recorded], events)
            self.assertEqual(recorded._recorded, [])
            logged = _AsyncLoggedChunks(client, AsyncIterator(chunks), {}, False)
            self.assertEqual([c async for c in logged], chunks)
            self.assertEqual(logged._raws, [])
            self.assertEqual(logged._texts, [])
        self.assertEqual(len(client.saved), 1)
        self.assertEqual(client.saved[0][1],
                         {'text': None, 'chunks': None, 'truncated': True})

    async def test_async_cache_metadata_and_overflow(self):
        events = [SSEEvent(None, "data"), SSEEvent(None, "[DONE]")]
        for limit in (1000, 1):
            client = Client()
            with patch.object(_http, "_STREAM_BUFFER_LIMIT", limit):
                stream = _AsyncRecordedEvents(client, AsyncIterator(events), {})
                self.assertEqual([event async for event in stream], events)
            self.assertEqual((stream.request_id, stream.retries), ("request-123", 2))
            if limit == 1:
                self.assertEqual(client.saved, [])
            else:
                stored = client.saved[0][1]
                self.assertEqual((stored.request_id, stored.retries), ("request-123", 2))
                self.assertGreaterEqual(stored.latency, 0)

    async def test_async_exact_boundary_and_early_close(self):
        client = Client()
        chunk = ChatChunk('犬', {'text': '犬'})
        limit = _http._stream_item_size(['犬', {'text': '犬'}])
        with patch.object(_http, '_STREAM_BUFFER_LIMIT', limit):
            stream = _AsyncLoggedChunks(client, AsyncIterator([chunk]), {}, False)
            self.assertEqual([c async for c in stream], [chunk])
        self.assertEqual(client.saved[0][1], {'text': '犬', 'chunks': [{'text': '犬'}]})
        client.saved.clear()
        with patch.object(_http, '_STREAM_BUFFER_LIMIT', 1):
            stream = _AsyncLoggedChunks(client, AsyncIterator([chunk]), {}, False)
            await stream.__anext__()
            await stream.aclose()
        self.assertEqual(client.saved, [])
