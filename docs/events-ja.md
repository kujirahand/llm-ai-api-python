# イベント

English: [events.md](events.md)

`LLM` またはプロバイダークライアント（`OpenAIClient` など）にリスナーを登録すると、リトライ、失敗、応答ヘッダーの受信を知らせます。入出力ログは成功したチャットだけを残します。リトライと失敗の観測にはリスナーを使います。

以下の payload の `latency` はすべて**秒**（`float`）で、リスナーを呼ぶ前に測ります。リトライで待った時間も含みます。`None` は測っていないときです（キャッシュから再生したストリームのエラーなど）。

## リスナーを登録する

```python
def on_event(event, payload):
    print(event, payload.get("request_id"), payload.get("retries"))

m = llm("openai:gpt-6-luna")

m.add_event_listener("retry", on_event)     # このイベントだけ
m.add_event_listener(None, on_event)        # すべてのイベント
m.remove_event_listener("retry", on_event)  # 登録を 1 件外す
```

```text
add_event_listener(event, listener) -> None
remove_event_listener(event, listener) -> None
```

- 呼び出しは `listener(event, payload)` です。`event` はイベント名の文字列、`payload` は呼び出しごとに新しい普通の `dict` です。
- `event=None` はすべてのイベントに登録します。その登録を外すときも `None` を渡します。名前を指定した登録とは別のエントリです。
- 同じ関数は複数回登録できます。登録した順に、登録の数だけ呼ばれます。`remove_event_listener` は一致するものを 1 件だけ外します（`is` による同一性）。登録されていないリスナーを外してもエラーにはなりません。
- 未知のイベント名は、登録時も削除時も `LLMConfigError`（`code="invalid_event"`）です。呼び出し可能でないリスナーは `LLMConfigError`（`code="invalid_listener"`）です。
- リスナーが `Exception` を出しても、その例外は捨てます。リクエストは続き、リトライは変わらず、後続のリスナーも呼ばれます。`BaseException`（`KeyboardInterrupt` や `asyncio.CancelledError` など）は捕まえません。
- `m.add_event_listener` と `m.client.add_event_listener` は同じリストです。最初の `aask` / `achat` / `astream` で作る非同期クライアントもそのリストを使います。同期と非同期の呼び出しは、同じリスナーに知らせます。
- リスナーは同期関数です。非同期の経路でもイベントループのスレッドから呼ぶので、長くブロックしないでください。
- プロバイダークライアント（`OpenAIClient` など）も同じ 2 つのメソッドを持ちます。自分で作ったクライアントは、別のリストを持ちます。

payload に API キー、認証ヘッダー、リクエスト本文、レスポンス本文は入りません。

## `request_id` の参照先

ヘッダーは `x-request-id`（OpenAI 系）または `request-id`（Anthropic）です。どちらも無いとき、およびヘッダーより前に失敗したときは `None` です。

| 場所 | 取れるもの |
|---|---|
| `chat()` / `achat()` の `ChatResult` | `request_id`、`latency`（ボディを読み終わるまでの秒）、`retries` |
| `stream_chat()` の `ChatChunk` | 各チャンクの `request_id`（すべて同じ値） |
| `stream()` / `stream_chat()` / `request_stream()` のイテレータ | 呼び出しが返った時点の `request_id` と `retries` |
| `astream()` のイテレータ | 最初の反復がヘッダーを受け取ったあと、最初のテキストを返す前の `request_id` と `retries`。ヘッダーより前に失敗したときは未設定（`None` / `0`）のまま |
| `APIConnectionError`、`APITimeoutError` | `provider`、`request_id`、`retries`、`latency`。ヘッダーのあとでストリームが切れたときは `request_id` が入る |
| `APIStatusError`（HTTP 4xx / 5xx） | 上に加え `status_code`、`body`、`headers` |
| `APIStreamError` | `provider`、`request_id`、`retries`、`latency`、`body` |
| `request()` | ボディの `dict` だけ。`request_id` は `response` イベントで取る |

`ask()` / `aask()` はテキストだけを返します。`request_id` が必要なときは `chat()` / `achat()` か、リスナーを使います。

`retries` は、この結果の前に行ったリトライの回数です。最初の試行で終われば `0` です。payload の `attempt` は、そのイベントが表す HTTP 試行の 0 始まりの番号です。これらのイベントでは `retries` は `attempt` と同じです。`max_retries=2` を使い切って失敗したとき、最後のエラーの `retries` は `2`（試行は 3 回）です。

キャッシュにヒットしたときは、保存してあった元の呼び出しの `request_id`、`latency`、`retries` を返します。今回測り直した値ではありません。これらのフィールドが無かった頃の行は、`None`、`None`、`0` として読めます。

## イベント

| イベント | いつ |
|---|---|
| `retry` | 失敗した試行をリトライする。待つ前に出る |
| `connection_error` | もうリトライしない通信失敗。ストリームの読み取り中に切れたときも含む |
| `response` | ステータス 400 未満の HTTP 応答を受け入れた |
| `http_error` | もうリトライしない HTTP エラー。リスナーのあとで `APIStatusError` が出る |
| `request_error` | ライブラリがボディを拒否した（`response_too_large` または `invalid_json_response`） |
| `stream_error` | ストリーム途中の error イベント、またはチャットストリームで終端なしの EOF。リスナーのあとで `APIStreamError` が出る |
| `stream_end` | 終端 SSE（`[DONE]` または `message_stop`）のあとで、ライブのストリームを閉じた |
| `cache_error` / `log_error` | キャッシュの検索・保存、またはログの書き込みに失敗。チャットは続行 |
| `cache_hit` | `chat` / `stream_chat`（と非同期版）が保存済みの応答を返した。`response` は出ない |

### `retry`

| キー | 意味 |
|---|---|
| `provider` | `"openai"`、`"anthropic"`、`"openrouter"`、`"google"` |
| `method` | `"POST"` などの HTTP メソッド |
| `path` | リクエストのパス。URL 全体ではない |
| `stream` | この呼び出しがストリームなら `True` |
| `attempt` | いま失敗した試行の、0 始まりの番号 |
| `retries` | その試行より前に済ませたリトライ回数（`attempt` と同じ） |
| `max_retries` | クライアントの上限 |
| `delay` | このリトライで待つ秒（`retry_after_max` を適用したあと） |
| `reason` | 失敗の理由。下表 |
| `status_code` | HTTP ステータス。応答が無いときは `None` |
| `request_id` | 失敗した応答のもの。無ければ `None` |

`reason` の値:

| 値 | とき |
|---|---|
| `status` | HTTP 408 / 409 / 429 / 5xx |
| `connect` | `ConnectError` または `ConnectTimeout` |
| `timeout` | それ以外のタイムアウト（`PoolTimeout` や `WriteTimeout` など） |
| `read_timeout` | `ReadTimeout` |
| `transport` | その他の通信エラー（`ReadError`、`WriteError`、プロトコルエラーなど） |

### `connection_error`

`retry` と同じキーから `max_retries` と `delay` を除き、次が加わります。

| キー | 意味 |
|---|---|
| `latency` | 呼び出しの開始からこの失敗までの秒 |
| `code` | `"timeout"` または `"connection_error"`（例外の `code`） |
| `reason` | `retry` と同じ値。ただし `status` は使わない |

ヘッダーより前の接続失敗では、`status_code` と `request_id` は `None` です。ストリームの読み取り中に切れたときは、その応答の `request_id` と HTTP の `status_code` が残ります。このときの `stream` は `True` です。

### `response`

| キー | 意味 |
|---|---|
| `provider`, `method`, `path`, `stream` | `retry` と同じ |
| `attempt`, `retries` | 成功した試行。`retries` は、その前に行ったリトライ回数 |
| `status_code` | HTTP ステータス（400 未満） |
| `request_id` | 応答ヘッダー。無ければ `None` |
| `latency` | ボディを読み終わるまでの秒。ストリームではヘッダーまでの秒（ボディはまだ開いている） |
| `cached` | 常に `False`。キャッシュヒットは `response` ではなく `cache_hit` |

### `http_error`

`provider`、`method`、`path`、`stream`、`attempt`、`retries`、`status_code`、`request_id`、`latency`。

`latency` は、このエラー応答までの秒です。ボディは payload ではなく `APIStatusError` に入っています。

### `request_error`

`http_error` のキーに `code` が加わります。

| `code` | とき |
|---|---|
| `response_too_large` | ボディ、SSE の 1 行、または 1 イベントがサイズ上限を超えた。受け入れる前に拒否したときは `response` の代わりに出る |
| `invalid_json_response` | ボディまたは SSE の `data` が JSON オブジェクトでない。非ストリームで HTTP が成功したときは、先に `response`、続いてこのイベント |

ストリームをキャッシュから再生しているとき、`method`、`path`、`status_code` は `None` になることがあります。

### `stream_error`

| キー | 意味 |
|---|---|
| `provider` | プロバイダー名 |
| `request_id` | ストリームを開いた応答のもの。無ければ `None` |
| `retries` | その応答の前のリトライ回数 |
| `latency` | error イベントまでの秒。キャッシュの再生では `None` |
| `stream` | `True` |
| `code` | `"stream_error"` または `"stream_incomplete"` |

エラーの本文は payload ではなく `APIStreamError` に入っています。この呼び出しでは `stream_end` は出ません。

### `stream_end`

| キー | 意味 |
|---|---|
| `provider` | プロバイダー名 |
| `request_id` | ストリームを開いた応答のもの |
| `retries` | その応答の前のリトライ回数 |
| `latency` | 呼び出しの開始からストリームを閉じるまでの秒 |
| `stream` | `True` |
| `complete` | `True` |

ライブのストリームを、終端 SSE のあとで閉じたときだけ出ます。途中で止めたもの、終端なしで終わったもの、失敗したものは出ません。完了したキャッシュの再生は `cache_hit` だけで、`stream_end` は出ません。非同期ストリームを `aclose()` せず捨てたときの回収は、レスポンスを閉じるだけで `stream_end` は出しません。

### `cache_hit`

| キー | 意味 |
|---|---|
| `provider` | プロバイダー名 |
| `stream` | キャッシュしたストリームなら `True`、チャットなら `False` |
| `model` | リクエストのモデル名。文字列でなければ `None` |
| `request_id`, `retries`, `latency` | 元の応答と一緒に保存した値 |
| `cached` | `True` |

## 例

```python
from llm_ai_api import llm


def on_event(event, payload):
    if event == "retry":
        print("retry", payload["attempt"], "in", payload["delay"], "s")
    elif event == "response":
        print("id", payload["request_id"], "after", payload["latency"], "s")
    elif event in ("connection_error", "http_error", "stream_error"):
        print(event, payload.get("code"), payload.get("request_id"))


m = llm("openai:gpt-6-luna")
m.add_event_listener(None, on_event)

result = m.chat([{"role": "user", "content": "こんにちは"}])
print(result.request_id, result.retries, result.latency)

stream = m.stream("短い物語を書いて")
print(stream.request_id)  # 呼び出しが返った時点で入っている
for piece in stream:
    print(piece, end="", flush=True)
```

チャットストリームが終端イベントなしで EOF に達すると、受信済みチャンクの後に `code="stream_incomplete"` の `APIStreamError` を送出し、`stream_error` を通知します。不完全なキャッシュの再生にも同じ挙動が適用されます。生の `request_stream()` は SSE をそのまま返します。

### `cache_error` / `log_error`

キャッシュの検索・保存、またはログの書き込みに失敗するとイベントを通知し、`llm_ai_api` ロガーに警告を出します。チャットは続行し、検索失敗はミスとして扱い、保存・書き込み失敗でも応答を返します。payload は `provider`、`operation`（`lookup`、`store`、`write`）、`error_type`（例外クラス名）、`message`（常に `Details omitted`）を含みます。例外メッセージは機密を含む可能性があるため省略します。非同期リスナーはイベントループ上で実行します。

標準の `SQLiteCache` と `JSONLLog` の読み取り専用 `failure_count` は、生成後にクライアント経由で観測した失敗数を同期・非同期で共有して数えます。スレッドセーフで、オブジェクトの直接呼び出しは数えません。カスタムオブジェクトにこの属性は不要で、失敗時は警告とイベントを出します。
