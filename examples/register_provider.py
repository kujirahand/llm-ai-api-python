"""Add your own provider with register_provider() and call it like a built-in one.

Usage:
    python examples/register_provider.py MODEL_NAME

This registers an OpenAI-compatible server under the name "mybox". Point it at
your server with MYBOX_BASE_URL (default: a local server on port 8080) and, if the
server wants a key, MYBOX_API_KEY. The model can also be set with MYBOX_MODEL.

Registration is process-wide, so do it once at startup, before the first llm() call.
"""

import os
import sys

from llm_ai_api import llm, register_provider


model = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("MYBOX_MODEL")
if not model:
    sys.exit(
        "Usage: python examples/register_provider.py MODEL_NAME\n"
        "Alternatively, set MYBOX_MODEL."
    )

register_provider(
    "mybox",
    base_url="http://127.0.0.1:8080/v1",  # default; MYBOX_BASE_URL overrides it
    base_url_env="MYBOX_BASE_URL",
    api_key_env="MYBOX_API_KEY",
    api_key_required=False,  # a server without authentication also works
)

with llm(f"mybox:{model}") as client:
    print("[ask]")
    print(client.ask("Reply with a short greeting."))

    print("\n[ask_stream]")
    for piece in client.ask_stream("Reply with a short greeting."):
        print(piece, end="", flush=True)
    print()
