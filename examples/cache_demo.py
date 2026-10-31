"""Ask the same question twice; the second answer is served from the SQLite cache.

Usage: python examples/cache_demo.py PROVIDER:MODEL
"""

import time

from _common import get_model_spec

from llm_ai_api import llm, set_cache

set_cache("llm_ai_api_cache.db")  # process-wide: on (an SQLite file path)

m = llm(get_model_spec())
question = "Suggest a name for a cute dog. Answer with the name only."

for label in ("first call (hits the API)", "second call (from the cache)"):
    start = time.time()
    answer = m.ask(question)
    print("%s: %s  [%.3f s]" % (label, answer, time.time() - start))
