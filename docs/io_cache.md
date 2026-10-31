# Input/output cache

日本語: [io_cache-ja.md](io_cache-ja.md)

Skips the API call for a request that was already made and returns the previous response from SQLite. Use it in tests and debugging to save cost and waiting time. Responses are stored encrypted.

This is a local response cache in the library. It is separate from the providers' prompt caching ([cache.md](cache.md)).

## Enabling

Set a directory with an environment variable:

```sh
export LLM_AI_API_CACHE_DIR=./.llm_cache
```

Or in code (this takes precedence over the environment variable):

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna", cache_dir="./.llm_cache")
print(m.ask("Suggest a cute name for a dog"))  # calls the API and stores the response
print(m.ask("Suggest a cute name for a dog"))  # served from the cache (no API call)
```

Without either, the cache is off. The directory is created if missing. Everything is stored in one file, `<dir>/cache.db`.

## Deleting old entries

```python
from llm_ai_api import clear_cache

n = clear_cache(7)                         # delete entries older than 7 days (directory from the env var)
n = clear_cache(30, "./.llm_cache")        # explicit directory
n = clear_cache(0)                         # delete everything
print(n, "entries deleted")
```

It deletes entries stored more than `days` days ago and returns how many were deleted. If no directory is given anywhere, it raises `LLMConfigError` (`code="cache_dir_not_set"`).

## Behavior

- **Key**: hex `sha256("{provider}:{model}@{api_key}>>>{input}")`. `{input}` is the method, path, stream flag and request body (`messages`, `temperature`, `max_tokens`, anything added with `extra`, ...) as JSON with sorted keys.
- **Value**: the whole response, encrypted. The response JSON for normal calls, the list of SSE events for streams.
- **A different API key means a separate cache.** The API key is used only to build the key hash and to derive the encryption key; it is never stored in plain text.
- **Encryption**: built from the standard library only (a key derived from the API key with `scrypt`, HMAC-SHA256 in counter mode for encryption, and an HMAC to detect tampering). It keeps cached responses from sitting in plain text; it does not replace protecting your API key. The encryption key comes from the API key, so anyone holding the API key can read the cache.
- Only successful responses are stored. HTTP errors are not.
- A stream is stored only when it was read to the end. Streams stopped early or failed are not stored.
- A corrupt file or a tampered value is treated as a miss and the API is called. A failed write never fails the call.
- Entries do not expire by themselves. Even without `temperature` the same response keeps coming back; use `clear_cache()` or delete the file to get a fresh one.
- Do not commit the cache file to a repository.
