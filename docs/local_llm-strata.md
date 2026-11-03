# Using Strata (local / LAN LLM server)

日本語: [local_llm-strata-ja.md](local_llm-strata-ja.md)

Strata is a local LLM server with an OpenAI-compatible API. This page explains how to call it from `llm-ai-api`, both from the same machine and from another machine on your LAN.

## 1. Quick start (same machine)

```python
from llm_ai_api import llm

m = llm("strata:iq3_s")  # "strata:<model name>"
print(m.ask("Suggest a cute name for a dog"))
```

Without any settings, the client connects to `http://127.0.0.1:47831/v1` and sends `local` as the API key. That is the port Strata listens on when sharing is off (see note 1), so no environment variable is needed on the machine that runs Strata. Strata does not need a real key unless you turned authentication on.

## 2. Settings

| Environment variable | Meaning | Default |
|---|---|---|
| `STRATA_BASE_URL` | Base URL of the Strata API (include `/v1`) | `http://127.0.0.1:47831/v1` |
| `STRATA_API_KEY` | API key. Optional: only needed if you set one in Strata | `local` (sent when unset) |
| `STRATA_MODEL` | Model name. Only used by `examples/local-llm-strata.py`; the library has no default model | none |

You can also pass them as arguments: `llm("strata:iq3_s", base_url="...", api_key="...")`.

## 3. Connecting over the LAN

Example of a working setup (from another machine):

```sh
# STRATA API
export STRATA_BASE_URL="http://100.xxx.xxx.xxx:47832/v1"
export STRATA_API_KEY="sk-strata-xxx"
export STRATA_MODEL="iq3_s"
```

```python
import os
from llm_ai_api import llm

m = llm(f"strata:{os.environ['STRATA_MODEL']}")  # base_url and api_key come from the environment
print(m.ask("Hello"))
```

Or run the bundled example:

```sh
python examples/local-llm-strata.py "$STRATA_MODEL"
```

### Notes

1. **The port number changes when you turn on sharing.**
   With sharing off, Strata listens on port `47831` on the local machine only, and that is also this library's default. When you set the local network to "Share" (see note 2), the port becomes `47832`. So the default URL only works on the Strata machine itself: over the LAN, set `STRATA_BASE_URL` to the server's address with port `47832`. If the port does not match, check the address shown in Strata's settings.
2. **Set the local network to "Share" in Strata's service settings.**
   By default Strata only listens on the local machine. Until you change the local network setting to **Share** in the service settings, other machines cannot connect (the connection is refused or times out, and you get `APIConnectionError` / `APITimeoutError`). Remember that the port changes from `47831` to `47832` at the same time (note 1).
3. **The API key is optional.**
   You only need to set `STRATA_API_KEY` (or `api_key=`) if you enabled an API key in Strata. If you did not, leave it unset and the library sends the placeholder `local`. If you did enable one, a missing or wrong key gives a 401 `AuthenticationError`.
4. **Include `/v1` in `STRATA_BASE_URL`.** The library appends `/chat/completions` to it.
5. **Use the address the server shows you.** The `100.x.x.x` form in the example is a private-network address (for example a VPN or overlay network). Use the address that the Strata machine reports, not this placeholder.
6. **Keep the API key secret.** Do not commit real keys to the repository. Put them in your shell profile or a local `.env` that is not tracked.

## 4. Troubleshooting

| Symptom | What to check |
|---|---|
| `APIConnectionError` (`code="connection_error"`) right away | Wrong IP or port. The default `http://127.0.0.1:47831/v1` only reaches Strata on the same machine; over the LAN use the server's address with port `47832`. Also check that the local network is set to "Share" and that a firewall does not block the port. |
| `APITimeoutError` | The machine is unreachable (different network, sleeping), or the model is still loading. Raise `timeout=` if the model is slow to start. |
| 401 `AuthenticationError` | You enabled an API key in Strata, and `STRATA_API_KEY` is missing or wrong. |
| 404 `NotFoundError` | `/v1` is missing from the base URL, or the model name is wrong. Check the name Strata lists. |
| Works locally, fails over the LAN | See notes 1 and 2 above. |

To test the connection without this library:

```sh
curl "$STRATA_BASE_URL/models" -H "Authorization: Bearer $STRATA_API_KEY"
```

If `curl` fails too, the problem is in the network or Strata's settings, not in `llm-ai-api`.

## 5. Other usage

Streaming, `chat()` with a message list, and raw requests work the same as for the other providers. See the [tutorial](tutorial.md) and the [API reference](api.md). The provider runs on `OpenAICompatClient`, so `max_tokens` is sent as `max_tokens`.
