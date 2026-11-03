"""Try ask(), chat(), and ask_stream() with a local Strata API.

Usage:
    python examples/local-llm-strata.py $STRATA_MODEL

The library default (http://127.0.0.1:47831/v1) matches Strata's local port,
so no settings are needed on the machine that runs Strata. Set STRATA_BASE_URL
when the server runs on another machine (port 47832 with sharing on) or listens
on another port. STRATA_API_KEY is optional. The model can also be set with
STRATA_MODEL.
"""

import os
import sys

from llm_ai_api import llm


model = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("STRATA_MODEL")
if not model:
    sys.exit(
        "Usage: python examples/local-llm-strata.py MODEL_NAME\n"
        "Alternatively, set STRATA_MODEL."
    )

with llm(f"strata:{model}") as client:
    print("[ask]")
    print(client.ask("Reply with a short greeting."))

    print("\n[chat]")
    result = client.chat([{"role": "user", "content": "Reply with a short greeting."}])
    print(result.text)

    print("\n[ask_stream]")
    for piece in client.ask_stream("Reply with a short greeting."):
        print(piece, end="", flush=True)
    print()
