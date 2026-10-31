# Input/output log

日本語: [io_logs-ja.md](io_logs-ja.md)

Records the input and output of every chat call to a file in JSON Lines format (one JSON object per line). Use it to review prompts and answers, debug, or audit usage. Off by default.

## Enabling

```sh
# 1. Environment variable (writes to <dir>/llm.jsonl)
export LLM_AI_API_LOG_DIR=./.llm_log
```

```python
from llm_ai_api import llm, set_log

# 2. Process-wide (takes precedence over the env var; set_log(None) turns it off explicitly)
set_log("./llm_log.jsonl")

# 3. Per instance (takes precedence over the global setting)
m = llm("openai:gpt-6-luna", log="./llm_log.jsonl")   # True uses the default llm_ai_api_log.jsonl
off = llm("openai:gpt-6-luna", log=False)              # off for this instance only

m.ask("Suggest a cute name for a dog")
```

`get_log()` returns the process-wide log object, or `None` when it is off.

## What is recorded

`ask()`, `chat()`, `stream()` and `stream_chat()` each append one line. The raw layer (`request()` / `request_stream()`) is not recorded.

| Field | Meaning |
|---|---|
| `time` | UTC time, ISO 8601 |
| `provider` | e.g. `openai`, `anthropic` |
| `model` | The model sent in the request |
| `stream` | `true` for `stream()` / `stream_chat()` |
| `cached` | `true` when the response came from the response cache ([io_cache.md](io_cache.md)) |
| `request` | The request body as sent, after parameters the model rejects are removed |
| `response` | The raw response dict. For a stream: `{"text": "<concatenated text>", "chunks": [<raw event JSON>, ...]}` |

Example (pretty-printed; the file has one object per line):

```json
{
  "time": "2026-10-31T01:23:45.678901+00:00",
  "provider": "openai",
  "model": "gpt-6-luna",
  "stream": false,
  "cached": false,
  "request": {"model": "gpt-6-luna", "messages": [{"role": "user", "content": "Suggest a cute name for a dog"}]},
  "response": {"choices": [{"message": {"content": "Pochi"}, "finish_reason": "stop"}]}
}
```

```python
import json

with open("llm_log.jsonl", encoding="utf-8") as f:
    for line in f:
        record = json.loads(line)
        print(record["time"], record["model"])
```

## Maximum size

```python
from llm_ai_api import JSONLLog, llm, set_log

set_log("./llm_log.jsonl", max_size=50 * 1024 * 1024)   # 50 MB (when created from a path or True)
set_log("./llm_log.jsonl", max_size=None)                # unlimited
m = llm("openai:gpt-6-luna", log=JSONLLog("./llm_log.jsonl", max_size=10_000_000))
```

- `max_size` (bytes) defaults to **100 MB** (`llm_ai_api.log.DEFAULT_MAX_SIZE`). A path or `True`, and the `LLM_AI_API_LOG_DIR` environment variable, use this default.
- The file size is checked after every appended line. When it is over `max_size`, the first (oldest) third of the lines is dropped and the rest is rewritten. If the file is still over the limit, the next write trims again. The most recently written record is always kept, even if it alone is larger than `max_size`.
- Threads of one process are serialized by a lock. Several **processes** writing to the same log file are not fully supported while a trim runs: the trim is abandoned if the file changed since it was read (the next write retries), but a record appended by another process in the tiny window just before the final rename can still be lost. Use one log file per process if every record matters. (The cache uses SQLite's own locking, so this caveat applies to the log only.)
- `max_size=None` means unlimited. Zero, a negative number or a non-integer raises `LLMConfigError` (`code="invalid_log"`).
- The `max_size` of `set_log()` is used only when it creates the log from a path or `True`. When you pass a `JSONLLog` object, its own `max_size` applies.
- A failure while trimming never fails the call (best effort).

## Notes

- The API key and auth headers are never recorded.
- The log is **plain text** and contains your prompts and the answers as they are. Keep the file private. It is created with permissions `0600` (best effort), and a new parent directory with `0700`.
- A stream is recorded only after it has been read to the end. Streams that are stopped early and calls that fail are not recorded. To observe retries and failures, use `add_event_listener` rather than the log (see [Events](events.md)).
- A failure while writing the log is ignored, so a response you already paid for is never lost. An invalid setting (a wrong value or an unwritable path) raises `LLMConfigError` with `code="invalid_log"` when the client is created.
- You can pass your own object instead of a path. It needs `write(provider, model, request, response, *, stream, cached)`.
