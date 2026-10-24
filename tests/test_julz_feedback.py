"""julz_vault: feedback written in the app, SECURITY.md 120. The text I sign, the note it
becomes through the vault's own create request, and the list the app shows."""
import json
import unittest
from datetime import datetime

from test_julz_vault import VaultBase, vault_mod

NOW = datetime(2026, 10, 18, 2, 31, 12)


class FeedbackTextTest(unittest.TestCase):
    def test_text_names_the_kind_then_my_words(self):
        self.assertEqual(vault_mod.feedback_text("bug", "Voice stops after a while.\nAgain today."),
                         "feedback: bug\nVoice stops after a while.\nAgain today.\n")

    def test_refusals(self):
        for name, (kind, text) in {
            "unknown kind": ("rant", "x"), "kind not a string": (5, "x"), "empty": ("idea", "  "),
            "too long": ("idea", "y" * 2001), "a link": ("idea", "see https://evil.example"),
            "a secret": ("bug", "token ghp_" + "A1b2" * 10), "hidden": ("bug", "a\u202eb"),
            "html": ("idea", "<img src=x>"), "not a string": ("idea", None),
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.feedback_text(kind, text)

    def test_the_request_is_one_create_in_feedback(self):
        req = vault_mod.feedback_request("feedback: idea\nTabs for Messages.\n", NOW)
        self.assertEqual(set(req), {"op", "note", "text"})
        self.assertEqual(req["op"], "create")
        self.assertEqual(req["note"], "feedback/2026-10-18 tabs-for-messages 023112.md")
        self.assertEqual(req["text"], "---\ntags:\n  - feedback\ncreated: 2026-10-18\nkind: idea\nstate: new\n"
                                      "from: phone\n---\n\n# Feedback 2026-10-18\n\nTabs for Messages.\n")

    def test_requests_refuse_what_feedback_text_did_not_build(self):
        for bad in ("", "feedback: idea\n", "feedback: rant\nx\n", "approve: x\ny\n",
                    "feedback: idea\nsee https://evil.example\n", "feedback: idea\nno last newline"):
            with self.subTest(bad=bad[:30]):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.feedback_request(bad, NOW)


class FeedbackVaultTest(VaultBase):
    def setUp(self):
        super().setUp()
        self.fb = self.vault / "feedback"
        (self.fb / "done").mkdir(parents=True)
        (self.fb / "2026-10-16 voice.md").write_text(
            "---\ntags:\n  - feedback\ncreated: 2026-10-16\n---\n\n# Feedback 2026-10-16\n\nVoice works badly.\n")
        (self.fb / "2026-10-17 tabs.md").write_text(
            "---\ntags:\n  - feedback\ncreated: 2026-10-17\nkind: idea\nstate: planned\nwhere: BACKLOG 41\n---\n\n"
            "# Feedback 2026-10-17\n\nTabs \u202efor messages.\n")
        (self.fb / "done" / "2026-10-15 old.md").write_text(
            "---\ntags:\n  - feedback\ncreated: 2026-10-15\n---\n\n# Feedback\n\nFixed thing.\n\nFixed in abc123\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "feedback fixture")

    def test_a_signed_note_lands_in_feedback(self):
        req = vault_mod.feedback_request(vault_mod.feedback_text("bug", "Logs title wraps."), NOW)
        vault_mod.write_request(self.requests, req)
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("kind: bug", (self.fb / "2026-10-18 logs-title-wraps 023112.md").read_text())

    def test_feedback_logs_as_feedback_not_as_a_note(self):
        vault_mod.write_request(self.requests, vault_mod.feedback_request(vault_mod.feedback_text("idea", "More tabs."), NOW))
        self.run_vault()
        self.assertEqual(self.log()[-1]["action"], "feedback")

    def test_an_ordinary_note_still_logs_as_a_note(self):
        self.request({"op": "create", "note": "daily/plan.md", "text": "# Plan\n"})
        self.run_vault()
        self.assertEqual(self.log()[-1]["action"], "note")

    def test_the_list_has_open_and_done_with_states(self):
        items = {i["name"]: i for i in vault_mod.feedback_snapshot(self.vault)["items"]}
        self.assertEqual(items["2026-10-17 tabs"], {"name": "2026-10-17 tabs", "done": False, "created": "2026-10-17",
                                                    "kind": "idea", "state": "planned", "where": "BACKLOG 41",
                                                    "text": "Tabs �for messages."})
        self.assertEqual(items["2026-10-16 voice"]["state"], "new")  # no state yet: new
        self.assertTrue(items["2026-10-15 old"]["done"])
        self.assertEqual(items["2026-10-15 old"]["state"], "done")
        self.assertEqual([i["name"] for i in vault_mod.feedback_snapshot(self.vault)["items"] if not i["done"]],
                         ["2026-10-17 tabs", "2026-10-16 voice"])  # newest first

    def test_run_writes_the_feedback_list(self):
        self.run_vault()
        data = json.loads((self.state / "feedback.json").read_text())
        self.assertEqual(len(data["items"]), 3)



class VaultStatusTest(VaultBase):
    """122: julz-vault counts today's commits for the Integrations list."""

    def test_run_writes_commits_today(self):
        self.request({"op": "create", "note": "daily/plan.md", "text": "# Plan\n"})
        self.run_vault()
        data = json.loads((self.state / "vault-status.json").read_text())
        self.assertGreaterEqual(data["commits_today"], 2)  # the fixture and the new note
        self.assertEqual(set(data), {"date", "commits_today"})


if __name__ == "__main__":
    unittest.main()
