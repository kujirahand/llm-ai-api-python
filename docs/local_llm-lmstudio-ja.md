# LM Studio（ローカルの LLM サーバー）を使う

English: [local_llm-lmstudio.md](local_llm-lmstudio.md)

LM Studio は自分のマシンでモデルを動かし、OpenAI 互換の API を提供するアプリです。このページでは、同じマシンから、または LAN 内の別のマシンから `llm-ai-api` で呼び出す方法を説明します。

## 1. まず試す（同じマシン）

```python
from llm_ai_api import llm

m = llm("lmstudio:google/gemma-4-e4b")  # "lmstudio:<モデル名>"
print(m.ask("可愛い犬の名前を考えて"))
```

モデル名は LM Studio が表示する名前です（例: `google/gemma-4-e4b`）。名前に `/` が含まれていても問題ありません。最初の `:` だけがプロバイダーとモデルを区切ります。

何も設定しなければ、`http://localhost:1234/v1` に接続し、API キーとして `lm-studio` を送ります。LM Studio 側で「Require Authentication」を有効にするかぎり（注意点 3）、この値はチェックされません。

### サーバーを起動する

サーバーを起動するまで、LM Studio は API を待ち受けていません。アプリの **Developer** タブでサーバーを起動するか、コマンドラインから:

```sh
lms server start      # ポートを変えるには -p <port>
lms server status     # "The server is running on port 1234."
lms ls                # "lmstudio:<モデル名>" に使う名前の一覧
```

## 2. 設定

| 環境変数 | 意味 | 既定値 |
|---|---|---|
| `LMSTUDIO_BASE_URL` | LM Studio API のベース URL（`/v1` まで含める） | `http://localhost:1234/v1` |
| `LMSTUDIO_API_KEY` | API キー。任意で、「Require Authentication」がオンのときだけ必要 | `lm-studio`（未設定時に送る） |
| `LMSTUDIO_MODEL` | モデル名。`examples/local-llm-lmstudio.py` だけが使う（ライブラリにデフォルトモデルはない） | なし |

引数でも指定できます: `llm("lmstudio:google/gemma-4-e4b", base_url="...", api_key="...")`。

## 3. LAN 越しに接続する

LM Studio は、他の端末を許可するまで自分のマシンだけの接続を受け付けます。アプリのサーバー設定で **Serve on Local Network** をオンにするか、コマンドラインでは `lms server start --bind 0.0.0.0` を使います。

そのうえで、別のマシンで:

```sh
export LMSTUDIO_BASE_URL="http://192.168.1.20:1234/v1"
export LMSTUDIO_API_KEY="<LM Studio の API トークン>"   # 認証がオンのときだけ
export LMSTUDIO_MODEL="google/gemma-4-e4b"
```

```python
import os
from llm_ai_api import llm

m = llm(f"lmstudio:{os.environ['LMSTUDIO_MODEL']}")  # base_url と api_key は環境変数から読まれる
print(m.ask("こんにちは"))
```

付属のサンプルでも試せます:

```sh
python examples/local-llm-lmstudio.py "$LMSTUDIO_MODEL"
```

### 注意点

1. **`LMSTUDIO_BASE_URL` には `/v1` まで含める。** ライブラリがその後ろに `/chat/completions` を付けます。
2. **モデルはダウンロード済みであること。** `lms ls` はディスク上のモデルを並べます（`lms get <モデル>` でダウンロード）。一覧にない名前は、そのサーバーでは動かせません。
3. **API キーには 2 の状態がある。**
   「Require Authentication」がオフ（LM Studio の既定）なら、キーは不要で、ライブラリは仮の値 `lm-studio` を送ります。オン（LM Studio 0.4.0 以降）なら、すべてのリクエストが有効なトークンを持つ必要があります。サーバー設定の **Manage Tokens → Create Token** で作り、コピーし（一度だけ表示される）、`LMSTUDIO_API_KEY` に入れてください。この状態で仮の値を送ると 401 になります。LAN 越しに公開する前に、本物のトークンを設定してください。
4. **`request_id` は無い。** LM Studio は `x-request-id` ヘッダーを送らないので、`ChatResult.request_id` は `None` で、`response` イベントの `request_id` も `None` です。
5. **サーバーのマシンが表示するアドレスを使う。** `192.168.1.20` はプレースホルダーです。ポートが塞がれていないかはファイアウォールを確認します。
6. **API キーは秘密にする。** 本物のキーをリポジトリにコミットしないこと。シェルの設定ファイルや、Git に含めないローカルの `.env` に置きます。

## 4. うまくいかないとき

| 症状 | 確認すること |
|---|---|
| すぐに `APIConnectionError`（`code="connection_error"`） | サーバーが動いていない（`lms server status`）かポートの間違い。LAN 越しなら「Serve on Local Network」（または `--bind 0.0.0.0`）がオンか、ファイアウォールがポートを塞いでいないかを確認する。 |
| API トークンを指摘する 401 `AuthenticationError` | 「Require Authentication」がオン。サーバー設定でトークンを作り、`LMSTUDIO_API_KEY`（または `api_key=`）に設定する。ライブラリ既定の `lm-studio` はトークンではない。 |
| モデル名を指摘するエラー | そのモデルはサーバーに無い。`lms ls` で正確な名前を確認し、`lms get <モデル>` でダウンロードする。 |
| `APITimeoutError` | モデルの読み込み中、またはマシンに届かない。起動が遅いモデルは `timeout=` を大きくする。 |
| ローカルでは動くが LAN 越しだと失敗する | 上の注意点 3（認証）とバインドアドレスを参照。 |

このライブラリを使わずに接続だけ確かめるには:

```sh
curl "$LMSTUDIO_BASE_URL/models" -H "Authorization: Bearer $LMSTUDIO_API_KEY"
```

`curl` でも失敗するなら、原因は `llm-ai-api` ではなく、ネットワークか LM Studio の設定です。

## 5. そのほかの使い方

ストリーミング、メッセージのリストを渡す `chat()`、生リクエストは、ほかのプロバイダーと同じです。[チュートリアル](tutorial-ja.md)と [API リファレンス](api-ja.md)を参照してください。このプロバイダーは `OpenAICompatClient` で動いており、`max_tokens` は `max_tokens` のまま送られます。LM Studio は独自の REST API や Anthropic 互換のエンドポイントも持っています。それらは生レイヤー（`m.client.request(...)`）で呼べます。
