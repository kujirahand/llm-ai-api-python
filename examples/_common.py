"""Helpers shared by the examples (not part of the library)."""

import base64
import mimetypes
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


def image_message(provider, path, text):
    """Build a user message that contains an image and a text prompt.

    The library does not convert content between providers, so the image block
    has to be written in each provider's own format.
    """
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    media_type = mimetypes.guess_type(path)[0] or "image/png"
    if provider == "anthropic":
        image = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": data},
        }
    else:  # openai / openrouter (OpenAI-compatible)
        image = {
            "type": "image_url",
            "image_url": {"url": "data:%s;base64,%s" % (media_type, data)},
        }
    return {"role": "user", "content": [image, {"type": "text", "text": text}]}
