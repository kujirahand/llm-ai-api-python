"""Try ask(), chat(), and ask_stream() with a local LM Studio server.

Usage:
    python examples/local-llm-lmstudio.py google/gemma-4-e4b

Start the server first (LM Studio's Developer tab, or `lms server start`).
The library default (http://localhost:1234/v1) matches LM Studio's default
port, so no settings are needed on the machine that runs LM Studio. Set
LMSTUDIO_BASE_URL when the server runs on another machine or listens on
another port. LMSTUDIO_API_KEY is optional: LM Studio accepts any key unless
you turn authentication on. The model can also be set with LMSTUDIO_MODEL.
"""

import os
import sys

from llm_ai_api import llm


model = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LMSTUDIO_MODEL")
if not model:
    sys.exit(
        "Usage: python examples/local-llm-lmstudio.py MODEL_NAME\n"
        "Alternatively, set LMSTUDIO_MODEL.\n"
        "List the models you can use with: lms ls"
    )

with llm(f"lmstudio:{model}") as client:
    print("[ask]")
    print(client.ask("Reply with a short greeting."))

    print("\n[chat]")
    result = client.chat([{"role": "user", "content": "Reply with a short greeting."}])
    print(result.text)

    print("\n[ask_stream]")
    for piece in client.ask_stream("Reply with a short greeting."):
        print(piece, end="", flush=True)
    print()
