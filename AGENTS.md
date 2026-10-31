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
4. **デフォルトモデルを持たない**: `model` は常に呼び出し側が指定する。ライブラリの処理が特定のモデル名に依存してはならない（分岐しない）。モデル名を書いてよいのは `models.py`（便利な定数）、サンプルコード、README、ライブテストだけ。`models.py` の定数は例にすぎず、載っていないモデルも文字列でそのまま指定できること。
5. **API バージョン・URL は差し替え可能にする**: ベース URL、`anthropic-version` ヘッダー、追加ヘッダーはすべて引数または環境変数で上書きできるようにする。
6. **エスケープハッチを常に用意する**: 共通インターフェイスが対応していない機能（ツール呼び出し、画像入力、構造化出力など）も、生レイヤー（`request()`）や `extra` 引数で必ず使えるようにする。
7. **小さく保つ**: 1 プロバイダーあたり 1 ファイル、数百行程度を目安にする。

## 3. 対応範囲

### v1 で対応する

| プロバイダー | 名前 | エンドポイント | 認証 |
|---|---|---|---|
| OpenAI | `openai` | `POST https://api.openai.com/v1/chat/completions` | `Authorization: Bearer $OPENAI_API_KEY` |
| OpenRouter | `openrouter` | `POST https://openrouter.ai/api/v1/chat/completions` | `Authorization: Bearer $OPENROUTER_API_KEY`（任意で `HTTP-Referer`, `X-Title`） |
| Google Gemini | `google` | `POST https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`（OpenAI 互換エンドポイント。Google 自身が「ベータ」と明記している） | `Authorization: Bearer $GEMINI_API_KEY`（なければ `GOOGLE_API_KEY`） |
| Anthropic | `anthropic`（別名 `claude`） | `POST https://api.anthropic.com/v1/messages` | `x-api-key: $ANTHROPIC_API_KEY` + `anthropic-version: 2026-10-21` |

- 共通インターフェイス `llm()` によるテキストの一問一答・ストリーミング
- 共通インターフェイス（`llm()` / `LLM`）の非同期版 `aask()` / `achat()` / `astream()`（内部実装のみで、プロバイダークライアントと生レイヤーの非同期版は公開しない。5.2 を参照）
- テキストチャット（非ストリーミング / ストリーミング）
- 任意パス・任意ボディを送る生リクエスト（上記以外のエンドポイントも呼べる）
- 任意の API 応答キャッシュ（SQLite。既定はオフ。5.7 を参照）
- 任意の入出力ログ（JSON Lines。既定はオフ。5.8 を参照）

### v1 では対応しない（必要になったら別途検討）

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
│       ├── _async_http.py   # 非同期版の送受信・SSE・リトライ（内部専用、httpx.AsyncClient）
│       ├── _async_clients.py # 非同期のプロバイダークライアント（内部専用、LLM の a* メソッドが使う）
│       ├── errors.py        # 例外クラス
│       ├── types.py         # ChatResult などの dataclass
│       ├── cache.py         # SQLite による応答キャッシュ（暗号化、既定はオフ）、set_cache() / clear_cache()
│       ├── log.py           # JSON Lines の入出力ログ（既定はオフ）、set_log() / get_log()
│       ├── openai.py        # OpenAIClient
│       ├── openrouter.py    # OpenRouterClient（OpenAI 互換部分を共有）
│       ├── google.py        # GoogleClient（OpenAI 互換部分を共有）
│       ├── anthropic.py     # AnthropicClient
││       ├── llm.py           # 共通インターフェイス llm() / LLM
│       ├── models.py        # 代表的なモデルの定数（"provider:model" 形式の文字列）
│       └── lang/            # エラーメッセージの多言語化
│           ├── __init__.py  # 言語判定、フォールバック、t()
│           ├── en.py        # 英語（フォールバック先。全メッセージ ID を持つ）
│           └── ja.py        # 日本語
├── tests/
│   ├── helpers.py           # MockTransport 用ヘルパー
│   ├── test_http.py
│   ├── test_sse.py
│   ├── test_openai.py
│   ├── test_openrouter.py
│   ├── test_google.py
│   ├── test_anthropic.py
│   ├── test_llm.py
│   ├── test_async_clients.py # 内部の非同期クライアント
│   ├── test_async_llm.py     # LLM の aask / achat / astream
│   ├── test_models.py
│   ├── test_lang.py
│   ├── test_cache.py
│   ├── test_log.py
│   ├── test_cache_crypto.py
│   ├── test_stream_close.py  # ストリームの閉じ忘れ（#25）
│   └── test_live.py         # 実 API を叩くテスト（環境変数で有効化）
├── docs/
│   ├── publish.md       # PyPI への公開手順
│   ├── cache.md         # プロンプトキャッシュの使い方（英語）
│   ├── cache-ja.md      # 同（日本語）
│   ├── io_cache.md      # 応答のローカルキャッシュ（英語）
│   ├── io_cache-ja.md   # 同（日本語）
│   ├── io_logs.md       # 入出力ログ（英語）
│   └── io_logs-ja.md    # 同（日本語）
└── examples/                # 使い方のサンプル（コメントは英語。_common.py は共通ヘルパー）
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
- `ask()` / `stream()` / `chat()` は、キーワード引数（`system`, `max_tokens`, `temperature`, `extra`）で `llm()` の既定値を呼び出しごとに上書きできる。引数を渡さなければ既定値を使い、**`None` を明示すると、その呼び出しだけ既定値を無効にして送らない**（`llm(..., temperature=0.4).ask("q", temperature=None)` は `temperature` を送らない）。両者を区別するため、これらの引数の既定値は内部のセンチネル `UNSET` で、`None` ではない。`extra` は dict を渡すと既定値と浅くマージし、`None` で既定の `extra` を無効にする。ただし Claude の `max_tokens` は API の必須項目なので、`None` を指定してもライブラリ既定の 16000 が使われる。`llm()` 自体の引数では `None` は「既定値なし」の意味。
- `ask()` / `stream()` は **状態を持たない**（会話履歴を保持しない）。会話を続けたい場合は `chat()` に messages を渡してもらう。
- `ask()` は `ChatResult.text` をそのまま返す。`stop_reason` が `"refusal"` や `"max_tokens"` でも例外にしない（必要なら `chat()` を使って確認してもらう）。
- `LLM` は `close()` とコンテキストマネージャ（`with llm(...) as m:`）に対応する。

#### 非同期（async）

```python
async with llm("openai:gpt-6-luna") as m:
    text = await m.aask("可愛い犬の名前を考えて")
    result = await m.achat([{"role": "user", "content": "..."}])
    async for piece in m.astream("長い物語を書いて"):   # await は付けない
        print(piece, end="", flush=True)
    answers = await asyncio.gather(m.aask("A"), m.aask("B"))  # 同じ LLM を共有してよい
```

- `aask()` / `achat()` / `astream()` は同期版と同じ引数・意味（`UNSET` と `None` の区別、`extra` のマージ、キャッシュ・ログ）。新しい公開名は増やさない（`__all__` は変えない）。
- 非同期クライアントは最初の `a*` 呼び出しで内部に作る（`llm()` の時点では作らない）。キャッシュとログのファイル操作は `asyncio.to_thread()` で行う。同期版とキャッシュを共有する（キーと形式が同じ）。このため、カスタムのキャッシュ／ログオブジェクトは非同期経路ではワーカースレッドから呼ばれる（スレッドセーフであること）。非同期クライアントは同期クライアントが生成時に解決した設定（API キー、ベース URL、キャッシュ／ログのオブジェクト）をそのまま使う（生のオプションを再解決しない）。
- 閉じるには `async with` か `await m.aclose()`。`aclose()` は非同期・同期の両クライアントを閉じ、何度呼んでもよい。`close()` は同期クライアントだけを閉じる（従来どおり）。閉じた `LLM` は再利用しない。
- `astream()` は最初の反復で通信を始めるので、接続エラーや HTTP エラーも最初の反復で出る（同期版 `stream()` は呼び出し時）。途中でやめるときは `await stream.aclose()` を呼ぶ。キャンセルされたストリームはレスポンスを閉じ、キャッシュ・ログに残さない。閉じずに捨てられた `_AsyncEventStream` は、最後の手段として `__del__` から生成時のイベントループに `resp.aclose()` を予約する（ループがなければ `ResourceWarning`）。
- イベントループをまたいで使わない。`asyncio.run()` ごとに新しい `llm()` を作る。
- 実装は `_async_http.py` / `_async_clients.py`（内部専用）。ボディ生成とパースは同期版の関数を共用する。ストリームは async generator ではなく `__anext__` / `aclose` を持つ通常のクラスで組む（generator の `finally` で `await` しないため）。Python 3.9 互換のため `anext()` / `contextlib.aclosing` / `asyncio.TaskGroup` / `asyncio.timeout` は使わない。

### 5.2.1 モデル定数（`models.py`）

```python
from llm_ai_api import llm, models

m = llm(models.OPENAI_GPT6_LUNA)              # "openai:gpt-6-luna"
m = llm(models.ANTHROPIC_CLAUDE_OPUS_5_5)     # "anthropic:claude-opus-5-5"
m = llm(models.OPENROUTER_OPENAI_GPT6_SOL)    # "openrouter:openai/gpt-6-sol"
```

- 値は `llm()` にそのまま渡せる `"プロバイダー:モデル"` 形式の文字列（`str`）。専用の型は作らない。
- 命名規則: `<プロバイダー>_<モデル名>`。モデル名は大文字にして `-` と `.` を `_` に置き換える（`gpt-6.1-sol` → `OPENAI_GPT6_1_SOL`）。OpenRouter は `OPENROUTER_<ベンダー>_<モデル名>`。
- 追加・更新するときは、必ず公式の一覧で実在を確認する（OpenRouter: `https://openrouter.ai/api/v1/models`、OpenAI: `GET /v1/models`、Anthropic: `GET /v1/models`）。推測で書かない。
- 古くなったモデルを削除すると利用者のコードが壊れるため、定数は原則として消さない（API 側で廃止されたものだけ削除する）。
- `OPENAI_*` は OpenAI 直接のモデル ID（OpenRouter の `openai/` 付き ID から接頭辞を除いたもの）。直接 API での実在は、公開一覧がないため API キーで `GET /v1/models` を叩いて確認すること。

### 5.3 クライアント

```python
from llm_ai_api import OpenAIClient, OpenRouterClient, AnthropicClient

client = AnthropicClient(
    api_key=None,          # None なら環境変数 ANTHROPIC_API_KEY
    base_url=None,         # None なら環境変数 ANTHROPIC_BASE_URL、なければ既定値
    timeout=600.0,         # 秒
    max_retries=2,
    headers=None,          # 追加ヘッダー（dict）
    cache=CACHE_NOT_SET,   # 応答キャッシュ（未指定ならグローバル設定。5.7 を参照）
    log=LOG_NOT_SET,       # 入出力ログ（未指定ならグローバル設定。5.8 を参照）
    anthropic_version="2026-10-21",  # AnthropicClient のみ
)
```

- `OpenRouterClient` は追加で `app_url`（→ `HTTP-Referer`）、`app_name`（→ `X-Title`）を受け取れる。
- API キーが見つからない場合は、リクエスト時ではなく **クライアント生成時** に `LLMConfigError` を送出する。
- API キーを `repr()` やログ、例外メッセージに含めない。`repr()` に出す `base_url` は、userinfo（`user:pass@`）を `***` に置き換え、クエリ文字列とフラグメントを除いてマスクする。
- クライアントは内部に `httpx.Client` を 1 つ持って再利用する。`close()` とコンテキストマネージャに対応する。

環境変数:

| 変数 | 用途 |
|---|---|
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | OpenAI |
| `OPENROUTER_API_KEY` / `OPENROUTER_BASE_URL` | OpenRouter |
| `GEMINI_API_KEY`（なければ `GOOGLE_API_KEY`） / `GOOGLE_BASE_URL` | Google Gemini |
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

| 項目 | OpenAI | OpenRouter | Google | Anthropic |
|---|---|---|---|---|
| `role: system` | そのまま送信 | そのまま送信 | そのまま送信 | messages から取り出して連結し、トップレベル `system` に設定 |
| `max_tokens` | `max_completion_tokens` として送信 | `max_tokens` として送信 | `max_tokens` として送信 | `max_tokens`（必須。未指定時 16000） |
| `content` | 文字列またはパーツ配列をそのまま | 同左 | 同左 | 同左（Claude 形式のブロック配列をそのまま） |
| ストリーミング | `stream: true` と `stream_options: {"include_usage": true}` を付与 | `stream: true` | `stream: true` | `stream: true` |

- Google は OpenAI 互換エンドポイントを使うため、OpenAI 系の共通実装（`OpenAICompatClient`）を継承する。Google が互換エンドポイントを変更・廃止した場合は、ネイティブ API（`:generateContent`、`contents[]` / `systemInstruction` / `generationConfig.maxOutputTokens`）に切り替える。切り替えても `llm("google:...")` の使い方は変えない。
- Google の `max_tokens` と `stream_options` の扱いは、実際の API で未確認（ライブテストで確かめる）。

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

### 5.7 キャッシュ（`cache.py`）

- **既定はオフ**。有効にすると、同じリクエストへの 2 回目以降は API を呼ばず、保存済みの結果を返す。
- グローバル設定: `set_cache(cache)` / `get_cache()`。`set_cache(None)` でオフに戻す（環境変数より優先）。環境変数 `LLM_AI_API_CACHE_DIR` にディレクトリを指定すると、`set_cache()` を呼ばなくても `<dir>/cache.db` でオンになる。
- インスタンスごとの設定: `llm(..., cache=...)` と各クライアントの `cache=...`。値は `True`（既定ファイル `llm_ai_api_cache.db`）、パス（`str` / `os.PathLike`）、`SQLiteCache`（同等のオブジェクトも可。インターフェイスは `get(key) -> ChatResult | None` と `put(key, provider, result)`）、`False` / `None`（このインスタンスだけオフ）。引数を渡さなければグローバル設定に従う（内部のセンチネル `CACHE_NOT_SET`）。
- **キー**: `sha256("{provider}:{model}@{api_key}>>>{input}")`。`input` は、リクエストボディと、応答に影響するクライアント設定（`base_url`、追加ヘッダー、Anthropic の `anthropic_version`）の正規化 JSON（`sort_keys=True`）。ストリームかどうかはボディの `stream` で区別される。API キーはハッシュと暗号鍵の導出にだけ使い、平文では保存しない。API キーが違うクライアント同士はキャッシュを共有しない。
- **値**: `ChatResult`（text / model / stop_reason / usage / raw）を JSON にして、API キーから導出した鍵で暗号化し、SQLite のテーブル `llm_cache` に入れる。ストリームは `raw["events"]` に SSE イベントの一覧を入れた `ChatResult` として保存する。
- **暗号**: 標準ライブラリだけで組む（`scrypt` による鍵導出、HMAC-SHA256 のカウンターモード、HMAC による改ざん検出）。平文のまま置かないための保護で、API キーの管理に代わるものではない。鍵は API キーから作るので、API キーを持つ人はキャッシュを読める。MAC にはキャッシュキーも含め（別の行への暗号文の差し替えを検出する）、`secret` を渡して読むときは暗号化形式以外（平文の値）を受け付けない。`SQLiteCache.get/put` に `secret` を渡さなければ暗号化しない（クライアント経由では常に渡す）。
- キャッシュファイルは新規作成時に権限 `0600`（親ディレクトリを作る場合は `0700`）にする（権限を設定できないファイルシステムではベストエフォート）。
- 接続は操作ごとに開閉し、書き込みはロックで保護する。壊れた行・改ざんされた行はミスとして扱い、読み取り時に削除する。
- **削除**: `clear_cache(days, cache_dir=None)` は `days` 日より古いエントリを消して件数を返す（`days=0` で全削除）。ディレクトリは `cache_dir`、環境変数、グローバルキャッシュの順に探し、なければ `LLMConfigError`（`code="cache_dir_not_set"`）。`SQLiteCache.clear(days=None)` も同じ動き。
- 有効にしている間、同じリクエストには常に同じ保存済み応答が返る。新しい応答が欲しい場合はキャッシュを空にするかオフにする。
- 対象は `chat()` / `ask()` と `stream_chat()` / `stream()`。ストリームは、最後まで（または終端イベントまで）読み切ったときだけ保存し、途中で止めたもの・エラーになったものは保存しない。生レイヤー（`request()` / `request_stream()`）は対象外。
- 実行時のキャッシュの失敗はベストエフォート（読み取りはミス扱い、書き込みは無視）にして、料金を払って得た応答を失わない。設定の誤り（不正な値、使えないパス）は生成時に `LLMConfigError`（`code="invalid_cache"`）を送出する。
- `close()` は渡されたキャッシュを閉じない（グローバルと共有されうるため）。

### 5.8 入出力ログ（`log.py`）

- **既定はオフ**。有効にすると、`chat()` / `ask()` / `stream_chat()` / `stream()` の呼び出しごとに 1 行の JSON を追記する（JSON Lines）。生レイヤー（`request()` / `request_stream()`）は対象外。
- グローバル設定: `set_log(log)` / `get_log()`。`set_log(None)` でオフに戻す（環境変数より優先）。環境変数 `LLM_AI_API_LOG_DIR` にディレクトリを指定すると、`<dir>/llm.jsonl` でオンになる。
- インスタンスごとの設定: `llm(..., log=...)` と各クライアントの `log=...`。値は `True`（既定ファイル `llm_ai_api_log.jsonl`）、パス、`JSONLLog`（`write(provider, model, request, response, *, stream, cached)` を持つオブジェクトも可）、`False` / `None`（このインスタンスだけオフ）。引数を渡さなければグローバル設定に従う（内部のセンチネル `LOG_NOT_SET`）。
- **1 行の内容**: `time`（UTC, ISO 8601）, `provider`, `model`, `stream`, `cached`（キャッシュから返したか）, `request`（送ったボディ）, `response`（生の応答 dict。ストリームは `{"text": 連結したテキスト, "chunks": [生のイベント JSON, ...]}`）。API キーと認証ヘッダーは記録しない。
- ログは平文で、プロンプトと回答がそのまま入る。ファイルは新規作成時に権限 `0600`（親ディレクトリを作る場合は `0700`）にする（ベストエフォート）。
- ストリームは最後まで読み切ったときだけ記録する。エラーになった呼び出しは記録しない。
- 実行時のログの失敗はベストエフォート（無視する）にして、料金を払って得た応答を失わない。設定の誤り（不正な値、書けないパス）は生成時に `LLMConfigError`（`code="invalid_log"`）を送出する。

## 6. HTTP 層の仕様（`_http.py`）

- `httpx.Client` を使う。プロキシは httpx の環境変数対応（`trust_env=True`、`HTTPS_PROXY` 等）に任せる。
- 共通ヘッダー: `Content-Type: application/json`, `Accept: application/json`（ストリーム時 `text/event-stream`）, `User-Agent: llm-ai-api-python/<version>`。
- JSON は `json.dumps(body, ensure_ascii=False).encode("utf-8")` で自前でシリアライズして `content=` に渡す（httpx の `json=` の挙動差に依存しない）。
- タイムアウト既定値は 600 秒（長い生成に対応するため）。接続タイムアウトは 10 秒。
- ストリーミングは `client.stream("POST", ...)` と `response.iter_lines()` を使い、SSE パースは自前で行う。
- `request_stream()` は `httpx.Response` を所有する `_EventStream`（`close()` を持つイテレータ）を返す。最後まで読んだとき・エラー時・`close()` でレスポンスを閉じ、一度も読まずに捨てられた場合も `__del__` で閉じる（素の generator では `finally` が動かず、接続プールが枯渇するため。#25）。
- 例外の変換: `httpx.TimeoutException` → `APITimeoutError`、その他の `httpx.RequestError`（`TransportError` や `DecodingError` など）→ `APIConnectionError`（リトライ対象）。リクエスト組み立て時の `httpx.InvalidURL` → `LLMConfigError`（`code="invalid_url"`、URL は `_mask_url()` でマスクして表示）。httpx の例外をそのまま外に出さない。
- リトライ（自前で実装する）:
  - 対象: 408, 409, 429, 500 以上、および接続エラー・タイムアウト。
  - 既定 2 回。指数バックオフ（0.5 秒起点、上限 8 秒、ジッターあり）。
  - `retry-after` ヘッダーがあれば優先（上限 60 秒）。
  - ストリーミングは、レスポンスを読み始めた後はリトライしない。
- ストリーミングでは、HTTP エラー応答のボディ読み取り（`resp.read()`）もヘッダー受信と同じ例外変換・リトライの対象にする。ここで httpx の例外を外に漏らしてはならない。
- パッケージ内の `llm` は関数（`llm_ai_api.llm`）で、同名のモジュール `llm.py` を隠す。モジュールを直接参照するときは `sys.modules["llm_ai_api.llm"]` を使う。
- エラー時はレスポンスボディを読み、JSON として解釈できれば dict、できなければ文字列として例外に格納する。

### SSE パーサー

- 行単位で読み、空行でイベントを確定する。`event:` / `data:`（複数行は `\n` で連結）を扱う。
- `:` で始まる行はコメントとして無視する（OpenRouter は `: OPENROUTER PROCESSING` を送ってくる）。
- OpenAI 系は `data: [DONE]` で終了。ストリームの途中で `error` フィールドを持つイベント（OpenRouter など）を受け取ったら、空のチャンクとして扱わず `APIStreamError` を送出する（本文は `body` に保持する）。部分的な回答を完成したものと誤認させないため。
- Anthropic は `ping` を無視し、`error` イベントを受け取ったら `APIStreamError` を送出する。`message_stop` で終了。
- `data` が有効な JSON でない場合は、`json.JSONDecodeError` ではなく `LLMError`（`code="invalid_json_response"`）に変換して送出する（`SSEEvent.json()`）。JSON として有効でもオブジェクト（dict）でない場合（配列・数値・文字列・`null`）も同じ扱い。非ストリームのレスポンス本文（`request()`）も同様に、dict でなければ `invalid_json_response`。
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
- 例外メッセージには、API が返したエラーメッセージ（`error.message`）を含める（翻訳せず、そのまま付ける）。
- すべての例外は、言語に依存しない識別子 `code` を持つ。コードで判定するときは、翻訳で変わるメッセージではなく `code` を使う。

  | `code` | 例外 |
  |---|---|
  | `missing_api_key` / `invalid_model_spec` / `unknown_provider` | `LLMConfigError` |
  | `connection_error` | `APIConnectionError` |
  | `timeout` | `APITimeoutError` |
  | `api_error` | `APIStatusError` とそのサブクラス（HTTP ステータスは `status_code`） |
  | `stream_error` | `APIStreamError` |
  | `cache_dir_not_set` | `LLMConfigError`（`clear_cache()` でディレクトリ未指定） |
  | `invalid_cache` | `LLMConfigError`（キャッシュ設定の誤り） |
  | `invalid_log` | `LLMConfigError`（ログ設定の誤り） |
  | `invalid_url` | `LLMConfigError`（ベース URL / パスが URL として不正） |
  | `invalid_json_response` | `LLMError` |

## 7.1 多言語化（`lang/`）

パッケージが自分で作るメッセージ（設定ミス、接続失敗、HTTP エラーの見出しとヒントなど）を、利用者の言語で出す。対応言語は `ja` と `en`。

- **メッセージの置き場所**: `lang/<言語コード>.py` の `MESSAGES`（メッセージ ID → `str.format` 形式のテンプレート）。メッセージ ID は `missing_api_key` のような英小文字のスネークケースで、エラーの `code` と揃える。`gettext` / `.po` は使わない。
- **フォールバック**: `指定された言語 → en → メッセージ ID そのもの`。言語ファイルに ID がなければ英語を使う。英語にもなければ ID を返す（例外にしない）。テンプレートの書式が壊れていたときも次の言語に進む。
- **英語がマスター**: `en.py` が全メッセージ ID を持つ。新しいメッセージは、まず `en.py` に追加し、他の言語は後から足してよい。他言語にだけ存在する ID を作らない。
- **言語の追加**: `lang/<コード>.py` を 1 つ作るだけでよい（登録は不要。初回に `importlib` で自動的に読み込まれる）。言語コードは 2〜3 文字の小文字。
- **言語の決め方**（優先順）: `lang=` 引数（`llm(..., lang="en")`、各クライアント） → `set_language()` → 環境変数 `LLM_AI_API_LANG` → `LANGUAGE`（`ja:en` のようなコロン区切りで、対応している最初のもの） → `LC_ALL` → `LC_MESSAGES` → `LANG`（最初に設定されているもの。`C` / `POSIX` は英語） → `locale.getlocale()` → 英語。macOS の GUI の言語設定を読むための外部コマンドは使わない。
- **翻訳しないもの**: API が返した `error.message`、プロバイダー名、モデル名、パラメータ名。
- **ヒント**: HTTP エラーには、原因の見当がつくものだけ、メッセージの 2 行目に `ヒント: ...` を付ける（400 / 401 / 403 / 404 / 429 / 5xx）。
- メッセージは `t(msg_id, lang, **params)` で作る。例外クラスや呼び出し側に、文章を直接書かない。
- 公開 API: `set_language(lang)`, `get_language()`（`llm_ai_api` から import できる）。

## 8. 対応 Python バージョン・パッケージング

- Python 3.9 以上。型ヒントは `from __future__ import annotations` を使い、3.9 で動く書き方にする。
- `pyproject.toml` の `dependencies` は `httpx>=0.27,<1` のみ。httpx の新しいメジャーバージョンが出たら、動作確認してから上限を上げる。
- ビルドバックエンドは setuptools。`py.typed` を同梱する。
- バージョンは `pyproject.toml` と `src/llm_ai_api/__init__.py` の `__version__` の 2 か所で管理し、必ず同時に更新する。

## 9. テスト

- テストフレームワークは標準の `unittest`。実行: `PYTHONPATH=src python -m unittest discover -s tests -t .`（`pip install -e .` 済みなら `PYTHONPATH` は不要）
- テスト共通のヘルパーは `tests/helpers.py`（`Recorder` が送信内容を記録して応答を返す）。
- ユニットテストはネットワークに出ない。`httpx.MockTransport` を使って、送信内容の検証と応答の差し替えを行う。
- 最低限テストすること:
  - 共通インターフェイス: モデル指定文字列の分割（`:` を含むモデル名）、別名、エラー、既定値と呼び出しごとの上書き
  - 送信ボディ: 未指定パラメータが送られないこと、`extra` が最後にマージされること、system メッセージの変換、`max_tokens` の名前変換
  - ヘッダー: 認証ヘッダー、`anthropic-version`、追加ヘッダー
  - SSE: 複数行 data、コメント行、`[DONE]`、`ping`、`error` イベント、改行コード `\r\n`
  - エラー: ステータスコードごとの例外クラス、JSON/非 JSON のエラーボディ、リトライと `retry-after`、httpx 例外の変換
  - 多言語化: 言語判定の優先順位、フォールバック（言語 → en → ID）、ja が en にない ID を持たないこと、テンプレートの引数が言語間で一致すること、コード中のメッセージ ID が `en.py` に存在すること
  - テストは実行環境のロケールに依存してはならない。メッセージを検証するときは `lang=` を明示する
- ライブテスト（`tests/test_live.py`）は `LLM_AI_API_LIVE=1` かつ各 API キーがあるときだけ実行する。課金が発生するため `max_tokens` を小さくする。

## 10. コーディング規約

- `httpx` と標準ライブラリ以外を import しない（これに違反する変更は受け入れない）。
- 公開関数・クラスには型ヒントと docstring を付ける。
- **ソースコード中のコメントと docstring は英語で書く**（`src/`、`tests/`、`examples/` のすべて）。理由: 海外の利用者・コントリビューターも読めるようにするため。
  - 対象外: ユーザーに見せる文言は `lang/<言語コード>.py` に置く（それぞれの言語で書く）。コード中に日本語などの文章を直接書かない。
  - 対象外: テストデータとして日本語の文字列を使うのは構わない（日本語の入出力を検証するため）。
  - 既存のコードに日本語のコメントが残っている場合は、そのファイルを触るついでに英語にする。新しく書くコメントは英語にする。
- 公開 API は `__init__.py` で明示的に re-export し、それ以外は内部扱い（`_` 始まり）とする。
- ユーザーに見えるメッセージを追加・変更したら、`lang/en.py` と `lang/ja.py` を更新する。
- 公開 API を変更したら README-ja.md、README.md とこのファイルを同時に更新する。
- **README-ja.md（日本語）が元で、README.md（英語）はその翻訳**。README-ja.md を変更したら、同じコミットで README.md にも同じ内容を英語で反映する（片方だけの変更はしない）。見出しの順序・コード例・リンクを両者で揃える。PyPI に表示されるのは README.md。そのため README.md 内のリポジトリ内ファイル・ディレクトリへのリンク（日本語 README、docs、examples など）は、PyPI からも開けるよう `https://github.com/kujirahand/llm-ai-api-python/blob/main/...` またはディレクトリ用の `.../tree/main/...` の絶対 URL にする。相対リンクは使わない。
- フォーマットは PEP 8 に準拠（ツールは強制しない）。

## 11. 公式 API 仕様の参照先

仕様に迷ったら以下の公式ドキュメントを確認すること（推測で実装しない）。

- OpenAI Chat Completions: https://platform.openai.com/docs/api-reference/chat
- OpenRouter: https://openrouter.ai/docs/api-reference/overview
- Anthropic Messages: https://docs.claude.com/en/api/messages
- Anthropic API バージョン: https://platform.claude.com/docs/en/api/versioning
