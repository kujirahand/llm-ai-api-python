import os
import sys
import unittest
from unittest import mock

import llm_ai_api
from llm_ai_api import AnthropicClient, LLMConfigError, OpenAIClient, llm, set_language
from llm_ai_api.errors import APIStatusError

from .helpers import Recorder, json_response

loc = sys.modules["llm_ai_api.lang"]
from llm_ai_api.lang import en as loc_en  # noqa: E402
from llm_ai_api.lang import ja as loc_ja  # noqa: E402


def env(**kw):
    """言語関連の環境変数をすべて消した上で、kw だけ設定する。"""
    return mock.patch.dict(os.environ, kw, clear=True)


class DetectTest(unittest.TestCase):
    def setUp(self):
        set_language(None)
        p = mock.patch.object(loc._stdlib_locale, "getlocale", return_value=(None, None))
        p.start()
        self.addCleanup(p.stop)

    def test_normalize(self):
        n = loc.normalize_language
        self.assertEqual(n("ja_JP.UTF-8"), "ja")
        self.assertEqual(n("en-US"), "en")
        self.assertEqual(n("EN"), "en")
        for bad in ["C", "POSIX", "C.UTF-8", "", None, "../x", "japanese"]:
            self.assertIsNone(n(bad), bad)

    def test_env_priority(self):
        with env(LANG="en_US.UTF-8", LLM_AI_API_LANG="ja"):
            self.assertEqual(loc.get_language(), "ja")
        with env(LANG="ja_JP.UTF-8", LC_ALL="en_US.UTF-8"):
            self.assertEqual(loc.get_language(), "en")
        with env(LANG="ja_JP.UTF-8"):
            self.assertEqual(loc.get_language(), "ja")

    def test_language_list_skips_unsupported(self):
        with env(LANGUAGE="fr:ja:en", LANG="en_US.UTF-8"):
            self.assertEqual(loc.get_language(), "ja")

    def test_c_locale_and_unset_are_english(self):
        with env(LANG="C"):
            self.assertEqual(loc.get_language(), "en")
        with env():
            self.assertEqual(loc.get_language(), "en")

    def test_getlocale_fallback(self):
        with env(), mock.patch.object(loc._stdlib_locale, "getlocale", return_value=("ja_JP", "UTF-8")):
            self.assertEqual(loc.get_language(), "ja")

    def test_override_order(self):
        with env(LANG="en_US.UTF-8"):
            set_language("ja")
            self.assertEqual(loc.get_language(), "ja")
            self.assertEqual(loc.get_language("en"), "en")  # 引数が最優先


class FallbackTest(unittest.TestCase):
    def setUp(self):
        set_language(None)

    def test_languages(self):
        self.assertIn("API キー", loc.t("missing_api_key", "ja", provider="x", env="E"))
        self.assertIn("No API key", loc.t("missing_api_key", "en", provider="x", env="E"))

    def test_unsupported_language_falls_back_to_en(self):
        self.assertIn("No API key", loc.t("missing_api_key", "fr", provider="x", env="E"))

    def test_missing_id_in_language_falls_back_to_en(self):
        with mock.patch.dict(loc._catalogs, {"ja": {"only_ja": "日本語だけ"}, "en": {"only_en": "english"}}):
            self.assertEqual(loc.t("only_ja", "ja"), "日本語だけ")
            self.assertEqual(loc.t("only_en", "ja"), "english")  # ja に無い → en
            self.assertEqual(loc.t("nothing", "ja"), "nothing")  # どこにも無い → ID

    def test_broken_template_falls_back(self):
        with mock.patch.dict(loc._catalogs, {"ja": {"m": "{missing}"}, "en": {"m": "ok {x}"}}):
            self.assertEqual(loc.t("m", "ja", x=1), "ok 1")

    def test_ja_has_no_ids_unknown_to_en(self):
        self.assertFalse(set(loc_ja.MESSAGES) - set(loc_en.MESSAGES))

    def test_templates_use_same_params(self):
        import string

        def fields(tpl):
            return {f for _, f, _, _ in string.Formatter().parse(tpl) if f}

        for msg_id, tpl in loc_ja.MESSAGES.items():
            self.assertEqual(fields(tpl), fields(loc_en.MESSAGES[msg_id]), msg_id)

    def test_every_en_id_is_used_in_code(self):
        src = ""
        base = os.path.dirname(llm_ai_api.__file__)
        for name in (
            "_http.py",
            "_async_http.py",
            "_events.py",
            "llm.py",
            "anthropic.py",
            "cache.py",
            "log.py",
            "_connection.py",
            "_structured.py",
        ):
            with open(os.path.join(base, name), encoding="utf-8") as f:
                src += f.read()
        for msg_id in loc_en.MESSAGES:
            if msg_id.startswith("hint_"):
                continue  # "hint_%d" で組み立てるため
            self.assertIn('"%s"' % msg_id, src, msg_id)


class ErrorMessageTest(unittest.TestCase):
    def setUp(self):
        set_language(None)

    def test_config_error_language_and_code(self):
        with env():
            for lang, word in (("ja", "見つかりません"), ("en", "No API key")):
                with self.assertRaises(LLMConfigError) as cm:
                    OpenAIClient(lang=lang)
                self.assertIn(word, str(cm.exception))
                self.assertIn("OPENAI_API_KEY", str(cm.exception))
                self.assertEqual(cm.exception.code, "missing_api_key")

    def test_model_spec_errors_via_llm(self):
        with self.assertRaises(LLMConfigError) as cm:
            llm("gpt-6", lang="ja", api_key="k")
        self.assertIn("プロバイダー:モデル名", str(cm.exception))
        self.assertEqual(cm.exception.code, "invalid_model_spec")
        with self.assertRaises(LLMConfigError) as cm:
            llm("nope:x", lang="en", api_key="k")
        self.assertIn("Unknown provider", str(cm.exception))
        self.assertEqual(cm.exception.code, "unknown_provider")

    def test_status_error_with_hint_keeps_api_message(self):
        reply = json_response({"error": {"message": "Incorrect API key"}}, 401)
        for lang, head, hint in (("ja", "エラーを返しました", "ヒント"), ("en", "API error", "Hint")):
            c = OpenAIClient(api_key="k", lang=lang, transport=Recorder(reply).transport)
            with self.assertRaises(APIStatusError) as cm:
                c.request("/x", {})
            msg = str(cm.exception)
            self.assertIn(head, msg)
            self.assertIn("(HTTP 401)", msg)
            self.assertIn("Incorrect API key", msg)  # API の文言は翻訳しない
            self.assertIn(hint, msg)
            self.assertEqual(cm.exception.code, "api_error")

    def test_global_language_applies(self):
        set_language("ja")
        self.addCleanup(set_language, None)
        c = OpenAIClient(api_key="k", transport=Recorder(json_response({}, 404)).transport)
        with self.assertRaises(APIStatusError) as cm:
            c.request("/x", {})
        self.assertIn("ヒント", str(cm.exception))

    def test_stream_error_message(self):
        from .helpers import sse_response

        text = 'event: error\ndata: {"type":"error","error":{"message":"Overloaded"}}\n\n'
        c = AnthropicClient(api_key="k", lang="ja", transport=Recorder(sse_response(text)).transport)
        with self.assertRaises(llm_ai_api.APIStreamError) as cm:
            list(c.stream_chat("m", [{"role": "user", "content": "q"}]))
        self.assertIn("ストリーム", str(cm.exception))
        self.assertIn("Overloaded", str(cm.exception))
        self.assertEqual(cm.exception.code, "stream_error")


if __name__ == "__main__":
    unittest.main()
