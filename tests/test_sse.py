import unittest

from llm_ai_api._http import iter_sse


class SSETest(unittest.TestCase):
    def parse(self, text):
        return list(iter_sse(text.split("\n")))

    def test_basic_and_multiline_data(self):
        evs = self.parse("event: a\ndata: x\ndata: y\n\ndata: z\n\n")
        self.assertEqual([(e.event, e.data) for e in evs], [("a", "x\ny"), (None, "z")])

    def test_comments_ignored(self):
        evs = self.parse(": OPENROUTER PROCESSING\n\ndata: {}\n\n")
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].data, "{}")

    def test_no_trailing_blank_line(self):
        self.assertEqual(self.parse("data: last")[0].data, "last")

    def test_json(self):
        self.assertEqual(self.parse('data: {"a": 1}\n\n')[0].json(), {"a": 1})


if __name__ == "__main__":
    unittest.main()
