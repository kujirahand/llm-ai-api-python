# ツール呼び出しと thinking

[English](tools.md)

`LLM.chat()` / `LLM.achat()` は `tools=` を受け取り、`ChatResult` から応答のツール呼び出しと推論テキストを読めます。ライブラリは応答から読み取り、**同じプロバイダー内**の 1 往復分のメッセージを作るだけです。ツールの実行やループの自動化、履歴管理はしません。ストリーミング（`ask_stream()` / `chat_stream()` など）は対象外です。ストリームの `result` は既定値（`tool_calls=[]`、`thinking=None`、`message=None`）のままです。

## `tools=`

次のキーだけを持つ dict のリストです。

| キー | 必須 | 意味 |
|---|---|---|
| `name` | はい | 空でない文字列 |
| `description` | いいえ | 文字列 |
| `parameters` | いいえ | JSON Schema の dict（省略時は `{"type": "object", "properties": {}}`） |

それ以外は `LLMConfigError(code="invalid_tools")` です。ライブラリがプロバイダーの形式に写して `extra` に入れます。

- OpenAI 系: `{"type": "function", "function": {"name", "description", "parameters"}}`
- Anthropic: `{"name", "description", "input_schema"}`

利用者の `extra` に `tools` があればそちらが勝ちます。組み込みツールや `tool_choice` などは、`extra` にプロバイダーの JSON を書くか生レイヤーを使います。`ask()` 系に `tools=` はありません。

## 往復の例

```python
from llm_ai_api import llm

m = llm("anthropic:claude-opus-5-5")   # "openai:..." でも同じ書き方
tools = [{
    "name": "get_weather",
    "description": "都市の天気を返す",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}]
history = [{"role": "user", "content": "東京の天気は？"}]

result = m.chat(history, tools=tools, max_tokens=1024)
while result.tool_calls:
    history.append(result.message)                      # assistant メッセージをそのまま足す
    outputs = [(call, get_weather(**(call.arguments or {}))) for call in result.tool_calls]
    history += m.tool_results(outputs)                  # プロバイダー形式のツール結果
    result = m.chat(history, tools=tools, max_tokens=1024)
print(result.text)
```

（`get_weather` は利用者の関数です。実際のコードでは回数の上限も付けてください。）

## `ToolCall`

| フィールド | 意味 |
|---|---|
| `id` | プロバイダーの id。無ければ `None`（作り出さない） |
| `name` | ツール名（名前の無い要素は飛ばす。`raw` には残る） |
| `arguments` | パース済みの dict。JSON オブジェクトでなければ `None`（例外にしない） |
| `arguments_raw` | 送られてきた JSON 文字列 |
| `type` | 生の値: `"function"` / `"custom"` / `"tool_use"` など |
| `raw` | 元の要素 |

Anthropic の `server_tool_use` ブロックは含みません（`message` / `raw` を参照）。

## `tool_results()`

`m.tool_results([(call_or_id, output), (call_or_id, output, is_error), ...])`

- `call_or_id`: `ToolCall`、id の文字列、または `None`（id は書かない）。
- `output`: 文字列はそのまま、それ以外は `json.dumps(..., ensure_ascii=False)`。
- Anthropic: `tool_result` ブロックを 1 つの `user` メッセージにまとめる。`is_error` は True のときだけ `is_error: true` を付ける（bool 以外を渡すと `invalid_tools`）。
- OpenAI 系: 呼び出しごとに `{"role": "tool", "tool_call_id", "content"}`。`is_error` は無視する。
- 形が不正なら `LLMConfigError(code="invalid_tools")`。

## `message`

`ChatResult.message` は、プロバイダー形式の assistant メッセージの deep copy です（OpenAI 系は `choices[0].message`、Anthropic は `{"role": "assistant", "content": [...]}`）。履歴には**そのまま**足してください。編集しないでください。Anthropic は `thinking` ブロックの `signature` を検証し、拡張 thinking とツール使用を併用するときは thinking ブロックを変更せずに返す必要があります。応答に無ければ `None` です。

## `thinking`

文字列または `None` です。

- OpenAI 系: `message.reasoning_content`、無ければ `message.reasoning`（空でない文字列のみ）。
- Anthropic: `thinking` ブロックの `thinking` を空行で連結。`redacted_thinking` は含みません。

`text` には含まれません。元は `raw` と `message` に残ります。

## thinking を出させる指定

共通の引数はありません。`extra` に各社の形式を書きます。

| プロバイダー | `extra` の例 |
|---|---|
| Anthropic | `{"thinking": {"type": "enabled", "budget_tokens": 2048}}` |
| OpenAI | `{"reasoning_effort": "medium"}` |
| OpenRouter | `{"reasoning": {"effort": "medium"}}` |

名前や対応モデルは各社の最新ドキュメントで確認してください。

## 制限

- 履歴はプロバイダー間で持ち越せません。`message` と `tool_results()` の出力は、生成元と同じプロバイダーにだけ返してください。
- `tool_calls` / `thinking` / `message` は応答キャッシュには保存せず、キャッシュヒット時に `raw` から作り直します。
- `schema=` と `tools=` を併用したとき、ツール呼び出しを含む応答は検証せずに返します（`parsed` は `None`）。
