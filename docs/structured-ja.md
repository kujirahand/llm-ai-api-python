# 構造化出力

`LLM.chat()` と `LLM.achat()` は `schema=` で JSON の構造化出力を要求できます。検証した値は `ChatResult.parsed` に入ります。ストリーミング（`ask_stream()` / `chat_stream()` など）では使えません。

## 使い方

JSON Schema の dict を渡す方法:

```python
from llm_ai_api import llm

result = llm("openai:gpt-6-luna").chat(
    [{"role": "user", "content": "犬の名前を1つ返して"}],
    schema={
        "title": "DogName",
        "type": "object",
        "properties": {"name": {"type": "string"}},
        "required": ["name"],
    },
)
print(result.parsed["name"])  # dict として読み取った値
```

pydantic v2 互換のモデルクラス（`model_json_schema()` と `model_validate_json()` を持つもの）も渡せます。このライブラリは pydantic を依存に含まないため、モデルクラスは利用者側で用意します。

```python
from pydantic import BaseModel


class DogName(BaseModel):
    name: str


result = m.chat(messages, schema=DogName)
dog: DogName = result.parsed  # 検証済みのオブジェクト
```

## プロバイダーごとの形式

| プロバイダー | 送るもの |
|---|---|
| OpenAI / OpenRouter / Google | `response_format`（`json_schema`、strict） |
| Anthropic | `output_config.format`（`json_schema`） |

OpenAI 系のスキーマ名は、スキーマの `title`、モデルクラスの `__name__`、`"response"` の順で決まります。

## スキーマの正規化

モデルクラス由来のスキーマは、strict モードで通るようにコピーして正規化します（元のスキーマは変更しません）。

- object の `additionalProperties` を `false` にする
- `required` を全プロパティにする
- 元は任意だったプロパティを nullable 化する
- プロパティの `default` を取り除く

dict で渡した JSON Schema は無加工で送ります。

## エラー

| 状況 | 例外 |
|---|---|
| モデルが拒否した | `StructuredOutputError`（`code="output_refused"`） |
| 長さ上限などで出力が完了しなかった | `StructuredOutputError`（`code="output_incomplete"`） |
| JSON として読めない／モデルの検証に失敗した | `StructuredOutputError`（`code="invalid_structured_output"`、元の例外は `__cause__`） |
| `schema=` の値が不正 | `LLMConfigError`（`code="invalid_schema"`） |

`StructuredOutputError.result` に元の `ChatResult` が入っているため、課金済みの応答（`text` や `raw`）を失わずに済みます。

### code ごとの意味と対処

| `code` | 意味 | よくある原因 | 対処 |
|---|---|---|---|
| `output_refused` | モデルが回答を拒否した | 要求内容がモデルのポリシーに触れた。Claude が `stop_reason="refusal"` を返した | 要求内容を見直す。`StructuredOutputError.result.text` / `raw` で拒否の詳細を確認する |
| `output_incomplete` | 出力が途中で終わり、JSON が完成しなかった | `max_tokens` の上限に達した（`stop_reason="max_tokens"`）。応答が長すぎる | `max_tokens` を増やす。スキーマや要求する項目を小さくする |
| `invalid_structured_output` | 応答を JSON として読めない、またはスキーマ検証に失敗した | モデルが JSON 以外の文章を返した。必須項目の欠落や型の不一致 | `__cause__`（元の例外）と `.result.text`（生の応答）を確認する。プロンプトにスキーマの要点を明記する、項目を減らす、別のモデルを試す。再試行で解消することもある |

どの code でも、再試行の前に `.result`（元の応答）と `__cause__`（検証失敗の詳細）を記録しておくと原因を切り分けやすくなります。

## extra での上書き

`extra` は従来どおり最後に適用され、自動生成したキーに勝ちます。たとえば OpenAI 系で `extra={"response_format": ...}` を渡せば自動設定を完全に置き換えられます。Anthropic の `output_config` は浅くマージされるため、`extra={"output_config": {"effort": "high"}}` のように別キーを足しても自動の `format` は残ります。
