"""Tests for ask(images=...) and its stream / async variants."""

import base64
import os
import tempfile
import unittest

from llm_ai_api import LLMConfigError, llm

from .helpers import Recorder, json_response, sse_response

OPENAI_REPLY = {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}]}
CLAUDE_REPLY = {"content": [{"type": "text", "text": "ok"}], "stop_reason": "end_turn"}
OPENAI_STREAM = (
    'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
    'data: {"choices":[{"delta":{"content":"b"}}]}\n\n'
    "data: [DONE]\n\n"
)

PNG = b"\x89PNG\r\n\x1a\n" + b"png-body"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-body"
GIF = b"GIF89a" + b"gif-body"
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 "
URL = "https://example.com/cat.png"


def b64(data):
    return base64.b64encode(data).decode("ascii")


def openai_llm(rec, spec="openai:gpt-x"):
    return llm(spec, api_key="k", lang="en", transport=rec.transport)


def claude_llm(rec):
    return llm("anthropic:claude-x", api_key="k", lang="en", transport=rec.transport)


class MultimodalTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def write(self, name, data):
        path = os.path.join(self.tmp.name, name)
        with open(path, "wb") as f:
            f.write(data)
        return path


class OpenAIImagesTest(MultimodalTestBase):
    def test_path_bytes_and_url(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        path = self.write("a.bin", PNG)  # type decided by the signature, not the extension
        self.assertEqual(openai_llm(rec).ask("look", images=[path, JPEG, URL]), "ok")
        self.assertEqual(
            rec.body()["messages"],
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look"},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/png;base64," + b64(PNG)},
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + b64(JPEG)},
                        },
                        {"type": "image_url", "image_url": {"url": URL}},
                    ],
                }
            ],
        )

    def test_pathlike_and_other_signatures(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        import pathlib

        path = pathlib.Path(self.write("x.dat", GIF))
        openai_llm(rec).ask("q", images=[path, WEBP])
        urls = [p["image_url"]["url"] for p in rec.body()["messages"][0]["content"][1:]]
        self.assertEqual(
            urls,
            ["data:image/gif;base64," + b64(GIF), "data:image/webp;base64," + b64(WEBP)],
        )

    def test_extension_fallback(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        path = self.write("photo.JPG", b"no signature here")
        openai_llm(rec).ask("q", images=[path])
        url = rec.body()["messages"][0]["content"][1]["image_url"]["url"]
        self.assertTrue(url.startswith("data:image/jpeg;base64,"))

    def test_openrouter_and_google_use_the_same_format(self):
        for spec in ("openrouter:a/b", "google:gemini-x"):
            rec = Recorder(json_response(OPENAI_REPLY))
            openai_llm(rec, spec).ask("q", images=[URL])
            self.assertEqual(
                rec.body()["messages"][0]["content"][1],
                {"type": "image_url", "image_url": {"url": URL}},
                spec,
            )

    def test_no_images_keeps_string_content(self):
        for kwargs in ({}, {"images": None}, {"images": []}, {"images": ()}):
            rec = Recorder(json_response(OPENAI_REPLY))
            openai_llm(rec).ask("q", **kwargs)
            self.assertEqual(rec.body()["messages"], [{"role": "user", "content": "q"}])

    def test_system_is_still_prepended(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        openai_llm(rec).ask("q", system="S", images=[URL])
        msgs = rec.body()["messages"]
        self.assertEqual(msgs[0], {"role": "system", "content": "S"})
        self.assertIsInstance(msgs[1]["content"], list)

    def test_ask_stream_sends_content_array(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        self.assertEqual(list(openai_llm(rec).ask_stream("q", images=[PNG])), ["a", "b"])
        b = rec.body()
        self.assertTrue(b["stream"])
        self.assertEqual(b["messages"][0]["content"][0], {"type": "text", "text": "q"})
        self.assertEqual(b["messages"][0]["content"][1]["type"], "image_url")

    def test_old_stream_alias_accepts_images(self):
        rec = Recorder(sse_response(OPENAI_STREAM))
        self.assertEqual(list(openai_llm(rec).stream("q", images=[URL])), ["a", "b"])
        self.assertIsInstance(rec.body()["messages"][0]["content"], list)


class AnthropicImagesTest(MultimodalTestBase):
    def test_base64_and_url_sources(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        path = self.write("a.png", PNG)
        claude_llm(rec).ask("look", images=[path, URL])
        self.assertEqual(
            rec.body()["messages"],
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "look"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64(PNG),
                            },
                        },
                        {"type": "image", "source": {"type": "url", "url": URL}},
                    ],
                }
            ],
        )


class InvalidImagesTest(MultimodalTestBase):
    def assert_invalid(self, rec, call):
        with self.assertRaises(LLMConfigError) as cm:
            call()
        self.assertEqual(cm.exception.code, "invalid_media")
        self.assertEqual(rec.requests, [])
        return cm.exception

    def test_messages_list_with_images(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        history = [{"role": "user", "content": "q"}]
        self.assert_invalid(rec, lambda: openai_llm(rec).ask(history, images=[URL]))
        self.assert_invalid(rec, lambda: openai_llm(rec).ask_stream(history, images=[URL]))
        self.assertEqual(history, [{"role": "user", "content": "q"}])

    def test_messages_list_with_empty_images_is_unchanged(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        history = [{"role": "user", "content": "q"}]
        openai_llm(rec).ask(history, images=[])
        self.assertEqual(rec.body()["messages"], history)

    def test_bad_arguments(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = openai_llm(rec)
        for bad in (
            [1],
            [{"url": URL}],
            [None],
            "photo.png",
            b"\x89PNG....",
            URL,
            42,
            {"a": 1},
        ):
            self.assert_invalid(rec, lambda: m.ask("q", images=bad))

    def test_unknown_type(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = openai_llm(rec)
        self.assert_invalid(rec, lambda: m.ask("q", images=[b"not an image"]))
        self.assert_invalid(rec, lambda: m.ask("q", images=[b""]))
        path = self.write("data.txt", b"text")
        self.assert_invalid(rec, lambda: m.ask("q", images=[path]))

    def test_unreadable_file_keeps_the_cause(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        missing = os.path.join(self.tmp.name, "missing.png")
        err = self.assert_invalid(rec, lambda: openai_llm(rec).ask("q", images=[missing]))
        self.assertIsInstance(err.__cause__, OSError)

    def test_messages_are_in_the_requested_language(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = llm("openai:gpt-x", api_key="k", lang="ja", transport=rec.transport)
        err = self.assert_invalid(rec, lambda: m.ask("q", images="x.png"))
        self.assertIn("images=", str(err))
        self.assertIn("リスト", str(err))


class AsyncImagesTest(MultimodalTestBase, unittest.IsolatedAsyncioTestCase):
    async def test_aask_matches_sync_body(self):
        path = self.write("a.png", PNG)
        sync_rec = Recorder(json_response(OPENAI_REPLY))
        openai_llm(sync_rec).ask("q", images=[path, URL])
        async_rec = Recorder(json_response(OPENAI_REPLY))
        m = openai_llm(async_rec)
        try:
            self.assertEqual(await m.aask("q", images=[path, URL]), "ok")
        finally:
            await m.aclose()
        self.assertEqual(async_rec.body(), sync_rec.body())

    async def test_aask_stream_sends_content_array(self):
        path = self.write("a.png", PNG)
        rec = Recorder(sse_response(OPENAI_STREAM))
        m = openai_llm(rec)
        try:
            stream = m.aask_stream("q", images=[path])
            self.assertEqual(rec.requests, [])  # lazy: nothing is read or sent yet
            self.assertEqual([p async for p in stream], ["a", "b"])
        finally:
            await m.aclose()
        content = rec.body()["messages"][0]["content"]
        self.assertEqual(content[0], {"type": "text", "text": "q"})
        self.assertEqual(content[1]["image_url"]["url"], "data:image/png;base64," + b64(PNG))

    async def test_aask_anthropic_url(self):
        rec = Recorder(json_response(CLAUDE_REPLY))
        m = claude_llm(rec)
        try:
            await m.aask("q", images=[URL])
        finally:
            await m.aclose()
        self.assertEqual(
            rec.body()["messages"][0]["content"][1],
            {"type": "image", "source": {"type": "url", "url": URL}},
        )

    async def test_async_errors(self):
        rec = Recorder(json_response(OPENAI_REPLY))
        m = openai_llm(rec)
        try:
            with self.assertRaises(LLMConfigError) as cm:
                await m.aask([{"role": "user", "content": "q"}], images=[URL])
            self.assertEqual(cm.exception.code, "invalid_media")
            # aask_stream checks the arguments at call time ...
            with self.assertRaises(LLMConfigError):
                m.aask_stream("q", images="x.png")
            # ... and reports unreadable files at the first iteration.
            stream = m.aask_stream("q", images=[os.path.join(self.tmp.name, "nope.png")])
            with self.assertRaises(LLMConfigError) as cm:
                await stream.__anext__()
            self.assertEqual(cm.exception.code, "invalid_media")
        finally:
            await m.aclose()
        self.assertEqual(rec.requests, [])


if __name__ == "__main__":
    unittest.main()
