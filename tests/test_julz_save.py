"""julz_vault: a chat answer saved into Inbox from the phone, SECURITY.md 139. The text I sign,
the note it becomes through the vault's own create request, and where it may land."""
import unittest
from datetime import datetime

from test_julz_vault import VaultBase, vault_mod

NOW = datetime(2026, 10, 18, 22, 41, 7)
ANSWER = "## DORA\n\n- **Discover**: the client asks\n- See [RFC 2131](https://www.rfc-editor.org/rfc/rfc2131)\n"
SAVED = "## DORA\n\n- **Discover**: the client asks\n- See RFC 2131 (rfc-editor.org/rfc/rfc2131)"


class SaveTextTest(unittest.TestCase):
    def test_text_is_the_answer_under_a_fixed_head_links_defanged(self):
        # The vault keeps no working web address (the Keep check): each stays readable, unclickable
        self.assertEqual(vault_mod.save_text(ANSWER), "save: chat answer\n" + SAVED + "\n")

    def test_defanging(self):
        for raw, saved in (("see https://example.org/a.", "see example.org/a."),
                           ("www.example.org and http://x.org/b", "example.org and x.org/b"),
                           ("![chart](https://evil.example/p.png)", "[image: chart]"),
                           ("[a](https://evil.example/x) [b](javascript:alert(1))", "a (evil.example/x) b (javascript:alert(1))"),
                           ("ftp://files.example/x", "files.example/x")):
            with self.subTest(raw=raw):
                self.assertEqual(vault_mod.save_text(raw), f"save: chat answer\n{saved}\n")

    def test_a_long_answer_is_cut_with_a_line_saying_so(self):
        text = vault_mod.save_text("x" * (vault_mod.MAX_SAVE + 500))
        body = text.removeprefix("save: chat answer\n")
        self.assertTrue(body.startswith("x" * vault_mod.MAX_SAVE + "\n\n"))
        self.assertTrue(body.endswith(vault_mod.SAVE_CUT + "\n"))
        self.assertLess(len(text), 4096)  # the app shows and signs at most 4096 characters (109)

    def test_refusals(self):
        for name, text in {"empty": "  ", "not a string": None, "hidden": "a\u202eb",
                           "a secret": "token ghp_" + "A1b2" * 10}.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.save_text(text)

    def test_the_request_is_one_create_in_inbox(self):
        req = vault_mod.save_request(vault_mod.save_text(ANSWER), NOW)
        self.assertEqual(set(req), {"op", "note", "text"})
        self.assertEqual(req["op"], "create")
        self.assertEqual(req["note"], "Inbox/2026-10-18 dora-discover-the-client-asks 224107.md")
        self.assertTrue(req["text"].startswith("---\ntags:\n  - chat\ncreated: 2026-10-18\nfrom: julz chat\n---\n\n"
                                               "# Saved from the chat 2026-10-18\n\n"))
        self.assertTrue(req["text"].endswith(SAVED + "\n"))

    def test_requests_refuse_what_save_text_did_not_build(self):
        for bad in ("", "save: chat answer\n", "save: other\nx\n", "feedback: idea\nx\n",
                    "save: chat answer\nno last newline", "save: chat answer\na\u202eb\n"):
            with self.subTest(bad=bad[:30]):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.save_request(bad, NOW)


class SaveVaultTest(VaultBase):
    def test_a_signed_answer_lands_in_inbox(self):
        vault_mod.write_request(self.requests, vault_mod.save_request(vault_mod.save_text(ANSWER), NOW))
        self.assertEqual(self.run_vault()[0][1], "ok")
        note = self.vault / "Inbox" / "2026-10-18 dora-discover-the-client-asks 224107.md"
        self.assertIn("from: julz chat", note.read_text())

    def test_create_reaches_inbox_but_not_its_hidden_folders(self):
        self.request({"op": "create", "note": "Inbox/.requests/x.md", "text": "# x\n"})
        self.request({"op": "create", "note": "Inbox/../study/x.md", "text": "# x\n"})
        results = self.run_vault()
        self.assertEqual([r[1] for r in results], ["refused", "refused"])
        self.assertFalse((self.vault / "study" / "x.md").exists())

    def test_inbox_is_the_only_new_root(self):
        self.assertEqual(vault_mod.OPS["create"][1], ("study", "daily", "feedback", "Inbox"))


if __name__ == "__main__":
    unittest.main()
