"""Usage: python examples/ask.py openai:MODEL_NAME "Your question"

Pass the API key via an environment variable
(OPENAI_API_KEY / OPENROUTER_API_KEY / ANTHROPIC_API_KEY).
"""

import sys

from llm_ai_api import llm

spec = sys.argv[1]
question = sys.argv[2] if len(sys.argv) > 2 else "Come up with a cute name for a dog"

m = llm(spec)
print(m.ask(question))
print("---- stream ----")
for piece in m.ask_stream(question):
    print(piece, end="", flush=True)
print()
