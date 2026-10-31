# llm-ai-api

A thin, stable HTTP wrapper for the OpenAI, OpenRouter, and Claude (Anthropic) APIs.
It does not use the official SDKs; the only dependency is `httpx`.

[日本語版 (Japanese)](README-ja.md)

## Installation

```sh
pip install llm-ai-api
```

## Usage

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
print(luna.ask("Come up with a cute name for a dog"))
```

Set the API key via an environment variable (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` or `GOOGLE_API_KEY`).
The model is always `"<provider>:<model>"` (providers: `openai`, `openrouter`, `anthropic` / `claude`, `google`).
Google Gemini is called through Google's OpenAI-compatible endpoint.

```python
for piece in luna.stream("Write a short story"):   # streaming
    print(piece, end="", flush=True)

result = luna.chat([{"role": "user", "content": "hi"}])  # ChatResult: text, stop_reason, usage, raw
```

Parameters you do not pass are never sent (newer models reject even default values such as `temperature`).
Anything else can go through `extra={...}`, or the raw layer: `luna.client.request(path, body)`.

You can also pick from the model constants (they are just `"provider:model"` strings):

```python
from llm_ai_api import llm, models

m = llm(models.ANTHROPIC_CLAUDE_OPUS_5_5)
```

The constants are examples. Any other model works as a plain string, e.g. `llm("openai:some-new-model")`.

## Response caching

Off by default. When on, a repeat call with the same provider, model and request (messages and parameters) returns the stored result without calling the API.

```python
from llm_ai_api import llm, set_cache

set_cache("cache.db")                    # process-wide: on (an SQLite file path)
m = llm("openai:gpt-6-luna")              # uses the global setting
m2 = llm("openai:gpt-6-luna", cache="other.db")  # per instance
m3 = llm("openai:gpt-6-luna", cache=False)       # off for this instance only
```

`cache=True` uses the default file `llm_ai_api_cache.db`. A `SQLiteCache` object can also be passed, and `SQLiteCache.clear()` empties it. Streaming (`stream()` / `stream_chat()`) is not cached.

## Examples

See [`examples/`](examples/). Each script takes a `provider:model` argument (or the `LLM_MODEL` env var).

| Script | What it shows |
|---|---|
| `hello.py` | Ask for a greeting |
| `hello_stream.py` | Print the reply as it streams |
| `chat_history.py` | Reply based on a chat history |
| `ocr_test.py` | Read the text in an image |
| `image_desc.py` | Describe an image |
| `models_test.py` | Two models (GPT-6 Luna and Claude Haiku) discuss the breakfast menu, using the `models` constants (needs both API keys) |
| `cache_demo.py` | Ask the same question twice and see the second answer come from the cache |

Image content is not converted between providers; the examples build the right format for each one (see `examples/_common.py`).

## Error messages

Error messages are available in English and Japanese. The language is chosen from
`LLM_AI_API_LANG`, then `LANGUAGE` / `LC_ALL` / `LC_MESSAGES` / `LANG`, and falls back to English.
You can also set it explicitly:

```python
from llm_ai_api import llm, set_language

set_language("ja")                       # for the whole process
m = llm("openai:gpt-6-luna", lang="en")  # or per model
```

Every exception has a language-independent `code` (e.g. `"missing_api_key"`) you can check instead of the message.
Messages returned by the API itself are never translated.

## License

MIT
