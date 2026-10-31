"""Print a reply as it is generated (streaming).

Usage: python examples/hello_stream.py PROVIDER:MODEL
"""

from _common import get_model_spec

from llm_ai_api import llm

m = llm(get_model_spec())
for piece in m.ask_stream("Say hello, then tell me a two-sentence story about a dog."):
    print(piece, end="", flush=True)
print()
