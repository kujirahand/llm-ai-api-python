# Input/output cache

日本語: [io_cache-ja.md](io_cache-ja.md)

Skips the API call for a request that was already made and returns the previous response from SQLite. Use it in tests and debugging to save cost and waiting time. Responses are stored encrypted. Off by default.

This is a local response cache in the library. It is separate from the providers' prompt caching ([cache.md](cache.md)).

## Enabling

There are three ways.

```sh
# 1. Environment variable (uses <dir>/cache.db)
export LLM_AI_API_CACHE_DIR=./.llm_cache
```

```python
from llm_ai_api import llm, set_cache

# 2. Process-wide (takes precedence over the env var; set_cache(None) turns it off explicitly)
set_cache("./cache.db")

# 3. Per instance (takes precedence over the global setting)
m = llm("openai:gpt-6-luna", cache="./cache.db")   # True uses the default llm_ai_api_cache.db
off = llm("openai:gpt-6-luna", cache=False)         # off for this instance only

print(m.ask("Suggest a cute name for a dog"))  # calls the API and stores the response
print(m.ask("Suggest a cute name for a dog"))  # served from the cache (no API call)
```

A `SQLiteCache` object can also be passed to `cache=` or `set_cache()`. Directories and files are created if missing.

## Deleting old entries

```python
from llm_ai_api import clear_cache

n = clear_cache(7)                    # delete entries older than 7 days (directory from the env var)
n = clear_cache(30, "./.llm_cache")   # explicit directory
n = clear_cache(0)                    # delete everything
print(n, "entries deleted")
```

It deletes entries stored more than `days` days ago and returns how many were deleted. The directory is looked up in the argument, then the env var, then the cache set with `set_cache()`. If none is found it raises `LLMConfigError` (`code="cache_dir_not_set"`). `SQLiteCache.clear(days=None)` behaves the same.

## Maximum size

```python
from llm_ai_api import SQLiteCache, llm, set_cache

set_cache("./cache.db", max_size=50 * 1024 * 1024)   # 50 MB (when created from a path or True)
set_cache("./cache.db", max_size=None)                # unlimited
m = llm("openai:gpt-6-luna", cache=SQLiteCache("./cache.db", max_size=10_000_000))
```

- `max_size` (bytes) defaults to **100 MB** (`llm_ai_api.cache.DEFAULT_MAX_SIZE`). A path or `True`, and the `LLM_AI_API_CACHE_DIR` environment variable, use this default.
- When the file is larger than `max_size` after a `put()`, the oldest third of the rows (by storage time) is deleted and the file is shrunk with `VACUUM`. There is one trim per `put()`; if the file is still over the limit, the next `put()` trims again. The newest row is always kept.
- `max_size=None` means unlimited. Zero, a negative number or a non-integer raises `LLMConfigError` (`code="invalid_cache"`).
- The `max_size` of `set_cache()` is used only when it creates the cache from a path or `True`. When you pass a `SQLiteCache` object, its own `max_size` applies.
- A failure while trimming never fails the call (best effort).

## Behavior

- **Scope**: `chat()` / `ask()` and `stream_chat()` / `ask_stream()` / `chat_stream()` (streaming). The raw layer (`request()`) is not cached.
- **Key**: hex `sha256("{provider}:{model}@{api_key}>>>{input}")`. `{input}` is the request body (`messages`, `temperature`, `max_tokens`, anything added with `extra`, `stream`, ...) plus the client settings that can change a response (`base_url`, extra headers, Anthropic's `anthropic_version`) as JSON with sorted keys. The body is the one after parameters the model rejects have been removed. Two requests that differ only by a dropped key share a cache key.
- **Value**: the whole response (`ChatResult`, including `request_id`, `latency`, and `retries`), encrypted. A stream is stored as the list of its SSE events and replayed from the cache. On a cache hit those fields are the values stored with the original call. Rows written before the fields existed load with `request_id` and `latency` as `None` and `retries` as `0`.
- **A different API key means a separate cache.** The API key is used only to build the key hash and to derive the encryption key; it is never stored in plain text.
- **Encryption**: built from the standard library only (a key derived from the API key with `scrypt`, HMAC-SHA256 in counter mode for encryption, and an HMAC to detect tampering. The HMAC also covers the cache key, so moving a ciphertext to another row is detected, and a read that uses an API key never accepts an unencrypted value). It keeps cached responses from sitting in plain text; it does not replace protecting your API key. The encryption key comes from the API key, so anyone holding the API key can read the cache.
- Only successful responses are stored. HTTP errors are not.
- A stream is stored only when it was read up to its terminal event (`[DONE]` or `message_stop`). Streams that were cut off without a terminal event, stopped early or failed are not stored.
- A corrupt row or a tampered value is treated as a miss (and that row is deleted) and the API is called. A cache read/write failure at run time never fails the call.
- A newly created cache file is owner-only (0600) from the moment it is created; existing files keep their permissions.
- The cache file uses SQLite's WAL journal mode (falls back to the default where WAL is unavailable), so several processes can share one file. You may see `-wal` / `-shm` files next to it; they get the same permissions as the main file.
- Entries do not expire by themselves. The same request keeps returning the same response; use `clear_cache()` or turn the cache off to get a fresh one.
- Do not commit the cache file to a repository.

Stream cache buffering has a fixed 16 MiB budget per stream (the sum of each event’s JSON-encoded UTF-8 byte size). If exceeded, buffered events are released and the stream is not cached; delivery continues. This budget is independent of file `max_size`.

With caching enabled, concurrent non-streaming chats with the same cache key in one process share the first successful cached result, across threads and asyncio tasks. If the first call fails or does not store a result, a waiter makes its own call. Streaming and raw requests are excluded. Waiting is not covered by the per-operation timeout.

Runtime lookup/store failures emit warnings and `cache_error` events; `cache.failure_count` counts failures observed through clients. See [Events](events.md#cache_error--log_error).

Header names in cache keys are normalized to lowercase, and the effective Anthropic version is used. Existing cache entries may miss after this change.
