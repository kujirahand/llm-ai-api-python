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

## ログとキャッシュの注意

画像は base64 で本文に入るため、入出力ログ（`JSONLLog`）とキャッシュには巨大な base64 文字列が残ることがあります。ログに残したくない場合は `JSONLLog(path, redact=...)` のフックで画像パートを取り除いてください（[io_logs-ja.md](io_logs-ja.md)）。
