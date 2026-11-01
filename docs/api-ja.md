# API リファレンス

`llm_ai_api` の公開 API の一覧です。使い方は [チュートリアル](tutorial-ja.md)、設定値の詳細は [設定リファレンス](config-ja.md) を参照してください。

## クライアントの生成

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
```

`llm(spec, **options)` は `LLM` インスタンスを返します。`spec` は `"<プロバイダー>:<モデル名>"`（`openai` / `openrouter` / `anthropic`（別名 `claude`） / `google`）です。`LLM(spec, ...)` と直接生成することもできます。

生成時の主なオプション（キーワード引数）:

| オプション | 既定値 | 説明 |
|---|---|---|
| `system` | `None` | 呼び出し共通のシステムプロンプト |
| `max_tokens` | `None` | 呼び出し共通の最大出力トークン数 |
| `temperature` | `None` | 呼び出し共通の温度 |
| `extra` | `None` | 呼び出し共通でリクエストボディへマージする dict |
| `api_key` | 環境変数 | API キー（未指定時はプロバイダーごとの環境変数から読む） |
| `base_url` | プロバイダーの既定 | API のベース URL の上書き |
| `timeout` | `600.0` | タイムアウト（秒）。操作ごとに数え直される |
| `max_retries` | `2` | 再送の回数（[設定リファレンス](config-ja.md) 参照） |
| `retry_read_timeout` | `False` | `True` のとき読み取りタイムアウトも再送する |
| `retry_after_max` | `60.0` | `Retry-After` に従う待機の上限（秒） |
| `headers` | `None` | 追加ヘッダーの dict |
| `cache` | なし | 応答キャッシュ（`set_cache()` の説明を参照） |
| `log` | なし | 入出力ログ（`set_log()` の説明を参照） |
| `connection` | なし | 接続設定の dict（`set_connection()` のキーをインスタンス単位で上書き） |
| `transport` | `None` | テスト等で差し替える httpx トランスポート |
| `lang` | `None` | エラーメッセージの言語（`"ja"` / `"en"`） |

## LLM のメソッド

すべての呼び出しメソッドには、呼び出し単位で上書きできるキーワード引数 `system` / `max_tokens` / `temperature` / `extra`（生成時の値を上書き）と `timeout`（この呼び出しだけのタイムアウト、秒）があります。指定しない場合は生成時の値が使われます。

### 質問と応答

| メソッド | メソッド（async） | 説明 |
|---|---|---|
| `ask(prompt: str \| list[dict])` | `aask(prompt: str \| list[dict])` | 質問または履歴を送り、回答のテキスト（`str`）だけを返す |
| `ask_stream(prompt: str \| list[dict])` | `aask_stream(prompt: str \| list[dict])` | 質問または履歴を送り、回答のテキストを少しずつ（イテレータで）返す |
| `chat(messages)` | `achat(messages)` | 会話履歴を送り、`ChatResult` を返す |
| `chat_stream(messages)` | `achat_stream(messages)` | 会話履歴を送り、回答のテキストを少しずつ（イテレータで）返す |

- `prompt` は文字列または空でない辞書のリストを受け取ります。それ以外は `LLMConfigError(code="invalid_messages")` になります。
- `messages` は `[{"role": "user", "content": "..."}]` 形式のリストです。呼び出し側のリストは変更されません。
- `chat()` / `achat()` には `schema=`（JSON Schema の dict、または pydantic v2 互換のモデルクラス）も渡せます。構造化出力を要求し、読み取り・検証した値が `ChatResult.parsed` に入ります。詳細は [構造化出力](structured-ja.md) を参照してください。
- `transcribe(file, *, extra=None, timeout=None) -> str` / `atranscribe()` は音声（パスまたは `bytes`）を文字起こしして文字列を返します（OpenAI のみ。キャッシュ・ログの対象外）。詳細は [マルチモーダル](multimodal-ja.md) を参照してください。生レイヤーの `request()` は `files=` / `form_data=` で multipart を送れます。
- `ask()` / `ask_stream()` / `aask()` / `aask_stream()` には `images=`（ファイルのパス、`bytes`、http(s) URL のリスト）も渡せます。詳細は [マルチモーダル](multimodal-ja.md) を参照してください。
- 同期のストリームは通常のイテレータ、非同期のストリームは非同期イテレータ（`async for` で使う。`await` は不要）です。ストリームのイテレータには、レスポンスヘッダー受信後に `request_id` と `retries` が設定されます。最後まで読み切るか、同期は `close()`、非同期は `aclose()` を呼ぶと接続が解放されます。
- 旧名 `stream()` / `astream()` は非推奨のエイリアスとして残っています（`ask_stream()` / `aask_stream()` と同じ動作）。新規のコードでは新しい名前を使ってください。

### 後片付けと設定

| メソッド | 説明 |
|---|---|
| `close()` | 同期クライアントを閉じる。再利用はできない |
| `aclose()` | 非同期クライアント（生成済みの場合）と同期クライアントの両方を閉じる |
| `set_config(max_retries=, retry_read_timeout=, retry_after_max=)` | 生成後に再送方針だけを変更する。渡した項目だけが変わる |
| `add_event_listener(event, listener)` | イベントリスナーを登録する（`event=None` で全イベント） |
| `remove_event_listener(event, listener)` | 登録したリスナーを外す |

`LLM` は `with` / `async with` にも対応します（終了時に `close()` / `aclose()` が呼ばれます）。イベントの種類と payload は [イベント](events-ja.md) を参照してください。

## 戻り値の型

### ChatResult

`chat()` / `achat()` の戻り値です。

| フィールド | 型 | 説明 |
|---|---|---|
| `text` | `str` | 回答のテキスト |
| `model` | `str` または `None` | 応答したモデル名 |
| `stop_reason` | `str` または `None` | 終了理由（プロバイダーの値を正規化したもの） |
| `usage` | `Usage` または `None` | `input_tokens` / `output_tokens` |
| `raw` | `dict` | レスポンスの生 JSON |
| `request_id` | `str` または `None` | プロバイダーのリクエスト ID（ヘッダーが無い応答では `None`。キャッシュヒット時は保存されていた値） |
| `latency` | `float` または `None` | 応答までの秒数 |
| `retries` | `int` | 実際に行った再送の回数 |
| `parsed` | 任意 | `schema=` を渡したときの、読み取り・検証済みの構造化出力。それ以外は `None` |

### ChatChunk / SSEEvent / Usage

- `ChatChunk` は低レベル層のストリーミング（`stream_chat()`）が返す断片で、`text` / `raw` / `request_id` を持ちます。
- `SSEEvent` は生レイヤーのストリーミングが返すイベントで、`json()` でボディを dict として取り出せます。
- `Usage` は `input_tokens` / `output_tokens` を持つデータクラスです。

## モジュール関数

| 関数 | 説明 |
|---|---|
| `set_cache(cache=None, *, max_size=...)` / `get_cache()` | 応答キャッシュの全体設定。詳細は [入出力のキャッシュ](io_cache-ja.md) |
| `clear_cache(days=0, cache_dir=None)` | 期限切れのキャッシュを削除し、削除件数を返す |
| `set_log(log=None, *, max_size=...)` / `get_log()` | 入出力ログの全体設定。詳細は [入出力のログ](io_logs-ja.md) |
| `set_connection(*, max_connections, max_keepalive_connections, keepalive_expiry, connect_timeout, verify, cert, proxy)` / `get_connection()` | 接続設定の全体設定（引数なしの呼び出しで既定に戻す置き換え式）。詳細は [設定リファレンス](config-ja.md) |
| `set_language(lang)` / `get_language()` | エラーメッセージの言語（`"ja"` / `"en"`）の全体設定。プロセス全体に効く |

キャッシュのクラスは `SQLiteCache`、ログのクラスは `JSONLLog` です。どちらもコンストラクタでファイルパス等を指定して作り、`llm(..., cache=...)` / `log=...` や `set_cache()` / `set_log()` に渡せます。

## プロバイダークライアント（低レベル層）

`OpenAIClient` / `OpenRouterClient` / `AnthropicClient` / `GoogleClient` を直接使う層です。共通インターフェイスで対応していない機能（ツール呼び出し、画像入力など）は、こちらの `request()` で生の JSON を送って使えます。

| メソッド | 説明 |
|---|---|
| `chat(model, messages, *, max_tokens, temperature, extra, timeout)` | 会話を送り `ChatResult` を返す |
| `stream_chat(model, messages, *, ...)` | 会話を送り `ChatChunk` のイテレータを返す |
| `request(path, body=None, *, method="POST", headers, timeout)` | 任意のエンドポイントへ JSON を送り、応答の dict を返す |
| `request_stream(path, body=None, *, headers, timeout)` | 任意のエンドポイントへ送り `SSEEvent` のイテレータを返す |
| `close()` | クライアントを閉じる |

## モデル名の定数

`llm_ai_api.models` モジュールに、主なモデルの `"<プロバイダー>:<モデル名>"` 定数があります（例: `models.OPENAI_GPT6_LUNA`）。あくまで例としての定数で、表にないモデルも文字列でそのまま指定できます。

## 例外

すべての例外は `LLMError` のサブクラスです。設定の誤りは `LLMConfigError`（`code` 属性で種別が分かります）。

| 例外 | 発生条件 |
|---|---|
| `APIConnectionError` | 接続に失敗した |
| `APITimeoutError` | タイムアウトした |
| `APIStatusError` | HTTP エラー応答（基底クラス） |
| `BadRequestError` | 400 |
| `AuthenticationError` | 401 |
| `PermissionDeniedError` | 403 |
| `NotFoundError` | 404 |
| `RateLimitError` | 429 |
| `InternalServerError` | 5xx |
| `APIStreamError` | ストリーミング中のエラー（`provider` / `request_id` 属性付き） |
| `StructuredOutputError` | `schema=` の構造化出力が拒否・未完了・検証失敗になった（`result` に元の `ChatResult`） |
