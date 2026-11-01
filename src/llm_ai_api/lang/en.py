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
    "invalid_connection": "Invalid connection setting: {detail}",
    "invalid_url": "Invalid URL: {url}",
    "invalid_messages": "Messages must be a non-empty list of dictionaries.",
    "invalid_media": "Invalid images= argument: {reason}",
    "media_reason_not_list": "pass a list of images, even for a single image.",
    "media_reason_bad_item": "each image must be a file path, bytes, or an http(s) URL string (got {kind}).",
    "media_reason_needs_text": "images= can only be used when the prompt is a string; put the image parts into the messages yourself.",
    "media_reason_unknown_type": "cannot tell the image type (supported: PNG, JPEG, GIF, WEBP): {source}",
    "media_reason_read_error": "cannot read the image file: {source}",
    "invalid_option": "{name} must be a finite number of 0 or more: {value!r}",
    "invalid_schema": "schema= must be a JSON Schema dict or a pydantic-v2-compatible model.",
    "invalid_event": "Unknown event {event!r}. Known events: {known}.",
    "invalid_listener": "An event listener must be callable.",
    "unknown_provider": "Unknown provider: {provider!r} (supported: {supported})",
    "cache_dir_not_set": "Set cache_dir=... or the LLM_AI_API_CACHE_DIR environment variable to choose the cache directory.",
    # 通信
    "timeout": "The request timed out. Try a larger timeout=, or check your network.",
    "connection_error": "Could not connect to the API: {detail}",
    "stream_timeout": "Reading the stream timed out.",
    "stream_connection_error": "Reading the stream failed: {detail}",
    "unclosed_stream": "A stream was garbage-collected without being closed; call aclose() when you stop early.",
    "invalid_json_response": "The response was not valid JSON: {preview!r}",
    "response_too_large": "The response is larger than the size limit ({limit} bytes)",
    # API エラー
    "api_error": "{provider} API error (HTTP {status})",
    "stream_incomplete": "{provider} stream ended without a terminal event",
    "stream_error": "{provider} stream error",
    "output_refused": "{provider} refused the structured output.",
    "output_incomplete": "{provider} did not finish the structured output.",
    "invalid_structured_output": "The response from {provider} could not be read as structured output.",
    "hint_400": (
        "Hint: parameters this library knows the model rejects are omitted before "
        "the request. If this is still HTTP 400, check the request and remove the "
        "other parameters you sent. Some models reject values such as temperature "
        "even at their defaults."
    ),
    "hint_401": "Hint: check that the API key is correct and has not expired or been revoked.",
    "hint_403": "Hint: this API key may not have permission to use this model or feature.",
    "hint_404": "Hint: check the model name and the base URL.",
    "hint_429": "Hint: rate limit or quota exceeded. Wait a while and retry, or check your plan and billing.",
    "hint_server": "Hint: the service may be having trouble. Wait a while and retry.",
}
