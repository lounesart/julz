"""Tests for eval-recall.py's judging (129). Nothing reaches Open WebUI: answers are faked.
A case with "tries" is asked that many times and passes only if every try has the keywords and
cites the source, because the model's query rewrite makes one try a coin flip."""
import importlib.util
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


recall = load("eval_recall", "eval-recall.py")
NOTE = "nftables-basics.md"


def reply(answer, *names):
    return answer, {"sources": [{"metadata": [{"name": f"study__linux__{n}"} for n in names]}]}


def asker(*replies):
    calls = []

    def ask(q):
        calls.append(q)
        return replies[len(calls) - 1]
    return ask, calls


class JudgeTest(unittest.TestCase):
    def case(self, **extra):
        return {"q": "policy?", "expect": ["drop"], "source": NOTE, **extra}

    def test_one_try_passes_on_keywords_as_before(self):
        ask, calls = asker(reply("Policy drop.", "other.md"))
        result = recall.run_case(self.case(), ask)
        self.assertTrue(result["ok"])
        self.assertFalse(result["cited"])
        self.assertEqual(len(calls), 1)

    def test_tries_asks_that_many_times(self):
        ask, calls = asker(*[reply("drop", NOTE)] * 5)
        result = recall.run_case(self.case(tries=5), ask)
        self.assertTrue(result["ok"])
        self.assertEqual((result["good"], result["tries"]), (5, 5))
        self.assertEqual(len(calls), 5)

    def test_tries_fail_when_one_try_misses_the_source(self):
        # The model knows "drop" without my note: right words, wrong retrieval
        ask, _ = asker(*[reply("drop", NOTE)] * 4, reply("drop", "other.md"))
        result = recall.run_case(self.case(tries=5), ask)
        self.assertFalse(result["ok"])
        self.assertEqual(result["good"], 4)

    def test_tries_fail_when_one_try_misses_a_keyword(self):
        ask, _ = asker(reply("accept", NOTE), *[reply("drop", NOTE)] * 2)
        result = recall.run_case(self.case(tries=3), ask)
        self.assertFalse(result["ok"])
        self.assertEqual(result["good"], 2)
        self.assertEqual(result["missing"], ["drop"])

    def test_claude_mode_passes_on_citation(self):
        ask, _ = asker(reply("nothing useful", NOTE))
        self.assertTrue(recall.run_case(self.case(), ask, claude=True)["ok"])
        ask, _ = asker(reply("drop", "other.md"))
        self.assertFalse(recall.run_case(self.case(), ask, claude=True)["ok"])

    def test_forbid_fails_a_try_that_says_the_wrong_thing(self):
        # 118: right note, right word, and a wrong fact beside it (CPTS called PenTest+)
        ask, _ = asker(reply("Policy drop, as in PenTest+.", NOTE))
        result = recall.run_case(self.case(forbid=["pentest+"]), ask)
        self.assertFalse(result["ok"])
        self.assertEqual(result["said"], ["pentest+"])
        ask, _ = asker(reply("Policy drop.", NOTE))
        result = recall.run_case(self.case(forbid=["pentest+"]), ask)
        self.assertTrue(result["ok"])
        self.assertEqual(result["said"], [])

    def test_forbid_gates_claude_mode_too(self):
        ask, _ = asker(reply("nothing useful, PenTest+", NOTE))
        self.assertFalse(recall.run_case(self.case(forbid=["PenTest+"]), ask, claude=True)["ok"])

    def test_forbid_fails_one_bad_try_of_several(self):
        ask, _ = asker(*[reply("drop", NOTE)] * 2, reply("drop PenTest+", NOTE))
        result = recall.run_case(self.case(tries=3, forbid=["PenTest+"]), ask)
        self.assertFalse(result["ok"])
        self.assertEqual(result["good"], 2)
        self.assertEqual(result["said"], ["PenTest+"])

    def test_cpts_cases_cite_the_cpts_notes_and_forbid_pentest(self):
        cases = json.loads(recall.CLAUDE_EVAL_FILE.read_text())
        cpts = [c for c in cases if c["source"].startswith("Claude__cpts__")]
        self.assertGreaterEqual(len(cpts), 4)
        self.assertTrue(all("PenTest+" in c.get("forbid", []) for c in cpts))

    def test_chat_mode_attaches_no_collection_as_julz_chat(self):
        # 118: julz-chat sends no files, so --chat asks the way the app does
        sent = []
        real = recall.api
        recall.api = lambda key, method, path, body, timeout: (
            sent.append(body) or {"choices": [{"message": {"content": "x"}}]})
        try:
            recall.ask("k", "julz:latest", {"id": "kb1"}, "q?")
            recall.ask("k", "julz:latest", None, "q?")
        finally:
            recall.api = real
        self.assertEqual(sent[0]["files"], [{"type": "collection", "id": "kb1"}])
        self.assertNotIn("files", sent[1])

    def test_cross_language_cases_are_asked_several_times(self):
        cases = json.loads(recall.EVAL_FILE.read_text())
        ru_note = [c for c in cases if c["source"] == NOTE]
        self.assertEqual(len(ru_note), 2)  # the Russian question and the English one
        self.assertTrue(all(c.get("tries", 1) >= 5 for c in ru_note))


if __name__ == "__main__":
    unittest.main()
