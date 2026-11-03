# Documentation

日本語: [README-ja.md](README-ja.md)

Guides for [`llm-ai-api`](../README.md), the thin HTTP wrapper for OpenAI, OpenRouter, Anthropic, Google Gemini, LM Studio, Ollama and Strata.

The guides have an English and a Japanese version (`foo.md` and `foo-ja.md`) and each links to its counterpart at the top. When you change one page, change the other one in the same commit.

## Start here

| Page | What it covers |
|---|---|
| [Tutorial](tutorial.md) / [チュートリアル](tutorial-ja.md) | Installation and API keys, the first question, switching models, continuing a conversation, streaming, per-call options, async (`aask` / `achat` / `aask_stream`), handling errors, reusing and closing clients. Start with this one. |
| [API reference](api.md) / [API リファレンス](api-ja.md) | The public API as a list: `llm()`, the `LLM` methods and their async versions, return types (`ChatResult`, `ChatChunk`, `Usage`), module functions, provider clients and the low-level `request()` / `request_stream()` layers, model name constants, and every exception with its `code`. |
| [Configuration reference](config.md) / [設定リファレンス](config-ja.md) | Every setting you can pass to `llm()` (`timeout`, `max_retries`, `retry_read_timeout`, `retry_after_max`, `base_url`, `headers`, `lang`, …), the retry policy — which failures are retried and why — and the settings that matter in production (connection pool, TLS, proxy). |

## Features

| Page | What it covers |
|---|---|
| [Structured output](structured.md) / [構造化出力](structured-ja.md) | `schema=` on `chat()` / `achat()`: JSON Schema or a model class, how the schema is normalized, the per-provider request shape, validation and the errors you get back. |
| [Image input](multimodal.md) / [画像入力](multimodal-ja.md) | `images=` on the `ask` family (paths, bytes, URLs), what is sent to each provider, audio transcription with `transcribe()` / `atranscribe()` (OpenAI only), and how both interact with the cache and the log. |
| [Events](events.md) / [イベント](events-ja.md) | `add_event_listener()` / `remove_event_listener()`: `retry`, `response`, `http_error`, `connection_error`, `stream_error`, `stream_end`, `cache_hit`, `cache_error`, `log_error`, and how to read `request_id`, `latency` and `retries`. This is how you observe failures and retries — the log only records successes. |
| [Response cache](io_cache.md) / [入出力のキャッシュ](io_cache-ja.md) | Caching **this library's** calls in SQLite so a repeated request costs nothing: `set_cache()`, per-client `cache=`, the cache key, encryption, deleting old entries, and the maximum size. Off by default. |
| [I/O log](io_logs.md) / [入出力ログ](io_logs-ja.md) | Recording every chat call as one JSON line (`set_log()`, per-client `log=`), what each line holds, redacting records with a hook, and the maximum size. Off by default. |
| [Prompt caching](cache.md) / [プロンプトキャッシュの使い方](cache-ja.md) | Not a library feature: how the provider-side prompt caches of Claude and the OpenAI-compatible providers work when you pass `content` blocks through unchanged. No API of its own. |

Note the two similar names: **cache.md** is about the provider's prompt cache (nothing to configure here), **io_cache.md** is this library's own response cache (`set_cache()`).

## Local model servers

OpenAI-compatible servers on your own machine. No API key is needed unless you turned authentication on.

| Page | What it covers |
|---|---|
| [LM Studio](local_llm-lmstudio.md) / [LM Studio](local_llm-lmstudio-ja.md) | `llm("lmstudio:<model>")` on `http://localhost:1234/v1`, starting the server (`lms server start`, the Developer tab), `LMSTUDIO_BASE_URL` / `LMSTUDIO_API_KEY` / `LMSTUDIO_MODEL`, API tokens when "Require Authentication" is on, and serving the API on the local network. |
| [Ollama](local_llm-ollama.md) / [Ollama](local_llm-ollama-ja.md) | `llm("ollama:gemma4:e2b")` on `http://localhost:11434/v1` — including model names that contain `:` — pulling models, `OLLAMA_BASE_URL` / `OLLAMA_API_KEY` / `OLLAMA_MODEL`, the fact that the local server has no API-key authentication of its own (put a proxy in front), LAN access with `OLLAMA_HOST`, and Ollama's hosted models through `https://ollama.com/v1`. |
| [Strata](local_llm-strata.md) / [Strata](local_llm-strata-ja.md) | `llm("strata:<model>")` on `http://127.0.0.1:47831/v1`, `STRATA_BASE_URL` / `STRATA_API_KEY` / `STRATA_MODEL`, and connecting over the LAN, where the port changes to `47832` when sharing is on. |

Each page ends with a troubleshooting table and a `curl` command to check the connection without this library. Runnable samples: [`examples/local-llm-lmstudio.py`](../examples/local-llm-lmstudio.py), [`examples/local-llm-ollama.py`](../examples/local-llm-ollama.py), [`examples/local-llm-strata.py`](../examples/local-llm-strata.py).

---

Source: [`src/llm_ai_api/`](../src/llm_ai_api) · Design notes for contributors: [AGENTS.md](../AGENTS.md) · Samples: [`examples/`](../examples)
