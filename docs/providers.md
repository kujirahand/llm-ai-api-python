# Adding a provider (`register_provider()`)

日本語: [providers-ja.md](providers-ja.md)

For a service that is not built in, an OpenAI-compatible or Anthropic-compatible API works with one declaration: after that, `llm("<name>:<model>")` calls it. You do not write a subclass, and the same declaration also covers async (`aask()` and friends).

```python
from llm_ai_api import llm, register_provider

register_provider(
    "deepseek",
    base_url="https://api.deepseek.com/v1",
    api_key_env="DEEPSEEK_API_KEY",
)

print(llm("deepseek:deepseek-chat").ask("Hello"))
```

Registration affects the **whole process**. Call it once at application startup. Nothing is registered by merely importing the package, or from environment variables or config files. It returns `None`.

## Examples

```python
# A local server (a placeholder key is enough)
register_provider("localbox", base_url="http://127.0.0.1:8080/v1", api_key_default="local")

# A server that also works without a key (the key is sent when there is one)
register_provider("openbox", base_url="https://llm.example.internal/v1",
                  api_key_env="OPENBOX_KEY", api_key_required=False)

# Authentication that is not Bearer (Azure-style api-key header)
register_provider("corp", base_url="https://llm.example.internal/v1",
                  api_key_env="CORP_LLM_KEY", auth_header="api-key", auth_scheme="")

# An Anthropic-compatible proxy
register_provider("claude-proxy", api_format="anthropic",
                  base_url="https://proxy.example.com", api_key_env="PROXY_KEY")

# An alias
register_provider("deepseek", base_url="https://api.deepseek.com/v1",
                  api_key_env="DEEPSEEK_API_KEY", aliases=("ds",))
llm("ds:deepseek-chat")
```

## Arguments

| Argument | Default | Description |
|---|---|---|
| `name` (positional) | required | The provider name. `^[a-z][a-z0-9_-]{0,31}$` (starts with a lowercase letter, up to 32 characters) |
| `base_url` | required | The API base URL (up to the part before `/chat/completions` or `/v1/messages`) |
| `api_format` | `"openai"` | `"openai"` (`/chat/completions`) or `"anthropic"` (`/v1/messages`) |
| `api_key_env` | `None` | The environment variable that holds the API key. A string, or a tuple (the first has priority, the rest are fallbacks) |
| `base_url_env` | `None` | The environment variable that overrides `base_url` |
| `api_key_default` | `None` | A placeholder key used when none is found (for local servers) |
| `api_key_required` | `True` | With `False`, `llm()` can be created without a key. With no key, no auth header is sent |
| `auth_header` / `auth_scheme` | `"Authorization"` / `"Bearer"` | The name and scheme of the auth header. `auth_scheme=""` sends the bare key as the value. With `api_format="anthropic"` the defaults are `"x-api-key"` / no scheme |
| `headers` | `None` | Fixed extra headers (a dict). The caller's `headers=` overrides them. The auth header wins over a fixed header |
| `max_tokens_field` | `"max_tokens"` | The field name used to send `max_tokens` (`"openai"` format only, for example `"max_completion_tokens"`) |
| `stream_include_usage` | `False` | Add `stream_options: {"include_usage": true}` to streams (`"openai"` format only) |
| `models` | `True` | With `False`, `models()` raises `unsupported_models` |
| `aliases` | `()` | Alternative names. `llm("<alias>:<model>")` works too (the same mechanism as `claude`) |
| `replace` | `False` | With `True`, replaces an earlier definition of the same name **that you registered yourself** |

If you give neither `api_key_env` nor `api_key_default` and keep `api_key_required=True`, pass the key with `api_key=` to `llm()`. When no key is found anywhere, creating the `llm()` raises `LLMConfigError` (`code="missing_api_key"`).

## What works like a built-in provider

A registered provider goes through the same machinery as a built-in one:

- `ask()` / `chat()` / `ask_stream()` / `chat_stream()` and their async versions, `models()` / `amodels()`
- The response cache, the I/O log, [events](events.md), retries, and `request_id`
- `images=` (`image_url` parts for the `"openai"` format, `image` blocks for `"anthropic"`) and `schema=` (`response_format` or `output_config.format`, by format)
- The raw layer (`m.client.request(...)`). Features the common interface does not cover are available there

These differ from the built-in providers:

- **The table of parameters that are not sent does not apply.** The table in [`_model_params.py`](../src/llm_ai_api/_model_params.py) covers only built-in models. Do not pass parameters through `temperature=` or `extra=` that the model on a registered provider rejects. The one exception is a registration with `api_format="anthropic"`: when `anthropic-version` is `2026-10-21`, `temperature` / `top_p` / `top_k` are dropped, as for the built-in Anthropic provider (sending another value with `anthropic_version=` keeps them).
- `transcribe()` (audio transcription) works only for the built-in `openai`. A registered provider raises `unsupported_modality`. Use the raw `request()` if you need it.
- Only OpenAI-compatible and Anthropic-compatible APIs can be registered. An API with its own body format or SSE is not supported. If you want one added, please open an issue.

## Name conflicts and `replace`

| Situation | Result |
|---|---|
| The name or an alias breaks the rule, `base_url` is missing, a type is wrong, `api_format` is unknown, or `max_tokens_field` / `stream_include_usage` is given for the `"anthropic"` format | `LLMConfigError` (`code="invalid_provider"`) |
| The same as a built-in name or alias (`openai`, `anthropic`, `claude`, ...) | `LLMConfigError` (`code="provider_exists"`). **It cannot be overwritten, even with `replace=True`** |
| The same as a name you registered (`replace=False`) | `LLMConfigError` (`code="provider_exists"`) |
| The same as a name you registered (`replace=True`) | The definition is replaced. Its old aliases are removed |
| The same as another registration's name or alias | `LLMConfigError` (`code="provider_exists"`). Not even `replace=True` takes it over |

To only change where a built-in provider connects, use an environment variable such as `OPENAI_BASE_URL`, or `base_url=` on `llm()`.

After a replacement, an `LLM` that already exists keeps using the definition it was created with (including whether `models()` / `amodels()` is supported).

The response cache key includes the fixed headers given in `headers`, in addition to the registered name, `base_url`, and the body that is sent. Changing only the fixed headers with `replace=True` does not return responses stored before the replacement.

## Trust boundary (only trusted code should declare providers)

Declare providers only from trusted code. Do not build a declaration from user input or from an external configuration file.

`api_key_env` accepts any environment variable name. Whoever can create a declaration can therefore send any environment variable of the process (for example cloud credentials) as a credential to the destination given in `base_url`. Together with the fact that `base_url` has no scheme or host restriction, treat a declaration with the same level of trust as a secret.

## About authentication

Only the shape "header name + scheme + key" is supported (Bearer, `x-api-key`, Azure's `api-key`, and so on). Keys in query parameters (easily leaked through URLs into logs and exceptions), request signing (SigV4 and the like), and OAuth token refresh are out of scope. When you need one, pass a short-lived token in `headers=`, or go through a gateway that supports it.

## Notes

- There is no restriction on the scheme or host of `base_url`. API keys and message bodies are sent even to a plain-HTTP external host, so pass only trusted values and do not pass user input straight through ([security notes in the README](../README.md#security-notes)). Use HTTPS for hosted APIs.
- Error messages do not include `base_url`. The `base_url` shown by `repr()` masks userinfo, as for the built-in providers.
- A runnable sample: [`examples/register_provider.py`](../examples/register_provider.py)
