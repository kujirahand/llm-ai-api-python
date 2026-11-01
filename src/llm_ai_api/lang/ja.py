"""日本語のメッセージ。ここにないメッセージ ID は英語（en.py）にフォールバックする。"""

MESSAGES = {
    # 設定
    "missing_api_key": (
        "{provider} の API キーが見つかりません。"
        "api_key=... で渡すか、環境変数 {env} を設定してください。"
    ),
    "invalid_model_spec": (
        'モデルは "プロバイダー:モデル名" の形式で指定してください（例: "openai:gpt-6-luna"）: {spec!r}'
    ),
    "invalid_log": "ログの設定が正しくありません: {detail}",
    "invalid_cache": "キャッシュの設定が正しくありません: {detail}",
    "invalid_connection": "接続設定が不正です: {detail}",
    "invalid_url": "URL が正しくありません: {url}",
    "invalid_messages": "messages は辞書の空でないリストで指定してください。",
    "invalid_media": "images= の指定が正しくありません: {reason}",
    "media_reason_not_list": "画像が 1 枚でもリストで渡してください。",
    "media_reason_bad_item": "画像にはファイルのパス、bytes、http(s) の URL 文字列を指定してください（{kind} が渡されました）。",
    "media_reason_needs_text": "images= はプロンプトが文字列のときだけ使えます。messages には画像パートを自分で入れてください。",
    "media_reason_unknown_type": "画像の種類を判定できません（対応: PNG, JPEG, GIF, WEBP）: {source}",
    "media_reason_read_error": "画像ファイルを読み込めません: {source}",
    "invalid_audio": "音声の指定が正しくありません: {reason}",
    "media_reason_bad_audio": "音声にはファイルのパスまたは bytes を指定してください（{kind} が渡されました）。",
    "media_reason_unknown_audio": "音声の種類を判定できません（対応: WAV, MP3, FLAC, OGG, WEBM, M4A）: {source}",
    "media_reason_audio_read_error": "音声ファイルを読み込めません: {source}",
    "media_reason_bad_extra": "extra[{key!r}] はフォームフィールドとして送れません（{kind} が渡されました）。文字列・数値・bool、またはそのリストを指定してください。",
    "unsupported_modality": "{provider} では、このライブラリ経由の {modality} は使えません（対応は OpenAI のみ）。API が対応していれば生レイヤー（client.request）を使ってください。",
    "invalid_multipart_body": "files= または form_data= を指定するときは body を None にしてください。",
    "invalid_option": "{name} には 0 以上の有限の数を指定してください: {value!r}",
    "invalid_schema": "schema= には JSON Schema の dict または pydantic v2 互換のモデルを指定してください。",
    "invalid_event": "未知のイベントです: {event!r}（使えるイベント: {known}）",
    "invalid_listener": "イベントリスナーは呼び出し可能である必要があります。",
    "unknown_provider": "未知のプロバイダーです: {provider!r}（対応: {supported}）",
    "cache_dir_not_set": "cache_dir=... か環境変数 LLM_AI_API_CACHE_DIR で、キャッシュのディレクトリを指定してください。",
    # 通信
    "timeout": "リクエストがタイムアウトしました。timeout= を大きくするか、ネットワークを確認してください。",
    "connection_error": "API に接続できませんでした: {detail}",
    "stream_timeout": "ストリームの読み取りがタイムアウトしました。",
    "stream_connection_error": "ストリームの読み取りに失敗しました: {detail}",
    "unclosed_stream": "閉じられていないストリームが回収されました。途中でやめるときは aclose() を呼んでください。",
    "invalid_json_response": "レスポンスが正しい JSON ではありません: {preview!r}",
    "response_too_large": "レスポンスがサイズの上限（{limit} バイト）を超えました",
    # API エラー
    "api_error": "{provider} API がエラーを返しました (HTTP {status})",
    "stream_incomplete": "{provider} のストリームが終端イベントなしで終了しました",
    "stream_error": "{provider} のストリームでエラーが発生しました",
    "output_refused": "{provider} が構造化出力を拒否しました。",
    "output_incomplete": "{provider} の構造化出力が完了しませんでした。",
    "invalid_structured_output": "{provider} の応答を構造化出力として読み取れませんでした。",
    "hint_400": (
        "ヒント: このライブラリが拒否を知っているパラメータは、送信前に省かれます。"
        "それでも HTTP 400 のときは、リクエスト内容を確認し、送っているほかのパラメータを"
        "外してください。モデルによっては temperature などをデフォルト値でも受け付けません。"
    ),
    "hint_401": "ヒント: API キーが正しいか、期限切れや無効化されていないか確認してください。",
    "hint_403": "ヒント: この API キーには、このモデルや機能を使う権限がない可能性があります。",
    "hint_404": "ヒント: モデル名とベース URL が正しいか確認してください。",
    "hint_429": "ヒント: レート制限または利用上限に達しています。しばらく待って再実行するか、プランと課金設定を確認してください。",
    "hint_server": "ヒント: サービス側の問題かもしれません。しばらく待って再実行してください。",
}
