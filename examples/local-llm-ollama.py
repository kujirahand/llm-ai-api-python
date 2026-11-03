"""Try ask(), chat(), and ask_stream() with a local Ollama server.

Usage:
    python examples/local-llm-ollama.py gemma4:e2b

The library default (http://localhost:11434/v1) matches Ollama's local port,
so no settings are needed on the machine that runs Ollama. Set OLLAMA_BASE_URL
when the server runs on another machine or listens on another port. OLLAMA_API_KEY
is optional: Ollama accepts any key unless a proxy in front of it needs one.
The model can also be set with OLLAMA_MODEL.
"""

import os
import sys

from llm_ai_api import llm


model = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("OLLAMA_MODEL")
if not model:
    sys.exit(
        "Usage: python examples/local-llm-ollama.py MODEL_NAME\n"
        "Alternatively, set OLLAMA_MODEL.\n"
        "List the models you can use with: ollama list"
    )

with llm(f"ollama:{model}") as client:
    print("[ask]")
    print(client.ask("Reply with a short greeting."))

    print("\n[chat]")
    result = client.chat([{"role": "user", "content": "Reply with a short greeting."}])
    print(result.text)

    print("\n[ask_stream]")
    for piece in client.ask_stream("Reply with a short greeting."):
        print(piece, end="", flush=True)
    print()
