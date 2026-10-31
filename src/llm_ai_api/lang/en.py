"""English messages. This is the fallback catalog: every message ID must exist here."""

MESSAGES = {
    # 設定
    "missing_api_key": (
        "No API key found for {provider}. "
        "Pass api_key=... or set the {env} environment variable."
    ),
    "invalid_model_spec": (
        'Specify the model as "provider:model" (e.g. "openai:gpt-6-luna"): {spec!r}'
    ),
    "invalid_log": "Invalid log setting: {detail}",
    "invalid_cache": "Invalid cache setting: {detail}",
    "unknown_provider": "Unknown provider: {provider!r} (supported: {supported})",
    "cache_dir_not_set": "Set cache_dir=... or the LLM_AI_API_CACHE_DIR environment variable to choose the cache directory.",
    # 通信
    "timeout": "The request timed out. Try a larger timeout=, or check your network.",
    "connection_error": "Could not connect to the API: {detail}",
    "stream_timeout": "Reading the stream timed out.",
    "stream_connection_error": "Reading the stream failed: {detail}",
    "invalid_json_response": "The response was not valid JSON: {preview!r}",
    # API エラー
    "api_error": "{provider} API error (HTTP {status})",
    "stream_error": "{provider} stream error",
    "hint_400": (
        "Hint: check the request. Some models reject parameters such as temperature "
        "even at their default value; try not passing them."
    ),
    "hint_401": "Hint: check that the API key is correct and has not expired or been revoked.",
    "hint_403": "Hint: this API key may not have permission to use this model or feature.",
    "hint_404": "Hint: check the model name and the base URL.",
    "hint_429": "Hint: rate limit or quota exceeded. Wait a while and retry, or check your plan and billing.",
    "hint_server": "Hint: the service may be having trouble. Wait a while and retry.",
}
