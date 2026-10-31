# 入出力ログ

English: [io_logs.md](io_logs.md)

チャット呼び出しの入力と出力を、JSON Lines 形式（1 行に 1 つの JSON）でファイルに記録します。プロンプトと回答の確認、デバッグ、利用状況の記録に使えます。デフォルトではオフです。

## 有効にする

```sh
# 1. 環境変数（<dir>/llm.jsonl に書き込む）
export LLM_AI_API_LOG_DIR=./.llm_log
```

```python
from llm_ai_api import llm, set_log

# 2. プロセス全体（環境変数より優先。set_log(None) で明示的にオフ）
set_log("./llm_log.jsonl")

# 3. インスタンスごと（グローバル設定より優先）
m = llm("openai:gpt-6-luna", log="./llm_log.jsonl")   # True なら既定の llm_ai_api_log.jsonl
off = llm("openai:gpt-6-luna", log=False)              # このインスタンスだけオフ

m.ask("可愛い犬の名前を考えて")
```

`get_log()` はプロセス全体のログオブジェクトを返します（オフなら `None`）。

## 記録される内容

`ask()` / `chat()` / `stream()` / `stream_chat()` の呼び出しごとに 1 行を追記します。生レイヤー（`request()` / `request_stream()`）は記録しません。

| フィールド | 意味 |
|---|---|
| `time` | UTC の時刻（ISO 8601） |
| `provider` | `openai`、`anthropic` など |
| `model` | リクエストで送ったモデル |
| `stream` | `stream()` / `stream_chat()` なら `true` |
| `cached` | 応答キャッシュ（[io_cache-ja.md](io_cache-ja.md)）から返したなら `true` |
| `request` | 送ったリクエストボディ（モデルが拒否するパラメータを落としたあと） |
| `response` | 生の応答 dict。ストリームは `{"text": "連結したテキスト", "chunks": [生のイベント JSON, ...]}` |

例（見やすく整形しています。実際のファイルは 1 行に 1 オブジェクトです）:

```json
{
  "time": "2026-10-31T01:23:45.678901+00:00",
  "provider": "openai",
  "model": "gpt-6-luna",
  "stream": false,
  "cached": false,
  "request": {"model": "gpt-6-luna", "messages": [{"role": "user", "content": "可愛い犬の名前を考えて"}]},
  "response": {"choices": [{"message": {"content": "ポチ"}, "finish_reason": "stop"}]}
}
```

```python
import json

with open("llm_log.jsonl", encoding="utf-8") as f:
    for line in f:
        record = json.loads(line)
        print(record["time"], record["model"])
```

## 記録内容の加工

既定ではリクエストボディと生の応答全体を平文で保存します。messages、追加フィールド、ストリームのチャンクに含まれる個人情報や秘密情報も対象です。ファイルを保護し、保存内容を選んでください。

```python
from llm_ai_api import JSONLLog, llm

def redact(record):
    record.pop("request", None)
    record.pop("response", None)
    return record

m = llm("openai:gpt-6-luna", log=JSONLLog("./llm_log.jsonl", redact=redact))
```

フックには記録全体の深いコピーが渡され、保存する dict を返します。`None` なら記録を省略します。ストリームのチャンクを含むすべての該当フィールドから機密情報を除去してください。コピー、フック、JSON 化の失敗時はその記録を保存せず、API の結果は返します。非同期呼び出しではワーカースレッドで実行されるため、フックはスレッドセーフにしてください。リクエスト、応答、別途設定する応答キャッシュや既存のログ行は変更しません。

## 最大サイズ

```python
from llm_ai_api import JSONLLog, llm, set_log

set_log("./llm_log.jsonl", max_size=50 * 1024 * 1024)   # 50 MB（パスや True から作るとき）
set_log("./llm_log.jsonl", max_size=None)                # 無制限
m = llm("openai:gpt-6-luna", log=JSONLLog("./llm_log.jsonl", max_size=10_000_000))
```

- `max_size`（バイト）の既定値は **100 MB** です（`llm_ai_api.log.DEFAULT_MAX_SIZE`）。パスや `True` を渡したときと、環境変数 `LLM_AI_API_LOG_DIR` では、この既定値になります。
- 1 行を追記するたびにファイルサイズを調べ、`max_size` を超えていたら、先頭（古いほう）の 1/3 の行を捨てて、残りを書き直します。まだ `max_size` を超えている場合は、次の書き込みでもう一度削除します。最後に書いた 1 行は、それだけで `max_size` を超えていても必ず残ります。
- 同じプロセス内では、正規化後に同じパスとなるログインスタンスがロックを共有し、追記と整理を直列化します。整理用の一時ファイルには一意の名前を使います。複数の**プロセス**が同じログファイルに書き込む場合、削除中の動作は完全にはサポートされません。読み込んでから書き換えるまでの間にファイルが変化していたら、その削除は中止され（次の書き込みでやり直します）、最後の置き換えの直前のごくわずかな間に別プロセスが追記した行は、失われる可能性があります。すべての行が重要な場合は、プロセスごとに別のログファイルを使ってください。（キャッシュは SQLite 自身のロックを使うため、この注意はログだけに当てはまります。）
- `max_size=None` で無制限（制限なし）になります。0 以下や整数以外は `LLMConfigError`（`code="invalid_log"`）です。
- `set_log()` の `max_size` は、パスや `True` から作るときだけ使われます。`JSONLLog` オブジェクトを渡したときは、そのオブジェクトの `max_size` が優先されます。
- 整理に失敗しても呼び出しは失敗しません（ベストエフォート）。

## 注意

- API キーと認証ヘッダーは記録されません。
- ログは**平文**で、プロンプトと回答がそのまま入ります。ファイルの取り扱いに注意してください。POSIX では開くときと追記前に `0600` に変更し、失敗時は書き込みません。新規の親ディレクトリは `0700` で作成します。他の OS では各 OS のアクセス制御に依存します。
- ストリームは最後まで読み切ったときだけ記録されます。途中で止めたものと、エラーになった呼び出しは記録されません。リトライや失敗を知りたいときは、ログではなく `add_event_listener` を使います（[イベント](events-ja.md)）。
- ログの書き込みに失敗しても無視されるので、料金を払って得た応答が失われることはありません。設定の誤り（不正な値、書き込めないパス）は、クライアントの生成時に `LLMConfigError`（`code="invalid_log"`）になります。
- パスの代わりに自作のオブジェクトを渡せます。`write(provider, model, request, response, *, stream, cached)` を持っていれば使えます。

ストリームのログ用蓄積には、1 ストリームあたり固定の 16 MiB の上限があります（各チャンクとテキストを JSON エンコードした UTF-8 バイト数の合計）。超過すると蓄積を解放し、正常終了時に `response` を `{"text": null, "chunks": null, "truncated": true}` として記録します。配信は続きます。この上限はファイルの `max_size` とは別です。

実行時の書き込み失敗は警告と `log_error` イベントで通知し、`log.failure_count` でクライアント経由の失敗数を確認できます。[イベント](events-ja.md#cache_error--log_error)を参照してください。
