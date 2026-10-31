# チュートリアル

English: [tutorial.md](tutorial.md)

`llm-ai-api` を使って、AI に質問するところから、会話・ストリーミング・非同期・エラー処理までを順に試します。

## 1. インストールと API キーの準備

```sh
pip install llm-ai-api
```

Python 3.9 以上が必要です。依存は `httpx` だけです。インポート名は `llm_ai_api` です。

API キーは環境変数で渡します。使うプロバイダーのものだけ設定してください。

| プロバイダー | 環境変数 |
|---|---|
| `openai` | `OPENAI_API_KEY` |
| `openrouter` | `OPENROUTER_API_KEY` |
| `anthropic`（別名 `claude`） | `ANTHROPIC_API_KEY` |
| `google` | `GEMINI_API_KEY`（なければ `GOOGLE_API_KEY`） |

```sh
export OPENAI_API_KEY="sk-..."
```

`llm(..., api_key="...")` で直接渡すこともできますが、キーをコードに書かないために環境変数を使うことをおすすめします。

## 2. 最初の質問

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna")
print(m.ask("可愛い犬の名前を考えて"))
```

モデルは `"<プロバイダー>:<モデル名>"` で指定します。`ask()` は回答のテキスト（`str`）だけを返します。

API キーが見つからないと、`llm()` を呼んだ時点でエラーになります。

## 3. モデルを変える

文字列を変えるだけで、他のプロバイダーのモデルを同じ書き方で使えます。

```python
from llm_ai_api import llm

m = llm("anthropic:claude-opus-5-5")
print(m.ask("可愛い犬の名前を考えて"))
```

この例には `ANTHROPIC_API_KEY` が必要です（OpenAI の `OPENAI_API_KEY` とは別に設定します）。

代表的なモデルは `models` の定数でも指定できます。中身は `"<プロバイダー>:<モデル名>"` の文字列です。

```python
from llm_ai_api import llm, models

print(models.OPENAI_GPT6_LUNA)  # openai:gpt-6-luna

m = llm(models.GOOGLE_GEMINI_4_ARGON)
print(m.ask("可愛い犬の名前を考えて"))
```

この例には `GEMINI_API_KEY`（または `GOOGLE_API_KEY`）が必要です。

定数は例です。載っていないモデルも、`llm("openai:新しいモデル名")` のように文字列でそのまま指定できます。使えるモデル ID は、各プロバイダーのモデル一覧で確認してください。

## 4. 会話を続ける

`ask()` は会話の履歴を保持しません。続きを聞くときは `ask()` / `stream()` / `chat()` に履歴（messages）を渡します。`chat()` は `ChatResult` を返します。リストは空でなく、要素がすべて辞書である必要があります。そうでない場合は `LLMConfigError`（code `invalid_messages`）が発生します。

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna")

messages = [{"role": "user", "content": "好きな果物を1つ挙げて"}]
result = m.chat(messages)
print(result.text)

# ask() にも同じ履歴を渡せる（戻り値は回答テキストのみ）
print(m.ask(messages))

# 応答を履歴に追加して、続きを聞く
messages.append({"role": "assistant", "content": result.text})
messages.append({"role": "user", "content": "それはどんな味？"})
result = m.chat(messages)
print(result.text)

print(result.model, result.stop_reason, result.usage)
```

`ChatResult` には次のフィールドがあります。

| フィールド | 内容 |
|---|---|
| `text` | 回答のテキスト |
| `model` | 応答したモデル名 |
| `stop_reason` | 終了理由（API が返した値のまま） |
| `usage` | `input_tokens` と `output_tokens`（取得できなければ `None`） |
| `raw` | API が返した JSON（dict）全体 |
| `request_id` | `x-request-id` または `request-id`（無ければ `None`） |
| `latency` | 呼び出し開始からボディ読了までの秒（リトライの待ちを含む） |
| `retries` | その応答の前に行ったリトライ回数（最初で成功すれば 0） |

`ask()` の戻り値はテキストだけです。`request_id` を見るときは `chat()` を使います。

## 5. ストリーミング

`stream()` は、生成されたテキストを少しずつ返します。

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna")

stream = m.stream("短い物語を書いて")
print(stream.request_id)  # 呼び出しが返った時点で入っている

for piece in stream:
    print(piece, end="", flush=True)
print()
```

### チャットアプリで履歴を使ってストリーミングする

履歴全体を `stream()` に渡し、各パーツを表示してから、集めた回答を assistant の履歴に追加します。イテレーターには `stream()` が返った時点で `request_id` が設定されています。

```python
from llm_ai_api import llm

with llm("openai:gpt-6-luna") as m:
    history = []
    history.append({"role": "user", "content": "短い物語を書いて"})
    stream = m.stream(history)
    print("request_id:", stream.request_id)
    pieces = []
    for piece in stream:
        print(piece, end="", flush=True)
        pieces.append(piece)
    history.append({"role": "assistant", "content": "".join(pieces)})
```

## 6. 条件を指定する

`system`（システムプロンプト）、`max_tokens`、`temperature`、`extra` を `llm()` の既定値として、または呼び出しごとに指定できます。

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna", system="あなたは簡潔に答えるアシスタントです。")

print(m.ask("日本の首都は？"))

# 呼び出しごとの指定は、既定値より優先される
print(m.ask("日本の首都は？", system="関西弁で答えてください。", max_tokens=200))
```

- 指定していないパラメータは API に送りません。新しいモデルは、デフォルト値の `temperature` などでも拒否することがあるためです。必要なときだけ指定してください。
- 公式仕様で拒否されると確認したパラメータは、明示しても `extra` で渡しても送りません。表にないモデルとパラメータ、および OpenRouter と Google はそのまま送ります。落とすキーをそのまま送りたいときは `m.client.request(path, body)` を使います。
- Claude の `max_tokens` は API の必須項目です。未指定のときはライブラリが 16000 を補います。送る API バージョンが `2026-10-21`（既定）のときは `temperature` / `top_p` / `top_k` を送りません。別のバージョンでは、指定した値を送ります。`headers` の `anthropic-version` は `anthropic_version=` を上書きします。
- ここにないパラメータは `extra={...}` で渡せます（拒否表に載っていないキーは、リクエストボディの最後にマージされます）。
- 呼び出しごとに `None` を渡すと、その呼び出しだけ `llm()` の既定値を使いません（例: `m.ask("q", temperature=None)`）。

## 7. 非同期で使う

メソッド名の先頭に `a` を付けると、`asyncio` で使えます（`aask()` / `achat()` / `astream()`）。
`aask()` と `astream()` にも、同期版と同じ空でないメッセージ履歴を渡せます。

```python
import asyncio
from llm_ai_api import llm


async def main():
    async with llm("openai:gpt-6-luna") as m:
        print(await m.aask("可愛い犬の名前を考えて"))

        async for piece in m.astream("短い物語を書いて"):  # await は付けない
            print(piece, end="", flush=True)
        print()

        # 同じ LLM で並行に呼び出せる
        answers = await asyncio.gather(m.aask("犬の名前を1つ"), m.aask("猫の名前を1つ"))
        print(answers)


asyncio.run(main())
```

- `async with`（または `await m.aclose()`）で閉じます。閉じた `LLM` は再利用できません。
- `asyncio.run()` のたびに新しい `llm()` を作ってください。
- 非同期コードの中で同期版の `ask()` / `chat()` / `stream()` を呼ぶと、イベントループ全体が止まります。必ず `aask()` / `achat()` / `astream()` を使ってください。

## 8. エラーを処理する

すべての例外は `LLMError` の派生です。HTTP エラー（4xx / 5xx）は `APIStatusError` で、`status_code` と `body` を持ちます。

```python
from llm_ai_api import llm, LLMError, APIStatusError

try:
    m = llm("openai:gpt-6-luna")
    print(m.ask("こんにちは"))
except APIStatusError as e:
    print("HTTP エラー:", e.status_code, e.body)
except LLMError as e:
    print("エラー:", e.code, e)
```

`APIStatusError` は `LLMError` の派生なので、先に書いてください。

すべての例外は、言語に依存しない `code` 属性（例: `"missing_api_key"`）を持っています。エラーの判定には、翻訳で変わるメッセージの文面ではなく `code` を使ってください。

失敗したリクエストは、最大 `max_retries` 回（既定 2 回）自動でリトライされます。対象は、接続段階の失敗（サーバーに届いていないもの）と、HTTP 408 / 409 / 429 / 5xx だけです。読み取りタイムアウトなど、送信した後の失敗はリトライしません（生成が二重に行われ、二重に課金されるのを防ぐため）。応答の速さが大事なサービスでは、`llm(..., max_retries=0)` や短い `timeout` を検討してください。詳しくは [設定リファレンス](config-ja.md) を参照してください。

接続失敗（`APIConnectionError` / `APITimeoutError`）とストリーム途中のエラー（`APIStreamError`）にも、`provider` と `request_id` があります。ヘッダーが届く前の接続失敗では `request_id` は `None` です。`retries` と `latency`（秒）も付きます。HTTP エラー（`APIStatusError`）にも `retries` と `latency` が付きます。

リトライや失敗は入出力ログには残りません。`add_event_listener` で受け取ります。リスナーが例外を出しても、そのリクエストは続行します。`None` を渡すとすべてのイベントを受け取ります。

```python
m.add_event_listener("retry", lambda event, payload: print(event, payload.get("request_id")))
```

イベント名、payload のキー、`request_id` の参照先は、[イベント](events-ja.md) を参照してください。

## 9. 使い回しと後片付け

`llm()` は接続プールを持つ HTTP クライアントを作ります。リクエストごとに作り直すと、接続や TLS ハンドシェイクが繰り返されます。プロセスやサービスの起動時に 1 つ作り、使い回してください。キャッシュや接続の再利用も有効になります。

同期版では、`with` を使うか、使い終わったら `close()` を呼びます。

```python
from llm_ai_api import llm

with llm("openai:gpt-6-luna") as m:
    print(m.ask("こんにちは"))

# または、アプリケーション終了時に閉じる
m = llm("openai:gpt-6-luna")
try:
    print(m.ask("こんにちは"))
finally:
    m.close()
```

非同期版では、`async with` を使うか、`await aclose()` を呼びます。`aclose()` は非同期・同期の両方のクライアントを閉じ、複数回呼んでも安全です。`close()` が閉じるのは同期クライアントだけです。

```python
import asyncio
from llm_ai_api import llm


async def main():
    async with llm("openai:gpt-6-luna") as m:
        print(await m.aask("こんにちは"))

    # または、アプリケーション終了時に閉じる
    m = llm("openai:gpt-6-luna")
    try:
        print(await m.aask("こんにちは"))
    finally:
        await m.aclose()


asyncio.run(main())
```

ストリームを途中で止めても問題ありません。ストリームオブジェクトが破棄または閉じられると、内部のレスポンスも閉じられます。長時間動くプログラムでは、早期終了する場合に `stream.close()` または `await stream.aclose()` を明示的に呼ぶと確実です。

閉じ忘れても、プロセス終了時やガベージコレクション時にはリソースが解放されます。ただし、長時間動くプロセスでは接続やファイルディスクリプタが残るため、明示的に閉じてください。閉じた `LLM` は再利用できません。新しく作り直してください。たとえば、`asyncio.run()` を呼ぶごとに新しい `llm()` を作ります。

本番環境で同時接続数やプロキシ、TLS を変えたいときは、README の「接続設定」（`set_connection()` と `connection=`）を参照してください。

## 10. 次のステップ

- [イベント](events-ja.md): `add_event_listener`、イベントの一覧、`request_id` の参照先です。
- [設定リファレンス](config-ja.md): `llm()` の設定とリトライの方針です。
- [応答のローカルキャッシュ](io_cache-ja.md): 同じリクエストでは API を呼ばず、保存済みの結果を返します（既定はオフ）。
- [入出力ログ](io_logs-ja.md): 入力と出力を JSON Lines で記録します（既定はオフ）。
- [プロンプトキャッシュ](cache-ja.md): プロバイダー側のキャッシュの使い方です。
- 生レイヤー: `m.client.request(path, body)` で、任意のエンドポイントに dict を送れます。
- [`examples/`](../examples/) ディレクトリ: 画像入力や履歴を使ったサンプルなどがあります。
