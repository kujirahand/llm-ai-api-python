"""テスト用ヘルパー。ネットワークには出ず、httpx.MockTransport で応答を差し替える。"""

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
