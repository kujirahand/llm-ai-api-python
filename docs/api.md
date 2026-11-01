# API Reference

A list of the public API of `llm_ai_api`. See the [Tutorial](tutorial.md) for usage and the [Configuration reference](config.md) for setting details.

## Creating a client

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
```

`llm(spec, **options)` returns an `LLM` instance. `spec` is `"<provider>:<model>"` (`openai` / `openrouter` / `anthropic` (alias `claude`) / `google`). You can also construct `LLM(spec, ...)` directly.

Main options at creation time (keyword arguments):

| Option | Default | Description |
|---|---|---|
| `system` | `None` | System prompt shared by all calls |
| `max_tokens` | `None` | Maximum output tokens shared by all calls |
| `temperature` | `None` | Temperature shared by all calls |
| `extra` | `None` | dict merged into every request body |
| `api_key` | environment variable | API key (read from the provider's environment variable when omitted) |
| `base_url` | provider default | Override for the API base URL |
| `timeout` | `600.0` | Timeout in seconds; counted per operation |
| `max_retries` | `2` | Number of retries (see the [Configuration reference](config.md)) |
| `retry_read_timeout` | `False` | When `True`, read timeouts are also retried |
| `retry_after_max` | `60.0` | Cap in seconds on waits that follow `Retry-After` |
| `headers` | `None` | dict of additional headers |
| `cache` | none | Response cache (see `set_cache()`) |
| `log` | none | Input/output log (see `set_log()`) |
| `connection` | none | dict of connection settings (per-instance override of the `set_connection()` keys) |
| `transport` | `None` | httpx transport, e.g. for tests |
| `lang` | `None` | Language of error messages (`"ja"` / `"en"`) |

## LLM methods

Every call method accepts the per-call keyword arguments `system` / `max_tokens` / `temperature` / `extra` (which override the creation-time values) and `timeout` (a timeout in seconds for this call only). When omitted, the creation-time values are used.

### Questions and answers

| Method | Method (async) | Description |
|---|---|---|
| `ask(prompt: str \| list[dict])` | `aask(prompt: str \| list[dict])` | Send a question or history and return only the answer text (`str`) |
| `ask_stream(prompt: str \| list[dict])` | `aask_stream(prompt: str \| list[dict])` | Send a question or history and return the answer text incrementally (as an iterator) |
| `chat(messages)` | `achat(messages)` | Send a conversation history and return a `ChatResult` |
| `chat_stream(messages)` | `achat_stream(messages)` | Send a conversation history and return the answer text incrementally (as an iterator) |

- `prompt` accepts a string or a non-empty list of dictionaries. Other inputs raise `LLMConfigError(code="invalid_messages")`.
- `messages` is a list in the form `[{"role": "user", "content": "..."}]`. The caller's list is not modified.
- `chat()` / `achat()` also accept `schema=` (a JSON Schema dict, or a pydantic-v2-compatible model class), which requests structured output and puts the decoded, validated value in `ChatResult.parsed`. See [Structured output](structured.md).
- Sync streams are regular iterators; async streams are async iterators (use `async for`; no `await` is needed). The stream iterator gets `request_id` and `retries` set once the response headers have been received. Read it to the end, or call `close()` (sync) / `aclose()` (async), to release the connection.
- The old names `stream()` / `astream()` remain as deprecated aliases (same behavior as `ask_stream()` / `aask_stream()`). Use the new names in new code.

### Cleanup and configuration

| Method | Description |
|---|---|
| `close()` | Close the sync client. It cannot be used again |
| `aclose()` | Close both the async client (if created) and the sync client |
| `set_config(max_retries=, retry_read_timeout=, retry_after_max=)` | Change only the retry policy after creation. Only the given items change |
| `add_event_listener(event, listener)` | Register an event listener (`event=None` for all events) |
| `remove_event_listener(event, listener)` | Remove a registered listener |

`LLM` also works with `with` / `async with` (which call `close()` / `aclose()` on exit). See [Events](events.md) for the event types and payloads.

## Return types

### ChatResult

The return value of `chat()` / `achat()`.

| Field | Type | Description |
|---|---|---|
| `text` | `str` | The answer text |
| `model` | `str` or `None` | The model that responded |
| `stop_reason` | `str` or `None` | Finish reason (provider value, normalized) |
| `usage` | `Usage` or `None` | `input_tokens` / `output_tokens` |
| `raw` | `dict` | The raw response JSON |
| `request_id` | `str` or `None` | The provider's request ID (`None` when the response had no such header; on a cache hit, the stored value) |
| `latency` | `float` or `None` | Seconds until the response |
| `retries` | `int` | The number of retries actually performed |
| `parsed` | any | The decoded, validated structured output when `schema=` was given; otherwise `None` |

### ChatChunk / SSEEvent / Usage

- `ChatChunk` is a fragment returned by the low-level streaming layer (`stream_chat()`), with `text` / `raw` / `request_id`.
- `SSEEvent` is an event returned by the raw streaming layer; `json()` extracts the body as a dict.
- `Usage` is a dataclass with `input_tokens` / `output_tokens`.

## Module functions

| Function | Description |
|---|---|
| `set_cache(cache=None, *, max_size=...)` / `get_cache()` | Global response-cache settings. See [Input/output cache](io_cache.md) |
| `clear_cache(days=0, cache_dir=None)` | Delete expired cache entries and return how many were removed |
| `set_log(log=None, *, max_size=...)` / `get_log()` | Global input/output log settings. See [Input/output log](io_logs.md) |
| `set_connection(*, max_connections, max_keepalive_connections, keepalive_expiry, connect_timeout, verify, cert, proxy)` / `get_connection()` | Global connection settings (replace-style: calling with no arguments resets to the defaults). See the [Configuration reference](config.md) |
| `set_language(lang)` / `get_language()` | Global language of error messages (`"ja"` / `"en"`); applies to the whole process |

The cache class is `SQLiteCache` and the log class is `JSONLLog`. Build either with a file path and pass it to `llm(..., cache=...)` / `log=...` or to `set_cache()` / `set_log()`.

## Provider clients (low-level layer)

Use `OpenAIClient` / `OpenRouterClient` / `AnthropicClient` / `GoogleClient` directly. Features the common interface does not cover (tool calls, image input, and so on) are available through `request()` with raw JSON.

| Method | Description |
|---|---|
| `chat(model, messages, *, max_tokens, temperature, extra, timeout)` | Send a conversation and return a `ChatResult` |
| `stream_chat(model, messages, *, ...)` | Send a conversation and return an iterator of `ChatChunk` |
| `request(path, body=None, *, method="POST", headers, timeout)` | Send JSON to any endpoint and return the response dict |
| `request_stream(path, body=None, *, headers, timeout)` | Send to any endpoint and return an iterator of `SSEEvent` |
| `close()` | Close the client |

## Model name constants

The `llm_ai_api.models` module holds `"<provider>:<model>"` constants for major models (e.g. `models.OPENAI_GPT6_LUNA`). They are examples only; models not in the table can be given as plain strings.

## Exceptions

Every exception is a subclass of `LLMError`. Configuration mistakes raise `LLMConfigError` (the `code` attribute tells the kind).

| Exception | Raised when |
|---|---|
| `APIConnectionError` | The connection failed |
| `APITimeoutError` | A timeout occurred |
| `APIStatusError` | An HTTP error response (base class) |
| `BadRequestError` | 400 |
| `AuthenticationError` | 401 |
| `PermissionDeniedError` | 403 |
| `NotFoundError` | 404 |
| `RateLimitError` | 429 |
| `InternalServerError` | 5xx |
| `APIStreamError` | An error during streaming (carries `provider` / `request_id` attributes) |
| `StructuredOutputError` | The `schema=` structured output was refused, incomplete, or failed validation (`result` holds the original `ChatResult`) |
