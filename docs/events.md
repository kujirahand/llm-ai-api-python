# Events

日本語: [events-ja.md](events-ja.md)

Listeners on an `LLM` or a provider client (`OpenAIClient` and the others) are told when a call retries, fails, or receives response headers. The I/O log records successful chats only. Use listeners to see retries and failures.

`latency` in every payload below is **seconds** (`float`), measured before listeners run. It includes time spent waiting to retry. `None` means the value was not measured (for example a cache replay of a stream error).

## Register a listener

```python
def on_event(event, payload):
    print(event, payload.get("request_id"), payload.get("retries"))

m = llm("openai:gpt-6-luna")

m.add_event_listener("retry", on_event)     # this event only
m.add_event_listener(None, on_event)        # every event
m.remove_event_listener("retry", on_event)  # drop one registration
```

```text
add_event_listener(event, listener) -> None
remove_event_listener(event, listener) -> None
```

- `listener` is called as `listener(event, payload)`. `event` is the name string. `payload` is a new plain `dict` on every call.
- `event=None` registers the listener for every event. Removing that registration also takes `None`. A named registration is a different entry.
- The same function can be registered more than once. Each registration is called, in the order they were added. `remove_event_listener` drops one match, compared by identity (`is`). Removing a listener that was not registered does nothing.
- An unknown event name raises `LLMConfigError` (`code="invalid_event"`) on add and on remove. A listener that is not callable raises `LLMConfigError` (`code="invalid_listener"`).
- If a listener raises `Exception`, the exception is discarded. The request continues, retries are unchanged, and later listeners still run. `BaseException` (`KeyboardInterrupt`, `asyncio.CancelledError`, and similar) is not caught.
- `m.add_event_listener` and `m.client.add_event_listener` share one list. The async client, created on the first `aask` / `achat` / `astream`, uses that same list. Sync and async calls notify the same listeners.
- Listeners are synchronous. On the async path they run on the event-loop thread, so they should not block.
- Provider clients (`OpenAIClient` and the others) have the same two methods. A client you construct yourself has its own list.

Payloads never include the API key, authorization headers, or the request or response body.

## Where to read `request_id`

The header is `x-request-id` (OpenAI-style APIs) or `request-id` (Anthropic). It is `None` when the response had neither, and when the failure happened before headers arrived.

| Place | What you get |
|---|---|
| `ChatResult` from `chat()` / `achat()` | `request_id`, `latency` (seconds until the body was read), `retries` |
| `ChatChunk` from `stream_chat()` | `request_id` on every chunk (the same value) |
| Iterator from `stream()` / `stream_chat()` / `request_stream()` | `request_id` and `retries` as soon as the call returns |
| Iterator from `astream()` | `request_id` and `retries` after the first iteration receives headers, before the first text. Both stay unset (`None` / `0`) if the call fails before headers |
| `APIConnectionError`, `APITimeoutError` | `provider`, `request_id`, `retries`, `latency`. `request_id` is set when a stream drops after headers |
| `APIStatusError` (HTTP 4xx / 5xx) | the same, plus `status_code`, `body`, `headers` |
| `APIStreamError` | `provider`, `request_id`, `retries`, `latency`, and `body` |
| `request()` | the body `dict` only. Read `request_id` from the `response` event |

`ask()` / `aask()` return only the text. Use `chat()` / `achat()`, or a listener, when you need `request_id`.

`retries` is how many retries ran before this outcome. `0` means the first attempt produced it. `attempt` in a payload is the 0-based index of the HTTP attempt that event is about. On these events `retries` equals `attempt`. After `max_retries=2` is used up, the final error has `retries=2` (three attempts).

A cache hit returns the `request_id`, `latency`, and `retries` stored with the original response, not a new measurement. Rows written before those fields existed load as `None`, `None`, and `0`.

## Events

| Event | When |
|---|---|
| `retry` | A failed attempt will be retried. Emitted before the wait |
| `connection_error` | A transport failure that will not be retried, including a drop while reading a stream |
| `response` | An HTTP response below status 400 was accepted |
| `http_error` | An HTTP error that will not be retried. `APIStatusError` is raised after the listeners return |
| `request_error` | This library rejected the body (`response_too_large` or `invalid_json_response`) |
| `stream_error` | An error event or EOF without a terminal event in a chat stream. `APIStreamError` is raised after the listeners return |
| `stream_end` | A live stream was closed after a terminal SSE event (`[DONE]` or `message_stop`) |
| `cache_hit` | `chat` / `stream_chat` (and the async twins) returned a stored response. No `response` event |

### `retry`

| Key | Meaning |
|---|---|
| `provider` | `"openai"`, `"anthropic"`, `"openrouter"`, or `"google"` |
| `method` | HTTP method, such as `"POST"` |
| `path` | Request path, not the full URL |
| `stream` | `True` when this call is a stream |
| `attempt` | 0-based index of the attempt that just failed |
| `retries` | Retries already finished before that attempt (equal to `attempt`) |
| `max_retries` | The client's cap |
| `delay` | Seconds this retry will sleep (already capped by `retry_after_max`) |
| `reason` | Why this attempt failed. See below |
| `status_code` | HTTP status, or `None` when there was no response |
| `request_id` | From the failed response, or `None` |

`reason` is one of:

| Value | When |
|---|---|
| `status` | HTTP 408, 409, 429, or 5xx |
| `connect` | `ConnectError` or `ConnectTimeout` |
| `timeout` | Another timeout, such as `PoolTimeout` or `WriteTimeout` |
| `read_timeout` | `ReadTimeout` |
| `transport` | Any other transport error (`ReadError`, `WriteError`, protocol errors, and so on) |

### `connection_error`

Same keys as `retry`, without `max_retries` and `delay`, plus:

| Key | Meaning |
|---|---|
| `latency` | Seconds from the start of the call until this failure |
| `code` | `"timeout"` or `"connection_error"` (the exception's `code`) |
| `reason` | Same values as `retry`, except `status` |

`status_code` and `request_id` are `None` when the connection failed before headers. A drop while reading a stream keeps the `request_id` and the HTTP `status_code` of that response. `stream` is `True` in that case.

### `response`

| Key | Meaning |
|---|---|
| `provider`, `method`, `path`, `stream` | As in `retry` |
| `attempt`, `retries` | The attempt that succeeded. `retries` is how many retries ran before it |
| `status_code` | HTTP status (below 400) |
| `request_id` | Response header, or `None` |
| `latency` | Seconds until the body is read. For a stream, seconds until the headers (the body is still open) |
| `cached` | Always `False`. A cache hit is `cache_hit`, not `response` |

### `http_error`

`provider`, `method`, `path`, `stream`, `attempt`, `retries`, `status_code`, `request_id`, `latency`.

`latency` is seconds until this error response. The body is on the `APIStatusError`, not in the payload.

### `request_error`

The keys of `http_error`, plus `code`:

| `code` | When |
|---|---|
| `response_too_large` | The body, an SSE line, or an SSE event is over the size limit. Emitted instead of `response` when the body is rejected before it is accepted |
| `invalid_json_response` | The body or an SSE `data` line is not a JSON object. A non-stream HTTP success emits `response` first, then this event |

On a stream, `method`, `path`, and `status_code` are `None` when the events are replayed from the cache.

### `stream_error`

| Key | Meaning |
|---|---|
| `provider` | Provider name |
| `request_id` | From the response that opened the stream, or `None` |
| `retries` | Retries before that response |
| `latency` | Seconds until the error event, or `None` on a cache replay |
| `stream` | `True` |
| `code` | `"stream_error"` or `"stream_incomplete"` |

The error body is on the `APIStreamError`, not in the payload. `stream_end` is not emitted for this call.

### `stream_end`

| Key | Meaning |
|---|---|
| `provider` | Provider name |
| `request_id` | From the response that opened the stream |
| `retries` | Retries before that response |
| `latency` | Seconds from the start of the call until the stream is closed |
| `stream` | `True` |
| `complete` | `True` |

Emitted only when a live stream is closed after a terminal SSE event. Stopping early, reaching EOF without a terminal event, or failing does not emit it. A complete cache replay emits `cache_hit` only, not `stream_end`. An async stream that is garbage-collected without `aclose()` closes the response and does not emit `stream_end`.

### `cache_hit`

| Key | Meaning |
|---|---|
| `provider` | Provider name |
| `stream` | `True` for a cached stream, `False` for a cached chat |
| `model` | Model string from the request, or `None` |
| `request_id`, `retries`, `latency` | Values stored with the original response |
| `cached` | `True` |

## Example

```python
from llm_ai_api import llm


def on_event(event, payload):
    if event == "retry":
        print("retry", payload["attempt"], "in", payload["delay"], "s")
    elif event == "response":
        print("id", payload["request_id"], "after", payload["latency"], "s")
    elif event in ("connection_error", "http_error", "stream_error"):
        print(event, payload.get("code"), payload.get("request_id"))


m = llm("openai:gpt-6-luna")
m.add_event_listener(None, on_event)

result = m.chat([{"role": "user", "content": "Hello"}])
print(result.request_id, result.retries, result.latency)

stream = m.stream("Write a short story")
print(stream.request_id)  # set when stream() returns
for piece in stream:
    print(piece, end="", flush=True)
```

Chat streams that reach EOF without a terminal event raise `APIStreamError` with code `stream_incomplete` after any received chunks and emit `stream_error`. This also applies to incomplete cache replays; raw `request_stream()` remains an unmodified SSE iterator.
