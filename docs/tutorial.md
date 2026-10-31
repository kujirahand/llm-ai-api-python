# Tutorial

日本語: [tutorial-ja.md](tutorial-ja.md)

This tutorial walks through `llm-ai-api` step by step: asking a question, continuing a conversation, streaming, async, and error handling.

## 1. Installation and API keys

```sh
pip install llm-ai-api
```

Python 3.9 or later is required. The only dependency is `httpx`. The import name is `llm_ai_api`.

Pass API keys through environment variables. Set only the ones for the providers you use.

| Provider | Environment variable |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `anthropic` (alias `claude`) | `ANTHROPIC_API_KEY` |
| `google` | `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) |

```sh
export OPENAI_API_KEY="sk-..."
```

You can also pass a key directly with `llm(..., api_key="...")`, but environment variables are recommended so the key stays out of your code.

## 2. Your first question

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna")
print(m.ask("Come up with a cute name for a dog"))
```

The model is always `"<provider>:<model>"`. `ask()` returns only the text of the answer (a `str`).

If no API key is found, `llm()` raises an error right away.

## 3. Switch models

Change the string and use a model from another provider in exactly the same way.

```python
from llm_ai_api import llm

m = llm("anthropic:claude-opus-5-5")
print(m.ask("Come up with a cute name for a dog"))
```

This example needs `ANTHROPIC_API_KEY` (set separately from `OPENAI_API_KEY` for OpenAI).

Common models are also available as constants in `models`. They are just `"<provider>:<model>"` strings.

```python
from llm_ai_api import llm, models

print(models.OPENAI_GPT6_LUNA)  # openai:gpt-6-luna

m = llm(models.GOOGLE_GEMINI_4_ARGON)
print(m.ask("Come up with a cute name for a dog"))
```

This example needs `GEMINI_API_KEY` (or `GOOGLE_API_KEY`).

The constants are examples. Any other model works as a plain string, e.g. `llm("openai:some-new-model")`. Check each provider's model list for the model IDs you can use.

## 4. Continue a conversation

`ask()` does not keep the conversation history. To follow up, pass the history (messages) to `chat()`. `chat()` returns a `ChatResult`.

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna")

messages = [{"role": "user", "content": "Name one favorite fruit"}]
result = m.chat(messages)
print(result.text)

# Add the reply to the history and ask a follow-up
messages.append({"role": "assistant", "content": result.text})
messages.append({"role": "user", "content": "What does it taste like?"})
result = m.chat(messages)
print(result.text)

print(result.model, result.stop_reason, result.usage)
```

`ChatResult` has these fields:

| Field | Contents |
|---|---|
| `text` | The text of the answer |
| `model` | The model that responded |
| `stop_reason` | Why generation stopped (the raw value from the API) |
| `usage` | `input_tokens` and `output_tokens` (`None` if unavailable) |
| `raw` | The whole JSON (dict) returned by the API |
| `request_id` | `x-request-id` or `request-id` (`None` when absent) |
| `latency` | Seconds from the start of the call until the body was read, including retry waits |
| `retries` | How many retries ran before this response (0 when the first attempt succeeded) |

`ask()` returns only the text. Use `chat()` to read `request_id`.

## 5. Streaming

`stream()` returns the generated text piece by piece.

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna")

stream = m.stream("Write a short story")
print(stream.request_id)  # set when stream() returns

for piece in stream:
    print(piece, end="", flush=True)
print()
```

## 6. Set options

`system` (system prompt), `max_tokens`, `temperature` and `extra` can be set as defaults in `llm()` or per call.

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna", system="You are an assistant that answers concisely.")

print(m.ask("What is the capital of Japan?"))

# A per-call value takes priority over the default
print(m.ask("What is the capital of Japan?", system="Answer like a pirate.", max_tokens=200))
```

- Parameters you do not pass are never sent to the API, because newer models may reject even default values such as `temperature`. Set them only when you need them.
- Parameters the official docs say a model rejects are omitted even when you pass them through `extra`. Models and parameters that are not in that list, and OpenRouter and Google, are sent as given. To send a dropped key unchanged, call `m.client.request(path, body)`.
- `max_tokens` is required by the Claude API. When you leave it out, the library fills in 16000. When the API version that is sent is `2026-10-21` (the default), `temperature`, `top_p`, and `top_k` are not sent. On another version, values you pass are sent. A `headers` entry named `anthropic-version` overrides `anthropic_version=`.
- Any other parameter can go through `extra={...}` (keys that are not in the rejection list are merged into the request body last).
- Passing `None` for a call disables the `llm()` default for that call only (e.g. `m.ask("q", temperature=None)`).

## 7. Use it asynchronously

Add an `a` to the method name to use it with `asyncio` (`aask()` / `achat()` / `astream()`).

```python
import asyncio
from llm_ai_api import llm


async def main():
    async with llm("openai:gpt-6-luna") as m:
        print(await m.aask("Come up with a cute name for a dog"))

        async for piece in m.astream("Write a short story"):  # no await here
            print(piece, end="", flush=True)
        print()

        # One LLM can be shared by concurrent calls
        answers = await asyncio.gather(m.aask("One dog name"), m.aask("One cat name"))
        print(answers)


asyncio.run(main())
```

- Close it with `async with` (or `await m.aclose()`). A closed `LLM` cannot be reused.
- Create a new `llm()` for each `asyncio.run()`.
- Calling the sync `ask()` / `chat()` / `stream()` inside async code blocks the whole event loop. Always use `aask()` / `achat()` / `astream()` there.

## 8. Handle errors

Every exception derives from `LLMError`. HTTP errors (4xx / 5xx) are `APIStatusError`, which has `status_code` and `body`.

```python
from llm_ai_api import llm, LLMError, APIStatusError

try:
    m = llm("openai:gpt-6-luna")
    print(m.ask("Hello"))
except APIStatusError as e:
    print("HTTP error:", e.status_code, e.body)
except LLMError as e:
    print("Error:", e.code, e)
```

`APIStatusError` is a subclass of `LLMError`, so list it first.

Every exception has a language-independent `code` attribute (e.g. `"missing_api_key"`). Check `code` rather than the message text, which changes with translation.

Failed requests are retried automatically, up to `max_retries` times (2 by default). Only connection-stage failures (the request never reached the server) and HTTP 408 / 409 / 429 / 5xx are retried. Failures after the request was sent, such as read timeouts, are not retried (to avoid running and paying for the same generation twice). In latency-sensitive services, consider `llm(..., max_retries=0)` or a short `timeout`. See the [configuration reference](config.md) for details.

Connection failures (`APIConnectionError` / `APITimeoutError`) and mid-stream errors (`APIStreamError`) also have `provider` and `request_id`. `request_id` is `None` when the failure happened before response headers. They also have `retries` and `latency` (seconds). HTTP errors (`APIStatusError`) have `retries` and `latency` too.

Retries and failures are not written to the I/O log. Receive them with `add_event_listener`. A listener that raises does not fail the request. Pass `None` to receive every event.

```python
m.add_event_listener("retry", lambda event, payload: print(event, payload.get("request_id")))
```

Event names, payload keys, and where `request_id` appears are in [Events](events.md).

## 9. Reuse and cleanup

`llm()` creates an HTTP client with a connection pool. Creating one for every request repeats connection setup and TLS handshakes. Create one when your process or service starts, then reuse it. This also makes response caching and connection reuse effective.

For synchronous code, use `with` or call `close()` when you are done.

```python
from llm_ai_api import llm

with llm("openai:gpt-6-luna") as m:
    print(m.ask("Hello"))

# Or close it when the application exits.
m = llm("openai:gpt-6-luna")
try:
    print(m.ask("Hello"))
finally:
    m.close()
```

For asynchronous code, use `async with` or call `await aclose()`. `aclose()` closes both the async and synchronous clients, and it is safe to call more than once. `close()` closes only the synchronous client.

```python
import asyncio
from llm_ai_api import llm


async def main():
    async with llm("openai:gpt-6-luna") as m:
        print(await m.aask("Hello"))

    # Or close it when the application exits.
    m = llm("openai:gpt-6-luna")
    try:
        print(await m.aask("Hello"))
    finally:
        await m.aclose()


asyncio.run(main())
```

It is fine to stop a stream early. When the stream object is discarded or closed, its underlying response is also closed. In long-running programs, explicitly call `stream.close()` or `await stream.aclose()` when stopping early.

If you forget to close an instance, resources are released at process exit or during garbage collection. However, a long-running process can keep connections and file descriptors open, so close instances explicitly. A closed `LLM` cannot be reused; create a new one instead. For example, create a new `llm()` for each `asyncio.run()` call.

For production deployments where you need to change the number of concurrent connections, a proxy, or TLS settings, see "Connection settings" (`set_connection()` and `connection=`) in the README.

## 10. Next steps

- [Events](events.md): `add_event_listener`, the event list, and where to read `request_id`.
- [Configuration reference](config.md): `llm()` settings and the retry policy.
- [Local response cache](io_cache.md): repeat requests return the stored result without calling the API (off by default).
- [Input/output log](io_logs.md): record inputs and outputs as JSON Lines (off by default).
- [Prompt caching](cache.md): how to use the provider-side cache.
- Raw layer: `m.client.request(path, body)` sends a dict to any endpoint.
- The [`examples/`](../examples/) directory: more samples, including image input and chat history.
