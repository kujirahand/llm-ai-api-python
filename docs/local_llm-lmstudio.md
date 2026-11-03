# Using LM Studio (local LLM server)

日本語: [local_llm-lmstudio-ja.md](local_llm-lmstudio-ja.md)

LM Studio runs models on your own machine and serves an OpenAI-compatible API. This page explains how to call it from `llm-ai-api`, both from the same machine and from another machine on your LAN.

## 1. Quick start (same machine)

```python
from llm_ai_api import llm

m = llm("lmstudio:google/gemma-4-e4b")  # "lmstudio:<model name>"
print(m.ask("Suggest a cute name for a dog"))
```

The model name is the one LM Studio shows for the model (for example `google/gemma-4-e4b`); it often contains `/`, which is fine — only the first `:` splits the provider from the model.

Without any settings, the client connects to `http://localhost:1234/v1` and sends `lm-studio` as the API key. LM Studio does not check that value unless you turned on "Require Authentication" (see note 3).

### Starting the server

The server is off until you start it. In the LM Studio app, open the **Developer** tab and start the server. From the command line:

```sh
lms server start      # -p <port> to change the port
lms server status     # "The server is running on port 1234."
lms ls                # model names to use in "lmstudio:<model name>"
```

## 2. Settings

| Environment variable | Meaning | Default |
|---|---|---|
| `LMSTUDIO_BASE_URL` | Base URL of the LM Studio API (include `/v1`) | `http://localhost:1234/v1` |
| `LMSTUDIO_API_KEY` | API key. Optional: only needed if "Require Authentication" is on | `lm-studio` (sent when unset) |
| `LMSTUDIO_MODEL` | Model name. Only used by `examples/local-llm-lmstudio.py`; the library has no default model | none |

You can also pass them as arguments: `llm("lmstudio:google/gemma-4-e4b", base_url="...", api_key="...")`.

## 3. Connecting over the LAN

LM Studio listens on the local machine only until you allow other devices. In the app, turn on **Serve on Local Network** in the server settings; from the command line use `lms server start --bind 0.0.0.0`.

Then, on the other machine:

```sh
export LMSTUDIO_BASE_URL="http://192.168.1.20:1234/v1"
export LMSTUDIO_API_KEY="<your LM Studio API token>"   # only if authentication is on
export LMSTUDIO_MODEL="google/gemma-4-e4b"
```

```python
import os
from llm_ai_api import llm

m = llm(f"lmstudio:{os.environ['LMSTUDIO_MODEL']}")  # base_url and api_key come from the environment
print(m.ask("Hello"))
```

Or run the bundled example:

```sh
python examples/local-llm-lmstudio.py "$LMSTUDIO_MODEL"
```

### Notes

1. **Include `/v1` in `LMSTUDIO_BASE_URL`.** The library appends `/chat/completions` to it.
2. **The model must be downloaded.** `lms ls` lists what is on disk (`lms get <model>` downloads one). An unlisted name is not a model this server can run.
3. **API key: two cases.**
   With "Require Authentication" off (the LM Studio default), no key is needed and the library sends the placeholder `lm-studio`. With it on (LM Studio 0.4.0 or newer), every request must carry a valid token: create one in the server settings under **Manage Tokens → Create Token**, copy it (it is shown once), and put it in `LMSTUDIO_API_KEY`. The placeholder is rejected there with 401, so set a real token before serving over the network.
4. **There is no `request_id`.** LM Studio does not send an `x-request-id` header, so `ChatResult.request_id` is `None` and the `response` event carries `None` too.
5. **Use the address the server machine reports.** `192.168.1.20` is a placeholder; check a firewall if the port is blocked.
6. **Keep the API key secret.** Do not commit real keys to the repository. Put them in your shell profile or a local `.env` that is not tracked.

## 4. Troubleshooting

| Symptom | What to check |
|---|---|
| `APIConnectionError` (`code="connection_error"`) right away | The server is not running (`lms server status`) or the port is wrong. Over the LAN, check that "Serve on Local Network" (or `--bind 0.0.0.0`) is on and that a firewall does not block the port. |
| 401 `AuthenticationError` mentioning an API token | "Require Authentication" is on. Create a token in the server settings and set `LMSTUDIO_API_KEY` (or `api_key=`). The built-in placeholder `lm-studio` is not a token. |
| An error naming the model | The model is not on the server. Run `lms ls` and use the exact name; `lms get <model>` downloads it. |
| `APITimeoutError` | The model is still loading, or the machine is unreachable. Raise `timeout=` for models that are slow to load. |
| Works locally, fails over the LAN | See note 3 (authentication) and the bind address above. |

To test the connection without this library:

```sh
curl "$LMSTUDIO_BASE_URL/models" -H "Authorization: Bearer $LMSTUDIO_API_KEY"
```

If `curl` fails too, the problem is in the network or LM Studio's settings, not in `llm-ai-api`.

## 5. Other usage

Streaming, `chat()` with a message list, and raw requests work the same as for the other providers. See the [tutorial](tutorial.md) and the [API reference](api.md). The provider runs on `OpenAICompatClient`, so `max_tokens` is sent as `max_tokens`. LM Studio also serves its own REST and Anthropic-compatible endpoints; send them with the raw layer (`m.client.request(...)`).
