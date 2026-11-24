# API リファレンス

`llm_ai_api` の公開 API の一覧です。使い方は [チュートリアル](tutorial-ja.md)、設定値の詳細は [設定リファレンス](config-ja.md) を参照してください。

## クライアントの生成

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
```

`llm(spec, **options)` は `LLM` インスタンスを返します。`spec` は `"<プロバイダー>:<モデル名>"`（`openai` / `openrouter` / `anthropic`（別名 `claude`） / `google` / `grok` / `muse` / `lmstudio` / `ollama` / `strata`）です。`lmstudio` / `ollama` / `strata` はローカルサーバー向けで、API キーは任意です。`LLM(spec, ...)` と直接生成することもできます。

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

質問と応答のメソッドには、呼び出し単位で上書きできるキーワード引数 `system` / `max_tokens` / `temperature` / `extra`（生成時の値を上書き）と `timeout`（この呼び出しだけのタイムアウト、秒）があります。指定しない場合は生成時の値が使われます。

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

### モデル一覧

`models(*, raw=False, timeout=None)` と `await amodels(*, raw=False, timeout=None)` は、プロバイダーの順序でモデル ID の文字列を返します。`raw=True` では全ページのモデル辞書を無加工で返します。`timeout` は秒単位で、`None` ならクライアントの設定を使います。この呼び出しはキャッシュや入出力ログの対象外です。

OpenAI 互換プロバイダー（OpenRouter、Grok、Muse、LM Studio、Ollama、Strata を含む）は設定済みのベース URL の `/models`、Anthropic は `/v1/models` を使います。Google はベース URL が `/openai` で終わる場合に隣接するネイティブの `/models` を使い、それ以外は OpenAI 互換の `/models` を使います。OpenRouter の生成と一覧取得に API キーは不要です。設定されたキーは送信され、キーなしのチャットはリクエスト時にプロバイダーの HTTP エラーになります。

### 後片付けと設定

| メソッド | 説明 |
|---|---|
| `close()` | 同期クライアントを閉じる。再利用はできない |
| `aclose()` | 非同期クライアント（生成済みの場合）と同期クライアントの両方を閉じる |
| `set_config(max_retries=, retry_read_timeout=, retry_after_max=)` | 生成後に再送方針だけを変更する。渡した項目だけが変わる |
| `add_event_listener(event, listener)` | イベントリスナーを登録する（`event=None` で全イベント） |
| `remove_event_listener(event, listener)` | 登録したリスナーを外す |

`LLM` は `with` / `async with` にも対応します（終了時に `close()` / `aclose()` が呼ばれます）。イベントの種類と payload は [イベント](events-ja.md) を参照してください。

## アプリのテスト

`LLM` インスタンスを受け取るアプリをテストするとき、各社の JSON や SSE を組み立てる必要はなく、`transport=` も不要です。アプリが実際に呼ぶメソッドだけを `typing.Protocol` として定義し、決まった `str`、`ChatResult`、ストリーム、ライブラリの例外を返すスタブを渡します。標準ライブラリだけで書け、ネットワークも API キーも要りません。

次の例は `ask()` だけを使う関数のテストです。`chat()` や `ask_stream()` も使う場合は、プロトコルに合わせてください。

```python
from typing import Any, Protocol

from llm_ai_api.types import ChatResult


class AppLLM(Protocol):
    def ask(self, prompt: str | list[dict], **kwargs: Any) -> str: ...


class ScriptedLLM:
    def __init__(self, replies: list[str | ChatResult | BaseException]):
        self._replies = list(replies)

    def ask(self, prompt: str | list[dict], **kwargs: Any) -> str:
        if not self._replies:
            raise AssertionError("no scripted replies left")
        item = self._replies.pop(0)
        if isinstance(item, BaseException):
            raise item
        if isinstance(item, ChatResult):
            return item.text
        return item


def summarize(client: AppLLM, text: str) -> str:
    return client.ask("Summarize:\n" + text)
```

ユニットテストでは `ScriptedLLM(["a short summary"])` を渡し、`summarize(client, "a long article")` がその文字列を返すことを確認できます。エラー分岐を試すときは、`RateLimitError("slow down", status_code=429)` のようなライブラリ例外を脚本に入れてください。

非同期のアプリコードでは、プロトコルに `async def aask(...)`（必要なら `achat` / `aask_stream`）を定義し、コルーチンを返すスタブを使います。ストリームのスタブは文字列を返す小さなイテレータ（または非同期イテレータ）にし、公開されているストリームと同様に `request_id` と `retries` を属性として持たせられます。

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

`OpenAIClient` / `OpenRouterClient` / `AnthropicClient` / `GoogleClient` / `GrokClient` / `MuseClient` / `LMStudioClient` / `OllamaClient` / `StrataClient` を直接使う層です。共通インターフェイスで対応していない機能（ツール呼び出し、画像入力など）は、こちらの `request()` で生の JSON を送って使えます。

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
| `PermissionDeniedError` | 403（クレジット・課金不足は除く。`InsufficientCreditsError` を参照） |
| `NotFoundError` | 404 |
| `RateLimitError` | 429（クォータ不足は除く。`InsufficientCreditsError` を参照） |
| `InsufficientCreditsError` | クレジット・課金・クォータ不足。HTTP 402、4xx の機械可読な課金・支出・クォータのコード、OpenRouter の予算系 403、xAI の 403 `permission-denied` で本文が credit(s) の不足を示すもの、Anthropic のクレジット残高不足など文書にある文言。これらはリトライしません。通常の 400 / 403 / 429（Google の 429 `RESOURCE_EXHAUSTED` を含む）と 5xx は対象外です。 |
| `InternalServerError` | 5xx |
| `APIStreamError` | ストリーミング中のエラー（`provider` / `request_id` 属性付き） |
| `StructuredOutputError` | `schema=` の構造化出力が拒否・未完了・検証失敗になった（`result` に元の `ChatResult`） |

`InsufficientCreditsError` に含めるものと、含めないものは次のとおりです。判定に使うコードは、`error.code` / `error.type` / `error.status` と、Anthropic の `error.details.error_code` です（`_` と `-` は同一視します）。

- HTTP 402 は本文にかかわらず対象です。Meta の `billing_error`、OpenRouter のクレジット不足、Google の前払いクレジット枯渇（本文の `status` が `RESOURCE_EXHAUSTED` でも HTTP ステータスは 402）、Anthropic の `billing_error` がここに入ります。OpenRouter の in-flight 予算も 402 なので同じ扱いで、自動ではリトライしません。
- コードで区別できるものは対象です。OpenAI の `insufficient_quota`、`credit_balance_exhausted`、`organization_spend_limit_exceeded`、`project_spend_limit_exceeded`、`organization_usage_limit_exceeded`。Anthropic の月間支出上限 `enforced_spend_limit_reached`（`rate_limit_error` だけでは判定しません）。Google Interactions API の `quota_exceeded` と `payment_required`。Meta の `billing_not_configured`。
- OpenRouter の 403 は、`error.metadata.limit_source` が `openrouter_guardrail_budget`、`openrouter_workspace_budget`、`openrouter_key_limit` のときだけ対象です。コンテンツフィルタなど、それ以外の 403 は `PermissionDeniedError` のままです。
- xAI の 403 は、コードが `permission-denied` で、本文に単語としての credit / credits と、残高不足を示す表現（no、insufficient、depleted、exhausted、out of、used all、残高 0 など）の両方があるときだけ対象です。公式のデバッグ文書はクレジット不足用の別コードを公開していないため、この組み合わせで見ます。コードだけ、または credit-based billing にアクセスできないという通常の権限エラーは対象外です。
- Anthropic のクレジット残高不足（`Your credit balance is too low...`）と、利用者が設定した支出上限（`You have reached your specified API usage limits` / `... workspace API usage limits`）は、タイプが通常の 400 `invalid_request_error` と同じです。HTTP 400、`invalid_request_error`、文書にあるメッセージ先頭のすべてが一致するときだけ対象にします。

次は対象にしません。一時的な 429（OpenAI の `slow_down` や `rate_limit_exceeded`、Google Interactions API の `rate_limit_exceeded` と `too_many_requests`、Anthropic の支出上限コードが無い `rate_limit_error`）と、通常の 403 です。Google の OpenAI 互換エンドポイントが返す 429 `RESOURCE_EXHAUSTED` は、短時間のレート制限でも、待ってリトライする支出ペースの制限でも同じステータスで、本文だけでは区別できないため `RateLimitError` のままリトライします。`failed_precondition` も、課金停止はその説明の一例にすぎないため対象にしません。
