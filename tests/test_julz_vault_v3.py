"""julz_vault v3: replace a passage, move, delete, create, index notes (SECURITY.md 71 to 76).
Every op is checked again here: the container could write a request without my click."""
import hashlib
import os
import unittest

from test_julz_vault import VaultBase


class VaultV3Test(VaultBase):
    def setUp(self):
        super().setUp()
        (self.study / "network-plus").mkdir()
        self.vlan = self.study / "network-plus" / "vlan.md"
        self.vlan.write_text("---\ntags:\n  - network-plus\n---\n\n# VLAN\nSplits a switch.\n"
                             "Trunks carry many.\n")
        (self.study / "security-plus").mkdir()
        (self.study / "security-plus" / "ports.md").write_text(
            "---\ntags: [security-plus, network-plus]\n---\n\n# Ports\n")
        (self.vault / "daily").mkdir()
        self.inbox = self.vault / "Inbox"
        (self.inbox / "physio.md").write_text("# Physio\nWrite a review.\n")
        (self.inbox / "claude").mkdir()
        (self.inbox / "claude" / "spec.md").write_text("# spec\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "v3 fixture")

    @staticmethod
    def sha(p) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def julz_commits(self):
        return [c for c in self.commits() if c.startswith("julz")]

    # ----- replace -----

    def test_replace_changes_only_that_passage(self):
        before = self.vlan.read_text()
        self.request({"op": "replace", "note": "study/network-plus/vlan.md",
                      "old": "Trunks carry many.", "new": "Trunks carry many VLANs (802.1Q).",
                      "sha256": self.sha(self.vlan)})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertEqual(self.vlan.read_text(), before.replace(
            "Trunks carry many.", "Trunks carry many VLANs (802.1Q)."))
        self.assertRegex(self.julz_commits()[0], r"^julz: edited study/network-plus/vlan\.md")

    def test_replace_with_empty_removes_the_passage(self):
        self.request({"op": "replace", "note": "study/network-plus/vlan.md",
                      "old": "Trunks carry many.\n", "new": "", "sha256": self.sha(self.vlan)})
        self.run_vault()
        self.assertNotIn("Trunks", self.vlan.read_text())
        self.assertIn("Splits a switch.", self.vlan.read_text())

    def test_replace_refusals(self):
        h = self.sha(self.vlan)
        n = "study/network-plus/vlan.md"
        self.vlan.write_text(self.vlan.read_text() + "Splits a switch.\n")
        h2 = self.sha(self.vlan)
        before = self.vlan.read_text()
        for req in (
            {"op": "replace", "note": n, "old": "Trunks carry many.", "new": "x", "sha256": h},  # stale
            {"op": "replace", "note": n, "old": "Splits a switch.", "new": "x", "sha256": h2},  # twice
            {"op": "replace", "note": n, "old": "not there", "new": "x", "sha256": h2},
            {"op": "replace", "note": n, "old": "", "new": "x", "sha256": h2},
            {"op": "replace", "note": n, "old": "Trunks carry many.", "new": "[a](https://e.com)",
             "sha256": h2},
            {"op": "replace", "note": n, "old": "Trunks carry many.",
             "new": "x" * 5000, "sha256": h2},
            {"op": "replace", "note": n, "old": "Trunks carry many.", "new": 5, "sha256": h2},
            {"op": "replace", "note": "Claude/acls.md", "old": "# ACLs", "new": "x",
             "sha256": self.sha(self.vault / "Claude" / "acls.md")},
        ):
            self.request(req)
        results = self.run_vault()
        self.assertEqual([r[1] for r in results], ["refused"] * 8, results)
        self.assertEqual(self.vlan.read_text(), before)
        self.assertEqual(self.julz_commits(), [])

    # ----- move -----

    def test_move_inbox_note_to_daily(self):
        src = self.inbox / "physio.md"
        self.request({"op": "move", "note": "Inbox/physio.md", "to": "daily/physio.md",
                      "sha256": self.sha(src)})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertFalse(src.exists())
        self.assertEqual((self.vault / "daily" / "physio.md").read_text(),
                         "# Physio\nWrite a review.\n")
        moved = [c for c in self.julz_commits() if c.startswith("julz: moved")]
        self.assertEqual(len(moved), 1)
        self.assertTrue(moved[0].startswith("julz: moved Inbox/physio.md to daily/physio.md"))
        rev = self.git("log", "--format=%h", "--grep=julz: moved").split()[0]
        self.assertIn("R100", self.git("show", "--name-status", "--format=", rev))

    def test_move_makes_one_new_folder(self):
        self.request({"op": "move", "note": "study/osi.md", "to": "study/network-plus/osi.md",
                      "sha256": self.sha(self.study / "osi.md")})
        self.request({"op": "move", "note": "Inbox/physio.md", "to": "daily/health/physio.md",
                      "sha256": self.sha(self.inbox / "physio.md")})
        self.assertEqual([r[1] for r in self.run_vault()], ["ok", "ok"])
        self.assertTrue((self.vault / "daily" / "health" / "physio.md").exists())

    def test_move_refusals(self):
        src = self.inbox / "physio.md"
        h = self.sha(src)
        for to in ("study/network-plus/vlan.md",  # exists: never overwrite
                   "Claude/physio.md", "Outbox/physio.md", "Templates/physio.md",
                   "../physio.md", "/tmp/physio.md", "study/a/b/physio.md",
                   "study/.hidden/physio.md", "study/Bad Folder/physio.md", "daily/physio.txt",
                   "Inbox/claude/physio.md", "daily/physio..md", 7):
            self.request({"op": "move", "note": "Inbox/physio.md", "to": to, "sha256": h})
        self.request({"op": "move", "note": "Inbox/physio.md", "to": "daily/p.md", "sha256": "0" * 64})
        self.request({"op": "move", "note": "Inbox/claude/spec.md", "to": "daily/spec.md",
                      "sha256": self.sha(self.inbox / "claude" / "spec.md")})
        self.request({"op": "move", "note": "Claude/acls.md", "to": "daily/acls.md",
                      "sha256": self.sha(self.vault / "Claude" / "acls.md")})
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertEqual(len(results), 16)
        self.assertTrue(src.exists())
        self.assertTrue((self.inbox / "claude" / "spec.md").exists())
        self.assertEqual(self.julz_commits(), [])

    # ----- delete -----

    def test_delete_and_restore_from_git(self):
        src = self.inbox / "physio.md"
        self.request({"op": "delete", "note": "Inbox/physio.md", "sha256": self.sha(src)})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertFalse(src.exists())
        self.assertTrue(self.julz_commits()[0].startswith("julz: deleted Inbox/physio.md"))
        rev = self.git("log", "--format=%h", "--grep=julz: deleted").split()[0]
        self.git("checkout", rev + "^", "--", "Inbox/physio.md")
        self.assertEqual(src.read_text(), "# Physio\nWrite a review.\n")
        entry = self.log()[-1]
        self.assertEqual((entry["action"], entry["status"]), ("note-delete", "ok"))

    def test_delete_refusals(self):
        for note, path in (("Claude/acls.md", self.vault / "Claude" / "acls.md"),
                           ("Inbox/claude/spec.md", self.inbox / "claude" / "spec.md"),
                           ("study/dhcp.md", None)):
            self.request({"op": "delete", "note": note,
                          "sha256": self.sha(path) if path else "0" * 64})
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertTrue((self.study / "dhcp.md").exists())
        self.assertTrue((self.vault / "Claude" / "acls.md").exists())

    # ----- create -----

    def test_create_in_daily_and_study(self):
        self.request({"op": "create", "note": "daily/physio review.md",
                      "text": "---\ntags:\n  - todo\n---\n\n# Physio review\n\n- [ ] write it\n"})
        self.request({"op": "create", "note": "study/linux/systemd.md", "text": "# systemd\n"})
        self.assertEqual([r[1] for r in self.run_vault()], ["ok", "ok"])
        self.assertIn("- [ ] write it", (self.vault / "daily" / "physio review.md").read_text())
        self.assertTrue((self.study / "linux" / "systemd.md").exists())

    def test_create_in_inbox_is_allowed_since_139(self):
        # The container writes Inbox directly anyway, so this gives Julz nothing new; the
        # approver's signed save reaches the vault only through requests (139)
        self.request({"op": "create", "note": "Inbox/x.md", "text": "x"})
        self.assertEqual([r[1] for r in self.run_vault()], ["ok"])

    def test_create_refusals(self):
        for req in ({"op": "create", "note": "study/network-plus/vlan.md", "text": "x"},  # exists
                    {"op": "create", "note": "Claude/x.md", "text": "x"},
                    {"op": "create", "note": "daily/x.md", "text": "<script>x</script>"},
                    {"op": "create", "note": "daily/x.md", "text": ""},
                    {"op": "create", "note": "daily/a/b/x.md", "text": "x"}):
            self.request(req)
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertIn("Splits a switch.", self.vlan.read_text())
        self.assertFalse((self.vault / "daily" / "x.md").exists())

    # ----- index notes (MOC) -----

    def test_index_per_cert_folder_from_folder_and_tags(self):
        self.run_vault()
        moc = (self.study / "network-plus" / "network-plus.md").read_text()
        self.assertTrue(moc.startswith("---\nkind: moc\n---\n"))
        self.assertIn("[[study/network-plus/vlan|VLAN]]", moc)
        self.assertIn("[[study/security-plus/ports|Ports]]", moc)  # tagged network-plus elsewhere
        self.assertIn("[[study/security-plus/ports|Ports]]",
                      (self.study / "security-plus" / "security-plus.md").read_text())
        self.assertEqual(self.commits()[0], "vault: index notes updated")
        n = len(self.commits())
        self.run_vault()
        self.assertEqual(len(self.commits()), n)  # unchanged index, no new commit

    def test_index_drops_a_title_with_hidden_chars(self):
        self.vlan.write_text("# VLAN\u202e evil\n")
        self.run_vault()
        moc = (self.study / "network-plus" / "network-plus.md").read_text()
        self.assertIn("[[study/network-plus/vlan|vlan]]", moc)
        self.assertNotIn("\u202e", moc)

    def test_index_never_overwrites_my_own_note_of_that_name(self):
        mine = self.study / "network-plus" / "network-plus.md"
        mine.write_text("# My own overview\n")
        self.run_vault()
        self.assertEqual(mine.read_text(), "# My own overview\n")

    def test_requests_on_an_index_are_refused(self):
        self.run_vault()
        moc = self.study / "network-plus" / "network-plus.md"
        self.request({"op": "append", "note": "study/network-plus/network-plus.md", "text": "x"})
        self.request({"op": "delete", "note": "study/network-plus/network-plus.md",
                      "sha256": self.sha(moc)})
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertTrue(moc.exists())

    def test_move_and_delete_are_pushed_without_names(self):
        self.request({"op": "move", "note": "Inbox/physio.md", "to": "daily/physio.md",
                      "sha256": self.sha(self.inbox / "physio.md")})
        self.run_vault()
        raw = self.dirs.log.read_text()
        self.assertIn('"note-move"', raw)
        self.assertNotIn("physio", raw)

    # ----- found by the mutation check -----

    def test_new_note_through_a_linked_folder_is_refused(self):
        (self.vault / "daily" / "away").symlink_to(self.vault / "Claude")
        self.request({"op": "create", "note": "daily/away/x.md", "text": "x"})
        self.request({"op": "move", "note": "Inbox/physio.md", "to": "daily/away/physio.md",
                      "sha256": self.sha(self.inbox / "physio.md")})
        self.assertEqual([r[1] for r in self.run_vault()], ["refused", "refused"])
        self.assertFalse((self.vault / "Claude" / "x.md").exists())
        self.assertFalse((self.vault / "Claude" / "physio.md").exists())

    def test_move_never_overwrites_even_if_the_target_appears_late(self):
        # the target shows up between the check and the move: link refuses, rename would not
        import julz_vault
        dest = self.vault / "daily" / "physio.md"
        dest.write_text("MINE\n")
        real = julz_vault.new_target
        julz_vault.new_target = lambda vault, note, roots: vault / note
        try:
            self.request({"op": "move", "note": "Inbox/physio.md", "to": "daily/physio.md",
                          "sha256": self.sha(self.inbox / "physio.md")})
            self.assertNotEqual(self.run_vault()[0][1], "ok")
        finally:
            julz_vault.new_target = real
        self.assertEqual(dest.read_text(), "MINE\n")
        self.assertTrue((self.inbox / "physio.md").exists())

    def test_reviewed_only_in_study(self):
        (self.vault / "daily" / "week.md").write_text("# Week\n")
        self.request({"op": "reviewed", "note": "daily/week.md"})
        self.request({"op": "reviewed", "note": "Inbox/physio.md"})
        self.assertEqual([r[1] for r in self.run_vault()], ["refused", "refused"])
        self.assertEqual((self.vault / "daily" / "week.md").read_text(), "# Week\n")

    def test_unchanged_index_is_not_rewritten(self):
        # or recent_notes would list the index notes as changed every 15 minutes
        self.run_vault()
        index = self.study / "network-plus" / "network-plus.md"
        old = index.stat().st_mtime_ns
        os.utime(index, ns=(old - 10**9, old - 10**9))
        self.run_vault()
        self.assertEqual(index.stat().st_mtime_ns, old - 10**9)


    # ----- due count for the push (julz-vault has no network, the push unit reads no notes) -----

    def test_due_count_follows_the_review_rules(self):
        from datetime import date
        import julz_vault
        (self.study / "network-plus" / "solid.md").write_text(
            "---\nstatus: solid\nreviewed: 2026-10-10\n---\n# Solid\n")
        (self.study / "network-plus" / "fresh.md").write_text(
            "---\nstatus: learning\nreviewed: 2026-10-15\n---\n# Fresh\n")
        (self.study / "network-plus" / "edge.md").write_text(  # exactly 3 days: due, as the tool says
            "---\nstatus: learning\nreviewed: 2026-10-13\n---\n# Edge\n")
        (self.vault / "daily" / "week.md").write_text("# Week\n")  # daily is never quizzed
        self.run_vault()  # also writes the index notes, which never count
        # due: dhcp, osi (never reviewed), vlan, ports, edge. Not due: solid, fresh, indexes
        self.assertEqual(julz_vault.due_count(self.vault, date(2026, 10, 16)), 5)

    def test_run_writes_the_due_count_for_today(self):
        import json as j
        self.run_vault()
        data = j.loads((self.state / "due.json").read_text())
        self.assertEqual(data, {"date": "2026-10-16", "due": 4})

    def test_review_rules_match_the_tool(self):
        import julz_vault
        from test_julz_notes import load_tool_module
        tool = load_tool_module()
        self.assertEqual(julz_vault.REVIEW_DAYS, tool.REVIEW_DAYS)
        self.assertEqual(julz_vault.DEFAULT_REVIEW_DAYS, tool.DEFAULT_REVIEW_DAYS)


if __name__ == "__main__":
    unittest.main()
