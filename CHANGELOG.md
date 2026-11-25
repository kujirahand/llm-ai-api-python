# Changelog

## Unreleased

- Make the response cache work for providers that need no API key (for example OpenRouter without a key). Previously `cache_key(..., None)` raised, so every cache read and write on a key-less client failed and was swallowed, and nothing was cached. `cache_key()` now accepts `api_key=None`. Also, `SQLiteCache.put()` called directly without a `secret` (the only path that used to store plain text) now encrypts with a fixed default secret; the per-file random salt still goes into the key derivation. Plain rows written by earlier versions are still readable. If you downgrade to an earlier version, it cannot read the encrypted key-less rows: it drops them and the responses are fetched again (#147).
- Pin the GitHub Actions in the CI, CodeQL, and contract-replay workflows to commit SHAs (#147).
- Cap the number of items `models()` / `amodels()` accumulate (10,000); exceeding it raises `LLMError` with `code="models_pagination_limit"` (#147).
- Cap what a stream's `result` retains (16 MiB of text and event JSON). Past the cap `result` stays `None`; the chunks are still delivered (#147).
- Document in the `register_provider()` docs that declarations must come from trusted code only, since `api_key_env` can name any environment variable and its value is sent to `base_url` (#147).

## 0.6.3

- Change the response cache key to HMAC-SHA256 keyed with a scrypt-derived key of the API key, so the API key is no longer hashed directly with SHA-256 (fixes CodeQL code scanning alert #1, `py/weak-sensitive-data-hashing`). The key is still a 64-character hex string and different API keys still never share entries. Existing cache entries written by earlier versions will no longer hit and are simply re-fetched; use `clear_cache()` to remove them.
- Add `result` to streams. The objects returned by `chat_stream()` / `ask_stream()` / `achat_stream()` / `aask_stream()` (and the provider layer's `stream_chat()` iterator) expose a `ChatResult` for the whole response once the terminal event has been read: joined `text`, `model`, `stop_reason`, `usage` (including cache and reasoning tokens when sent; `None` if the provider sends none), `raw["events"]`, `request_id`, `retries`, and `latency` (`None` for cache replays). It stays `None` before the end, after an error, and after an early close (#136).

- Add `register_provider()` to add an OpenAI-compatible or Anthropic-compatible provider from a declaration (`base_url`, `api_key_env`, `auth_header` / `auth_scheme`, `headers`, `aliases`, `replace`, ...), with sync and async clients generated from it. Built-in providers now come from the same internal registry (`_providers.py`), their async classes are generated instead of hand-written, and `models()` / images / structured output / `transcribe()` read declared attributes instead of provider names. Built-in names cannot be replaced, and the table of rejected parameters stays built-in only, except for the `anthropic-version` rule, which also applies to `api_format="anthropic"` registrations. New error codes: `invalid_provider`, `provider_exists` (#141).

- Add optional `cache_read_tokens`, `cache_creation_tokens`, and `reasoning_tokens` to `Usage`. OpenAI-compatible responses map `prompt_tokens_details.cached_tokens` and `completion_tokens_details.reasoning_tokens`; Anthropic maps `cache_read_input_tokens` and `cache_creation_input_tokens`. Missing values stay `None`, an explicit zero is `0`, and existing `input_tokens` / `output_tokens` totals are not adjusted. Cached rows written before these keys existed still load (#127). Note: `Usage` equality now also compares the new fields.

- Add `models()` and `amodels()` to list provider models, including pagination (#123).

- Add `InsufficientCreditsError` (`APIStatusError`) for credit, billing, or quota exhaustion: HTTP 402, an xAI 403 whose body is `permission-denied` and mentions missing credits or licenses, and OpenAI 429 `insufficient_quota`. These responses are not retried (including 429 quota errors). The English and Japanese hint is `hint_credits`. Ordinary 403 and 429 responses keep `PermissionDeniedError` / `RateLimitError` and the existing retry behavior (#120).
- Recognize more billing and quota errors as `InsufficientCreditsError`, and still do not retry them: OpenAI `credit_balance_exhausted` and the organization/project spend and usage limit codes, Anthropic's credit-balance sentence and `enforced_spend_limit_reached`, Google Interactions `quota_exceeded`, and OpenRouter budget `limit_source` values. An xAI 403 `permission-denied` matches when the message says credit(s) are exhausted, so reworded shortage messages still classify without treating every mention of credits as billing exhaustion. Google 429 `RESOURCE_EXHAUSTED` stays `RateLimitError` and is still retried (#124).
- Require Python 3.10 or later, and run CI on Python 3.10 and 3.13.
- Raise the isolated build requirement to `setuptools>=84.1.0` and document recommended minimum versions for patched transitive dependencies.
- Add weekly Dependabot updates, Python CI, and CodeQL analysis workflows.
- Add the `muse` provider (Muse, Meta Model API) as an OpenAI-compatible client: `MuseClient`, default base URL `https://api.meta.ai/v1`, API key from `MODEL_API_KEY`, base URL override via `MUSE_BASE_URL`, and the `models.MUSE_MUSE_WONDER_1_0` constant.
- Add the `grok` provider (xAI, OpenAI-compatible; `XAI_API_KEY` / `XAI_BASE_URL`) with `GrokClient` and `models.GROK_GROK_4_7`.
- Reorganize the READMEs around a quick start and provider table, and add a how-it-works diagram featuring the project mascot to the README header.

## 0.6.2

- Clarify the `base_url` caution placement, link README security notes to each local provider page, and correct the full-read wording for paths vs `bytes` (#97).
- Open logs with `O_NONBLOCK` to avoid FIFO hangs, test `fstat` with a real device, skip cache permission changes on symlinks, and warn at most once per path on chmod failure; document the fallback without `O_NOFOLLOW` (#96).
- Fix the retry test to detect a missing response close before sleep (#95).
- Check the whole model schema graph for cycles and excessive depth, with distinct messages (#94).
- Document cautions for unrestricted `base_url` (including plain HTTP), unbounded image/audio reads, and unverified local-provider connections (#88).
- Tighten existing cache file permissions on POSIX and guard log opens against symlinks and non-regular files (#84).
- Close synchronous error responses before waiting for a status retry (#85).
- Report only keys and value types in invalid transcription response errors (#86).
- Reject cyclic or excessively deep model schemas with `LLMConfigError(code="invalid_schema")` (#87).

## 0.6.1

- Add `docs/local_llm-lmstudio.md` / `-ja.md` and `docs/local_llm-ollama.md` / `-ja.md` (starting the server, environment variables, LAN access, troubleshooting), and a `docs/README.md` / `docs/README-ja.md` index of every document. The LM Studio page covers the API token needed when "Require Authentication" is on; the Ollama page notes that the local server has no API-key authentication of its own.

- Add local OpenAI-compatible providers: `lmstudio` (LM Studio), `ollama` (Ollama) and `strata` (Strata). An API key is optional for these providers (#73, #74, #75). `strata` defaults to `http://127.0.0.1:47831/v1`, the port Strata listens on with sharing off, so no `STRATA_BASE_URL` is needed on the machine that runs Strata.

- Add remediation hints to the `StructuredOutputError` messages (`output_refused`, `output_incomplete`, `invalid_structured_output`) in English and Japanese, and refine the per-code table in `docs/structured.md` (#70).

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
