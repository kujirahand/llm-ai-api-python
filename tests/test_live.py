"""実際の API を叩くテスト。課金が発生するため、LLM_AI_API_LIVE=1 のときだけ実行する。

使うモデルは環境変数で指定する（ライブラリ本体にモデル名は持たない）:
  LIVE_OPENAI_MODEL / LIVE_OPENROUTER_MODEL / LIVE_ANTHROPIC_MODEL / LIVE_GOOGLE_MODEL
"""

import os
import unittest

from llm_ai_api import llm

LIVE = os.environ.get("LLM_AI_API_LIVE") == "1"


def _case(provider, key_env, model_env):
    model = os.environ.get(model_env)

    @unittest.skipUnless(LIVE and os.environ.get(key_env) and model, "ライブテストは無効")
    def test(self):
        m = llm("%s:%s" % (provider, model), max_tokens=64)
        self.assertTrue(m.ask("Reply with one short word.").strip())
        self.assertTrue("".join(m.ask_stream("Reply with one short word.")).strip())

    return test


class LiveTest(unittest.TestCase):
    test_openai = _case("openai", "OPENAI_API_KEY", "LIVE_OPENAI_MODEL")
    test_openrouter = _case("openrouter", "OPENROUTER_API_KEY", "LIVE_OPENROUTER_MODEL")
    test_anthropic = _case("anthropic", "ANTHROPIC_API_KEY", "LIVE_ANTHROPIC_MODEL")
    test_google = _case("google", "GEMINI_API_KEY", "LIVE_GOOGLE_MODEL")


if __name__ == "__main__":
    unittest.main()
