# Changelog

## Unreleased

- Add `LLM.transcribe()` / `atranscribe()` (OpenAI `/audio/transcriptions`; other providers raise `unsupported_modality`) and multipart `files=` / `form_data=` arguments on the raw `request()` (#58).

- Add a keyword-only `images=` argument to `ask()` / `ask_stream()` / `aask()` / `aask_stream()` (file paths, bytes, or http(s) URLs), converted to each provider's image format; invalid input raises `LLMConfigError(code="invalid_media")` (#58).

- Add `schema=` structured output to `LLM.chat()` / `LLM.achat()`: a JSON Schema dict or a pydantic-v2-compatible model class, validated into `ChatResult.parsed`, with `StructuredOutputError` for refusals, incomplete output, and validation failures (#60).

- Add a main-methods table to the README and a full API reference at `docs/api.md` / `docs/api-ja.md` (#61).

- Rename `LLM.stream()` / `astream()` to `ask_stream()` / `aask_stream()`, and add `chat_stream()` / `achat_stream()`, which take `messages` like `chat()` (#62).
- The old names `stream()` / `astream()` remain as deprecated aliases (no warning is emitted).
- Accept conversation history in `ask()` / `ask_stream()` / `aask()` / `aask_stream()` and the deprecated `stream()` / `astream()` aliases (#59). List input is handled like `chat()` messages, including system handling, cache keys, logging, events, and `request_id` on stream iterators. String input requests and cache keys are unchanged. A non-string, non-list input, an empty list, or a list containing non-dict items raises `LLMConfigError(code="invalid_messages")`.

## 0.6.0

Production hardening (#49):

- Limit decoded response bodies while reading (`iter_bytes()` / `aiter_bytes()`), including HTTP error responses, in sync and async calls. The `Content-Length` pre-check is kept. Oversized bodies raise `response_too_large` and emit `request_error`.
- Raise `APIStreamError` with code `stream_incomplete` and emit `stream_error` when a chat stream ends without its terminal event. Such a stream is not cached. `APIStreamError` accepts a `code` argument (default `stream_error`).
- Secure existing log file permissions (0600) on POSIX before writing, and support an optional `redact=` hook on `JSONLLog`.
- Limit stream cache and log buffers to 16 MiB each; oversized streams remain readable, skip caching, and log a truncated response marker.
- Bound SSE lines while reading (no unbounded line without a newline) and limit retained event data to 16 MiB; oversized streams raise `response_too_large` and emit `request_error`.
- Serialize writes and trims across log instances targeting the same normalized path, and use unique temporary files for trims.
- Coalesce concurrent cache misses for the same non-streaming chat within one process (threads and asyncio).
- Report runtime cache and log failures with a `logging` warning (logger `llm_ai_api`), new `cache_error` / `log_error` events, and a `failure_count` on `SQLiteCache` / `JSONLLog`.
- Merge header names case-insensitively (later values win; sent names are lower-cased) and align Anthropic parameter filtering and cache keys with the effective headers. Cache entries created with extra headers under different name casing are not reused.
- Support HTTP-date `Retry-After` values; ignore negative, NaN, or infinite values (normal backoff is used) and cap received values with `retry_after_max`.

## 0.5.0

- Call metadata on success: `ChatResult.request_id`, `latency` (seconds), and `retries`. The same fields are on `APIConnectionError`, `APITimeoutError`, `APIStatusError`, and `APIStreamError`. Streaming exposes `request_id` on each `ChatChunk` and on the iterators from `stream()` / `stream_chat()` / `request_stream()` (#30).
- `add_event_listener` / `remove_event_listener` on `LLM` and provider clients. Events: `retry`, `connection_error`, `response`, `http_error`, `request_error`, `stream_error`, `stream_end`, `cache_hit`. A listener that raises `Exception` does not fail the request. Sync and async calls share one listener list.

## 0.3.1

- Optional encrypted SQLite response cache for chat and streaming (`set_cache()`, `cache=`, `LLM_AI_API_CACHE_DIR`) and `clear_cache(days)`, see `docs/io_cache.md`.
- Docs on provider prompt caching (`docs/cache.md`).
- Optional JSON Lines log of inputs and outputs (`set_log()`, `log=`, `LLM_AI_API_LOG_DIR`), see `docs/io_logs.md` (#7).
- Async support in the common interface: `LLM.aask()` / `achat()` / `astream()`, `aclose()` and `async with` (#12).
  No new public names; the cache and the log work as in the sync API. Async provider clients and an async raw layer are not public.
- Step-by-step tutorial (`docs/tutorial.md`).
- Fixes from post-merge reviews: a failed Anthropic stream (broken or error terminal event) is no longer
  stored in the cache, the async client reuses the settings the sync client resolved at construction,
  and stream/`LLM` close operations are safe to cancel.
- httpx exceptions no longer leak: `httpx.RequestError` subclasses such as `DecodingError` are converted
  to `APIConnectionError`, and an invalid URL raises `LLMConfigError` (`code="invalid_url"`) (#17).

## 0.2.0

First functional release (0.0.1 only reserved the package name).

- Providers: OpenAI, OpenRouter, Anthropic (Claude), and Google Gemini (via Google's
  OpenAI-compatible endpoint), each with `chat` / `stream_chat` / raw `request`.
- Common interface: `llm("provider:model")` with `ask`, `stream`, `chat`.
  Parameters that are not passed are never sent; an explicit `None` turns a default off for one call.
- `models` module with constants such as `models.OPENAI_GPT6_LUNA`.
- Localized error messages (ja/en) with fallback `language -> en -> message id`;
  every exception has a language-independent `code`.
- Retries with `retry-after`, an SSE parser, and httpx errors converted to package exceptions.
- Examples in `examples/`.
- Only dependency: `httpx`.
