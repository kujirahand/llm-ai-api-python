# llm-ai-api

OpenAI / OpenRouter / Claude (Anthropic) の API を呼び出す、薄くて壊れにくい HTTP ラッパーです。
公式 SDK を使わず、依存は `httpx` のみです。

[English](README.md)

> 現在は開発初期段階です。API はまだ実装されていません。

## インストール

```sh
pip install llm-ai-api
```

## 使い方（予定）

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
print(luna.ask("可愛い犬の名前を考えて"))
```

## ライセンス

MIT
