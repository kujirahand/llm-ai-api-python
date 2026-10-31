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

Set the API key via an environment variable (`OPENAI_API_KEY`, `OPENROUTER_API_KEY`, `ANTHROPIC_API_KEY`).
The model is always `"<provider>:<model>"` (providers: `openai`, `openrouter`, `anthropic` / `claude`).

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

## License

MIT
