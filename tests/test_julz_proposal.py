"""Threat 156: a change Julz asks for in the native chat becomes a card I sign (208). The
proposal is model output, so julz_vault checks it as a request and builds the card text from
its checked fields in fixed words."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import julz_vault as vault  # noqa: E402

SHA = "a" * 64


def raw(**req):
    return json.dumps(req).encode()


class CardTextTest(unittest.TestCase):
    def card(self, **req):
        return vault.proposal_card(raw(**req))

    def test_each_op_in_fixed_words(self):
        cases = [
            ({"op": "append", "note": "daily/week.md", "text": "- [ ] bread"},
             "Julz asks to add to daily/week.md:\n\n- [ ] bread\n"),
            ({"op": "replace", "note": "study/network-plus/dhcp.md", "old": "Relay agents.",
              "new": "Relays.", "sha256": SHA},
             "Julz asks to change study/network-plus/dhcp.md\n\nBefore:\nRelay agents.\n\nAfter:\nRelays.\n"),
            ({"op": "replace", "note": "daily/week.md", "old": "bread", "new": "", "sha256": SHA},
             "Julz asks to change daily/week.md\n\nBefore:\nbread\n\nAfter:\n(removed)\n"),
            ({"op": "move", "note": "Inbox/physio.md", "to": "daily/physio.md", "sha256": SHA},
             "Julz asks to move Inbox/physio.md to daily/physio.md\n"),
            ({"op": "delete", "note": "Inbox/physio.md", "sha256": SHA},
             "Julz asks to delete Inbox/physio.md\n\ngit keeps a copy on the laptop.\n"),
            ({"op": "create", "note": "daily/eat.md", "text": "# Eat\n\n- [ ] eat\n"},
             "Julz asks to create daily/eat.md:\n\n# Eat\n\n- [ ] eat\n"),
            ({"op": "create", "note": "feedback/2026-10-25 too-long.md", "text": "Too long.\n"},
             "Julz asks to create feedback/2026-10-25 too-long.md:\n\nToo long.\n"),
        ]
        for req, text in cases:
            with self.subTest(op=req["op"]):
                got, card = self.card(**req)
                self.assertEqual(got, req)
                self.assertEqual(card, text)

    def test_only_five_ops(self):
        for req in ({"op": "reviewed", "note": "study/linux/nftables.md"},
                    {"op": "tick", "note": "daily/week.md", "item": "bread"},
                    {"op": "resolve", "note": "feedback/x.md"},
                    {"op": "goal", "note": "goals/2026-W43.md", "item": "x"},
                    {"op": "rm", "note": "daily/week.md"}):
            with self.subTest(op=req["op"]):
                with self.assertRaises(vault.Refused):
                    self.card(**req)

    def test_shape_refused(self):
        for data in (b"", b"not json", b"[]", b"\xff\xfe", b"x" * (vault.MAX_REQUEST_BYTES + 1),
                     raw(op="append", note="daily/week.md", text="x", extra=1),
                     raw(op="append", note="daily/week.md"),
                     raw(op="delete", note="daily/week.md", sha256="nothex"),
                     raw(op="delete", note="daily/week.md", sha256=5),
                     raw(op="delete", note="daily/week.md", sha256=SHA + "\n"),
                     raw(op="move", note="daily/a.md", to="daily/b.md", sha256=SHA.upper())):
            with self.subTest(data=data[:40]):
                with self.assertRaises(vault.Refused):
                    vault.proposal_card(data)

    def test_paths_refused(self):
        bad = ("Inbox/claude/spec.md", "Inbox/.requests/x.md", "Inbox/.proposals/x.md",
               ".git/config", "Claude/net/acls.md", "Outbox/r.md", "Templates/t.md",
               "goals/2026-W43.md", "feedback/x.md", "../outside.md", "/etc/passwd",
               "study/a/b/c.md", "daily/x.txt", "daily/a\u202eb.md", "daily/a\u200bb.md", "daily/.md")
        for note in bad:
            for req in ({"op": "append", "note": note, "text": "x"},
                        {"op": "delete", "note": note, "sha256": SHA},
                        {"op": "replace", "note": note, "old": "a", "new": "b", "sha256": SHA}):
                with self.subTest(note=note, op=req["op"]):
                    with self.assertRaises(vault.Refused):
                        self.card(**req)
        for to in ("Inbox/claude/x.md", "Claude/x.md", "feedback/x.md", "../x.md", "daily/a\u202eb.md"):
            with self.subTest(to=to):
                with self.assertRaises(vault.Refused):
                    self.card(op="move", note="Inbox/physio.md", to=to, sha256=SHA)
        # A new note never goes into Inbox (no card needed there) or an eval case folder
        for note in ("Inbox/x.md", "feedback/eval/x.md", "Claude/x.md", "study/x/y/z.md"):
            with self.subTest(create=note):
                with self.assertRaises(vault.Refused):
                    self.card(op="create", note=note, text="x")

    def test_text_refused(self):
        for text in ("", "   ", "a\u202eb", "a\u200bb", "<script>x</script>", 5, None,
                     "x" * (vault.MAX_APPEND_CHARS + 1)):
            with self.subTest(text=str(text)[:20]):
                with self.assertRaises(vault.Refused):
                    self.card(op="append", note="daily/week.md", text=text)
                with self.assertRaises(vault.Refused):
                    self.card(op="replace", note="daily/week.md", old=text, new="b", sha256=SHA)
                with self.assertRaises(vault.Refused):
                    self.card(op="create", note="daily/new.md", text=text)
        # An empty new text removes the passage; anything else in it is checked the same
        for text in ("a\u202eb", "<script>x</script>", 5, None, "x" * (vault.MAX_APPEND_CHARS + 1)):
            with self.subTest(new=str(text)[:20]):
                with self.assertRaises(vault.Refused):
                    self.card(op="replace", note="daily/week.md", old="a", new=text, sha256=SHA)

    def test_card_fits_the_phone(self):
        # The app shows the card whole: over the cap it is not listed at all
        long = "word " * (vault.MAX_CARD // 5)
        with self.assertRaises(vault.Refused):
            self.card(op="create", note="daily/long.md", text=long)
        req, card = self.card(op="create", note="daily/ok.md", text="x" * (vault.MAX_CARD - 100))
        self.assertLessEqual(len(card), vault.MAX_CARD)

    def test_ops_match_julz_vault(self):
        # A proposal is a request julz-vault would take, with exactly its fields
        for op in vault.PROPOSAL_OPS:
            self.assertIn(op, vault.OPS)


if __name__ == "__main__":
    unittest.main()
