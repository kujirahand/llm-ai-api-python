# Strata（ローカル / LAN の LLM サーバー）を使う

English: [local_llm-strata.md](local_llm-strata.md)

Strata は OpenAI 互換の API を持つローカル LLM サーバーです。このページでは、同じマシンから、または LAN 内の別のマシンから `llm-ai-api` で呼び出す方法を説明します。

## 1. まず試す（同じマシン）

```python
from llm_ai_api import llm

m = llm("strata:iq3_s")  # "strata:<モデル名>"
print(m.ask("可愛い犬の名前を考えて"))
```

何も設定しなければ、`http://127.0.0.1:8080/v1` に接続し、API キーとして `local` を送ります。Strata 側で認証を有効にしていなければ、本物のキーは不要です。

## 2. 設定

| 環境変数 | 意味 | 既定値 |
|---|---|---|
| `STRATA_BASE_URL` | Strata API のベース URL（`/v1` まで含める） | `http://127.0.0.1:8080/v1` |
| `STRATA_API_KEY` | API キー。任意で、Strata 側で設定した場合だけ必要 | `local`（未設定時に送る） |
| `STRATA_MODEL` | モデル名。`examples/local-llm-strata.py` だけが使う（ライブラリにデフォルトモデルはない） | なし |

引数でも指定できます: `llm("strata:iq3_s", base_url="...", api_key="...")`。

## 3. LAN 越しに接続する

接続できた設定の例（別のマシンから）:

```sh
# STRATA API
export STRATA_BASE_URL="http://100.xxx.xxx.xxx:47832/v1"
export STRATA_API_KEY="sk-strata-xxx"
export STRATA_MODEL="iq3_s"
```

```python
import os
from llm_ai_api import llm

m = llm(f"strata:{os.environ['STRATA_MODEL']}")  # base_url と api_key は環境変数から読まれる
print(m.ask("こんにちは"))
```

付属のサンプルでも試せます:

```sh
python examples/local-llm-strata.py "$STRATA_MODEL"
```

### 注意点

1. **共有をオンにするとポート番号が変わる。**
   共有がオフのとき、Strata は自分のマシンだけで、ポート `47831` を待ち受けます。ローカルネットワークを「共有」にする（注意点 2）と、ポートは `47832` になります。つまり `47831` は Strata を動かしているマシン自身で使い、`47832` は LAN 内の別のマシンから使います。どちらもライブラリの既定値（`8080`）ではないので、`STRATA_BASE_URL` を必ず明示してください。ポートが合わないときは、Strata の設定画面に表示されるアドレスを確認します。
2. **サービス設定で、ローカルネットワークを「共有」にする。**
   既定では Strata は自分のマシンからの接続しか受け付けません。サービス設定でローカルネットワークを **共有** に変えるまでは、別のマシンからは接続できません（接続拒否かタイムアウトになり、`APIConnectionError` / `APITimeoutError` になります）。このとき同時にポートが `47831` から `47832` に変わることに注意してください（注意点 1）。
3. **API キーは任意。**
   `STRATA_API_KEY`（または `api_key=`）が必要なのは、Strata 側で API キーを設定した場合だけです。設定していなければ指定は不要で、ライブラリは仮の値 `local` を送ります。設定している場合に、キーが無い・間違っていると 401 `AuthenticationError` になります。
4. **`STRATA_BASE_URL` には `/v1` まで含める。** ライブラリがその後ろに `/chat/completions` を付けます。
5. **サーバーが表示するアドレスを使う。** 例の `100.x.x.x` はプライベートネットワーク（VPN やオーバーレイネットワークなど）のアドレスです。このプレースホルダーではなく、Strata のマシンが示す実際のアドレスを使ってください。
6. **API キーは秘密にする。** 本物のキーをリポジトリにコミットしないこと。シェルの設定ファイルや、Git に含めないローカルの `.env` に置きます。

## 4. うまくいかないとき

| 症状 | 確認すること |
|---|---|
| すぐに `APIConnectionError`（`code="connection_error"`） | IP かポートの間違い（ローカルは `47831`、共有オンは `47832`）、ローカルネットワークが「共有」になっていない、ファイアウォールがポートを塞いでいる。 |
| `APITimeoutError` | マシンに届かない（別のネットワーク、スリープ中）、またはモデルを読み込み中。起動が遅いモデルなら `timeout=` を大きくする。 |
| 401 `AuthenticationError` | Strata 側で API キーを有効にしていて、`STRATA_API_KEY` が未設定か間違っている。 |
| 404 `NotFoundError` | ベース URL に `/v1` がない、またはモデル名が違う。Strata に表示されている名前を確認する。 |
| ローカルでは動くが LAN 越しだと失敗する | 上の注意点 1 と 2 を参照。 |

このライブラリを使わずに接続だけ確かめるには:

```sh
curl "$STRATA_BASE_URL/models" -H "Authorization: Bearer $STRATA_API_KEY"
```

`curl` でも失敗するなら、原因は `llm-ai-api` ではなく、ネットワークか Strata の設定です。

## 5. そのほかの使い方

ストリーミング、メッセージのリストを渡す `chat()`、生リクエストは、ほかのプロバイダーと同じです。[チュートリアル](tutorial-ja.md)と [API リファレンス](api-ja.md)を参照してください。このプロバイダーは `OpenAICompatClient` で動いており、`max_tokens` は `max_tokens` のまま送られます。
