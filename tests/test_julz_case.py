"""julz_vault: a bad answer kept as an eval case from the phone, SECURITY.md 153. The text I
sign, the note it becomes through the vault's own create request, and the one folder it may use."""
import unittest
from datetime import datetime

from test_julz_vault import VaultBase, vault_mod

NOW = datetime(2026, 10, 25, 21, 5, 9)
QUESTION = "Show me how to list my firewall rules with nft, as a bash block"
ANSWER = "```bash\nsudo iptables -L -n -v\n```\nSee https://wiki.archlinux.org/title/Iptables first."
SHOWN_A = "```bash\nsudo iptables -L -n -v\n```\nSee wiki.archlinux.org/title/Iptables first."
TEXT = (f"case: bad answer\nmode: none\nquestion: {len(QUESTION)}\n{QUESTION}\n"
        f"answer:\n{SHOWN_A}\n")


class CaseTextTest(unittest.TestCase):
    def test_text_is_mode_question_and_answer_under_a_fixed_head(self):
        self.assertEqual(vault_mod.case_text(QUESTION, ANSWER, "none"), TEXT)

    def test_mode_only_from_the_fixed_set(self):
        for mode in ("none", "learn", "notes", "unknown"):
            self.assertIn(f"\nmode: {mode}\n", vault_mod.case_text("q", "a", mode))
        for bad in ("", "Learn", "learn\n", "solve", None, 1):
            with self.subTest(mode=bad):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.case_text("q", "a", bad)

    def test_each_part_is_cut_at_its_cap_with_a_line_saying_so(self):
        text = vault_mod.case_text("q" * (vault_mod.MAX_CASE_Q + 50), "a" * (vault_mod.MAX_CASE_A + 50), "none")
        self.assertIn("q" * vault_mod.MAX_CASE_Q + "\n\n" + vault_mod.CASE_CUT + "\nanswer:\n", text)
        self.assertTrue(text.endswith("a" * vault_mod.MAX_CASE_A + "\n\n" + vault_mod.CASE_CUT + "\n"))
        self.assertLess(len(text), 4096)  # the app shows and signs at most 4096 characters (109)

    def test_a_short_part_is_not_cut(self):
        text = vault_mod.case_text("q" * vault_mod.MAX_CASE_Q, "a" * vault_mod.MAX_CASE_A, "none")
        self.assertNotIn(vault_mod.CASE_CUT, text)

    def test_refusals(self):
        for name, q, a in (("empty question", " ", "a"), ("empty answer", "q", "\n"),
                           ("not a string", None, "a"), ("answer not a string", "q", 5),
                           ("hidden", "a\u202eb", "a"), ("hidden answer", "q", "a\u200bb"),
                           ("a secret", "q", "token ghp_" + "A1b2" * 10)):
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.case_text(q, a, "none")

    def test_a_question_holding_the_answer_marker_still_parses(self):
        q = "what does\nanswer:\nmean"
        req = vault_mod.case_request(vault_mod.case_text(q, "x", "learn"), NOW)
        self.assertIn("\n## Question\n\n" + q + "\n\n## Answer\n\nx\n", req["text"])


class CaseRequestTest(unittest.TestCase):
    def test_the_request_is_one_create_in_feedback_eval(self):
        req = vault_mod.case_request(TEXT, NOW)
        self.assertEqual(set(req), {"op", "note", "text"})
        self.assertEqual(req["op"], "create")
        self.assertEqual(req["note"], "feedback/eval/2026-10-25 show-me-how-to-list 210509.md")
        self.assertEqual(req["text"],
                         "---\ntags:\n  - eval-case\ncreated: 2026-10-25\nfrom: phone\nmode: none\n"
                         f"state: new\nquestion_chars: {len(QUESTION)}\n---\n\n# Bad answer 2026-10-25\n\n"
                         f"## Question\n\n{QUESTION}\n\n## Answer\n\n{SHOWN_A}\n")

    def test_requests_refuse_what_case_text_did_not_build(self):
        good = TEXT
        n = len(QUESTION)
        for bad in ("", good[:-1], good.replace("case: bad answer", "case: good answer"),
                    good.replace("mode: none", "mode: solve"),
                    good.replace(f"question: {n}", f"question: {n + 1}"),
                    good.replace(f"question: {n}", f"question: {n - 1}"),
                    good.replace(f"question: {n}", "question: x"),
                    good.replace(f"question: {n}", "question: -1"),
                    good.replace(f"question: {n}", f"question: 0{n}"),
                    good.replace(QUESTION, " " + QUESTION[1:]),
                    good.replace(SHOWN_A, SHOWN_A[:-1] + " "),
                    good.replace("\nanswer:\n", "\nreply:\n"),
                    good.replace(SHOWN_A, ""), good.replace(QUESTION, " " * n),
                    good.replace(QUESTION, "a\u202e" + QUESTION[2:]),
                    "save: chat answer\nx\n", "feedback: idea\nx\n", None):
            with self.subTest(bad=str(bad)[:40]):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.case_request(bad, NOW)

    def test_an_overlong_part_is_refused(self):
        q = "q" * (vault_mod.MAX_CASE_Q + 2 + len(vault_mod.CASE_CUT) + 1)
        bad = f"case: bad answer\nmode: none\nquestion: {len(q)}\n{q}\nanswer:\na\n"
        with self.assertRaises(vault_mod.Refused):
            vault_mod.case_request(bad, NOW)


class CaseVaultTest(VaultBase):
    def test_a_signed_case_lands_in_feedback_eval(self):
        vault_mod.write_request(self.requests, vault_mod.case_request(TEXT, NOW))
        self.assertEqual(self.run_vault()[0][1], "ok")
        note = self.vault / "feedback" / "eval" / "2026-10-25 show-me-how-to-list 210509.md"
        self.assertIn("tags:\n  - eval-case", note.read_text())

    def test_eval_is_the_only_folder_under_feedback_and_only_for_create(self):
        (self.vault / "feedback" / "eval").mkdir(parents=True)
        (self.vault / "feedback" / "eval" / "old.md").write_text("# old\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "case")
        for note in ("feedback/other/x.md", "feedback/eval/deeper/x.md", "feedback/done/x.md",
                     "feedback/eval/.x.md", "study/eval/deeper/x.md"):
            self.request({"op": "create", "note": note, "text": "# x\n"})
        self.request({"op": "resolve", "note": "feedback/eval/old.md"})
        results = self.run_vault()
        self.assertEqual([r[1] for r in results], ["refused"] * 6)
        self.assertTrue((self.vault / "feedback" / "eval" / "old.md").exists())
        self.assertFalse((self.vault / "feedback" / "other").exists())

    def test_a_linked_eval_folder_is_refused(self):
        (self.vault / "feedback").mkdir()
        (self.vault / "feedback" / "eval").symlink_to(self.study)
        vault_mod.write_request(self.requests, vault_mod.case_request(TEXT, NOW))
        self.assertEqual(self.run_vault()[0][1], "refused")
        self.assertEqual(sorted(p.name for p in self.study.iterdir()), ["dhcp.md", "osi.md"])

    def test_a_case_is_not_a_feedback_note(self):
        vault_mod.write_request(self.requests, vault_mod.case_request(TEXT, NOW))
        self.run_vault()
        self.assertEqual(vault_mod.feedback_snapshot(self.vault)["items"], [])

    def test_the_keep_file_stays_beside_cases_and_is_committed(self):
        # 269: the folder must outlive its last case, git keeps no empty folder
        keep = self.vault / "feedback" / "eval" / ".keep"
        keep.parent.mkdir(parents=True)
        keep.write_text("")
        vault_mod.write_request(self.requests, vault_mod.case_request(TEXT, NOW))
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("feedback/eval/.keep", self.git("ls-files"))
        self.assertEqual(vault_mod.feedback_snapshot(self.vault)["items"], [])

    def test_no_new_create_root(self):
        self.assertEqual(vault_mod.OPS["create"][1], ("study", "daily", "feedback", "Inbox"))


if __name__ == "__main__":
    unittest.main()
