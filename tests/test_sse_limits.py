import unittest
from unittest.mock import patch

import httpx

from llm_ai_api import LLMError, OpenAIClient
from llm_ai_api._async_clients import _AsyncOpenAIClient


class SyncChunks(httpx.SyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read = 0
        self.closed = False

    def __iter__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk

    def close(self):
        self.closed = True


class AsyncChunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.read = 0
        self.closed = False

    async def __aiter__(self):
        for chunk in self.chunks:
            self.read += 1
            yield chunk

    async def aclose(self):
        self.closed = True


class SyncLimits(unittest.TestCase):
    def test_limits_close_and_notify(self):
        for chunks, limit in [([b'1234', b'56789', b'never'], '_MAX_SSE_LINE_BYTES'),
                              ([b'data: 1234\ndata: 5678\n', b'never'], '_MAX_SSE_EVENT_BYTES')]:
            with self.subTest(limit=limit), patch('llm_ai_api._http.' + limit, 8):
                source = SyncChunks(chunks)
                client = OpenAIClient(api_key='k', transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, stream=source)))
                seen = []
                client.add_event_listener('request_error', lambda event, payload: seen.append(payload['code']))
                stream = client.request_stream('/test', {})
                with self.assertRaises(LLMError) as error:
                    list(stream)
                self.assertEqual(error.exception.code, 'response_too_large')
                self.assertEqual(seen, ['response_too_large'])
                self.assertEqual(source.read, 2 if limit.endswith('LINE_BYTES') else 1)
                self.assertTrue(source.closed)
                client.close()

    def test_boundaries_and_split_crlf_utf8(self):
        from llm_ai_api._http import _SSELines, iter_sse
        with patch('llm_ai_api._http._MAX_SSE_EVENT_BYTES', 4):
            lines = _SSELines(None)
            result = []
            for chunk in [b'data: \xe3', b'\x81\x82\r', b'\n\r', b'\ndata: x\n\n']:
                result.extend(lines.feed(chunk))
            result.extend(lines.flush())
            self.assertEqual([e.data for e in iter_sse(result)], ['あ', 'x'])
            self.assertEqual(list(iter_sse(['data: ab', 'data: c', '']))[0].data, 'ab\nc')


class AsyncLimits(unittest.IsolatedAsyncioTestCase):
    async def test_limits_close_and_notify(self):
        for chunks, limit in [([b'1234', b'56789', b'never'], '_MAX_SSE_LINE_BYTES'),
                              ([b'data: 1234\ndata: 5678\n', b'never'], '_MAX_SSE_EVENT_BYTES')]:
            with self.subTest(limit=limit), patch('llm_ai_api._http.' + limit, 8):
                source = AsyncChunks(chunks)
                client = _AsyncOpenAIClient(api_key='k', transport=httpx.MockTransport(
                    lambda request: httpx.Response(200, stream=source)))
                seen = []
                client.add_event_listener('request_error', lambda event, payload: seen.append(payload['code']))
                stream = await client.request_stream('/test', {})
                with self.assertRaises(LLMError) as error:
                    async for _ in stream:
                        pass
                self.assertEqual(error.exception.code, 'response_too_large')
                self.assertEqual(seen, ['response_too_large'])
                self.assertEqual(source.read, 2 if limit.endswith('LINE_BYTES') else 1)
                self.assertTrue(source.closed)
                await client.aclose()
