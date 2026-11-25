# Tool calls and thinking

[日本語](tools-ja.md)

`LLM.chat()` / `LLM.achat()` accept `tools=`, and `ChatResult` exposes the tool calls and the reasoning text of a response. The library only reads these from the response and builds the messages for one round trip with the **same provider**. It does not run tools or loop for you, and it does not manage history. Streaming (`ask_stream()` / `chat_stream()` and friends) is not supported: the stream's `result` keeps the defaults (`tool_calls=[]`, `thinking=None`, `message=None`).

## `tools=`

A list of dicts with only these keys:

| Key | Required | Meaning |
|---|---|---|
| `name` | yes | Non-empty string |
| `description` | no | String |
| `parameters` | no | JSON Schema dict (`{"type": "object", "properties": {}}` when omitted) |

Anything else raises `LLMConfigError(code="invalid_tools")`. The library maps it to the provider's format and puts it in `extra`:

- OpenAI-style: `{"type": "function", "function": {"name", "description", "parameters"}}`
- Anthropic: `{"name", "description", "input_schema"}`

A `tools` key in your own `extra` wins. For anything else (built-in tools, `tool_choice`, ...) write the provider's JSON in `extra` or use the raw layer. `ask()` family does not take `tools=`.

## Round trip

```python
from llm_ai_api import llm

m = llm("anthropic:claude-opus-5-5")   # works the same with "openai:..."
tools = [{
    "name": "get_weather",
    "description": "Get the weather of a city",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]},
}]
history = [{"role": "user", "content": "What's the weather in Tokyo?"}]

result = m.chat(history, tools=tools, max_tokens=1024)
while result.tool_calls:
    history.append(result.message)                      # the assistant message, unchanged
    outputs = [(call, get_weather(**(call.arguments or {}))) for call in result.tool_calls]
    history += m.tool_results(outputs)                  # provider-format tool results
    result = m.chat(history, tools=tools, max_tokens=1024)
print(result.text)
```

(`get_weather` is your own function. Add a loop limit in real code.)

## `ToolCall`

| Field | Meaning |
|---|---|
| `id` | The provider's id, or `None` (never invented) |
| `name` | Tool name (elements without a name are skipped; they remain in `raw`) |
| `arguments` | Parsed dict, or `None` if the arguments are not a JSON object (never raises) |
| `arguments_raw` | The JSON string as sent |
| `type` | Raw value: `"function"`, `"custom"`, `"tool_use"`, ... |
| `raw` | The original element |

Anthropic `server_tool_use` blocks are not included (see `message` / `raw`).

## `tool_results()`

`m.tool_results([(call_or_id, output), (call_or_id, output, is_error), ...])`

- `call_or_id`: a `ToolCall`, an id string, or `None` (no id is written).
- `output`: a string is used as is; anything else is `json.dumps(..., ensure_ascii=False)`.
- Anthropic: one `user` message with `tool_result` blocks; `is_error: true` only when `is_error` is true.
- OpenAI-style: one `{"role": "tool", "tool_call_id", "content"}` message per call; `is_error` is ignored.
- Bad shapes raise `LLMConfigError(code="invalid_tools")`.

## `message`

`ChatResult.message` is a deep copy of the assistant message in the provider's format (OpenAI-style: `choices[0].message`; Anthropic: `{"role": "assistant", "content": [...]}`). Append it to the history **as is**. Do not edit it: Anthropic checks the `signature` of `thinking` blocks, and with extended thinking plus tool use the thinking blocks must be sent back unchanged. It is `None` when the response has none.

## `thinking`

A string, or `None`.

- OpenAI-style: `message.reasoning_content`, else `message.reasoning` (non-empty strings only).
- Anthropic: the `thinking` text of `thinking` blocks joined with a blank line. `redacted_thinking` is not included.

It is not part of `text`; the original is still in `raw` and `message`.

## Asking for thinking

The library has no common argument for this. Write each provider's format in `extra`:

| Provider | `extra` example |
|---|---|
| Anthropic | `{"thinking": {"type": "enabled", "budget_tokens": 2048}}` |
| OpenAI | `{"reasoning_effort": "medium"}` |
| OpenRouter | `{"reasoning": {"effort": "medium"}}` |

Check the provider's documentation for current names and which models support them.

## Limits

- History is not portable between providers. Send `message` and `tool_results()` output back only to the provider that produced them.
- `tool_calls`, `thinking` and `message` are not stored in the response cache; on a cache hit they are rebuilt from `raw`.
- With `schema=` and `tools=` together, a response that has tool calls is returned without validation (`parsed` is `None`).
