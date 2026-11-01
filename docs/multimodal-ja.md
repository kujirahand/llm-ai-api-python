# 画像入力（`images=`）

`ask()` / `ask_stream()` / `aask()` / `aask_stream()` はキーワード専用の `images=` を受け取ります。画像をプロバイダーごとの形式に組み立てるのはこの層だけで、プロバイダーレイヤーと生レイヤーは何も変換しません。

```python
from llm_ai_api import llm

m = llm("openai:gpt-6-luna")
print(m.ask("この写真には何が写っていますか？", images=["photo.png"]))
```

## 渡せるもの

`images` は**リスト**で渡します（1 枚でもリスト）。要素は次のいずれかです。

| 要素 | 扱い |
|---|---|
| ファイルのパス（`str` / `os.PathLike`） | ファイルを読み、base64 にして送る |
| `bytes` | そのまま base64 にして送る |
| `http://` または `https://` で始まる文字列 | URL のまま送る（読み込みなし） |

- 画像の種類（media type）は、先頭バイトのシグネチャ（PNG / JPEG / GIF / WEBP）で判定します。分からなければパスの拡張子（`.png` / `.jpg` / `.jpeg` / `.gif` / `.webp`）を使います。それでも分からなければ `LLMConfigError(code="invalid_media")` です。
- 読み込めないファイル、リストでない `images`、不正な型の要素も `invalid_media` です（元の `OSError` は `__cause__` に残ります）。
- プロンプトが文字列でない（messages のリスト）ときに `images` を渡すと `invalid_media` です。どのメッセージに付けるかを推測しないためです。
- `images` が `None` または空なら、リクエストは従来と完全に同じです（content は文字列のまま）。
- ライブラリ独自の枚数・サイズの上限はありません。上限は各プロバイダーの API に従います。

## 送られる形式

user メッセージの `content` は、テキストのパートに続けて画像のパートを指定順に並べた配列になります。

| プロバイダー | ファイル / bytes | URL |
|---|---|---|
| `openai` / `openrouter` / `google` | `{"type": "image_url", "image_url": {"url": "data:<media_type>;base64,<data>"}}` | `{"type": "image_url", "image_url": {"url": "<URL>"}}` |
| `anthropic` | `{"type": "image", "source": {"type": "base64", "media_type": "...", "data": "..."}}` | `{"type": "image", "source": {"type": "url", "url": "<URL>"}}` |

URL をそのまま受け付けるかどうかは各 API の判断です（ライブラリは止めません）。

## 非同期

`aask()` / `aask_stream()` はファイルの読み込みをワーカースレッドで行うので、イベントループは止まりません。`aask_stream()` は引数の形を呼び出し時に検査し、ファイルは最初の反復で読み込みます（読み込みエラーも最初の反復で出ます）。

## `chat()` ではネイティブの dict を使う

`chat()` / `chat_stream()` に `images=` はありません。画像を含むメッセージを渡すときは、各プロバイダーのネイティブな形式の dict をそのまま `content` に書いてください。ライブラリはプロバイダー間で変換しません。

```python
m.chat([{"role": "user", "content": [
    {"type": "text", "text": "説明して"},
    {"type": "image_url", "image_url": {"url": "https://example.com/cat.png"}},
]}])
```

## 音声の文字起こし（`transcribe()`）

`transcribe(file, *, extra=None, timeout=None) -> str` / `atranscribe()` は、音声を OpenAI の `/audio/transcriptions` に multipart/form-data で送り、文字起こしのテキスト（`str`）を返します。

```python
m = llm("openai:whisper-1")
print(m.transcribe("meeting.mp3"))
print(m.transcribe(wav_bytes, extra={"language": "ja", "timestamp_granularities": ["word", "segment"]}))
```

- 対応は **OpenAI のみ**です。他のプロバイダーでは通信せずに `LLMConfigError(code="unsupported_modality")` を送出します。
- `file` はパス（`str` / `os.PathLike`）または音声の `bytes` です。パスのときはファイル名をそのまま送り、`bytes` のときは `audio.<拡張子>` を使います。形式は先頭バイトのシグネチャ（WAV / MP3 / FLAC / OGG / WEBM / M4A）、だめなら拡張子で判定します。判定できない・読めない・型が違う場合は `invalid_media` です。
- フォームには `model`（`llm()` のモデル）、`response_format=json`、ファイル `file` が入ります。`extra` のキーはフォームフィールドになります。文字列・数値は文字列化、bool は `true` / `false`、リスト・タプルは `キー[]` の繰り返し、`None` は省略です。dict など展開できない値は `invalid_media` です。
- 応答 JSON の `text` を返します。`text` が文字列でなければ `LLMError(code="invalid_json_response")` です。
- 応答キャッシュ・入出力ログ・同時実行のまとめ（singleflight）の**対象外**です。リトライやイベント通知は生レイヤーと同じです。
- `atranscribe()` はファイルをワーカースレッドで読みます。
- `segments` や `duration` を含む詳細な応答が欲しいときは、生レイヤーを使います。

```python
resp = m.client.request(
    "/audio/transcriptions",
    files={"file": ("a.wav", wav_bytes, "audio/wav")},
    form_data=[("model", "whisper-1"), ("response_format", "verbose_json")],
)
```

`request()` の `files=`（フィールド名 → `(ファイル名, bytes, media_type)`）と `form_data=`（`(名前, 値)` のリスト。同じ名前を繰り返せる）を指定するときは `body` を `None` にします（そうでなければ `LLMConfigError(code="invalid_option")`）。`Content-Type` は httpx が boundary 付きで付けます。

## ログとキャッシュの注意

画像は base64 で本文に入るため、入出力ログ（`JSONLLog`）とキャッシュには巨大な base64 文字列が残ることがあります。ログに残したくない場合は `JSONLLog(path, redact=...)` のフックで画像パートを取り除いてください（[io_logs-ja.md](io_logs-ja.md)）。
