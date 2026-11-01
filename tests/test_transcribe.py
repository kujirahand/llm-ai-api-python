"""transcribe() / atranscribe() and multipart support in the raw layer (#58)."""

import asyncio
import os
import tempfile
import unittest
from email import message_from_bytes
from email.policy import default

from llm_ai_api import LLMConfigError, LLMError, llm
from llm_ai_api._media import sniff_audio_type
from llm_ai_api.openai import OpenAIClient

from tests.helpers import FreshRecorder, Recorder, json_response

WAV = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 16
MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 16


def parse_multipart(request):
    """Return (content_type, {name: [part, ...]}) for a recorded multipart request."""
    ctype = request.headers["content-type"]
    raw = b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + request.content
    msg = message_from_bytes(raw, policy=default)
    parts = {}
    for part in msg.iter_parts():
        parts.setdefault(part.get_param("name", header="content-disposition"), []).append(part)
    return ctype, parts


def text_of(part):
    return part.get_payload(decode=True).decode("utf-8")


class TranscribeTest(unittest.TestCase):
    def make(self, spec="openai:whisper-x", rec=None, **kw):
        rec = rec or Recorder(json_response({"text": "こんにちは"}))
        return llm(spec, api_key="k", transport=rec.transport, lang="en", **kw), rec

    def test_multipart_request(self):
        m, rec = self.make()
        self.assertEqual(m.transcribe(WAV), "こんにちは")
        req = rec.requests[0]
        self.assertEqual(str(req.url), "https://api.openai.com/v1/audio/transcriptions")
        ctype, parts = parse_multipart(req)
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertEqual(text_of(parts["model"][0]), "whisper-x")
        self.assertEqual(text_of(parts["response_format"][0]), "json")
        f = parts["file"][0]
        self.assertEqual(f.get_filename(), "audio.wav")
        self.assertEqual(f.get_content_type(), "audio/wav")
        self.assertEqual(f.get_payload(decode=True), WAV)

    def test_extra_must_be_a_dict(self):
        m, rec = self.make()
        for bad in (["language", "ja"], "ja", 42):
            with self.assertRaises(LLMConfigError) as cm:
                m.transcribe(WAV, extra=bad)
            self.assertEqual(cm.exception.code, "invalid_media")
        self.assertEqual(rec.requests, [])

    def test_extra_scalar_replaces_default_field(self):
        m, rec = self.make()
        m.transcribe(WAV, extra={"model": "whisper-custom", "response_format": "json"})
        _, parts = parse_multipart(rec.requests[0])
        self.assertEqual([text_of(p) for p in parts["model"]], ["whisper-custom"])

    def test_instance_extra_does_not_leak_into_transcribe(self):
        m, rec = self.make(extra={"user": "u"})
        m.transcribe(WAV)
        _, parts = parse_multipart(rec.requests[0])
        self.assertNotIn("user", parts)

    def test_extra_fields(self):
        m, rec = self.make()
        m.transcribe(
            WAV,
            extra={
                "language": "ja",
                "timestamp_granularities": ["word", "segment"],
                "temperature": 0,
                "skip": None,
                "flag": True,
            },
        )
        _, parts = parse_multipart(rec.requests[0])
        self.assertEqual(text_of(parts["language"][0]), "ja")
        self.assertEqual(
            [text_of(p) for p in parts["timestamp_granularities[]"]], ["word", "segment"]
        )
        self.assertEqual(text_of(parts["temperature"][0]), "0")
        self.assertEqual(text_of(parts["flag"][0]), "true")
        self.assertNotIn("skip", parts)

    def test_path_keeps_file_name(self):
        m, rec = self.make()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "voice memo.wav")
            with open(path, "wb") as f:
                f.write(WAV)
            self.assertEqual(m.transcribe(path), "こんにちは")
        f = parse_multipart(rec.requests[0])[1]["file"][0]
        self.assertEqual(f.get_filename(), "voice memo.wav")
        self.assertEqual(f.get_content_type(), "audio/wav")

    def test_path_falls_back_to_extension(self):
        m, rec = self.make()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "a.m4a")
            with open(path, "wb") as f:
                f.write(b"\x00" * 16)
            m.transcribe(path)
        self.assertEqual(parse_multipart(rec.requests[0])[1]["file"][0].get_content_type(), "audio/mp4")

    def test_bytes_mp3(self):
        m, rec = self.make()
        m.transcribe(MP3)
        f = parse_multipart(rec.requests[0])[1]["file"][0]
        self.assertEqual(f.get_filename(), "audio.mp3")
        self.assertEqual(f.get_content_type(), "audio/mpeg")

    def test_sniff_formats(self):
        self.assertEqual(sniff_audio_type(b"\xff\xfb\x90\x00"), "audio/mpeg")
        self.assertEqual(sniff_audio_type(b"fLaC\x00"), "audio/flac")
        self.assertEqual(sniff_audio_type(b"OggS\x00"), "audio/ogg")
        self.assertEqual(sniff_audio_type(b"\x1a\x45\xdf\xa3\x00"), "audio/webm")
        self.assertEqual(sniff_audio_type(b"\x00\x00\x00\x18ftypM4A "), "audio/mp4")
        self.assertIsNone(sniff_audio_type(b"RIFF\x00\x00\x00\x00AVI "))

    def test_missing_text_is_error(self):
        m, _ = self.make(rec=Recorder(json_response({"language": "ja"})))
        with self.assertRaises(LLMError) as cm:
            m.transcribe(WAV)
        self.assertEqual(cm.exception.code, "invalid_json_response")

    def test_non_string_text_is_error(self):
        m, _ = self.make(rec=Recorder(json_response({"text": 3})))
        with self.assertRaises(LLMError):
            m.transcribe(WAV)

    def test_unsupported_provider(self):
        for spec in ("anthropic:claude-x", "openrouter:a/b", "google:gemini-x"):
            rec = Recorder(json_response({"text": "x"}))
            m, _ = self.make(spec, rec=rec)
            with self.assertRaises(LLMConfigError) as cm:
                m.transcribe(WAV)
            self.assertEqual(cm.exception.code, "unsupported_modality")
            self.assertEqual(rec.requests, [])

    def test_unsupported_provider_async(self):
        rec = Recorder(json_response({"text": "x"}))
        m, _ = self.make("anthropic:claude-x", rec=rec)
        with self.assertRaises(LLMConfigError) as cm:
            asyncio.run(m.atranscribe(WAV))
        self.assertEqual(cm.exception.code, "unsupported_modality")
        self.assertEqual(rec.requests, [])

    def test_invalid_inputs(self):
        m, rec = self.make()
        for bad in (b"not audio at all", 123, "/no/such/file.wav"):
            with self.assertRaises(LLMConfigError) as cm:
                m.transcribe(bad)
            self.assertEqual(cm.exception.code, "invalid_media")
        with self.assertRaises(LLMConfigError) as cm:
            m.transcribe(WAV, extra={"x": {"a": 1}})
        self.assertEqual(cm.exception.code, "invalid_media")
        with self.assertRaises(LLMConfigError) as cm:
            m.transcribe(WAV, extra={"x": [{"a": 1}]})
        self.assertEqual(cm.exception.code, "invalid_media")
        self.assertEqual(rec.requests, [])

    def test_ja_message(self):
        m = llm("openai:x", api_key="k", lang="ja")
        with self.assertRaises(LLMConfigError) as cm:
            m.transcribe(b"zzzz")
        self.assertIn("音声", str(cm.exception))

    def test_not_cached_or_logged(self):
        with tempfile.TemporaryDirectory() as d:
            rec = Recorder(json_response({"text": "t"}))
            m = llm(
                "openai:whisper-x",
                api_key="k",
                transport=rec.transport,
                cache=os.path.join(d, "c.db"),
                log=os.path.join(d, "l.jsonl"),
            )
            m.transcribe(WAV)
            m.transcribe(WAV)
            self.assertEqual(len(rec.requests), 2)
            # The client may create the log file eagerly, but no record is written.
            log_path = os.path.join(d, "l.jsonl")
            if os.path.exists(log_path):
                with open(log_path, encoding="utf-8") as f:
                    self.assertEqual(f.read(), "")

    def test_async(self):
        rec = FreshRecorder(lambda: json_response({"text": "こんにちは"}))

        async def run():
            async with llm("openai:whisper-x", api_key="k", transport=rec.transport) as m:
                return await m.atranscribe(MP3, extra={"language": "ja"})

        self.assertEqual(asyncio.run(run()), "こんにちは")
        ctype, parts = parse_multipart(rec.requests[0])
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertEqual(text_of(parts["model"][0]), "whisper-x")
        self.assertEqual(text_of(parts["language"][0]), "ja")
        f = parts["file"][0]
        self.assertEqual(f.get_filename(), "audio.mp3")
        self.assertEqual(f.get_payload(decode=True), MP3)

    def test_async_path(self):
        rec = FreshRecorder(lambda: json_response({"text": "ok"}))

        async def run(path):
            async with llm("openai:whisper-x", api_key="k", transport=rec.transport) as m:
                return await m.atranscribe(path)

        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "x.wav")
            with open(path, "wb") as f:
                f.write(WAV)
            self.assertEqual(asyncio.run(run(path)), "ok")
        self.assertEqual(parse_multipart(rec.requests[0])[1]["file"][0].get_filename(), "x.wav")


class RawMultipartTest(unittest.TestCase):
    def test_sync_request(self):
        rec = Recorder(json_response({"text": "raw", "duration": 1.5}))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        resp = c.request(
            "/audio/transcriptions",
            files={"file": ("a.wav", WAV, "audio/wav")},
            form_data=[("model", "m"), ("tag[]", "a"), ("tag[]", "b")],
        )
        self.assertEqual(resp, {"text": "raw", "duration": 1.5})
        ctype, parts = parse_multipart(rec.requests[0])
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        self.assertEqual([text_of(p) for p in parts["tag[]"]], ["a", "b"])
        self.assertEqual(parts["file"][0].get_payload(decode=True), WAV)

    def test_body_with_files_is_rejected(self):
        rec = Recorder(json_response({}))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        with self.assertRaises(LLMConfigError) as cm:
            c.request("/x", {"a": 1}, files={"file": ("a.wav", WAV, "audio/wav")})
        self.assertEqual(cm.exception.code, "invalid_option")
        self.assertEqual(rec.requests, [])

    def test_json_path_unchanged(self):
        rec = Recorder(json_response({"ok": True}))
        c = OpenAIClient(api_key="k", transport=rec.transport)
        c.request("/x", {"a": 1})
        self.assertEqual(rec.requests[0].headers["content-type"], "application/json")
        self.assertEqual(rec.body(), {"a": 1})

    def test_retry_resends_multipart(self):
        rec = Recorder(json_response({"error": {}}, status=500), json_response({"text": "t"}))
        c = OpenAIClient(api_key="k", transport=rec.transport, max_retries=1)
        c._sleep = lambda seconds: None
        c.request("/audio/transcriptions", files={"file": ("a.wav", WAV, "audio/wav")})
        self.assertEqual(len(rec.requests), 2)
        for req in rec.requests:
            self.assertEqual(parse_multipart(req)[1]["file"][0].get_payload(decode=True), WAV)


class RawMultipartAsyncTest(unittest.IsolatedAsyncioTestCase):
    async def test_async_request_and_body_rejection(self):
        from llm_ai_api._async_clients import _AsyncOpenAIClient

        rec = Recorder(json_response({"text": "raw"}))
        c = _AsyncOpenAIClient(api_key="k", transport=rec.transport)
        try:
            resp = await c.request(
                "/audio/transcriptions",
                files={"file": ("a.wav", WAV, "audio/wav")},
                form_data=[("model", "m")],
            )
            self.assertEqual(resp, {"text": "raw"})
            ctype, parts = parse_multipart(rec.requests[0])
            self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
            self.assertEqual(parts["file"][0].get_payload(decode=True), WAV)
            with self.assertRaises(LLMConfigError) as cm:
                await c.request("/x", {"a": 1}, files={"file": ("a.wav", WAV, "audio/wav")})
            self.assertEqual(cm.exception.code, "invalid_option")
        finally:
            await c.aclose()


if __name__ == "__main__":
    unittest.main()
