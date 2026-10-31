# 設定リファレンス

English: [config.md](config.md)

`llm()` に渡せる設定の一覧です。生成時のリクエストの既定値（`system` / `max_tokens` / `temperature` / `extra`）は、[チュートリアル](tutorial-ja.md) の「6. 条件を指定する」を参照してください。

```python
from llm_ai_api import llm

m = llm(
    "openai:gpt-6-luna",       # "<プロバイダー>:<モデル名>"
    api_key=None,              # None なら環境変数
    base_url=None,             # None なら環境変数、なければ既定値
    timeout=600.0,             # 秒
    max_retries=2,
    retry_read_timeout=False,
    retry_after_max=60.0,      # 秒
    headers=None,              # 追加ヘッダー（dict）
    lang=None,                 # エラーメッセージの言語（"ja" / "en"）
    # cache=..., log=...      # 未指定ならグローバル設定に従う
)
```

## 設定の一覧

| 引数 | 既定値 | 内容 |
|---|---|---|
| 第 1 引数 | （必須） | `"<プロバイダー>:<モデル名>"`。最初の `:` で分割するので、モデル名に `:` や `/` を含んでもかまいません（例: `"openrouter:meta-llama/llama-4:free"`）。 |
| `api_key` | 環境変数 | `OPENAI_API_KEY` / `OPENROUTER_API_KEY` / `ANTHROPIC_API_KEY` / `GEMINI_API_KEY`（なければ `GOOGLE_API_KEY`）。見つからなければ `llm()` の時点で `LLMConfigError` になります。 |
| `base_url` | 環境変数 → 既定値 | `OPENAI_BASE_URL` などで上書きできます。プロキシやゲートウェイを通すときに使います。 |
| `timeout` | `600.0` | 1 回のリクエストのタイムアウト（秒）。接続のタイムアウトは 10 秒です。 |
| `max_retries` | `2` | リトライの回数。`0` でリトライしません。 |
| `retry_read_timeout` | `False` | `True` にすると、読み取りタイムアウトもリトライします（下の「リトライの方針」を参照）。 |
| `retry_after_max` | `60.0` | `retry-after` ヘッダーに従って待つ秒数の上限。0 以上の有限の数を指定します。負の値・NaN・無限大は、クライアントの生成時や `set_config()` で `LLMConfigError`（`code="invalid_option"`）になります。 |
| `headers` | `None` | すべてのリクエストに付ける追加ヘッダー（dict）。 |
| `cache` | グローバル設定 | 応答のローカルキャッシュ。[io_cache-ja.md](io_cache-ja.md) を参照。 |
| `log` | グローバル設定 | 入出力ログ。[io_logs-ja.md](io_logs-ja.md) を参照。 |
| `lang` | 環境から判定 | エラーメッセージの言語（`"ja"` / `"en"`）。 |

プロバイダー固有の設定もあります。Anthropic は `anthropic_version`（既定 `"2026-10-21"`）、OpenRouter は `app_url`（`HTTP-Referer` として送信）と `app_name`（`X-Title` として送信）を受け取ります。

## リトライの方針

| 失敗の種類 | 既定 | `retry_read_timeout=True` |
|---|---|---|
| 接続の失敗（接続できない、接続タイムアウト、接続プールの待ちタイムアウト） | リトライする | リトライする |
| HTTP 408 / 409 / 429 / 5xx | リトライする（`retry-after` があれば従う） | リトライする |
| 読み取りタイムアウト | リトライしない | リトライする |
| その他の通信エラー（送信・受信中の切断、プロトコルエラーなど） | リトライしない | リトライしない |

リトライしなかった通信エラーは、すぐに `APITimeoutError`（タイムアウト）または `APIConnectionError` になります。待ち時間は指数バックオフ（0.5 秒から、上限 8 秒）です。リトライする直前には `retry` イベントが、リトライせず失敗するときには `connection_error` または `http_error` イベントが届きます（[イベント](events-ja.md)）。

接続の段階で失敗したリクエストは、サーバーに届いていないので、もう一度送っても安全です。一方、生成のリクエストは冪等ではありません。送信した後の失敗では、サーバーがすでに処理を始めている可能性があり、リトライすると同じ生成が二重に行われることがあります。このため、既定では接続段階の失敗だけをリトライします。

### 生成後に変更する

`set_config()` で、`llm()` の後からリトライの設定を変えられます。渡した引数だけが変わります。

```python
m = llm("openai:gpt-6-luna")
m.set_config(max_retries=0)                        # リトライしない
m.set_config(retry_read_timeout=True, retry_after_max=10)
```

非同期（`aask()` など）にも反映されます。

## 本番環境での設定

- 既定のリトライは、接続段階の失敗と、サーバーが返した 408 / 409 / 429 / 5xx だけが対象です。
- 応答の速さが大事なサービスでは、`max_retries=0` や短い `timeout` を検討してください。既定の `timeout=600` は長い生成のための値で、リトライと合わせると 1 回の呼び出しが長く止まることがあります。リトライは、アプリ側で状況に合わせて行うほうが制御しやすくなります。
- `retry_read_timeout=True` は、二重課金になることがあります。読み取りタイムアウトの時点で、サーバーはすでに生成を始めているかもしれないためです。リトライのたびに料金とサーバーの処理時間がかかることを理解したうえで使ってください。
- `Retry-After` は秒数または HTTP 日時を受け付け、同期・非同期とも `retry_after_max` で上限を設けます。不正な値、NaN、無限大、負の秒数、過去の日時は無視し、通常のバックオフを使います。

非ストリーミング応答と HTTP エラー応答（ストリーム開始時を含む）は、解凍後の本文を 64 MiB に制限します。超過時は `LLMError`（コード `response_too_large`）を送出します。`Content-Length` が上限を超える場合は読み取り前に拒否します。個々の解凍済みチャンクや JSON の解析には追加メモリが必要で、ストリーム全体のサイズには上限がありません。

SSE の各行は解凍後のバイト数と UTF-8 換算の両方で 16 MiB に制限し、読み取り中にも検査します。各イベントは event 名と連結した data の UTF-8 合計（data 行間の改行を含む）を 16 MiB に制限します。超過時はレスポンスを閉じ、`LLMError`（コード `response_too_large`）を送出し、`request_error` を通知します。生ストリームにも適用します。

ヘッダー名の大文字・小文字は区別しません。既定値、認証、クライアントの `headers`、リクエストごとの `headers` の順に上書きし、同じ dict 内では最後の値を使います。OpenRouter では `headers` が `app_url` と `app_name` より優先されます。Anthropic のパラメーター除去は実際に送るバージョンを使います。
