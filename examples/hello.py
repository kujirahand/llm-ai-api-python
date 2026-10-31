"""Ask the model for a greeting.

Usage: python examples/hello.py PROVIDER:MODEL
"""

from _common import get_model_spec

from llm_ai_api import llm

m = llm(get_model_spec())
print(m.ask("Say hello in one short, friendly sentence."))
