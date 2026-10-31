# AGENTS.md

このリポジトリで作業するエージェント（および人間の開発者）向けの仕様書です。
実装・修正を行う前に必ず読み、ここに書かれた方針に従ってください。
方針を変える場合は、先にこのファイルを更新してください。

## 1. プロジェクトの目的

OpenAI / OpenRouter / Anthropic (Claude) の API を呼び出すための、**薄い HTTP ラッパー** と、プロバイダー間の差異を埋める **共通インターフェイス** を提供する。

```python
from llm_ai_api import llm

luna = llm("openai:gpt-6-luna")
question = "可愛い犬の名前を考えて"
print(luna.ask(question))  # ポチ
```

- 公式 SDK は仕様変更・メジャーアップデートで動かなくなることがある。本パッケージは **HTTP の JSON をほぼそのまま送受信する** ことで、長期間安定して動くことを最優先にする。
- 「便利さ」より「壊れにくさ」と「透明性」を優先する。抽象化は最小限にとどめ、利用者がいつでも生の JSON にアクセスできるようにする。

## 2. 基本方針（設計原則）

1. **依存は `httpx` のみ**: ランタイム依存として許可するのは `httpx` だけ。それ以外は標準ライブラリ（`json`, `os`, `time`, `dataclasses` など）で実装する。
   - `openai`, `anthropic` などの公式 SDK パッケージや、`requests`, `pydantic` などのサードパーティパッケージは一切使わない（テスト用も含めて導入しない）。
   - `httpx` の例外・型は公開 API に漏らさない（自前の例外に包んで送出する）。将来 HTTP ライブラリを差し替えられるようにするため。
2. **パススルー優先**: リクエストボディは利用者が渡した dict をそのまま送る。レスポンスは生の dict を必ず保持して返す。未知のフィールドを削ったり検証したりしない。
3. **指定されていないパラメータは送らない**: `temperature`, `top_p`, `max_tokens` などは利用者が明示した場合のみ送信する。
   - 理由: 新しいモデルや API バージョンでは、デフォルト値であっても送るだけで 400 になるパラメータがある（例: Claude の API バージョン `2026-10-21` では `temperature` / `top_p` / `top_k` が全モデルで拒否される。OpenAI の推論系モデルも `temperature` を拒否する）。
   - 例外: API 仕様上必須のもの（Claude の `max_tokens`）のみ、デフォルト値を補う。
4. **モデル名をハードコードしない**: ライブラリ本体にデフォルトモデルを持たない。`model` は常に呼び出し側が指定する。モデル名はサンプルコード・README・ライブテストにのみ書く。
5. **API バージョン・URL は差し替え可能にする**: ベース URL、`anthropic-version` ヘッダー、追加ヘッダーはすべて引数または環境変数で上書きできるようにする。
6. **エスケープハッチを常に用意する**: 共通インターフェイスが対応していない機能（ツール呼び出し、画像入力、構造化出力など）も、生レイヤー（`request()`）や `extra` 引数で必ず使えるようにする。
7. **小さく保つ**: 1 プロバイダーあたり 1 ファイル、数百行程度を目安にする。

## 3. 対応範囲

### v1 で対応する

| プロバイダー | 名前 | エンドポイント | 認証 |
|---|---|---|---|
| OpenAI | `openai` | `POST https://api.openai.com/v1/chat/completions` | `Authorization: Bearer $OPENAI_API_KEY` |
| OpenRouter | `openrouter` | `POST https://openrouter.ai/api/v1/chat/completions` | `Authorization: Bearer $OPENROUTER_API_KEY`（任意で `HTTP-Referer`, `X-Title`） |
| Anthropic | `anthropic`（別名 `claude`） | `POST https://api.anthropic.com/v1/messages` | `x-api-key: $ANTHROPIC_API_KEY` + `anthropic-version: 2026-10-21` |

- 共通インターフェイス `llm()` によるテキストの一問一答・ストリーミング
- テキストチャット（非ストリーミング / ストリーミング）
- 任意パス・任意ボディを送る生リクエスト（上記以外のエンドポイントも呼べる）

### v1 では対応しない（必要になったら別途検討）

- async（asyncio）対応
- OpenAI Responses API 専用の便利レイヤー（生レイヤー経由では呼べる）
- Embeddings / 画像生成 / 音声 / ファイルアップロード / Batch の便利レイヤー
- ツール呼び出しループの自動化、会話履歴管理
- トークン数の計算

## 4. ディレクトリ構成

```
llm-ai-api-python/
├── AGENTS.md
├── README.md        # 英語（PyPI に表示される）
├── README-ja.md     # 日本語
├── LICENSE
├── pyproject.toml
├── src/
│   └── llm_ai_api/
│       ├── __init__.py      # 公開 API の re-export、__version__
│       ├── py.typed
│       ├── _http.py         # httpx による送受信、SSE パーサー、リトライ
│       ├── errors.py        # 例外クラス
│       ├── types.py         # ChatResult などの dataclass
│       ├── openai.py        # OpenAIClient
│       ├── openrouter.py    # OpenRouterClient（OpenAI 互換部分を共有）
│       ├── anthropic.py     # AnthropicClient
│       └── llm.py           # 共通インターフェイス llm() / LLM
├── tests/
│   ├── test_http.py
│   ├── test_sse.py
│   ├── test_openai.py
│   ├── test_openrouter.py
│   ├── test_anthropic.py
│   ├── test_llm.py
│   └── test_live.py         # 実 API を叩くテスト（環境変数で有効化）
└── examples/
```

- インポート名は `llm_ai_api`、配布名（PyPI）は `llm-ai-api`。
- `src` レイアウトを採用する。

## 5. 公開 API 仕様

### 5.1 レイヤー構成

| レイヤー | 役割 | 例 |
|---|---|---|
| 共通インターフェイス | `"プロバイダー:モデル"` を指定して、どのプロバイダーも同じ書き方で使う | `llm("anthropic:claude-opus-5-5").ask("...")` |
| プロバイダーレイヤー | 各 API のチャットを呼び、`ChatResult` を返す | `client.chat(model=..., messages=...)` |
| 生レイヤー | 任意のパスに dict を送り、生の dict / SSE イベントを返す | `client.request("/v1/messages", body)` |

上のレイヤーは下のレイヤーだけを使って実装する（共通インターフェイスは独自に HTTP を送らない）。

### 5.2 共通インターフェイス（`llm.py`）

```python
from llm_ai_api import llm

m = llm(
    "openai:gpt-6-luna",   # "<プロバイダー>:<モデル>"
    system=None,           # 既定のシステムプロンプト
    max_tokens=None,       # 既定の最大出力トークン（指定時のみ送信）
    temperature=None,      # 既定の temperature（指定時のみ送信）
    extra=None,            # 既定の追加ボディ（dict）
    **client_options,      # api_key, base_url, timeout, max_retries, headers など → クライアントへ
)

text: str = m.ask("可愛い犬の名前を考えて")              # 一問一答。テキストだけ返す
for piece in m.stream("長い物語を書いて"):              # テキスト差分を順に返す
    print(piece, end="", flush=True)
result: ChatResult = m.chat([{"role": "user", "content": "..."}])  # 詳細が必要なとき

m.provider  # "openai"
m.model     # "gpt-6-luna"
m.client    # 下位の OpenAIClient など（生レイヤーにアクセスできる）
```

- モデル指定文字列は **最初の `:` で分割** する。OpenRouter のモデル名は `/` や `:` を含むため（例: `"openrouter:meta-llama/llama-4:free"` → provider `openrouter`、model `meta-llama/llama-4:free`）。
- プロバイダー名は小文字に正規化する。`claude` は `anthropic` の別名。未知のプロバイダーや `:` がない文字列は `LLMConfigError`。
- `ask()` / `stream()` / `chat()` は、キーワード引数（`system`, `max_tokens`, `temperature`, `extra`）で `llm()` の既定値を呼び出しごとに上書きできる。`extra` は既定値と浅くマージする。
- `ask()` / `stream()` は **状態を持たない**（会話履歴を保持しない）。会話を続けたい場合は `chat()` に messages を渡してもらう。
- `ask()` は `ChatResult.text` をそのまま返す。`stop_reason` が `"refusal"` や `"max_tokens"` でも例外にしない（必要なら `chat()` を使って確認してもらう）。
- `LLM` は `close()` とコンテキストマネージャ（`with llm(...) as m:`）に対応する。

### 5.3 クライアント

```python
from llm_ai_api import OpenAIClient, OpenRouterClient, AnthropicClient

client = AnthropicClient(
    api_key=None,          # None なら環境変数 ANTHROPIC_API_KEY
    base_url=None,         # None なら環境変数 ANTHROPIC_BASE_URL、なければ既定値
    timeout=600.0,         # 秒
    max_retries=2,
    headers=None,          # 追加ヘッダー（dict）
    anthropic_version="2026-10-21",  # AnthropicClient のみ
)
```

- `OpenRouterClient` は追加で `app_url`（→ `HTTP-Referer`）、`app_name`（→ `X-Title`）を受け取れる。
- API キーが見つからない場合は、リクエスト時ではなく **クライアント生成時** に `LLMConfigError` を送出する。
- API キーを `repr()` やログ、例外メッセージに含めない。
- クライアントは内部に `httpx.Client` を 1 つ持って再利用する。`close()` とコンテキストマネージャに対応する。

環境変数:

| 変数 | 用途 |
|---|---|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | OpenAI |
| `OPENROUTER_API_KEY` / `OPENROUTER_BASE_URL` | OpenRouter |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` | Anthropic |

### 5.4 生レイヤー

```python
resp: dict = client.request(path, body, *, method="POST", headers=None, timeout=None)
events: Iterator[SSEEvent] = client.request_stream(path, body, *, headers=None, timeout=None)
```

- `body` は一切加工せずに JSON 化して送る。
- `SSEEvent` は `event: str | None`, `data: str`（生文字列）, `json() -> dict` を持つ。

### 5.5 プロバイダーレイヤー（チャット）

```python
result = client.chat(
    model="...",
    messages=[{"role": "system", "content": "..."}, {"role": "user", "content": "..."}],
    max_tokens=None,       # 指定時のみ送信（Anthropic のみ未指定時 16000 を補う）
    temperature=None,      # 指定時のみ送信
    extra=None,            # dict。ボディにそのままマージ（最後に適用し、上書き可）
)
for chunk in client.stream_chat(model=..., messages=..., ...):
    print(chunk.text, end="")  # テキスト差分
```

メッセージ形式とパラメータ変換（ライブラリが行う変換はこれだけ）:

| 項目 | OpenAI | OpenRouter | Anthropic |
|---|---|---|---|
| `role: system` | そのまま送信 | そのまま送信 | messages から取り出して連結し、トップレベル `system` に設定 |
| `max_tokens` | `max_completion_tokens` として送信 | `max_tokens` として送信 | `max_tokens`（必須。未指定時 16000） |
| `content` | 文字列またはパーツ配列をそのまま | 同左 | 同左（Claude 形式のブロック配列をそのまま） |
| ストリーミング | `stream: true` と `stream_options: {"include_usage": true}` を付与 | `stream: true` | `stream: true` |

- 画像などのマルチモーダル content は **プロバイダー間で変換しない**。各プロバイダーの形式で渡してもらう。
- 共通インターフェイスの `system=` 引数は、先頭に `{"role": "system", ...}` を追加することで実現する（変換は上表のとおりプロバイダーレイヤーで行う）。

### 5.6 戻り値

```python
@dataclass
class ChatResult:
    text: str                 # テキスト部分を連結したもの
    model: str | None
    stop_reason: str | None   # 生の値（OpenAI: finish_reason / Claude: stop_reason）
    usage: Usage | None       # input_tokens, output_tokens（取れない場合 None）
    raw: dict                 # レスポンス JSON 全体

@dataclass
class ChatChunk:
    text: str                 # このイベントのテキスト差分（なければ ""）
    raw: dict                 # イベント JSON
```

- テキスト抽出:
  - OpenAI / OpenRouter: `choices[0].message.content`（`None` は `""` とする）
  - Anthropic: `content` のうち `type == "text"` のブロックの `text` を連結。`thinking` などその他のブロックは `text` に含めず `raw` から参照してもらう。
- `stop_reason` は正規化しない（生の値を返す）。Claude の `"refusal"` なども例外にせず、そのまま返す。
- `usage` の対応: OpenAI 系は `prompt_tokens` → `input_tokens`、`completion_tokens` → `output_tokens`。

## 6. HTTP 層の仕様（`_http.py`）

- `httpx.Client` を使う。プロキシは httpx の環境変数対応（`trust_env=True`、`HTTPS_PROXY` 等）に任せる。
- 共通ヘッダー: `Content-Type: application/json`, `Accept: application/json`（ストリーム時 `text/event-stream`）, `User-Agent: llm-ai-api-python/<version>`。
- JSON は `json.dumps(body, ensure_ascii=False).encode("utf-8")` で自前でシリアライズして `content=` に渡す（httpx の `json=` の挙動差に依存しない）。
- タイムアウト既定値は 600 秒（長い生成に対応するため）。接続タイムアウトは 10 秒。
- ストリーミングは `client.stream("POST", ...)` と `response.iter_lines()` を使い、SSE パースは自前で行う。
- 例外の変換: `httpx.TimeoutException` → `APITimeoutError`、その他の `httpx.TransportError` → `APIConnectionError`。httpx の例外をそのまま外に出さない。
- リトライ（自前で実装する）:
  - 対象: 408, 409, 429, 500 以上、および接続エラー・タイムアウト。
  - 既定 2 回。指数バックオフ（0.5 秒起点、上限 8 秒、ジッターあり）。
  - `retry-after` ヘッダーがあれば優先（上限 60 秒）。
  - ストリーミングは、レスポンスを読み始めた後はリトライしない。
- エラー時はレスポンスボディを読み、JSON として解釈できれば dict、できなければ文字列として例外に格納する。

### SSE パーサー

- 行単位で読み、空行でイベントを確定する。`event:` / `data:`（複数行は `\n` で連結）を扱う。
- `:` で始まる行はコメントとして無視する（OpenRouter は `: OPENROUTER PROCESSING` を送ってくる）。
- OpenAI 系は `data: [DONE]` で終了。
- Anthropic は `ping` を無視し、`error` イベントを受け取ったら `APIStreamError` を送出する。`message_stop` で終了。
- テキスト差分の取り出し:
  - OpenAI 系: `choices[0].delta.content`
  - Anthropic: `content_block_delta` のうち `delta.type == "text_delta"` の `delta.text`

## 7. 例外

```
LLMError                      # 基底
├── LLMConfigError            # API キー未設定、モデル指定文字列の誤りなど
├── APIConnectionError        # 接続失敗
│   └── APITimeoutError
├── APIStatusError            # HTTP 4xx/5xx
│   │   属性: status_code, body (dict|str), provider, request_id, headers
│   ├── BadRequestError       # 400
│   ├── AuthenticationError   # 401
│   ├── PermissionDeniedError # 403
│   ├── NotFoundError         # 404
│   ├── RateLimitError        # 429
│   └── InternalServerError   # 500 以上
└── APIStreamError            # ストリーム途中の error イベント
```

- `request_id` は `x-request-id`（OpenAI）/ `request-id`（Anthropic）ヘッダーから取得する。
- 例外メッセージには、API が返したエラーメッセージ（`error.message`）を含める。

## 8. 対応 Python バージョン・パッケージング

- Python 3.9 以上。型ヒントは `from __future__ import annotations` を使い、3.9 で動く書き方にする。
- `pyproject.toml` の `dependencies` は `httpx>=0.27,<1` のみ。httpx の新しいメジャーバージョンが出たら、動作確認してから上限を上げる。
- ビルドバックエンドは setuptools。`py.typed` を同梱する。
- バージョンは `pyproject.toml` と `src/llm_ai_api/__init__.py` の `__version__` の 2 か所で管理し、必ず同時に更新する。

## 9. テスト

- テストフレームワークは標準の `unittest`。実行: `python -m unittest discover -s tests`
- ユニットテストはネットワークに出ない。`httpx.MockTransport` を使って、送信内容の検証と応答の差し替えを行う。
- 最低限テストすること:
  - 共通インターフェイス: モデル指定文字列の分割（`:` を含むモデル名）、別名、エラー、既定値と呼び出しごとの上書き
  - 送信ボディ: 未指定パラメータが送られないこと、`extra` が最後にマージされること、system メッセージの変換、`max_tokens` の名前変換
  - ヘッダー: 認証ヘッダー、`anthropic-version`、追加ヘッダー
  - SSE: 複数行 data、コメント行、`[DONE]`、`ping`、`error` イベント、改行コード `\r\n`
  - エラー: ステータスコードごとの例外クラス、JSON/非 JSON のエラーボディ、リトライと `retry-after`、httpx 例外の変換
- ライブテスト（`tests/test_live.py`）は `LLM_AI_API_LIVE=1` かつ各 API キーがあるときだけ実行する。課金が発生するため `max_tokens` を小さくする。

## 10. コーディング規約

- `httpx` と標準ライブラリ以外を import しない（これに違反する変更は受け入れない）。
- 公開関数・クラスには型ヒントと docstring を付ける。docstring・コメントは日本語でよい。
- 公開 API は `__init__.py` で明示的に re-export し、それ以外は内部扱い（`_` 始まり）とする。
- 公開 API を変更したら README.md（英語）、README-ja.md（日本語）とこのファイルを同時に更新する。
- フォーマットは PEP 8 に準拠（ツールは強制しない）。

## 11. 公式 API 仕様の参照先

仕様に迷ったら以下の公式ドキュメントを確認すること（推測で実装しない）。

- OpenAI Chat Completions: https://platform.openai.com/docs/api-reference/chat
- OpenRouter: https://openrouter.ai/docs/api-reference/overview
- Anthropic Messages: https://docs.claude.com/en/api/messages
- Anthropic API バージョン: https://platform.claude.com/docs/en/api/versioning
