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

代表的なモデルは定数でも指定できます（中身は `"プロバイダー:モデル"` の文字列です）。

```python
from llm_ai_api import llm, models

m = llm(models.ANTHROPIC_CLAUDE_OPUS_5_5)
```

定数は例です。載っていないモデルも `llm("openai:新しいモデル名")` のように文字列でそのまま使えます。

## エラーメッセージ

エラーメッセージは日本語と英語に対応しています。言語は環境変数 `LLM_AI_API_LANG`、
`LANGUAGE` / `LC_ALL` / `LC_MESSAGES` / `LANG` の順に判定し、判定できなければ英語です。
明示的に指定することもできます。

```python
from llm_ai_api import llm, set_language

set_language("ja")                       # プロセス全体
m = llm("openai:gpt-6-luna", lang="en")  # モデルごと
```

すべての例外は、言語に依存しない `code`（例: `"missing_api_key"`）を持っています。メッセージの文面ではなく `code` で判定してください。
API 自身が返したメッセージは翻訳しません。

## ライセンス

MIT
