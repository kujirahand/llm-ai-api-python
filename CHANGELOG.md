# Changelog

## Unreleased

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
