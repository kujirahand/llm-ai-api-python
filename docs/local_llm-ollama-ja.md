# Ollama（ローカルの LLM サーバー）を使う

English: [local_llm-ollama.md](local_llm-ollama.md)

Ollama は自分のマシンでモデルを動かし、OpenAI 互換の API を提供するアプリです。このページでは、同じマシンから、または LAN 内の別のマシンから `llm-ai-api` で呼び出す方法を説明します。

## 1. まず試す（同じマシン）

```python
from llm_ai_api import llm

m = llm("ollama:gemma4:e2b")  # "ollama:<モデル名>"
print(m.ask("可愛い犬の名前を考えて"))
```

モデル名はタグとして `:` を含むことがよくあります（`gemma4:e2b`）。問題ありません。**最初の** `:` だけがプロバイダーとモデルを区切るので、`"ollama:gemma4:e2b"` はプロバイダー `ollama`、モデル `gemma4:e2b` です。

何も設定しなければ、`http://localhost:11434/v1` に接続し、API キーとして `ollama` を送ります。Ollama はこの値を無視するので、キーの設定は不要です。

### サーバーの起動とモデルの取得

macOS と Windows のアプリは、メニューバーにサーバーを保ちます。コマンドラインからは `ollama serve` で起動します。呼び出せる名前の一覧と、モデルのダウンロード:

```sh
ollama list                 # "ollama:<モデル名>" に使う名前の一覧
ollama pull gemma4:e2b      # モデルをダウンロード
ollama --version
```

## 2. 設定

| 環境変数 | 意味 | 既定値 |
|---|---|---|
| `OLLAMA_BASE_URL` | Ollama API のベース URL（`/v1` まで含める） | `http://localhost:11434/v1` |
| `OLLAMA_API_KEY` | API キー。任意で、ローカルのサーバーはチェックしない（注意点 3）。Ollama のホスト済み API を使うか、前に置くプロキシが要求するときだけ必要 | `ollama`（未設定時に送る） |
| `OLLAMA_MODEL` | モデル名。`examples/local-llm-ollama.py` だけが使う（ライブラリにデフォルトモデルはない） | なし |

引数でも指定できます: `llm("ollama:gemma4:e2b", base_url="...", api_key="...")`。

## 3. LAN 越しに接続する

Ollama は既定でポート `11434` を `127.0.0.1` にバインドするため、`OLLAMA_HOST` でバインドアドレスを変えるまで、別のマシンからは接続できません。macOS でアプリとして動かしている場合は、`launchctl` で設定して Ollama を再起動します:

```sh
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"   # その後 Ollama アプリを再起動
```

そのうえで、別のマシンで:

```sh
export OLLAMA_BASE_URL="http://192.168.1.20:11434/v1"
export OLLAMA_MODEL="gemma4:e2b"
```

```python
import os
from llm_ai_api import llm

m = llm(f"ollama:{os.environ['OLLAMA_MODEL']}")  # base_url は環境変数から読まれる
print(m.ask("こんにちは"))
```

付属のサンプルでも試せます:

```sh
python examples/local-llm-ollama.py "$OLLAMA_MODEL"
```

### 注意点

1. **`OLLAMA_BASE_URL` には `/v1` まで含める。** ライブラリがその後ろに `/chat/completions` を付けます。`http://localhost:11434` だけでは Ollama 固有のネイティブ API であり、このプロバイダーは呼べません。
2. **ローカルのサーバーには認証が無い。** ポートに届く人は誰でもモデルを実行できます。`0.0.0.0` にバインドする前に、信頼できるネットワークであることを確認し、ファイアウォールを前に置いてください。
3. **API キー認証は、そもそもオンにできない。** Ollama はローカル API について「認証は不要」と明記しており、キーを一切チェックしません。`Authorization` ヘッダーを付けないリクエストも、本ライブラリが送る仮の値も、でたらめな文字列も、すべて成功します（Ollama 0.40.13 で 2026-11-03 に確認）。ローカルのサーバーにキーを必須にするオプションも環境変数もありません。`OLLAMA_API_KEY` を設定するのは、Ollama の前に置くプロキシ（下記）がキーを期望する場合か、ベース URL をキーをチェックする Ollama のホスト済み API に向ける場合だけです。
4. **最初のリクエストは遅い。** Ollama はモデルをメモリに読み込むためです。大きなモデルでは `timeout=` を大きくしてください。
5. **コンテキスト長の既定値は VRAM に依存します。** [Ollama の説明](https://docs.ollama.com/context-length)を参照してください。例えば `OLLAMA_CONTEXT_LENGTH=8192 ollama serve` で変更できます。長くすると必要なメモリも増えます。
6. **サーバーのマシンが表示するアドレスを使う。** `192.168.1.20` はプレースホルダーです。

### プロキシでキーをチェックする

サーバー自体がキーをチェックできないので、ネットワークに出した Ollama を守る定番の方法は、Ollama を `127.0.0.1` のままにして、`Authorization: Bearer <キー>` ヘッダーをチェックするリバースプロキシを前に置くことです。本ライブラリは `OLLAMA_API_KEY` / `api_key=` の値をこのヘッダーで送ります。nginx での最小のチェック:

```nginx
server {
    listen 443 ssl;
    server_name ollama.example.com;
    ssl_certificate /path/to/fullchain.pem;
    ssl_certificate_key /path/to/privkey.pem;

    location / {
        if ($http_authorization != "Bearer <長いランダムなトークン>") {
            return 401;
        }
        proxy_pass http://127.0.0.1:11434;
        proxy_read_timeout 600s;   # ストリーミングの生成は数分続くことがある
    }
}
```

証明書と秘密鍵のパスは、サーバー用に用意した実際のファイルに置き換えてください。

そのうえで、クライアントをプロキシに向けます:

```sh
export OLLAMA_BASE_URL="https://ollama.example.com/v1"
export OLLAMA_API_KEY="<長いランダムなトークン>"
```

トークンを付けないリクエストは 401 `AuthenticationError` になります。「ローカルの Ollama」を呼んだのにこのエラーが出るとしたら、このケースだけです。

## 4. うまくいかないとき

| 症状 | 確認すること |
|---|---|
| すぐに `APIConnectionError`（`code="connection_error"`） | サーバーが動いていない（`ollama serve`、またはメニューバーのアプリ）、ポートの間違い、LAN 越しで `OLLAMA_HOST` を設定していない。 |
| 404 `NotFoundError`、`model '...' not found` | その名前はローカルにダウンロードされていない。`ollama list` で正確な名前を確認するか、`ollama pull <モデル>` を実行する。 |
| 「ローカル」のサーバーに対して 401 `AuthenticationError` | ローカルのサーバーはキーをチェックせず、このエラーを出せない。ベース URL がキーをチェックする先を向いている: Ollama のホスト済み API、または Ollama の前に置くプロキシ（上記）。`OLLAMA_API_KEY` / `api_key=` を設定するか、ベース URL を直す。 |
| 回答が途中で止まる | コンテキストウィンドウか出力上限に届いた。サーバーの `OLLAMA_CONTEXT_LENGTH` を上げるか、`chat()` で `stop_reason` と `usage` を確認する。 |
| `APITimeoutError` | モデルの読み込み中、またはマシンに届かない。`timeout=` を大きくする。 |
| ローカルでは動くが LAN 越しだと失敗する | 上の注意点 2 と 3、およびファイアウォールを参照。 |

このライブラリを使わずに接続だけ確かめるには:

```sh
curl "${OLLAMA_BASE_URL:-http://localhost:11434/v1}/models" -H "Authorization: Bearer ${OLLAMA_API_KEY:-ollama}"
```

`curl` でも失敗するなら、原因は `llm-ai-api` ではなく、ネットワークか Ollama の設定です。

## 5. そのほかの使い方

ストリーミング、メッセージのリストを渡す `chat()`、生リクエストは、ほかのプロバイダーと同じです。[チュートリアル](tutorial-ja.md)と [API リファレンス](api-ja.md)を参照してください。このプロバイダーは `OpenAICompatClient` で動いており、`max_tokens` は `max_tokens` のまま送られます。

Ollama は `https://ollama.com/v1` 経由でホスト済みのモデルも提供しています。ベース URL をそこに向け、Ollama のアカウントのキーを `OLLAMA_API_KEY` に入れます:

```sh
export OLLAMA_BASE_URL="https://ollama.com/v1"
export OLLAMA_API_KEY="<Ollama のキー>"
```
