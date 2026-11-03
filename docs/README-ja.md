# ドキュメント

English: [README.md](README.md)

[`llm-ai-api`](../README-ja.md) のガイドです。OpenAI、OpenRouter、Anthropic、Google Gemini、LM Studio、Ollama、Strata を呼ぶ薄い HTTP ラッパーです。

すべてのページは日本語版（`foo-ja.md`）と英語版（`foo.md`）の 2 つがあり、先頭でお互いへリンクしています。一方を変えたら、同じコミットでもう一方も同じ内容にしてください（`publish.md` は例外で、日本語のみ）。

## まず読む

| ページ | 内容 |
|---|---|
| [チュートリアル](tutorial-ja.md) / [Tutorial](tutorial.md) | インストールと API キー、最初の一問一答、モデルの切り替え、会話の続き、ストリーミング、呼び出しごとのオプション、非同期（`aask` / `achat` / `aask_stream`）、エラー処理、クライアントの再利用と閉じ方。ここから読んでください。 |
| [API リファレンス](api-ja.md) / [API reference](api.md) | 公開 API の一覧。`llm()`、`LLM` のメソッドとその非同期版、戻り値の型（`ChatResult`、`ChatChunk`、`Usage`）、モジュールの関数、プロバイダークライアントと生レイヤーの `request()` / `request_stream()`、モデル名の定数、例外クラスとその `code` すべて。 |
| [設定リファレンス](config-ja.md) / [Configuration reference](config.md) | `llm()` に渡せる設定（`timeout`、`max_retries`、`retry_read_timeout`、`retry_after_max`、`base_url`、`headers`、`lang` など）、どの失敗をリトライするかとその理由（リトライの方針）、本番で効いてくる設定（接続プール、TLS、プロキシ）。 |

## 機能

| ページ | 内容 |
|---|---|
| [構造化出力](structured-ja.md) / [Structured output](structured.md) | `chat()` / `achat()` の `schema=`。JSON Schema とモデルクラスの指定、schema の正規化、プロバイダーごとのリクエストの形、応答の検証とエラー。 |
| [画像入力（`images=`）](multimodal-ja.md) / [Image input](multimodal.md) | `ask` 系の `images=`（パス、bytes、URL）、プロバイダーに送られる形、`transcribe()` / `atranscribe()` による音声の文字起こし（OpenAI のみ）、キャッシュとログとの関係。 |
| [イベント](events-ja.md) / [Events](events.md) | `add_event_listener()` / `remove_event_listener()`。`retry`、`response`、`http_error`、`connection_error`、`stream_error`、`stream_end`、`cache_hit`、`cache_error`、`log_error` と、`request_id` / `latency` / `retries` の読み方。失敗とリトライの観測はこちらです（ログは成功した呼び出しだけを残します）。 |
| [入出力のキャッシュ](io_cache-ja.md) / [Response cache](io_cache.md) | **本ライブラリの**呼び出しを SQLite に保存して、同じリクエストで料金を払わないようにする機能。`set_cache()`、インスタンスごとの `cache=`、キャッシュキー、暗号化、古い行の削除、最大サイズ。既定はオフ。 |
| [入出力ログ](io_logs-ja.md) / [I/O log](io_logs.md) | チャットの呼び出しごとに 1 行の JSON を追記する機能（`set_log()`、インスタンスごとの `log=`）、1 行の内容、フックによる記録の書き換え・省略、最大サイズ。既定はオフ。 |
| [プロンプトキャッシュの使い方](cache-ja.md) / [Prompt caching](cache.md) | ライブラリの機能ではなく、プロバイダー側のプロンプトキャッシュの話。`content` を各社の形式のまま渡せばそのまま効きます。設定 API はありません。 |

名前の似た 2 ページに注意してください。**cache.md** はプロバイダー側のプロンプトキャッシュ（ここで設定するものはない）、**io_cache.md** は本ライブラリ自身の応答キャッシュ（`set_cache()`）です。

## ローカルの LLM サーバー

自分のマシンで動く OpenAI 互換のサーバーです。認証を有効にしないかぎり、API キーは不要です。

| ページ | 内容 |
|---|---|
| [LM Studio（ローカルの LLM サーバー）を使う](local_llm-lmstudio-ja.md) / [Using LM Studio](local_llm-lmstudio.md) | `llm("lmstudio:<モデル名>")` と `http://localhost:1234/v1`。サーバーの起動（`lms server start`、Developer タブ）、`LMSTUDIO_BASE_URL` / `LMSTUDIO_API_KEY` / `LMSTUDIO_MODEL`、「Require Authentication」がオンのときの API トークン、ローカルネットワークへの公開。 |
| [Ollama（ローカルの LLM サーバー）を使う](local_llm-ollama-ja.md) / [Using Ollama](local_llm-ollama.md) | `llm("ollama:gemma4:e2b")` と `http://localhost:11434/v1`。`:` を含むモデル名の扱い、モデルのダウンロード、`OLLAMA_BASE_URL` / `OLLAMA_API_KEY` / `OLLAMA_MODEL`、ローカルのサーバーに API キー認証の機能が無い点（プロキシで守る）、`OLLAMA_HOST` での LAN 越しの接続、`https://ollama.com/v1` 経由のホスト済みモデル。 |
| [Strata（ローカル / LAN の LLM サーバー）を使う](local_llm-strata-ja.md) / [Using Strata](local_llm-strata.md) | `llm("strata:<モデル名>")` と `http://127.0.0.1:47831/v1`。`STRATA_BASE_URL` / `STRATA_API_KEY` / `STRATA_MODEL`、LAN 越しの接続で共有オンになるときポートが `47832` に変わる点。 |

どのページにも、最後に「うまくいかないとき」の表と、本ライブラリを使わずに接続を確かめる `curl` コマンドがあります。実行できるサンプルは [`examples/local-llm-lmstudio.py`](../examples/local-llm-lmstudio.py)、[`examples/local-llm-ollama.py`](../examples/local-llm-ollama.py)、[`examples/local-llm-strata.py`](../examples/local-llm-strata.py) です。

## 開発者向け

| ページ | 内容 |
|---|---|
| [PyPI への公開手順](publish.md) | PyPI への公開の手順（バージョンの 2 か所の更新、ビルド、`twine upload`）。日本語のみ。 |

---

ソースコード: [`src/llm_ai_api/`](../src/llm_ai_api) · 貢献者のための設計方針: [AGENTS.md](../AGENTS.md) · サンプル: [`examples/`](../examples)
