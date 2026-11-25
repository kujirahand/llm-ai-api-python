"""Print a reply as it is generated (streaming).

Usage: python examples/hello_stream.py PROVIDER:MODEL
"""

from _common import get_model_spec

from llm_ai_api import llm

m = llm(get_model_spec())
stream = m.ask_stream("Say hello, then tell me a two-sentence story about a dog.")
for piece in stream:
    print(piece, end="", flush=True)
print()

# Once the stream has been read to the end, `result` holds the whole response.
if stream.result is not None:
    print("stop_reason:", stream.result.stop_reason)
    print("usage:", stream.result.usage)
