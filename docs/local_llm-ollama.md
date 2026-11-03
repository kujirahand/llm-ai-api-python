# Using Ollama (local LLM server)

日本語: [local_llm-ollama-ja.md](local_llm-ollama-ja.md)

Ollama runs models on your own machine and serves an OpenAI-compatible API. This page explains how to call it from `llm-ai-api`, both from the same machine and from another machine on your LAN.

## 1. Quick start (same machine)

```python
from llm_ai_api import llm

m = llm("ollama:gemma4:e2b")  # "ollama:<model name>"
print(m.ask("Suggest a cute name for a dog"))
```

Model names usually carry a tag with a colon (`gemma4:e2b`). That is not a problem: only the **first** `:` splits the provider from the model, so `"ollama:gemma4:e2b"` means provider `ollama`, model `gemma4:e2b`.

Without any settings, the client connects to `http://localhost:11434/v1` and sends `ollama` as the API key. Ollama ignores that value, so no key is needed.

### Starting the server and getting a model

The macOS and Windows apps keep a server running in the menu bar. From the command line, start one with `ollama serve`. To see what you can call, and to pull a model:

```sh
ollama list                 # model names to use in "ollama:<model name>"
ollama pull gemma4:e2b      # download a model
ollama --version
```

## 2. Settings

| Environment variable | Meaning | Default |
|---|---|---|
| `OLLAMA_BASE_URL` | Base URL of the Ollama API (include `/v1`) | `http://localhost:11434/v1` |
| `OLLAMA_API_KEY` | API key. Optional, and not checked by the local server (see note 3). Only needed for Ollama's hosted API or for a proxy you put in front | `ollama` (sent when unset) |
| `OLLAMA_MODEL` | Model name. Only used by `examples/local-llm-ollama.py`; the library has no default model | none |

You can also pass them as arguments: `llm("ollama:gemma4:e2b", base_url="...", api_key="...")`.

## 3. Connecting over the LAN

Ollama binds `127.0.0.1` port `11434` by default, so other machines cannot connect until you change the bind address with `OLLAMA_HOST`. On macOS, when Ollama runs as an app, set it with `launchctl` and restart Ollama:

```sh
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"   # then restart the Ollama app
```

Then, on the other machine:

```sh
export OLLAMA_BASE_URL="http://192.168.1.20:11434/v1"
export OLLAMA_MODEL="gemma4:e2b"
```

```python
import os
from llm_ai_api import llm

m = llm(f"ollama:{os.environ['OLLAMA_MODEL']}")  # base_url comes from the environment
print(m.ask("Hello"))
```

Or run the bundled example:

```sh
python examples/local-llm-ollama.py "$OLLAMA_MODEL"
```

### Notes

1. **Include `/v1` in `OLLAMA_BASE_URL`.** The library appends `/chat/completions` to it. `http://localhost:11434` alone is Ollama's own native API, which this provider does not call.
2. **The local server has no authentication.** Anyone who can reach the port can run your models. Before binding `0.0.0.0`, make sure the network is one you trust, and keep a firewall in front of it.
3. **There is no API key authentication to turn on.** Ollama documents the local API as needing no authentication, and it checks no key: requests with no `Authorization` header, with the placeholder this library sends, and with a random string all succeed (checked against Ollama 0.40.13 on 2026-11-03). There is no flag and no environment variable that makes the local server require one. Set `OLLAMA_API_KEY` only when something in front of Ollama expects one — a proxy (see below) — or when you point the base URL at Ollama's hosted API, which does check keys.
4. **The first request is slow** because Ollama loads the model into memory. Raise `timeout=` for large models.
5. **The context window is Ollama's default (4096 tokens) unless you raise it** — for example `OLLAMA_CONTEXT_LENGTH=8192 ollama serve`. Short or cut-off answers usually come from that, not from this library.
6. **Use the address the server machine reports.** `192.168.1.20` is a placeholder.

### Putting a key in front of Ollama

Because the server itself cannot check a key, the usual way to protect a network-reachable Ollama is to keep it bound to `127.0.0.1` and run a reverse proxy that checks the `Authorization: Bearer <key>` header, which this library already sends from `OLLAMA_API_KEY` / `api_key=`. A minimal nginx check:

```nginx
server {
    listen 443 ssl;
    server_name ollama.example.com;

    location / {
        if ($http_authorization != "Bearer <a long random token>") {
            return 401;
        }
        proxy_pass http://127.0.0.1:11434;
        proxy_read_timeout 600s;   # streamed answers can run for minutes
    }
}
```

Then point the client at the proxy and put the token in the key:

```sh
export OLLAMA_BASE_URL="https://ollama.example.com/v1"
export OLLAMA_API_KEY="<a long random token>"
```

Requests without the token come back as 401 `AuthenticationError`, which is the one case where a local Ollama call can fail with a status this library reports as an authentication error.

## 4. Troubleshooting

| Symptom | What to check |
|---|---|
| `APIConnectionError` (`code="connection_error"`) right away | The server is not running (`ollama serve`, or the app in the menu bar), the port is wrong, or `OLLAMA_HOST` was not set for LAN access. |
| 404 `NotFoundError`, `model '...' not found` | That name is not pulled locally. Run `ollama list` and use the exact name, or `ollama pull <model>`. |
| 401 `AuthenticationError` from a "local" server | The local server ignores keys and cannot return this. The base URL points somewhere that checks them: Ollama's hosted API, or a proxy in front of Ollama (see above). Set `OLLAMA_API_KEY` / `api_key=`, or fix the base URL. |
| Answers stop early | The context window or the output limit was reached. Raise the server's `OLLAMA_CONTEXT_LENGTH`, or check `stop_reason` and `usage` with `chat()`. |
| `APITimeoutError` | The model is still loading, or the machine is unreachable. Raise `timeout=`. |
| Works locally, fails over the LAN | See notes 2 and 3 above, and check the firewall. |

To test the connection without this library:

```sh
curl "$OLLAMA_BASE_URL/models"
```

If `curl` fails too, the problem is in the network or Ollama's settings, not in `llm-ai-api`.

## 5. Other usage

Streaming, `chat()` with a message list, and raw requests work the same as for the other providers. See the [tutorial](tutorial.md) and the [API reference](api.md). The provider runs on `OpenAICompatClient`, so `max_tokens` is sent as `max_tokens`.

Ollama also offers hosted models through `https://ollama.com/v1`. Point the base URL there and put the key from your Ollama account in `OLLAMA_API_KEY`:

```sh
export OLLAMA_BASE_URL="https://ollama.com/v1"
export OLLAMA_API_KEY="<your Ollama key>"
```
