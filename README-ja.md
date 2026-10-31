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

API キーは環境変数（`OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`（または `GOOGLE_API_KEY`））で渡します。
モデルは `"<プロバイダー>:<モデル名>"` で指定します（`openai` / `openrouter` / `anthropic`（別名 `claude`） / `google`）。
Google Gemini は、Google の OpenAI 互換エンドポイント経由で呼び出します。

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

## サンプル

[`examples/`](examples/) を参照してください。どのスクリプトも、引数 `プロバイダー:モデル`（または環境変数 `LLM_MODEL`）でモデルを指定します。

| スクリプト | 内容 |
|---|---|
| `hello.py` | 挨拶を返してもらう |
| `hello_stream.py` | ストリーミングで返信を表示する |
| `chat_history.py` | チャット履歴に基づいて返信する |
| `ocr_test.py` | 画像に書かれた文字を読み取る |
| `image_desc.py` | 画像の内容を説明してもらう |
| `models_test.py` | `models` の定数を使い、2 つのモデル（GPT-6 Luna と Claude Haiku）に朝食のメニューについて意見交換してもらう（両方の API キーが必要） |

画像のコンテンツはプロバイダー間で変換されません。サンプルでは、プロバイダーごとの形式を組み立てています（`examples/_common.py` を参照）。

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
