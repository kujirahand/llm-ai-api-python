# llm-ai-api

OpenAI / OpenRouter / Claude (Anthropic) の API を呼び出す、薄くて壊れにくい HTTP ラッパーです。
公式 SDK を使わず、依存は `httpx` のみです。

[English](README.md)

## インストール

```sh
pip install llm-ai-api
```

## 使い方

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
print(luna.ask("可愛い犬の名前を考えて"))
```

API キーは環境変数（`OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY`）で渡します。
モデルは `"<プロバイダー>:<モデル名>"` で指定します（`openai` / `openrouter` / `anthropic`（別名 `claude`））。

```python
for piece in luna.stream("短い物語を書いて"):   # ストリーミング
    print(piece, end="", flush=True)

result = luna.chat([{"role": "user", "content": "こんにちは"}])  # ChatResult: text, stop_reason, usage, raw
```

指定していないパラメータは送りません（新しいモデルは `temperature` などをデフォルト値でも拒否することがあるため）。
それ以外のパラメータは `extra={...}` で、さらに細かい操作は生レイヤー `luna.client.request(path, body)` で扱えます。

## ライセンス

MIT
