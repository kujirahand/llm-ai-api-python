"""Read the text written in an image (OCR).

Usage: python examples/ocr_test.py PROVIDER:MODEL IMAGE_PATH
"""

import sys

from _common import get_model_spec, image_message

from llm_ai_api import llm

spec = get_model_spec(" IMAGE_PATH")
if len(sys.argv) < 3:
    sys.exit("Usage: python examples/ocr_test.py PROVIDER:MODEL IMAGE_PATH")

m = llm(spec)
prompt = "Transcribe all the text in this image exactly as written. Output only the text."
print(m.chat([image_message(m.provider, sys.argv[2], prompt)]).text)
