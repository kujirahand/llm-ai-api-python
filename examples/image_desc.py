"""Describe what is in an image.

Usage: python examples/image_desc.py PROVIDER:MODEL IMAGE_PATH
"""

import sys

from _common import get_model_spec, image_message

from llm_ai_api import llm

spec = get_model_spec(" IMAGE_PATH")
if len(sys.argv) < 3:
    sys.exit("Usage: python examples/image_desc.py PROVIDER:MODEL IMAGE_PATH")

m = llm(spec)
prompt = "Describe this image in a few sentences."
print(m.chat([image_message(m.provider, sys.argv[2], prompt)]).text)
