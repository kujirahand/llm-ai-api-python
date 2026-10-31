"""テスト用ヘルパー。ネットワークには出ず、httpx.MockTransport で応答を差し替える。"""

import asyncio
import json

import httpx


class Recorder:
    """送られたリクエストを記録し、用意した応答を順に返す。"""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        r = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(r, Exception):
            raise r
        return r

    @property
    def transport(self):
        return httpx.MockTransport(self)

    def body(self, i=-1):
        return json.loads(self.requests[i].content)


def json_response(data, status=200, headers=None):
    return httpx.Response(status, json=data, headers=headers)


def sse_response(text, status=200):
    return httpx.Response(
        status, content=text.encode("utf-8"), headers={"content-type": "text/event-stream"}
    )


class FailingStream(httpx.SyncByteStream):
    """A response body that fails while being read (e.g. a connection dropped mid-body)."""

    def __init__(self, exc):
        self.exc = exc

    def __iter__(self):
        raise self.exc
        yield b""  # pragma: no cover  (makes this a generator)


class FreshRecorder(Recorder):
    """Recorder whose responses may be factories (called once per request).

    httpx wraps a response's stream for the client that sent it, so one Response
    object cannot be returned to both a sync and an async client. Tests that mix
    both pass `lambda: json_response(...)` instead.
    """

    def __call__(self, request):
        r = super().__call__(request)
        return r() if callable(r) else r


class AsyncFailingStream(httpx.AsyncByteStream):
    """Async version of FailingStream: fails while the body is being read."""

    def __init__(self, exc):
        self.exc = exc

    async def __aiter__(self):
        raise self.exc
        yield b""  # pragma: no cover  (makes this an async generator)


class BlockingAsyncStream(httpx.AsyncByteStream):
    """Yields `first` once, then waits forever (until cancelled). Records `aclose()`.

    Create it inside the running test loop (Python 3.9 binds asyncio.Event to it).
    """

    def __init__(self, first=b""):
        self.first = first
        self.closed = False
        self.started = asyncio.Event()
        self._never = asyncio.Event()

    async def __aiter__(self):
        if self.first:
            yield self.first
        self.started.set()
        await self._never.wait()
        yield b""  # pragma: no cover

    async def aclose(self):
        self.closed = True
