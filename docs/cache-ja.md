# プロンプトキャッシュの使い方

English: [cache.md](cache.md)

`llm-ai-api` には、キャッシュ専用の API はありません。リクエストの `content` と、レスポンスの `raw` は加工せずに素通しするため、各プロバイダーのプロンプトキャッシュは、そのまま使えます。

キャッシュ用の引数は不要です。`chat()` に、プロバイダーの形式で書いた `content` を渡してください。

## Claude（Anthropic）

キャッシュしたいブロックに `cache_control` を付けます。`system` ロールのメッセージの `content` は、ブロックの配列で渡せます。ライブラリは、トップレベルの `system` にそのまま入れて送ります（`tests/test_anthropic.py` の `test_system_blocks` を参照）。

```python
from llm_ai_api import llm, models

m = llm(models.ANTHROPIC_CLAUDE_SONNET_5_5)

long_text = open("manual.txt", encoding="utf-8").read()  # 長い共通の前提

messages = [
    {
        "role": "system",
        "content": [
            {
                "type": "text",
                "text": long_text,
                "cache_control": {"type": "ephemeral"},  # ここまでをキャッシュする
            }
        ],
    },
    {"role": "user", "content": "第3章を要約して"},
]

result = m.chat(messages)
print(result.text)
print(result.raw["usage"])
```

`ask()` と `stream()` は文字列の質問を受け取るため、ブロック配列を渡すときは `chat()` を使います。

2 回目以降の呼び出しでは、前の呼び出しと同じ前半部分（上の例では `system`）が、キャッシュから読まれます。キャッシュが効いたかどうかは、`result.raw["usage"]` で確認します。

| フィールド | 意味 |
|---|---|
| `cache_creation_input_tokens` | キャッシュに書き込んだトークン数 |
| `cache_read_input_tokens` | キャッシュから読んだトークン数 |

`ChatResult.usage`（`input_tokens` / `output_tokens`）には、これらのフィールドは含まれません。キャッシュの状況は、必ず `raw` から読んでください。

キャッシュできる最小トークン数、有効期間、料金は、モデルによって異なります。最新の値は、公式ドキュメントで確認してください。

## OpenAI / OpenRouter / Google

OpenAI は、一定以上の長さのプロンプトで、自動的にキャッシュを使います。リクエスト側で指定することは、ありません。前半部分（`system` や共通の資料）を呼び出しの間で同一にして、変わる部分を後ろに置くと、キャッシュが効きやすくなります。

```python
m = llm(models.OPENAI_GPT6_LUNA)
result = m.chat([
    {"role": "system", "content": long_text},   # 毎回同じ
    {"role": "user", "content": "第3章を要約して"},  # 毎回変わる
])
print(result.raw["usage"])  # prompt_tokens_details.cached_tokens などを見る
```

OpenRouter と Google の OpenAI 互換エンドポイントでは、キャッシュの扱い（自動か、`cache_control` が必要か、使用量の項目名）が、モデルによって異なります。必要なら `extra=` でプロバイダー固有のパラメータを渡し、`result.raw["usage"]` で結果を確認してください。この組み合わせは、実際の API では未確認です。

## 注意

- キャッシュの有無で、返ってくるテキストは変わりません。変わるのは、処理時間と料金です。
- キャッシュは、前半部分が 1 文字でも違うと効きません。日時や乱数などを、キャッシュしたい部分に入れないでください。
- `result.raw["usage"]` の形式は、プロバイダー側の仕様です。変更されることがあるため、ライブラリは正規化しません（[AGENTS.md](../AGENTS.md) の「パススルー優先」）。
