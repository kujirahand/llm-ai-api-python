# llm-ai-api

[![PyPI](https://img.shields.io/pypi/v/llm-ai-api)](https://pypi.org/project/llm-ai-api/)

A thin, stable HTTP wrapper for the OpenAI, OpenRouter, Claude (Anthropic), and Google APIs. It does not use the official SDKs; the only dependency is `httpx`.

[日本語版 (Japanese)](https://github.com/kujirahand/llm-ai-api-python/blob/main/README-ja.md)

## Why use this package?

- **Unified code across providers**: Switch models simply by changing the model string—such as `llm("openai:gpt-6-luna")`, `llm("openrouter:anthropic/claude-sonnet-5.5")`, `llm("claude:claude-sonnet-5-5")`, or `llm("google:gemini-3.8-flash")`—while using the same `ask()`, `chat()`, and `ask_stream()` methods.
- **No boilerplate parameter handling**: Unspecified parameters are never sent. Furthermore, starting in v0.4.0, parameters confirmed to be rejected by official API specs (such as `temperature` and `top_p` on certain models) are automatically omitted according to a rule table, even if explicitly passed, removing the need to write custom workaround functions (such as `_is_no_temperature()`).
- **Built-in caching and logging**: SQLite response caching (encrypted with a key derived from your API key; streams can be cached too) via `set_cache()` (or `cache=`) and JSON Lines request/response logging via `set_log()` (or `log=`) are built right in.
- **Lightweight dependencies (`httpx` only)**: The only dependency is `httpx`; official packages like `openai` or `anthropic` are not required, keeping installs small and reducing dependency conflicts.

Header names are case-insensitive; client and per-request headers override earlier values. See the [configuration reference](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/config.md) for precedence.

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
For step-by-step setup, including how to configure an API key, see the [Tutorial](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/tutorial.md).

### Main methods

| Method | Method (async) | Description |
|---|---|---|
| `ask(prompt)` | `aask(prompt)` | Get a text response from the LLM |
| `ask_stream(prompt)` | `aask_stream(prompt)` | Get the LLM response as a stream |
| `chat(messages)` | `achat(messages)` | Give the LLM a conversation and get a response |
| `chat_stream(messages)` | `achat_stream(messages)` | Give the LLM a conversation and get the response as a stream |

For the full list of methods, see the [API Reference](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/api.md).

### Streaming and chat

```python
# Streaming
for piece in luna.ask_stream("Write a short story"):
    print(piece, end="", flush=True)

# Using a chat history
result = luna.chat([{"role": "user", "content": "hi"}])  # ChatResult: text, stop_reason, usage, raw, request_id, latency, retries

# Streaming with messages
for piece in luna.chat_stream([{"role": "user", "content": "hi"}]):
    print(piece, end="", flush=True)

# A chat app with history
history = []
while True:
    user_text = input("You: ")
    if not user_text:
        break
    history.append({"role": "user", "content": user_text})
    stream = luna.ask_stream(history)
    print("request_id:", stream.request_id)
    pieces = []
    for piece in stream:
        print(piece, end="", flush=True)
        pieces.append(piece)
    history.append({"role": "assistant", "content": "".join(pieces)})
```

`ask()` and `ask_stream()` also accept a non-empty list of message dictionaries. The async `aask()` and `aask_stream()` accept the same inputs. The caller owns the history; a `system=` argument is prepended just as in `chat()`. The stream iterator also has a `request_id`.

The old name `stream()` (`astream()` in async code) is deprecated. It remains as an alias of `ask_stream()` (`aask_stream()` in async code).

A stream closes its connection by itself when it is read to the end or dropped (for async streams, only while the event loop that created the stream is still running). To stop early, call `close()` (`await stream.aclose()` in async code) to release the connection right away.

Parameters you do not pass are never sent (newer models reject even default values such as `temperature`).
Parameters the official docs say a model rejects are omitted even when you pass them, including through `extra` (for example `temperature`, `top_p`, and `top_k` on Claude API version `2026-10-21`, and `temperature` on some OpenAI models such as `gpt-6-astra`). Models and parameters that are not in that list, and OpenRouter and Google, are sent as given. To send a dropped key unchanged, use the raw layer `luna.client.request(path, body)` (it does not rewrite the body). Anything else can go through `extra={...}`.

#### Per-call timeout

`ask()` / `chat()` / `ask_stream()` / `chat_stream()` (and the async `aask()` / `achat()` / `aask_stream()` / `achat_stream()`) take a keyword argument `timeout` (seconds) that overrides the timeout for that call only. If omitted (`None`), the client's setting is used (default 600 seconds).

```python
text = luna.ask("A short question", timeout=30)
```

This is a **per-operation timeout**, not a total deadline (for a stream, it is the time to wait for the next data). Retries (2 by default) extend the total time. This parameter alone cannot guarantee a total deadline in sync code: the wait resets whenever data arrives, so even with `max_retries=0` the total time is unbounded, especially for streams and slow-drip responses. In async code, if you need a hard deadline, wrap the coroutine that consumes the whole stream in `asyncio.wait_for()`, not just the `aask_stream()` call, because the request only starts at the first iteration.

You can also pick from the model constants (they are just `"provider:model"` strings):

```python
from llm_ai_api import llm, models

m = llm(models.ANTHROPIC_CLAUDE_OPUS_5_5)
```

The constants are examples. Any other model works as a plain string, e.g. `llm("openai:some-new-model")`.

### Timeouts and retries

```python
m = llm("openai:gpt-6-luna", timeout=60, max_retries=2, retry_read_timeout=False, retry_after_max=60)
m.set_config(max_retries=0)  # change after creation (only the given arguments; async too)
```

By default, only connection-stage failures (the request never reached the server) and HTTP 408 / 409 / 429 / 5xx are retried. Failures after the request was sent, such as read timeouts, are not retried, to avoid double billing (`retry_read_timeout=True` retries read timeouts too). `retry_after_max` caps how many seconds to wait when following a `retry-after` header. For the full list of settings and production recommendations, see the [configuration reference](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/config.md).

### Call results and events

`ChatResult` from `chat()` / `achat()` carries `request_id`, `latency` (seconds), and `retries` in addition to the response body (`raw`). `ask()` still returns only the text. Retries and failures are not written to the I/O log. Observe them with `add_event_listener`.

```python
luna.add_event_listener("retry", lambda event, payload: print(event, payload.get("request_id")))
result = luna.chat([{"role": "user", "content": "hi"}])
print(result.request_id, result.retries, result.latency)
```

The event list, payload keys, and where to read `request_id` (`ChatResult`, `ChatChunk`, stream iterators, exceptions, and `request()`) are in the [events reference](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/events.md).

### Async

The same `llm()` works with asyncio: add an `a` to the method name (`aask()`, `achat()`, `aask_stream()`, `achat_stream()`).

```python
import asyncio
from llm_ai_api import llm

async def main():
    async with llm("openai:gpt-6-luna") as m:
        print(await m.aask("Come up with a cute name for a dog"))

        async for piece in m.aask_stream("Write a short story"):  # no await here
            print(piece, end="", flush=True)

        # One LLM can be shared by concurrent calls
        answers = await asyncio.gather(m.aask("One dog name"), m.aask("One cat name"))
        print(answers)

asyncio.run(main())
```

- `aask_stream()` / `achat_stream()` start the request at the first iteration, so connection and HTTP errors are raised there (when `async for` starts), not when the method is called (the sync `ask_stream()` / `chat_stream()` raise on the call). To stop early, call `await stream.aclose()`.
- Close it with `async with` (or `await m.aclose()`). A closed `LLM` cannot be reused.
- Do not carry one across event loops: create a new `llm()` for each `asyncio.run()`.
- Do not call the sync `ask()` / `chat()` / `ask_stream()` / `chat_stream()` from async code (for example, a FastAPI handler running in the event loop): they block the whole loop until the request finishes. Use `aask()` / `achat()` / `aask_stream()` / `achat_stream()` instead.
- `close()` closes only the sync client, not the async one. If you used the async API, call `await m.aclose()` (or use `async with`), which closes both.

The cache and the log work the same way as in the sync API. Only the common interface (`llm()`) is async; there are no async provider clients or raw layer (`request()`).

For reusing and closing the client, see [“Reuse and cleanup” in the tutorial](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/tutorial.md#9-reuse-and-cleanup).

## Response caching

Off by default. When on, a repeat call with the same provider, model and request (messages and parameters) returns the stored result without calling the API.

```python
from llm_ai_api import llm, set_cache

set_cache("cache.db")                    # process-wide: on (an SQLite file path)
m = llm("openai:gpt-6-luna")              # uses the global setting
m2 = llm("openai:gpt-6-luna", cache="other.db")  # per instance
m3 = llm("openai:gpt-6-luna", cache=False)       # off for this instance only
```

`cache=True` uses the default file `llm_ai_api_cache.db`. A `SQLiteCache` object can also be passed. Setting the environment variable `LLM_AI_API_CACHE_DIR` to a directory turns the cache on as `<dir>/cache.db` without calling `set_cache()`. Streaming (`ask_stream()` / `chat_stream()` / `stream_chat()`) is cached too (stored only when read up to the terminal event).

Stored responses are encrypted with a key derived from the API key. The lookup key is a hash of `{provider}:{model}@{api_key}>>>{input}`, so a different API key means a separate cache. Remove old entries with `clear_cache(days)` (`clear_cache(0)` deletes everything). When the file grows past `max_size` (default 100 MB; `set_cache(..., max_size=None)` for unlimited), the oldest third of the rows is deleted automatically.

Note that while the cache is on, the same request always returns the same stored answer. Clear the cache or turn it off when you want a fresh generation. When the library creates the file, it is owner-only (0600).

See [docs/io_cache.md](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/io_cache.md) for details.

## Input/output log

Off by default. When enabled, every `ask()` / `chat()` / `ask_stream()` / `chat_stream()` / `stream_chat()` call appends one JSON Lines record with the input (request body) and the output (raw response).

```python
from llm_ai_api import llm, set_log

set_log("llm_log.jsonl")                       # on for the whole process
m = llm("openai:gpt-6-luna", log="other.jsonl")  # per instance
m2 = llm("openai:gpt-6-luna", log=False)         # off for this instance only
```

Set the `LLM_AI_API_LOG_DIR` environment variable to a directory to enable it as `<dir>/llm.jsonl`. Each line has `time`, `provider`, `model`, `stream`, `cached`, `request` and `response`. The API key is never recorded. The log is plain text and contains your prompts and the answers, so protect it. `JSONLLog(..., redact=hook)` can filter or skip records; on POSIX, file permissions are set to `0600` before writing. A stream is recorded only after it has been read to the end. When the file grows past `max_size` (default 100 MB; `set_log(..., max_size=None)` for unlimited), the oldest third of the lines is deleted automatically.

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
| `hello_async.py` | `aask()` and `aask_stream()` with `asyncio.run` and `async with` |
| `chat_history.py` | Reply based on a chat history |
| `ocr_test.py` | Read the text in an image |
| `image_desc.py` | Describe an image |
| `models_test.py` | Two models (GPT-6 Luna and Claude Haiku) discuss the breakfast menu, using the `models` constants (needs both API keys) |
| `cache_demo.py` | Ask the same question twice and see the second answer come from the cache |

`ask(prompt, images=[...])` builds each provider's image format from file paths, bytes, or http(s) URLs ([docs/multimodal.md](https://github.com/kujirahand/llm-ai-api-python/blob/main/docs/multimodal.md)). Native `content` dicts passed to `chat()` are not converted between providers.

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
