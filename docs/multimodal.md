# Image input (`images=`)

`ask()`, `ask_stream()`, `aask()` and `aask_stream()` take a keyword-only `images=` argument. Only this layer builds provider-specific image formats; the provider layer and the raw layer convert nothing.

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna")
print(m.ask("What is in this photo?", images=["photo.png"]))
```

## What you can pass

Pass `images` as a **list** (even for one image). Each item is one of:

| Item | Handling |
|---|---|
| File path (`str` / `os.PathLike`) | The file is read and sent as base64 |
| `bytes` | Sent as base64 as is |
| String starting with `http://` or `https://` | Sent as a URL (nothing is downloaded) |

- The media type comes from the leading signature bytes (PNG / JPEG / GIF / WEBP). If they are not recognized, the path's extension (`.png` / `.jpg` / `.jpeg` / `.gif` / `.webp`) is used. If that fails too, `LLMConfigError(code="invalid_media")` is raised.
- An unreadable file, an `images` value that is not a list, or an item of the wrong type also raises `invalid_media` (the original `OSError` is kept in `__cause__`).
- Passing `images` with a non-string prompt (a messages list) raises `invalid_media`: the library does not guess which message should get the images.
- With `images` set to `None` or empty, the request is exactly the same as before (the content stays a string).
- The library sets no limit on the number or size of images. The provider's API limits apply.

## What is sent

The user message `content` becomes an array: the text part first, then the image parts in the order given.

| Provider | File / bytes | URL |
|---|---|---|
| `openai` / `openrouter` / `google` | `{"type": "image_url", "image_url": {"url": "data:<media_type>;base64,<data>"}}` | `{"type": "image_url", "image_url": {"url": "<URL>"}}` |
| `anthropic` | `{"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}` | `{"type": "image", "source": {"type": "url", "url": "<URL>"}}` |

Whether a URL is accepted is up to each API; the library does not block it.

## Async

`aask()` / `aask_stream()` read files in a worker thread, so the event loop is not blocked. `aask_stream()` checks the arguments when called and reads the files at the first iteration (read errors are raised there too).

## Use native dicts with `chat()`

`chat()` / `chat_stream()` have no `images=`. To send an image there, put a dict in the provider's native format into `content`. The library does not convert it between providers.

```python
m.chat([{"role": "user", "content": [
    {"type": "text", "text": "Describe it"},
    {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
]}])
```

## Logs and cache

Images travel as base64 in the request body, so the I/O log (`JSONLLog`) and the cache can end up holding large base64 strings. To keep them out of the log, strip the image parts with the `JSONLLog(path, redact=...)` hook (see [io_logs.md](io_logs.md)).
