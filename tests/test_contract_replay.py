"""Replay redacted HTTP response fixtures through the public LLM interface."""

import json
import re
import unittest
from datetime import datetime
from pathlib import Path

from llm_ai_api import APIStreamError, InsufficientCreditsError, llm

from .helpers import FreshRecorder, replay_response

_FIXTURES = Path(__file__).with_name("fixtures")
_MESSAGES = [{"role": "user", "content": "Suggest a dog name."}]
_ALLOWED_HEADERS = {"content-type", "request-id", "x-request-id", "retry-after"}
_ALLOWED_KEYS = {
    "id",
    "kind",
    "source",
    "captured_at",
    "provider",
    "endpoint",
    "status",
    "headers",
    "body",
    "sse",
    "request",
    "expect",
}
# Per-provider replay setup. Add a row here when a fixture for another
# provider is recorded; an unknown provider fails loudly instead of
# silently replaying against the wrong base URL or request shape.
_BASE_URLS = {
    "openai": "https://contract.invalid/v1",
    "anthropic": "https://contract.invalid",
}
_SECRET = re.compile(
    r"\b(?:sk-|sk-ant-|xai-|AIza|gh[pousr]_|github_pat_)[\w-]{8,}"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\borg-[A-Za-z0-9]{8,}"
    r"|\beyJ[\w-]+\.[\w-]+\.[\w-]+"
    r"|\bBearer\s+[\w./+=-]+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r'|"(?:authorization|proxy[_-]?authorization|(?:x[_-]?)?api[_-]?key'
    r'|access[_-]?token|refresh[_-]?token|client[_-]?secret|password|cookie|set-cookie)"'
    r'\s*:\s*"[^"]+',
    re.IGNORECASE,
)


def _records():
    return {
        path.stem: json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(_FIXTURES.glob("*.json"))
    }


def _request_id(record):
    headers = record["headers"]
    return headers.get("x-request-id") or headers.get("request-id")


class ContractReplayTest(unittest.IsolatedAsyncioTestCase):
    def test_fixture_metadata_and_redaction(self):
        records = _records()
        self.assertTrue(records)
        for path in _FIXTURES.iterdir():
            self.assertTrue(
                path.name == "README.md" or path.suffix == ".json",
                f"unexpected file in fixtures/: {path.name}",
            )
        for name, record in records.items():
            with self.subTest(fixture=name):
                self.assertEqual(record["id"], name)
                self.assertFalse(set(record) - _ALLOWED_KEYS)
                self.assertIn(record["kind"], {"synthetic", "captured"})
                self.assertTrue(record["source"].strip())
                if record["kind"] == "synthetic":
                    self.assertIsNone(record["captured_at"])
                else:
                    captured_at = datetime.fromisoformat(record["captured_at"])
                    self.assertIsNotNone(captured_at.tzinfo)
                self.assertFalse(record["headers"].keys() - _ALLOWED_HEADERS)
                request_id = _request_id(record)
                if request_id is not None:
                    self.assertTrue(request_id.startswith("fixture-"), request_id)
                if "retry-after" in record["headers"]:
                    self.assertEqual(record["headers"]["retry-after"], "0")
                self.assertEqual(len({"body", "sse"} & record.keys()), 1)
                self.assertEqual(record["request"]["stream"], "sse" in record)

                # Avoid showing credential values in assertion output.
                self.assertFalse(
                    bool(_SECRET.search(json.dumps(record, ensure_ascii=False))),
                    "Possible secret in fixture metadata or JSON",
                )
                self.assertFalse(
                    bool(_SECRET.search(record.get("sse", ""))),
                    "Possible secret in SSE",
                )

    def test_stream_fixture_controls(self):
        records = _records()
        markers = {
            "openai": "data: [DONE]\n\n",
            "anthropic": 'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        }
        for provider, marker in markers.items():
            with self.subTest(provider=provider):
                if records[f"{provider}-sse-success"]["kind"] != "synthetic":
                    continue  # the exact-difference control only fits synthetic pairs
                complete = records[f"{provider}-sse-success"]["sse"]
                incomplete = records[f"{provider}-sse-incomplete"]["sse"]
                self.assertEqual(complete, incomplete + marker)
                self.assertNotIn(marker, incomplete)
        wire = records["openai-sse-success"]["sse"]
        self.assertIn("\r\n\r\n", wire)
        self.assertIn("\n\n", wire.replace("\r\n", ""))
        frames = [json.loads(line[6:]) for line in wire.splitlines()
                  if line.startswith("data: ") and line != "data: [DONE]"]
        self.assertEqual(frames[-1]["choices"], [])
        self.assertEqual(frames[-1]["usage"]["total_tokens"], 7)

    def _prepare(self, record, records):
        followup = record["expect"].get("retry_with")
        sequence = [record]
        if followup:
            final = records[followup]
            for key in ("provider", "endpoint", "request"):
                self.assertEqual(final[key], record[key])
            sequence.append(final)
        recorder = FreshRecorder(*(lambda reply=reply: replay_response(reply)
                                   for reply in sequence))
        client = llm(
            f'{record["provider"]}:{record["request"]["model"]}',
            api_key="fixture-key",
            base_url=_BASE_URLS[record["provider"]],
            transport=recorder.transport, max_retries=2, retry_after_max=0,
            cache=False, log=False,
        )
        return client, recorder, sequence

    def _check_requests(self, recorder, sequence):
        self.assertEqual(len(recorder.requests), len(sequence))
        for index, (request, record) in enumerate(zip(recorder.requests, sequence)):
            self.assertEqual(request.method, "POST")
            self.assertEqual(request.url.path, record["endpoint"])
            body = {"model": record["request"]["model"], "messages": _MESSAGES}
            if record["provider"] == "anthropic":
                body["max_tokens"] = 16000
            if record["request"]["stream"]:
                body["stream"] = True
                if record["provider"] == "openai":
                    body["stream_options"] = {"include_usage": True}
            self.assertEqual(recorder.body(index), body)

    def _check_result(self, result, sequence):
        final = sequence[-1]
        expect = final["expect"]
        self.assertEqual(result.raw, final["body"])
        self.assertEqual(result.text, expect["text"])
        self.assertEqual(result.model, final["body"].get("model"))
        self.assertEqual(result.stop_reason, expect["stop_reason"])
        self.assertEqual([result.usage.input_tokens, result.usage.output_tokens], expect["usage"])
        self.assertEqual(result.request_id, _request_id(final))
        self.assertEqual(result.retries, len(sequence) - 1)

    def _check_stream(self, stream, pieces, ends, record):
        self.assertEqual(pieces, record["expect"]["pieces"])
        self.assertEqual(stream.request_id, _request_id(record))
        self.assertEqual(stream.retries, 0)
        self.assertEqual([event["complete"] for event in ends],
                         [True] if record["expect"]["complete"] else [])

    def _watch_end(self, client):
        ends = []
        client.add_event_listener("stream_end", lambda _, payload: ends.append(payload))
        return ends

    def test_sync_replay(self):
        records = _records()
        for name, record in records.items():
            with self.subTest(fixture=name):
                client, recorder, sequence = self._prepare(record, records)
                with client:
                    if record["request"]["stream"]:
                        ends = self._watch_end(client)
                        stream = client.chat_stream(_MESSAGES)
                        pieces = []
                        if record["expect"]["complete"]:
                            pieces.extend(stream)
                        else:
                            with self.assertRaises(APIStreamError) as raised:
                                pieces.extend(stream)
                            self.assertEqual(raised.exception.code, "stream_incomplete")
                        self._check_stream(stream, pieces, ends, record)
                    elif record["expect"].get("error") == "credits":
                        with self.assertRaises(InsufficientCreditsError) as raised:
                            client.chat(_MESSAGES)
                        self.assertEqual(raised.exception.status_code, record["status"])
                    else:
                        self._check_result(client.chat(_MESSAGES), sequence)
                self._check_requests(recorder, sequence)

    async def test_async_replay(self):
        records = _records()
        for name, record in records.items():
            with self.subTest(fixture=name):
                client, recorder, sequence = self._prepare(record, records)
                async with client:
                    if record["request"]["stream"]:
                        ends = self._watch_end(client)
                        stream = client.achat_stream(_MESSAGES)
                        pieces = []
                        if record["expect"]["complete"]:
                            async for piece in stream:
                                pieces.append(piece)
                        else:
                            with self.assertRaises(APIStreamError) as raised:
                                async for piece in stream:
                                    pieces.append(piece)
                            self.assertEqual(raised.exception.code, "stream_incomplete")
                        self._check_stream(stream, pieces, ends, record)
                    elif record["expect"].get("error") == "credits":
                        with self.assertRaises(InsufficientCreditsError) as raised:
                            await client.achat(_MESSAGES)
                        self.assertEqual(raised.exception.status_code, record["status"])
                    else:
                        self._check_result(await client.achat(_MESSAGES), sequence)
                self._check_requests(recorder, sequence)
