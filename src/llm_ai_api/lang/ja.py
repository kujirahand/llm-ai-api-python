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
    "invalid_cache": "キャッシュの設定が正しくありません: {detail}",
    "unknown_provider": "未知のプロバイダーです: {provider!r}（対応: {supported}）",
    # 通信
    "timeout": "リクエストがタイムアウトしました。timeout= を大きくするか、ネットワークを確認してください。",
    "connection_error": "API に接続できませんでした: {detail}",
    "stream_timeout": "ストリームの読み取りがタイムアウトしました。",
    "stream_connection_error": "ストリームの読み取りに失敗しました: {detail}",
    "invalid_json_response": "レスポンスが正しい JSON ではありません: {preview!r}",
    # API エラー
    "api_error": "{provider} API がエラーを返しました (HTTP {status})",
    "stream_error": "{provider} のストリームでエラーが発生しました",
    "hint_400": (
        "ヒント: リクエスト内容を確認してください。モデルによっては temperature などを"
        "デフォルト値でも受け付けません。指定を外してみてください。"
    ),
    "hint_401": "ヒント: API キーが正しいか、期限切れや無効化されていないか確認してください。",
    "hint_403": "ヒント: この API キーには、このモデルや機能を使う権限がない可能性があります。",
    "hint_404": "ヒント: モデル名とベース URL が正しいか確認してください。",
    "hint_429": "ヒント: レート制限または利用上限に達しています。しばらく待って再実行するか、プランと課金設定を確認してください。",
    "hint_server": "ヒント: サービス側の問題かもしれません。しばらく待って再実行してください。",
}
