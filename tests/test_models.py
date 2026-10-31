import sys
import unittest

from llm_ai_api import models

parse_model_spec = sys.modules["llm_ai_api.llm"].parse_model_spec


class ModelsTest(unittest.TestCase):
    def constants(self):
        return {k: v for k, v in vars(models).items() if k.isupper()}

    def test_all_parse_and_prefix_matches_name(self):
        consts = self.constants()
        self.assertTrue(consts)
        for name, spec in consts.items():
            provider, model = parse_model_spec(spec)
            self.assertTrue(name.startswith(provider.upper() + "_"), name)
            self.assertTrue(model, name)

    def test_values_are_unique(self):
        values = list(self.constants().values())
        self.assertEqual(len(values), len(set(values)))

    def test_usable_with_llm(self):
        self.assertEqual(models.OPENAI_GPT6_LUNA, "openai:gpt-6-luna")


if __name__ == "__main__":
    unittest.main()
