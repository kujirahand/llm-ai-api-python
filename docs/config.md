# Configuration reference

日本語: [config-ja.md](config-ja.md)

The settings you can pass to `llm()`. For per-request defaults (`system` / `max_tokens` / `temperature` / `extra`), see "6. Set options" in the [tutorial](tutorial.md).

```python
from llm_ai_api import llm

m = llm(
    "openai:gpt-6-luna",       # "<provider>:<model>"
    api_key=None,              # None: from the environment variable
    base_url=None,             # None: from the environment variable, else the default
    timeout=600.0,             # seconds
    max_retries=2,
    retry_read_timeout=False,
    retry_after_max=60.0,      # seconds
    headers=None,              # extra headers (dict)
    lang=None,                 # error message language ("ja" / "en")
    # cache=..., log=...      # follow the global setting when not given
)
```

## Settings

| Argument | Default | Description |
|---|---|---|
| first argument | (required) | `"<provider>:<model>"`. Split at the first `:`, so model names may contain `:` and `/` (e.g. `"openrouter:meta-llama/llama-4:free"`). |
| `api_key` | environment variable | `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` (or `GOOGLE_API_KEY`). If none is found, `llm()` raises `LLMConfigError`. |
| `base_url` | environment variable → default | Can be overridden with `OPENAI_BASE_URL` and so on. Use it to go through a proxy or gateway. |
| `timeout` | `600.0` | Timeout for one request (seconds). The connect timeout is 10 seconds. |
| `max_retries` | `2` | Number of retries. `0` disables retries. |
| `retry_read_timeout` | `False` | When `True`, read timeouts are retried too (see "Retry policy" below). |
| `retry_after_max` | `60.0` | Upper limit (seconds) on how long to wait when following a `retry-after` header. Must be a finite number of 0 or more; negative values, NaN, and infinity raise `LLMConfigError` (`code="invalid_option"`) when the client is created or in `set_config()`. |
| `headers` | `None` | Extra headers sent with every request (dict). |
| `cache` | global setting | Local response cache. See [io_cache.md](io_cache.md). |
| `log` | global setting | Input/output logs. See [io_logs.md](io_logs.md). |
| `lang` | detected from the environment | Error message language (`"ja"` / `"en"`). |

There are provider-specific settings too: Anthropic takes `anthropic_version` (default `"2026-10-21"`), and OpenRouter takes `app_url` (sent as `HTTP-Referer`) and `app_name` (sent as `X-Title`).

## Retry policy

| Failure | Default | `retry_read_timeout=True` |
|---|---|---|
| Connection failure (cannot connect, connect timeout, connection pool timeout) | retried | retried |
| HTTP 408 / 409 / 429 / 5xx | retried (honoring `retry-after`) | retried |
| Read timeout | not retried | retried |
| Other transport errors (disconnect while sending or receiving, protocol errors, etc.) | not retried | not retried |

A transport error that is not retried is raised right away as `APITimeoutError` (timeouts) or `APIConnectionError`. The wait between attempts uses exponential backoff (from 0.5 seconds, up to 8 seconds). A `retry` event is emitted just before each retry, and a `connection_error` or `http_error` event when a failure will not be retried (see [Events](events.md)).

A request that failed at the connection stage never reached the server, so sending it again is safe. Generation requests, however, are not idempotent. After the request has been sent, the server may already be processing it, and a retry can run the same generation twice. That is why only connection-stage failures are retried by default.

### Change after creation

`set_config()` changes the retry settings after `llm()`. Only the arguments you pass are changed.

```python
m = llm("openai:gpt-6-luna")
m.set_config(max_retries=0)                        # no retries
m.set_config(retry_read_timeout=True, retry_after_max=10)
```

The change also applies to the async methods (`aask()` and so on).

## Production settings

- The default retries cover only connection-stage failures and 408 / 409 / 429 / 5xx responses from the server.
- In latency-sensitive services, consider `max_retries=0` or a short `timeout`. The default `timeout=600` is meant for long generations; combined with retries, a single call can block for a long time. Retrying in your application, where you know the situation, is easier to control.
- `retry_read_timeout=True` can double-bill: when a read timeout happens, the server may already be generating. Use it only if you accept that every retry costs money and server time.
- `Retry-After` accepts seconds or an HTTP date, capped by `retry_after_max` in sync and async calls. Invalid values, NaN, infinity, negative seconds, and past dates are ignored in favor of the normal backoff.

Non-streaming response bodies and HTTP error bodies (including errors starting a stream) are limited to 64 MiB after decompression. Oversized bodies raise `LLMError` with code `response_too_large`. A declared `Content-Length` over the limit is rejected before reading. Individual decoded chunks and JSON parsing can require additional memory; streaming responses have no total size limit.

Each SSE line is limited to 16 MiB in decompressed bytes and UTF-8 encoding, including while it is being read. Each event is limited to 16 MiB for its event name and joined data in UTF-8 (including newlines between data lines). Exceeding either limit closes the response, raises `LLMError` with code `response_too_large`, and emits `request_error`. These limits also apply to raw streams.

Header names are case-insensitive. Defaults are overridden in order by authentication, client `headers`, and per-request `headers`; within a dict, the last matching entry wins. OpenRouter `headers` also override `app_url` and `app_name`. Anthropic parameter filtering uses the effective version header.
