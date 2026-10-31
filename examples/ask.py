"""使い方: python examples/ask.py openai:モデル名 "質問"

API キーは環境変数（OPENAI_API_KEY / OPENROUTER_API_KEY / ANTHROPIC_API_KEY）で渡す。
"""

import sys

from llm_ai_api import llm

spec = sys.argv[1]
question = sys.argv[2] if len(sys.argv) > 2 else "可愛い犬の名前を考えて"

m = llm(spec)
print(m.ask(question))
print("---- stream ----")
for piece in m.stream(question):
    print(piece, end="", flush=True)
print()
