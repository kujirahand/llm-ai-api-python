import json
import os
import tempfile
import unittest

from llm_ai_api import ChatResult, JSONLLog, LLMConfigError, SQLiteCache, set_cache, set_log
from llm_ai_api import cache as cache_module
from llm_ai_api import log as log_module

DEFAULT = 100 * 1024 * 1024


def result(i, size=1000):
    return ChatResult(text="x" * size, model="m", stop_reason="stop", usage=None, raw={"i": i})


class TmpDirTest(unittest.TestCase):
    def setUp(self):
        set_cache(None)
        set_log(None)
        self.addCleanup(set_cache, None)
        self.addCleanup(set_log, None)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = tmp.name


class CacheMaxSizeTest(TmpDirTest):
    def setUp(self):
        super().setUp()
        self.db = os.path.join(self.dir, "cache.db")

    def test_default(self):
        self.assertEqual(cache_module.DEFAULT_MAX_SIZE, DEFAULT)
        self.assertEqual(SQLiteCache(self.db).max_size, DEFAULT)

    def test_invalid(self):
        for bad in (0, -1, 1.5, "10", True):
            with self.assertRaises(LLMConfigError) as cm:
                SQLiteCache(self.db, max_size=bad)
            self.assertEqual(cm.exception.code, "invalid_cache")

    def test_trims_oldest_third(self):
        # An empty database is already ~20 KB (one page per table/index), so use a larger limit.
        c = SQLiteCache(self.db, max_size=60000)
        counts = []
        sizes = []
        for i in range(60):
            c.put("k%d" % i, "openai", result(i, size=3000))
            counts.append(len(c))
            sizes.append(os.path.getsize(self.db))
        # The first put that leaves the file above the limit trims once.
        drop = next(i for i in range(1, 60) if counts[i] < counts[i - 1] + 1)
        before = counts[drop - 1] + 1
        self.assertEqual(counts[drop], before - max(1, before // 3))
        self.assertLess(sizes[drop], sizes[drop - 1])  # vacuumed: the file really shrank
        # The oldest rows are gone, the newest is served.
        self.assertIsNone(c.get("k0"))
        self.assertIsNotNone(c.get("k59"))

    def test_unlimited(self):
        c = SQLiteCache(self.db, max_size=None)
        self.assertIsNone(c.max_size)
        for i in range(40):
            c.put("k%d" % i, "openai", result(i, size=3000))
        self.assertEqual(len(c), 40)
        self.assertIsNotNone(c.get("k0"))

    def test_single_oversized_row_is_kept(self):
        c = SQLiteCache(self.db, max_size=1000)
        c.put("only", "openai", result(0, size=20000))
        self.assertIsNotNone(c.get("only"))

    def test_trim_failure_is_swallowed(self):
        c = SQLiteCache(self.db, max_size=1000)
        os.remove(self.db)  # getsize() fails inside the trim
        c._trim()  # must not raise

    def test_set_cache_passes_max_size(self):
        self.assertEqual(set_cache(self.db, max_size=5000).max_size, 5000)
        self.assertIsNone(set_cache(self.db, max_size=None).max_size)
        self.assertEqual(set_cache(self.db).max_size, DEFAULT)
        own = SQLiteCache(self.db, max_size=777)
        self.assertEqual(set_cache(own, max_size=5000).max_size, 777)
        with self.assertRaises(LLMConfigError):
            set_cache(self.db, max_size=0)


class LogMaxSizeTest(TmpDirTest):
    def setUp(self):
        super().setUp()
        self.path = os.path.join(self.dir, "log.jsonl")

    def write(self, log, i, size=100):
        log.write("openai", "m", {"i": i}, {"text": "y" * size})

    def lines(self):
        with open(self.path, encoding="utf-8") as f:
            return [json.loads(line) for line in f]

    def test_default(self):
        self.assertEqual(log_module.DEFAULT_MAX_SIZE, DEFAULT)
        self.assertEqual(JSONLLog(self.path).max_size, DEFAULT)

    def test_invalid(self):
        for bad in (0, -5, 2.5, True):
            with self.assertRaises(LLMConfigError) as cm:
                JSONLLog(self.path, max_size=bad)
            self.assertEqual(cm.exception.code, "invalid_log")

    def test_trims_oldest_third(self):
        log = JSONLLog(self.path, max_size=3000)
        counts = []
        for i in range(60):
            self.write(log, i)
            counts.append(len(self.lines()))
        drop = next(i for i in range(1, 60) if counts[i] < counts[i - 1] + 1)
        before = counts[drop - 1] + 1
        self.assertEqual(counts[drop], before - before // 3)
        recs = self.lines()
        self.assertEqual(recs[-1]["request"]["i"], 59)  # newest kept, writes keep working
        self.assertGreater(recs[0]["request"]["i"], 0)  # first records dropped
        self.assertEqual(
            [r["request"]["i"] for r in recs],
            list(range(59 - len(recs) + 1, 60)),  # contiguous newest records
        )
        self.assertLessEqual(os.path.getsize(self.path), 3000 + 400)
        self.assertFalse(os.path.exists(self.path + ".tmp"))

    def test_unlimited(self):
        log = JSONLLog(self.path, max_size=None)
        for i in range(60):
            self.write(log, i)
        self.assertEqual(len(self.lines()), 60)

    def test_single_oversized_record_is_kept(self):
        log = JSONLLog(self.path, max_size=100)
        self.write(log, 0, size=5000)
        recs = self.lines()
        self.assertEqual(len(recs), 1)
        self.write(log, 1, size=5000)  # the older one is dropped, the newest stays
        self.assertEqual([r["request"]["i"] for r in self.lines()], [1])

    def test_trim_abandoned_when_file_changes(self):
        log = JSONLLog(self.path, max_size=None)  # no trimming while the records are written
        written = 25
        for i in range(written):
            self.write(log, i)
        self.assertEqual(len(self.lines()), written)
        log.max_size = 3000  # now the file is over the limit and the next trim has work to do
        self.assertGreater(os.path.getsize(self.path), log.max_size)
        extra = json.dumps({"request": {"i": "other-process"}}) + "\n"
        real_stat = os.stat
        calls = []

        def stat(path, *a, **k):
            # _trim() stats JSONLLog._normalized_path (realpath). A raw compare
            # misses when the temp dir is reached through a symlink, which is
            # the usual case on macOS (/var/folders -> /private/var/folders).
            if os.path.realpath(path) == os.path.realpath(self.path):
                calls.append(path)
                if len(calls) == 2:  # the guard's stat: simulate another process appending
                    with open(self.path, "a", encoding="utf-8") as f:
                        f.write(extra)
            return real_stat(path, *a, **k)

        log_module.os.stat = stat
        try:
            log._trim()
        finally:
            log_module.os.stat = real_stat
        recs = self.lines()
        self.assertEqual(len(recs), written + 1)  # trim abandoned, the appended record survives
        self.assertEqual(recs[-1]["request"]["i"], "other-process")
        self.assertFalse(os.path.exists(self.path + ".tmp"))
        log._trim()  # without interference the next trim succeeds
        self.assertLess(len(self.lines()), written + 1)

    def test_set_log_passes_max_size(self):
        self.assertEqual(set_log(self.path, max_size=5000).max_size, 5000)
        self.assertIsNone(set_log(self.path, max_size=None).max_size)
        self.assertEqual(set_log(self.path).max_size, DEFAULT)
        own = JSONLLog(self.path, max_size=777)
        self.assertEqual(set_log(own, max_size=5000).max_size, 777)
        with self.assertRaises(LLMConfigError):
            set_log(self.path, max_size=-1)


if __name__ == "__main__":
    unittest.main()
