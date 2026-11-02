"""Try ask(), chat(), and ask_stream() with a local Strata API.

Usage:
    STRATA_BASE_URL=http://127.0.0.1:8080/v1 python examples/local-llm-strata.py MODEL_NAME

Set STRATA_BASE_URL to the server's base URL. STRATA_API_KEY is optional.
The model can also be set with STRATA_MODEL.
"""

import os
import sys

from llm_ai_api import llm


model = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("STRATA_MODEL")
if not model:
    sys.exit(
        "Usage: STRATA_BASE_URL=URL python examples/local-llm-strata.py MODEL_NAME\n"
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
