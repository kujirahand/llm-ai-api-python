# プロバイダーを追加する（`register_provider()`）

English: [providers.md](providers.md)

組み込みにないサービスでも、OpenAI 互換または Anthropic 互換の API なら、宣言を 1 回書くだけで `llm("<名前>:<モデル名>")` から呼べます。サブクラスを書く必要はなく、非同期（`aask()` など）も同じ宣言で使えます。

```python
from llm_ai_api import llm, register_provider

register_provider(
    "deepseek",
    base_url="https://api.deepseek.com/v1",
    api_key_env="DEEPSEEK_API_KEY",
)

print(llm("deepseek:deepseek-chat").ask("こんにちは"))
```

登録は **プロセス全体** に効きます。アプリの起動時に 1 回だけ呼んでください（`import` しただけで登録される仕組みや、環境変数・設定ファイルからの登録はありません）。戻り値は `None` です。

## 例

```python
# ローカルサーバー（仮のキーで足りる）
register_provider("localbox", base_url="http://127.0.0.1:8080/v1", api_key_default="local")

# キーなしでも使えるサーバー（キーがあれば送る）
register_provider("openbox", base_url="https://llm.example.internal/v1",
                  api_key_env="OPENBOX_KEY", api_key_required=False)

# Bearer ではない認証（Azure 型の api-key ヘッダー）
register_provider("corp", base_url="https://llm.example.internal/v1",
                  api_key_env="CORP_LLM_KEY", auth_header="api-key", auth_scheme="")

# Anthropic 互換のプロキシ
register_provider("claude-proxy", api_format="anthropic",
                  base_url="https://proxy.example.com", api_key_env="PROXY_KEY")

# 別名
register_provider("deepseek", base_url="https://api.deepseek.com/v1",
                  api_key_env="DEEPSEEK_API_KEY", aliases=("ds",))
llm("ds:deepseek-chat")
```

## 引数

| 引数 | 既定値 | 説明 |
|---|---|---|
| `name`（位置引数） | 必須 | プロバイダー名。`^[a-z][a-z0-9_-]{0,31}$`（小文字で始まる、32 文字まで） |
| `base_url` | 必須 | API のベース URL（`/chat/completions` や `/v1/messages` の手前まで） |
| `api_format` | `"openai"` | `"openai"`（`/chat/completions`）または `"anthropic"`（`/v1/messages`） |
| `api_key_env` | `None` | API キーを読む環境変数名。文字列、またはタプル（先頭が優先、残りは予備） |
| `base_url_env` | `None` | `base_url` を上書きする環境変数名 |
| `api_key_default` | `None` | キーが見つからないときに使う仮のキー（ローカルサーバー向け） |
| `api_key_required` | `True` | `False` ならキーがなくても `llm()` を作れる。キーがなければ認証ヘッダーは付けない |
| `auth_header` / `auth_scheme` | `"Authorization"` / `"Bearer"` | 認証ヘッダーの名前とスキーム。`auth_scheme=""` ならキーだけを値にする。`api_format="anthropic"` では `"x-api-key"` / スキームなし |
| `headers` | `None` | 固定で付けるヘッダー（dict）。呼び出し側の `headers=` が上書きする。認証ヘッダーは固定ヘッダーより優先 |
| `max_tokens_field` | `"max_tokens"` | `max_tokens` を送るときのフィールド名（`"openai"` 形式のみ。例: `"max_completion_tokens"`） |
| `stream_include_usage` | `False` | ストリームに `stream_options: {"include_usage": true}` を付ける（`"openai"` 形式のみ） |
| `models` | `True` | `False` なら `models()` は `unsupported_models` |
| `aliases` | `()` | 別名。`llm("<別名>:<モデル名>")` でも使える（`claude` と同じ仕組み） |
| `replace` | `False` | `True` なら、**自分で登録した**同じ名前の定義を差し替える |

`api_key_env` も `api_key_default` も指定せず、`api_key_required=True` のままなら、`llm()` の `api_key=` でキーを渡してください。キーがどこにもなければ、`llm()` の生成時に `LLMConfigError`（`code="missing_api_key"`）になります。

## 組み込みと同じように動くもの

登録したプロバイダーは、組み込みと同じ仕組みを通ります。

- `ask()` / `chat()` / `ask_stream()` / `chat_stream()` とその非同期版、`models()` / `amodels()`
- 応答キャッシュ、入出力ログ、[イベント](events-ja.md)、リトライ、`request_id`
- `images=`（`"openai"` 形式は `image_url`、`"anthropic"` 形式は `image` ブロック）、`schema=`（形式ごとに `response_format` または `output_config.format`）
- 生レイヤー（`m.client.request(...)`）。共通インターフェイスが対応していない機能はこちらで使えます

次の点は組み込みと異なります。

- **送らないパラメータの表は適用されません。** [`_model_params.py`](../src/llm_ai_api/_model_params.py) の表は組み込みのモデルだけが対象です。登録したプロバイダーでモデルが拒否するパラメータは、`temperature=` や `extra=` に渡さないでください。唯一の例外が `api_format="anthropic"` の登録で、`anthropic-version` が `2026-10-21` のとき、組み込みの Anthropic と同じく `temperature` / `top_p` / `top_k` を落とします（`anthropic_version=` で別の値を送れば落としません）。
- `transcribe()`（音声の文字起こし）は組み込みの `openai` だけです。登録したプロバイダーでは `unsupported_modality` になります。必要なら生レイヤーの `request()` を使ってください。
- 登録できるのは OpenAI 互換と Anthropic 互換までです。独自のボディ形式や SSE を持つ API には対応していません。そのような API を加えたいときは、Issue を立ててください。

## 名前の衝突と `replace`

| 状況 | 結果 |
|---|---|
| 名前・別名が規則に合わない、`base_url` がない、型が違う、`api_format` が未知、`"anthropic"` 形式に `max_tokens_field` / `stream_include_usage` を指定した | `LLMConfigError`（`code="invalid_provider"`） |
| 組み込みの名前・別名（`openai`、`anthropic`、`claude` など）と同じ | `LLMConfigError`（`code="provider_exists"`）。**`replace=True` でも上書きできません** |
| 自分で登録した名前と同じ（`replace=False`） | `LLMConfigError`（`code="provider_exists"`） |
| 自分で登録した名前と同じ（`replace=True`） | 定義を差し替える。古い別名は消える |
| 他の登録の名前・別名と同じ | `LLMConfigError`（`code="provider_exists"`）。`replace=True` でも奪えません |

組み込みの接続先を変えたいだけなら、`OPENAI_BASE_URL` などの環境変数か、`llm()` の `base_url=` を使ってください。

差し替えても、すでに作った `LLM` は作ったときの定義を使い続けます。

## 認証について

扱えるのは「ヘッダー名 + スキーム + キー」の形だけです（Bearer、`x-api-key`、Azure の `api-key` など）。クエリパラメータにキーを載せる方式（URL 経由でログや例外に漏れやすい）、署名（SigV4 など）、OAuth のトークン更新は対象外です。必要なときは、短期のトークンを `headers=` に渡すか、対応するゲートウェイ経由にしてください。

## 注意点

- `base_url` のスキームやホストに制限はありません。平文 HTTP の外部ホストにも API キーと本文を送るので、信頼できる値だけを渡し、利用者の入力をそのまま渡さないでください（[README のセキュリティ上の注意](../README-ja.md#セキュリティ上の注意)）。ホスト型の API では HTTPS を使ってください。
- エラーメッセージには `base_url` を出しません。`repr()` に出る `base_url` は、組み込みと同じく userinfo をマスクします。
- 実行できるサンプル: [`examples/register_provider.py`](../examples/register_provider.py)
