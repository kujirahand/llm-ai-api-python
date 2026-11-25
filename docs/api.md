# API Reference

A list of the public API of `llm_ai_api`. See the [Tutorial](tutorial.md) for usage and the [Configuration reference](config.md) for setting details.

## Creating a client

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
```

`llm(spec, **options)` returns an `LLM` instance. `spec` is `"<provider>:<model>"` (`openai` / `openrouter` / `anthropic` (alias `claude`) / `google` / `grok` / `muse` / `lmstudio` / `ollama` / `strata`). `lmstudio` / `ollama` / `strata` target local servers; an API key is optional. You can also construct `LLM(spec, ...)` directly.

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

The question and answer methods accept the per-call keyword arguments `system` / `max_tokens` / `temperature` / `extra` (which override the creation-time values) and `timeout` (a timeout in seconds for this call only). When omitted, the creation-time values are used.

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
- `chat()` / `achat()` also accept `tools=` (a list of `{"name", "description", "parameters"}` dicts mapped to the provider's format). `LLM.tool_results([(call_or_id, output[, is_error]), ...])` builds the tool-result messages for the next call. See [Tool calls and thinking](tools.md).
- `transcribe(file, *, extra=None, timeout=None) -> str` / `atranscribe()` transcribe audio (a path or `bytes`) and return a string (OpenAI only; not cached or logged). See [Multimodal](multimodal.md). The raw `request()` can send multipart with `files=` / `form_data=`.
- `ask()` / `ask_stream()` / `aask()` / `aask_stream()` also accept `images=` (a list of file paths, `bytes`, or http(s) URLs). See [Multimodal](multimodal.md).
- Sync streams are regular iterators; async streams are async iterators (use `async for`; no `await` is needed). The stream iterator gets `request_id` and `retries` set once the response headers have been received. Read it to the end, or call `close()` (sync) / `aclose()` (async), to release the connection.
- After the stream has been read to its end, `stream.result` is a `ChatResult` for the whole response: `text` (all deltas joined), `model`, `stop_reason`, `usage` (`None` if the provider sent none), `raw` (`{"events": [...]}`, the JSON of every stream event), `request_id`, `retries`, and `latency` (seconds until the end; `None` for a replay from the cache). It is `None` before the end, after an error, and after an early `close()` / `aclose()`. Read the iterator until it stops: stopping right after the last text delta does not reach the end of the stream. The provider layer's `stream_chat()` iterator has the same `result`. Building it keeps every event in memory until the stream ends, so a very long stream uses more memory than reading the deltas alone.
- The old names `stream()` / `astream()` remain as deprecated aliases (same behavior as `ask_stream()` / `aask_stream()`). Use the new names in new code.

### Model listing

`models(*, raw=False, timeout=None)` and `await amodels(*, raw=False, timeout=None)` return model ID strings in provider order. Pass `raw=True` for the unchanged model dictionaries across all pages. `timeout` is in seconds; `None` uses the client setting. These calls are not cached or written to the I/O log. If the listing exceeds the page limit or the item limit, it raises `LLMError` (`code="models_pagination_limit"`).

OpenAI-compatible providers (including OpenRouter, Grok, Muse, LM Studio, Ollama, and Strata) use `/models` on the configured base URL; Anthropic uses `/v1/models`. Google uses the native sibling `/models` endpoint when its base URL ends in `/openai`, and otherwise uses the OpenAI-compatible `/models` endpoint. OpenRouter construction and listing do not require an API key; a configured key is sent, and chat without a key fails at request time with the provider's HTTP error.

### Cleanup and configuration

| Method | Description |
|---|---|
| `close()` | Close the sync client. It cannot be used again |
| `aclose()` | Close both the async client (if created) and the sync client |
| `set_config(max_retries=, retry_read_timeout=, retry_after_max=)` | Change only the retry policy after creation. Only the given items change |
| `add_event_listener(event, listener)` | Register an event listener (`event=None` for all events) |
| `remove_event_listener(event, listener)` | Remove a registered listener |

`LLM` also works with `with` / `async with` (which call `close()` / `aclose()` on exit). See [Events](events.md) for the event types and payloads.

## Testing application code

To test an application that takes an `LLM` instance, you do not need to build provider JSON or SSE, and for testing the application's own logic you do not need `transport=` either. Define a `typing.Protocol` for the methods your application actually calls, and pass a stub that returns fixed `str` values, `ChatResult` values, stream iterators, or library exceptions. The standard library plus this package is enough; no network access or API key is required. When you want to verify the integration through the library itself (request building, retries, and so on), use `transport=` with `httpx.MockTransport` instead.

The following example tests a function that only uses `ask()`. Adapt the protocol if your code also calls `chat()` or `ask_stream()`.

```python
from typing import Any, Protocol

from llm_ai_api.types import ChatResult


class AppLLM(Protocol):
    def ask(self, prompt: str | list[dict], **kwargs: Any) -> str: ...


class ScriptedLLM:
    def __init__(self, replies: list[str | ChatResult | BaseException]):
        self._replies = list(replies)

    def ask(self, prompt: str | list[dict], **kwargs: Any) -> str:
        if not self._replies:
            raise AssertionError("no scripted replies left")
        item = self._replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ChatResult):
            return item.text
        return item


def summarize(client: AppLLM, text: str) -> str:
    return client.ask("Summarize:\n" + text)
```

A unit test can construct `ScriptedLLM(["a short summary"])` and assert that `summarize(client, "a long article")` returns that text. To exercise an error branch, script a library exception such as `RateLimitError("slow down", status_code=429)`.

So that a type checker (such as mypy) accepts a real `LLM` where the protocol is expected, declare in the protocol the keyword arguments your application actually passes (such as `system` or `max_tokens`). Note that the stub does not validate arguments, so a misspelled argument name will not be caught by the stub.

For async application code, define the protocol with `async def aask(...)` (and `achat` as needed) and use a stub whose methods are coroutines. The stream methods are the exception: on a real `LLM`, `aask_stream` / `achat_stream` are plain methods that return an async iterator, so the stub should not make them `async def` either, and callers use `async for` without `await`. A stream stub can be a small iterator (or async iterator) that yields strings and exposes `request_id` and `retries`, matching the public stream objects.

## Return types

### ChatResult

The return value of `chat()` / `achat()`.

| Field | Type | Description |
|---|---|---|
| `text` | `str` | The answer text |
| `model` | `str` or `None` | The model that responded |
| `stop_reason` | `str` or `None` | Finish reason (the raw provider value; it is not normalized). OpenAI and OpenAI-compatible providers: `finish_reason`; Anthropic: `stop_reason` |
| `usage` | `Usage` or `None` | `input_tokens` / `output_tokens`, plus optional `cache_read_tokens` / `cache_creation_tokens` / `reasoning_tokens` |
| `raw` | `dict` | The raw response JSON |
| `request_id` | `str` or `None` | The provider's request ID (`None` when the response had no such header; on a cache hit, the stored value) |
| `latency` | `float` or `None` | Seconds until the response |
| `retries` | `int` | The number of retries actually performed |
| `parsed` | any | The decoded, validated structured output when `schema=` was given; otherwise `None` |
| `tool_calls` | `list[ToolCall]` | Tool calls read from the response (empty when none). See [Tool calls and thinking](tools.md) |
| `thinking` | `str \| None` | Reasoning text, or `None` |
| `message` | `dict \| None` | Copy of the provider-format assistant message, to append to the history unchanged |

### ChatChunk / SSEEvent / Usage

- `ChatChunk` is a fragment returned by the low-level streaming layer (`stream_chat()`), with `text` / `raw` / `request_id`.
- `SSEEvent` is an event returned by the raw streaming layer; `json()` extracts the body as a dict.
- `Usage` is a dataclass with `input_tokens` / `output_tokens`. When the provider reports them, it also has `cache_read_tokens`, `cache_creation_tokens`, and `reasoning_tokens` (`None` if omitted; an explicit zero is `0`; a value that is not an `int` also becomes `None`). These values are copied from the response and are not added or subtracted from the totals, and the library does not estimate missing values or compute cost. The meaning of `input_tokens` differs by provider: for Anthropic it does not include cached tokens. These fields are available from `chat()` / `achat()`, and from a stream's `result` once it has been read to the end (the last `usage` the provider sent; for Anthropic, the `message_start` and `message_delta` values merged field by field). `usage` is `None` when the provider sends none while streaming (OpenAI needs `stream_options.include_usage`, which `openai` sets for you).

## Module functions

| Function | Description |
|---|---|
| `set_cache(cache=None, *, max_size=...)` / `get_cache()` | Global response-cache settings. See [Input/output cache](io_cache.md) |
| `clear_cache(days=0, cache_dir=None)` | Delete expired cache entries and return how many were removed |
| `set_log(log=None, *, max_size=...)` / `get_log()` | Global input/output log settings. See [Input/output log](io_logs.md) |
| `set_connection(*, max_connections, max_keepalive_connections, keepalive_expiry, connect_timeout, verify, cert, proxy)` / `get_connection()` | Global connection settings (replace-style: calling with no arguments resets to the defaults). See the [Configuration reference](config.md) |
| `set_language(lang)` / `get_language()` | Global language of error messages (`"ja"` / `"en"`); applies to the whole process |
| `register_provider(name, *, base_url, api_format="openai", api_key_env=None, base_url_env=None, api_key_default=None, api_key_required=True, auth_header=None, auth_scheme=None, headers=None, max_tokens_field=None, stream_include_usage=None, models=True, aliases=(), replace=False)` | Add an OpenAI-compatible or Anthropic-compatible API from a declaration so that `llm("<name>:<model>")` works. Returns `None`. It affects the whole process, so call it at startup. A built-in name or alias cannot be overwritten, even with `replace=True`. Errors are `LLMConfigError` (`code="invalid_provider"` / `"provider_exists"`). See [Adding a provider](providers.md) |

The cache class is `SQLiteCache` and the log class is `JSONLLog`. Build either with a file path and pass it to `llm(..., cache=...)` / `log=...` or to `set_cache()` / `set_log()`.

## Provider clients (low-level layer)

Use `OpenAIClient` / `OpenRouterClient` / `AnthropicClient` / `GoogleClient` / `GrokClient` / `MuseClient` / `LMStudioClient` / `OllamaClient` / `StrataClient` directly. Features the common interface does not cover (tool calls, image input, and so on) are available through `request()` with raw JSON.

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
| `PermissionDeniedError` | 403 (except credit/billing exhaustion; see `InsufficientCreditsError`) |
| `NotFoundError` | 404 |
| `RateLimitError` | 429 (except quota exhaustion; see `InsufficientCreditsError`) |
| `InsufficientCreditsError` | Credit, billing, or quota exhaustion: HTTP 402, a machine-readable billing, spend, or quota code on a 4xx, an OpenRouter budget 403, an xAI 403 `permission-denied` whose message says credit(s) are exhausted, or a documented Anthropic credit-balance or spend-limit sentence. These responses are not retried. Ordinary 400 / 403 / 429 responses, including Google 429 `RESOURCE_EXHAUSTED`, and 5xx responses are not included. |
| `InternalServerError` | 5xx |
| `APIStreamError` | An error during streaming (carries `provider` / `request_id` attributes) |
| `StructuredOutputError` | The `schema=` structured output was refused, incomplete, or failed validation (`result` holds the original `ChatResult`) |

`InsufficientCreditsError` is not retried. Codes are read from `error.code`, `error.type`, `error.status`, and Anthropic's `error.details.error_code` (`_` and `-` are treated as the same).

- HTTP 402 matches for any body. That covers Meta `billing_error`, OpenRouter insufficient credits, Google prepay depletion (the body's `status` may still say `RESOURCE_EXHAUSTED`; the HTTP status is 402), and Anthropic `billing_error`. OpenRouter's in-flight budget is also a 402, so it is classified the same way and is not retried automatically.
- A distinct code matches. OpenAI: `insufficient_quota`, `credit_balance_exhausted`, `organization_spend_limit_exceeded`, `project_spend_limit_exceeded`, `organization_usage_limit_exceeded`. Anthropic's monthly spend cap: `enforced_spend_limit_reached` (the `rate_limit_error` type alone does not match). Google Interactions API: `quota_exceeded` and `payment_required`. Meta: `billing_not_configured`.
- An OpenRouter 403 matches only when `error.metadata.limit_source` is `openrouter_guardrail_budget`, `openrouter_workspace_budget`, or `openrouter_key_limit`. Content-filter and other 403 responses stay `PermissionDeniedError`.
- An xAI 403 matches only when the code is `permission-denied` and the message contains both the word credit or credits and an exhaustion expression (such as no, insufficient, depleted, exhausted, out of, used all, or a zero balance). The debugging page does not publish a separate code for credit exhaustion, so this combination is the signal. The code alone, or an ordinary denial of access to credit-based billing, stays a permission error.
- Anthropic's empty credit balance (`Your credit balance is too low...`) and a spend limit the caller set (`You have reached your specified API usage limits` / `... workspace API usage limits`) use the same 400 `invalid_request_error` type as a bad request. They match only when the HTTP status, type, and documented message prefix all agree.

These do not match. Temporary 429s (OpenAI `slow_down` or `rate_limit_exceeded`, Google Interactions `rate_limit_exceeded` and `too_many_requests`, and an Anthropic `rate_limit_error` without the spend-cap code) and ordinary 403s. A Google OpenAI-compatible 429 `RESOURCE_EXHAUSTED` is the same status for a short-lived rate limit and for a spend-based limit that Google says to retry, and the body has no separate code, so it stays `RateLimitError` and is retried. `failed_precondition` is not included either: disabled billing is only one example of that code.
