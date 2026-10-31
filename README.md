# llm-ai-api

A thin, stable HTTP wrapper for the OpenAI, OpenRouter, Claude (Anthropic), and Google APIs. It does not use the official SDKs; the only dependency is `httpx`.

[日本語版 (Japanese)](https://github.com/kujirahand/llm-ai-api-python/blob/main/README-ja.md)

## Installation

```sh
pip install llm-ai-api
```

## Quick start

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
print(luna.ask("Come up with a cute name for a dog"))
```

Set the API key via an environment variable (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` or `GOOGLE_API_KEY`).
The model is always `"<provider>:<model>"` (providers: `openai`, `openrouter`, `anthropic` / `claude`, `google`).
Google Gemini is called through Google's OpenAI-compatible endpoint.

### Streaming and chat

```python
# Streaming
for piece in luna.stream("Write a short story"):
    print(piece, end="", flush=True)

# Using a chat history
result = luna.chat([{"role": "user", "content": "hi"}])  # ChatResult: text, stop_reason, usage, raw
```

A stream closes its connection by itself when it is read to the end or dropped (for async streams, only while the event loop that created the stream is still running). To stop early, call `close()` (`await stream.aclose()` in async code) to release the connection right away.

Parameters you do not pass are never sent (newer models reject even default values such as `temperature`).
Anything else can go through `extra={...}`, or the raw layer: `luna.client.request(path, body)`.

#### Per-call timeout

`ask()` / `chat()` / `stream()` (and the async `aask()` / `achat()` / `astream()`) take a keyword argument `timeout` (seconds) that overrides the timeout for that call only. If omitted (`None`), the client's setting is used (default 600 seconds).

```python
text = luna.ask("A short question", timeout=30)
```

This is a **per-operation timeout**, not a total deadline (for a stream, it is the time to wait for the next data). Retries (2 by default) extend the total time. This parameter alone cannot guarantee a total deadline in sync code: the wait resets whenever data arrives, so even with `max_retries=0` the total time is unbounded, especially for streams and slow-drip responses. In async code, if you need a hard deadline, wrap the coroutine that consumes the whole stream in `asyncio.wait_for()`, not just the `astream()` call, because the request only starts at the first iteration.

You can also pick from the model constants (they are just `"provider:model"` strings):

```python
from llm_ai_api import llm, models

m = llm(models.ANTHROPIC_CLAUDE_OPUS_5_5)
```

The constants are examples. Any other model works as a plain string, e.g. `llm("openai:some-new-model")`.

### Async

The same `llm()` works with asyncio: add an `a` to the method name (`aask()`, `achat()`, `astream()`).

```python
import asyncio
from llm_ai_api import llm

async def main():
    async with llm("openai:gpt-6-luna") as m:
        print(await m.aask("Come up with a cute name for a dog"))

        async for piece in m.astream("Write a short story"):  # no await here
            print(piece, end="", flush=True)

        # One LLM can be shared by concurrent calls
        answers = await asyncio.gather(m.aask("One dog name"), m.aask("One cat name"))
        print(answers)

asyncio.run(main())
```

- `astream()` starts the request at the first iteration, so connection and HTTP errors are raised there (when `async for` starts), not when `astream()` is called (the sync `stream()` raises on the call). To stop early, call `await stream.aclose()`.
- Close it with `async with` (or `await m.aclose()`). A closed `LLM` cannot be reused.
- Do not carry one across event loops: create a new `llm()` for each `asyncio.run()`.
- Do not call the sync `ask()` / `chat()` / `stream()` from async code (for example, a FastAPI handler running in the event loop): they block the whole loop until the request finishes. Use `aask()` / `achat()` / `astream()` instead.
- `close()` closes only the sync client, not the async one. If you used the async API, call `await m.aclose()` (or use `async with`), which closes both.

The cache and the log work the same way as in the sync API. Only the common interface (`llm()`) is async; there are no async provider clients or raw layer (`request()`).

To try things step by step from the beginning, see the [Tutorial](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/tutorial.md). For reusing and closing the client, see [“Reuse and cleanup” in the tutorial](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/tutorial.md#9-reuse-and-cleanup).

## Response caching

Off by default. When on, a repeat call with the same provider, model and request (messages and parameters) returns the stored result without calling the API.

```python
from llm_ai_api import llm, set_cache

set_cache("cache.db")                    # process-wide: on (an SQLite file path)
m = llm("openai:gpt-6-luna")              # uses the global setting
m2 = llm("openai:gpt-6-luna", cache="other.db")  # per instance
m3 = llm("openai:gpt-6-luna", cache=False)       # off for this instance only
```

`cache=True` uses the default file `llm_ai_api_cache.db`. A `SQLiteCache` object can also be passed. Setting the environment variable `LLM_AI_API_CACHE_DIR` to a directory turns the cache on as `<dir>/cache.db` without calling `set_cache()`. Streaming (`stream()` / `stream_chat()`) is cached too (stored only when read up to the terminal event).

Stored responses are encrypted with a key derived from the API key. The lookup key is a hash of `{provider}:{model}@{api_key}>>>{input}`, so a different API key means a separate cache. Remove old entries with `clear_cache(days)` (`clear_cache(0)` deletes everything). When the file grows past `max_size` (default 100 MB; `set_cache(..., max_size=None)` for unlimited), the oldest third of the rows is deleted automatically.

Note that while the cache is on, the same request always returns the same stored answer. Clear the cache or turn it off when you want a fresh generation. When the library creates the file, it is owner-only (0600).

See [docs/io_cache.md](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/io_cache.md) for details.

## Input/output log

Off by default. When enabled, every `ask()` / `chat()` / `stream()` / `stream_chat()` call appends one JSON Lines record with the input (request body) and the output (raw response).

```python
from llm_ai_api import llm, set_log

set_log("llm_log.jsonl")                       # on for the whole process
m = llm("openai:gpt-6-luna", log="other.jsonl")  # per instance
m2 = llm("openai:gpt-6-luna", log=False)         # off for this instance only
```

Set the `LLM_AI_API_LOG_DIR` environment variable to a directory to enable it as `<dir>/llm.jsonl`. Each line has `time`, `provider`, `model`, `stream`, `cached`, `request` and `response`. The API key is never recorded. The log is plain text and contains your prompts and the answers, so protect it. A stream is recorded only after it has been read to the end. When the file grows past `max_size` (default 100 MB; `set_log(..., max_size=None)` for unlimited), the oldest third of the lines is deleted automatically.

See [docs/io_logs.md](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/io_logs.md) for details.

## Connection settings

Connection-level settings such as the number of concurrent connections, a proxy, or TLS options can be set process-wide with `set_connection()`, or per instance with `connection=`.

```python
from llm_ai_api import llm, set_connection

set_connection(max_connections=50, proxy="http://proxy.example:8080")  # process-wide
m = llm("openai:gpt-6-luna", connection={"max_connections": 5})        # per-instance override
```

The available keys are `max_connections` (default 100), `max_keepalive_connections` (default 20), `keepalive_expiry` (seconds, default 5.0), `connect_timeout` (seconds, default 10.0), `verify` (bool or a CA path, default True), `cert` (a certificate path or pair), and `proxy` (an http/https URL). Settings are resolved when the client is created; calling `set_connection()` later does not affect existing instances. `set_connection()` replaces the whole setting, and calling it with no arguments restores the defaults.

## Examples

See [`examples/`](https://github.com/kujirahand/llm-ai-api-python/tree/main/examples). Each script takes a `provider:model` argument (or the `LLM_MODEL` env var).

| Script | What it shows |
|---|---|
| `hello.py` | Ask for a greeting |
| `hello_stream.py` | Print the reply as it streams |
| `hello_async.py` | `aask()` and `astream()` with `asyncio.run` and `async with` |
| `chat_history.py` | Reply based on a chat history |
| `ocr_test.py` | Read the text in an image |
| `image_desc.py` | Describe an image |
| `models_test.py` | Two models (GPT-6 Luna and Claude Haiku) discuss the breakfast menu, using the `models` constants (needs both API keys) |
| `cache_demo.py` | Ask the same question twice and see the second answer come from the cache |

Image content is not converted between providers; the examples build the right format for each one (see `examples/_common.py`).

## Error messages

Error messages are available in English and Japanese. The language is chosen from
`LLM_AI_API_LANG`, then `LANGUAGE` / `LC_ALL` / `LC_MESSAGES` / `LANG`, and falls back to English.
You can also set it explicitly:

```python
from llm_ai_api import llm, set_language

set_language("ja")                       # for the whole process
m = llm("openai:gpt-6-luna", lang="en")  # or per model
```

`set_language()` is process-global: it changes the language of error messages for the whole process, including other threads and instances created earlier when they raise (unlike `set_cache()` / `set_log()`, which are resolved when an instance is created). For a per-instance language, use the `lang=` option.

Every exception has a language-independent `code` (e.g. `"missing_api_key"`) you can check instead of the message.
Messages returned by the API itself are never translated.

## Prompt caching

See [docs/cache.md](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/cache.md).

## License

MIT
