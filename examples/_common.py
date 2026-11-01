"""Helpers shared by the examples (not part of the library)."""

import os
import sys


def get_model_spec(extra_usage=""):
    """Return the "provider:model" spec from argv[1] or the LLM_MODEL env var."""
    spec = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LLM_MODEL")
    if not spec:
        script = os.path.basename(sys.argv[0])
        sys.exit(
            "Usage: python examples/%s PROVIDER:MODEL%s\n"
            "  (or set LLM_MODEL). API keys come from OPENAI_API_KEY /\n"
            "  OPENROUTER_API_KEY / ANTHROPIC_API_KEY." % (script, extra_usage)
        )
    return spec
