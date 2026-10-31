"""Rules that drop parameters a model or API version rejects."""

import unittest

from llm_ai_api._model_params import DROP_RULES, DropRule, adjust_body
from llm_ai_api.cache import cache_key


def _body(**extra):
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "q"}],
        "temperature": 0.2,
        "top_p": 0.9,
        "top_k": 1,
        "logprobs": True,
        "top_logprobs": 3,
        "stop": "END",
        "max_tokens": 8,
        "n": 2,
    }
    body.update(extra)
    return body


class AdjustBodyTest(unittest.TestCase):
    def test_unknown_model_is_unchanged_and_input_is_not_mutated(self):
        body = _body()
        original = dict(body)
        got = adjust_body("openai", "m", body)
        self.assertEqual(got, original)
        self.assertEqual(body, original)
        self.assertIsNot(got, body)

    def test_unknown_provider_is_unchanged(self):
        body = _body(model="gpt-6-astra")
        self.assertEqual(adjust_body("openrouter", "gpt-6-astra", body), body)
        self.assertEqual(adjust_body("google", "gpt-6-astra", body), body)

    def test_rules_union_their_drop_sets(self):
        rules = (
            DropRule("openai", ("gpt-x",), frozenset({"temperature"})),
            DropRule("openai", ("gpt-*",), frozenset({"stop"})),
            DropRule("openai", ("other",), frozenset({"n"})),
        )
        got = adjust_body("openai", "gpt-x", _body(model="gpt-x"), rules=rules)
        self.assertNotIn("temperature", got)
        self.assertNotIn("stop", got)
        self.assertEqual(got["n"], 2)
        self.assertEqual(got["max_tokens"], 8)

    def test_pattern_does_not_match_a_longer_id(self):
        # "o3" must not take o3-mini with it. "gpt-5" must not take gpt-5.2.
        o3 = adjust_body("openai", "o3", _body(model="o3"))
        self.assertNotIn("stop", o3)
        self.assertEqual(o3["temperature"], 0.2)
        mini = adjust_body("openai", "o3-mini", _body(model="o3-mini"))
        self.assertEqual(mini["stop"], "END")
        snap = adjust_body("openai", "o3-2025-04-16", _body(model="o3-2025-04-16"))
        self.assertNotIn("stop", snap)
        self.assertIn("temperature", adjust_body("openai", "gpt-5.2", _body(model="gpt-5.2")))
        self.assertNotIn("temperature", adjust_body("openai", "gpt-5", _body(model="gpt-5")))
        self.assertNotIn(
            "temperature",
            adjust_body("openai", "gpt-5-2025-08-07", _body(model="gpt-5-2025-08-07")),
        )
        self.assertIn("temperature", adjust_body("openai", "gpt-6-luna", _body(model="gpt-6-luna")))

    def test_gpt6_astra_and_sol_drop_sampling_and_keep_other_keys(self):
        for model in ("gpt-6-astra", "gpt-6.1-sol"):
            got = adjust_body("openai", model, _body(model=model))
            for key in ("temperature", "top_p", "logprobs", "top_logprobs"):
                self.assertNotIn(key, got, model)
            self.assertEqual(got["stop"], "END")
            self.assertEqual(got["max_tokens"], 8)
            self.assertEqual(got["n"], 2)

    def test_older_gpt5_does_not_drop_top_logprobs(self):
        got = adjust_body("openai", "gpt-5-mini", _body(model="gpt-5-mini"))
        self.assertNotIn("temperature", got)
        self.assertNotIn("top_p", got)
        self.assertNotIn("logprobs", got)
        self.assertEqual(got["top_logprobs"], 3)

    def test_claude_version_drops_sampling_on_every_model(self):
        got = adjust_body(
            "anthropic", "claude-x", _body(), anthropic_version="2026-10-21"
        )
        for key in ("temperature", "top_p", "top_k"):
            self.assertNotIn(key, got)
        self.assertEqual(got["max_tokens"], 8)
        self.assertEqual(got["n"], 2)

    def test_other_anthropic_version_keeps_sampling(self):
        got = adjust_body("anthropic", "claude-x", _body(), anthropic_version="2023-06-01")
        self.assertEqual(got["temperature"], 0.2)
        self.assertEqual(got["top_p"], 0.9)
        self.assertEqual(got["top_k"], 1)
        self.assertEqual(
            adjust_body("anthropic", "claude-x", _body())["temperature"], 0.2
        )

    def test_body_model_overrides_the_argument(self):
        body = _body(model="gpt-6-astra")
        got = adjust_body("openai", "m", body)
        self.assertNotIn("temperature", got)
        kept = adjust_body("openai", "gpt-6-astra", _body(model="gpt-4o"))
        self.assertEqual(kept["temperature"], 0.2)

    def test_dropped_key_does_not_change_the_cache_key(self):
        plain = {"model": "claude-x", "messages": [], "max_tokens": 16000}
        with_temp = dict(plain, temperature=0.2, top_k=1)
        a = adjust_body("anthropic", "claude-x", plain, anthropic_version="2026-10-21")
        b = adjust_body("anthropic", "claude-x", with_temp, anthropic_version="2026-10-21")
        self.assertEqual(cache_key("anthropic", a), cache_key("anthropic", b))
        other = adjust_body(
            "anthropic", "claude-x", dict(plain, max_tokens=5), anthropic_version="2026-10-21"
        )
        self.assertNotEqual(cache_key("anthropic", a), cache_key("anthropic", other))

    def test_production_rules_cover_the_documented_ids(self):
        providers = {rule.provider for rule in DROP_RULES}
        self.assertEqual(providers, {"anthropic", "openai"})
        self.assertFalse(any(rule.provider in ("openrouter", "google") for rule in DROP_RULES))
