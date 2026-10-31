"""Ask for a greeting and stream a reply with the async API.

Usage: python examples/hello_async.py PROVIDER:MODEL
"""

import asyncio

from _common import get_model_spec

from llm_ai_api import llm


async def main(spec):
    # `async with` closes the connections when the block ends.
    async with llm(spec) as m:
        print(await m.aask("Say hello in one short sentence."))

        # astream() is iterated directly with `async for` (no await).
        async for piece in m.astream("Tell me a two-sentence story about a dog."):
            print(piece, end="", flush=True)
        print()


asyncio.run(main(get_model_spec()))
