"""Send a quick prompt to a local Strata-compatible API.

Usage:
    STRATA_BASE_URL=http://127.0.0.1:8080/v1 python example/local-llm-starata.py MODEL_NAME

Set STRATA_BASE_URL to the server's base URL. STRATA_API_KEY is optional.
"""

import os
import sys

from llm_ai_api import llm


model = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("STRATA_MODEL")
if not model:
    sys.exit(
        "Usage: STRATA_BASE_URL=URL python example/local-llm-starata.py MODEL_NAME\n"
        "Alternatively, set STRATA_MODEL."
    )

with llm(f"strata:{model}") as client:
    print(client.ask("Say hello in one short sentence."))
