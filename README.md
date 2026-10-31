# llm-ai-api

A thin, stable HTTP wrapper for the OpenAI, OpenRouter, and Claude (Anthropic) APIs.
It does not use the official SDKs; the only dependency is `httpx`.

[日本語版 (Japanese)](README-ja.md)

> This project is in an early stage. The API is not implemented yet.

## Installation

```sh
pip install llm-ai-api
```

## Usage (planned)

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
print(luna.ask("Come up with a cute name for a dog"))
```

## License

MIT
