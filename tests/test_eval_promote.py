"""eval-promote.py: a case from feedback/eval/ becomes an item in eval/answers.json only with
checks I typed; the answer is never copied (SECURITY.md 153)."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("eval_promote", ROOT / "eval-promote.py")
promote = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promote)
vault = promote.vault


def load_chat():
    spec = importlib.util.spec_from_file_location("julz_chat", ROOT / "julz-chat.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

QUESTION = "Show me how to list my firewall rules with nft"
ANSWER = "sudo iptables -L -n -v"


class PromoteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.cases = base / "julz-mem" / "feedback" / "eval"
        self.cases.mkdir(parents=True)
        self.answers = base / "answers.json"
        self.name = self.case(QUESTION, ANSWER, "none")

    def tearDown(self):
        self.tmp.cleanup()

    def case(self, q, a, mode, when=datetime(2026, 10, 25, 21, 5, 9)):
        req = vault.case_request(vault.case_text(q, a, mode), when)
        path = self.cases.parent.parent / req["note"]
        path.write_text(req["text"])
        return path.stem

    def items(self):
        return json.loads(self.answers.read_text())

    def test_the_question_and_mode_are_read_back_exactly(self):
        q = "what does\n## Answer\nmean here"
        name = self.case(q, "x", "learn", datetime(2026, 10, 25, 22, 0, 0))
        self.assertEqual(promote.read_case(self.cases, name), {"q": q, "mode": "learn"})

    def test_promote_writes_my_checks_never_the_answer(self):
        promote.promote(self.cases, self.answers, self.name, ["nft list ruleset"], ["iptables"], None)
        self.assertEqual(self.items(), [{"q": QUESTION, "mode": "none", "expect": ["nft list ruleset"],
                                         "avoid": ["iptables"], "case": self.name}])
        self.assertNotIn(ANSWER, self.answers.read_text())

    def test_it_appends_and_refuses_the_same_case_twice(self):
        self.answers.write_text(json.dumps([{"q": "old", "mode": "none", "expect": ["x"], "avoid": [], "case": "old"}]))
        promote.promote(self.cases, self.answers, self.name, ["nft"], [], None)
        self.assertEqual([i["case"] for i in self.items()], ["old", self.name])
        with self.assertRaises(promote.Refused):
            promote.promote(self.cases, self.answers, self.name, ["nft"], [], None)

    def test_a_check_is_needed(self):
        with self.assertRaises(promote.Refused):
            promote.promote(self.cases, self.answers, self.name, [], [], None)
        self.assertFalse(self.answers.exists())

    def test_bad_words_are_refused(self):
        for bad in ("", " ", "a\nb", "x" * 61, "a\u202eb"):
            with self.subTest(bad=bad[:10]):
                with self.assertRaises(promote.Refused):
                    promote.promote(self.cases, self.answers, self.name, [bad], [], None)

    def test_unknown_mode_needs_mine(self):
        name = self.case("q one", "a", "unknown", datetime(2026, 10, 25, 23, 0, 0))
        with self.assertRaises(promote.Refused):
            promote.promote(self.cases, self.answers, name, ["x"], [], None)
        promote.promote(self.cases, self.answers, name, ["x"], [], "learn")
        self.assertEqual(self.items()[0]["mode"], "learn")
        with self.assertRaises(promote.Refused):
            promote.promote(self.cases, self.answers, self.name, ["x"], [], "solve")

    def test_every_chat_mode_can_be_kept_and_replayed(self):
        # 133b: a mode julz-chat knows but the case path drops would lose its bad answers quietly
        chat = load_chat()
        self.assertEqual(promote.MODES, ("none", *chat.MODES))
        self.assertEqual(vault.CASE_MODES, ("none", *chat.MODES, "unknown"))
        name = self.case("q two", "a", "notes", datetime(2026, 10, 26, 12, 0, 0))
        promote.promote(self.cases, self.answers, name, ["not in your notes"], [], None)
        self.assertEqual(self.items()[-1]["mode"], "notes")

    def test_a_case_that_does_not_parse_is_refused(self):
        path = self.cases / f"{self.name}.md"
        good = path.read_text()
        for bad in (good.replace("question_chars: ", "question_chars: 9"), good.replace("question_chars: ", "x: "),
                    good.replace("tags:\n  - eval-case", "tags:\n  - other"), good.replace("## Question\n\n", ""),
                    good.replace("mode: none", "mode: solve"), good.replace(QUESTION, "a\u202e" + QUESTION[2:])):
            with self.subTest(bad=bad[:60]):
                path.write_text(bad)
                with self.assertRaises(promote.Refused):
                    promote.read_case(self.cases, self.name)

    def test_only_a_plain_name_in_the_folder(self):
        (self.cases.parent / "x.md").write_text((self.cases / f"{self.name}.md").read_text())
        (self.cases / "link.md").symlink_to(self.cases / f"{self.name}.md")
        for name in ("../x", "link", "missing", "/etc/passwd", ".hidden"):
            with self.subTest(name=name):
                with self.assertRaises(promote.Refused):
                    promote.read_case(self.cases, name)

    def test_the_list_marks_promoted_cases(self):
        other = self.case("second question", "a", "none", datetime(2026, 10, 26, 8, 0, 0))
        promote.promote(self.cases, self.answers, self.name, ["nft"], [], None)
        self.assertEqual(promote.list_cases(self.cases, self.answers),
                         [(other, False, "second question"), (self.name, True, QUESTION)])


if __name__ == "__main__":
    unittest.main()
