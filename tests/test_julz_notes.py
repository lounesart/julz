"""Attack tests for tools/julz_notes.py. Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

TOOL_FILE = Path(__file__).resolve().parent.parent / "tools" / "julz_notes.py"


def load_tool_module():
    spec = importlib.util.spec_from_file_location("julz_notes", TOOL_FILE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class JulzNotesTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.vault = base / "vault"
        self.inbox = self.vault / "Inbox"
        (self.vault / "study").mkdir(parents=True)
        self.inbox.mkdir()
        (self.vault / ".obsidian").mkdir()
        self.log = base / "actions.log"
        self.secret = base / "secret.md"  # outside the vault
        self.secret.write_text("TOP SECRET")
        (self.vault / "study" / "dns.md").write_text("# DNS\nPort 53, zone transfer uses TCP.\n")
        (self.vault / ".obsidian" / "hidden.md").write_text("hidden")
        os.environ.update(JULZ_VAULT=str(self.vault), JULZ_INBOX=str(self.inbox),
                          JULZ_LOG=str(self.log))
        self.mod = load_tool_module()
        self.tools = self.mod.Tools()

    def tearDown(self):
        self.tmp.cleanup()

    def log_entries(self):
        if not self.log.exists():
            return []
        return [json.loads(l) for l in self.log.read_text().splitlines()]

    # ----- read_note -----

    async def test_read_normal_note(self):
        out = await self.tools.read_note("study/dns.md")
        self.assertIn("zone transfer", out)

    async def test_read_traversal_refused(self):
        for evil in ["../secret.md", "../../.bashrc", "study/../../secret.md",
                     "/etc/passwd", "~/.bashrc", "study/dns.md\x00.txt"]:
            out = await self.tools.read_note(evil)
            self.assertTrue(out.startswith("Refused"), f"{evil!r} -> {out!r}")
            self.assertNotIn("TOP SECRET", out)

    async def test_read_symlink_escape_refused(self):
        (self.vault / "study" / "link.md").symlink_to(self.secret)
        out = await self.tools.read_note("study/link.md")
        self.assertTrue(out.startswith("Refused"), out)
        self.assertNotIn("TOP SECRET", out)

    async def test_read_hidden_and_non_md_refused(self):
        self.assertTrue((await self.tools.read_note(".obsidian/hidden.md")).startswith("Refused"))
        (self.vault / "study" / "notes.txt").write_text("x")
        self.assertTrue((await self.tools.read_note("study/notes.txt")).startswith("Refused"))

    # ----- search_notes -----

    async def test_search_finds_and_skips_hidden_and_symlinks(self):
        (self.vault / "study" / "link.md").symlink_to(self.secret)
        self.assertIn("study/dns.md", await self.tools.search_notes("zone transfer"))
        self.assertNotIn(".obsidian", await self.tools.search_notes("hidden"))
        self.assertNotIn("link.md", await self.tools.search_notes("SECRET"))

    async def test_search_by_file_name_never_looks_empty(self):
        # Found live 2026-10-16: "dhcp.md" matched the name, no line held it, the hit showed
        # nothing after the colon, and julz said the note was essentially empty
        out = await self.tools.search_notes("dns.md")
        self.assertIn("study/dns.md", out)
        self.assertIn("# DNS", out)
        self.assertFalse([l for l in out.splitlines() if l.rstrip().endswith(":")], out)
        (self.vault / "study" / "x-ray.md").write_text("# Something else\n")
        out = await self.tools.search_notes("x-ray")  # only the name has these words
        self.assertIn("(name matches) # Something else", out)

    # ----- read_note with a bare name -----

    async def test_read_bare_name_points_to_the_paths(self):
        (self.vault / "Claude" / "net" / "labs").mkdir(parents=True)
        (self.vault / "Claude" / "net" / "labs" / "dns.md").write_text("# Lab DNS\n")
        out = await self.tools.read_note("dns.md")
        self.assertIn("study/dns.md", out)
        self.assertIn("Claude/net/labs/dns.md", out)
        self.assertIn("read_note", out)  # tells her what to call next
        self.assertNotIn("zone transfer", out)  # no guessing which one she meant

    async def test_read_unknown_bare_name(self):
        out = await self.tools.read_note("nothing.md")
        self.assertIn("search_notes", out)

    # ----- read_note from loose words (asked for 2026-10-16) -----

    def two_dhcp_notes(self):
        (self.vault / "study" / "dhcp.md").write_text("# DHCP\nDORA, my own words.\n")
        labs = self.vault / "Claude" / "network-plus" / "ac7ec2c4" / "labs"
        labs.mkdir(parents=True)
        (labs / "05-dhcp.md").write_text("# Lab 05: DHCP Lease Process\nUDP 67 and 68.\n")

    async def test_loose_words_open_the_right_note(self):
        self.two_dhcp_notes()
        cases = {"dhcp": "my own words", "DHCP": "my own words", "dhcp.md": "my own words",
                 "my dhcp note": "my own words", "dhcp lab": "UDP 67", "05-dhcp": "UDP 67",
                 "DHCP lease": "UDP 67", "the dhcp lab guide": "UDP 67"}
        for words, expect in cases.items():
            with self.subTest(words=words):
                out = await self.tools.read_note(words)
                self.assertIn(expect, out)
                self.assertIn("opened", out)  # always says which file, so a wrong guess shows

    async def test_notes_win_a_tie_over_reports_and_drafts(self):
        # Found on the real vault: a run report's first line names every lab it wrote
        self.two_dhcp_notes()
        (self.vault / "Outbox").mkdir()
        (self.vault / "Outbox" / ("a" * 64 + ".md")).write_text("All dhcp labs written.\n")
        (self.inbox / "dhcp-lab-draft.md").write_text("# dhcp lab, draft by julz\n")
        out = await self.tools.read_note("dhcp lab")
        self.assertIn("UDP 67", out)

    async def test_tie_lists_choices_and_reads_nothing(self):
        (self.vault / "study" / "vlan-basics.md").write_text("# VLAN basics\nmine\n")
        (self.vault / "study" / "vlan-trunks.md").write_text("# VLAN trunks\nmine too\n")
        out = await self.tools.read_note("vlan")
        self.assertIn("study/vlan-basics.md", out)
        self.assertIn("study/vlan-trunks.md", out)
        self.assertNotIn("mine", out)

    async def test_choices_say_who_wrote_it(self):
        self.two_dhcp_notes()
        (self.vault / "Claude" / "network-plus" / "ac7ec2c4" / "labs" / "dhcp.md").write_text(
            "# DHCP\nanother\n")
        out = await self.tools.read_note("dhcp")
        self.assertIn("Claude wrote", out)
        self.assertIn("your note", out)

    async def test_loose_words_never_leave_the_vault(self):
        out = await self.tools.read_note("secret")
        self.assertNotIn("TOP SECRET", out)
        out = await self.tools.read_note("hidden")
        self.assertNotIn(".obsidian", out)

    async def test_search_any_word_order_any_case(self):
        self.two_dhcp_notes()
        out = await self.tools.search_notes("Lease DHCP")
        self.assertIn("Claude/network-plus/ac7ec2c4/labs/05-dhcp.md", out)
        self.assertNotIn("study/dhcp.md", out)  # "lease" is not in my note

    # ----- create_note -----

    async def test_create_new_note_in_inbox_and_log_it(self):
        out = await self.tools.create_note("vlan cheatsheet", "# VLANs\n802.1Q tags frames.")
        self.assertTrue(out.startswith("Saved"), out)
        self.assertEqual((self.inbox / "vlan cheatsheet.md").read_text(), "# VLANs\n802.1Q tags frames.")
        entry = self.log_entries()[-1]
        self.assertEqual(entry["action"], "create_note")
        self.assertNotIn("802.1Q", json.dumps(entry))  # content never logged

    async def test_create_traversal_names_refused(self):
        for evil in ["../../.bashrc", "../study/dns", "/etc/cron.d/x", ".hidden",
                     "a/b", "..", "x\x00y", ""]:
            out = await self.tools.create_note(evil, "pwned")
            self.assertTrue(out.startswith("Refused"), f"{evil!r} -> {out!r}")
        self.assertEqual(sorted(p.name for p in self.inbox.iterdir()), [])
        self.assertIn("zone transfer", (self.vault / "study" / "dns.md").read_text())

    async def test_bad_name_refusal_logged_and_says_nothing_saved(self):
        # Phone check 24 Oct: "todo/today" refused with no log line, and she claimed a save (208)
        out = await self.tools.create_note("todo/today", "- [ ] Buy bread")
        self.assertTrue(out.startswith("Refused"), out)
        self.assertIn("Nothing was saved", out)
        self.assertIn("folder", out)
        entry = self.log_entries()[-1]
        self.assertEqual((entry["action"], entry["reason"]), ("create_note_refused", "bad name"))
        self.assertEqual(entry["note"], "todo/today")
        self.assertNotIn("Buy bread", json.dumps(entry))  # content never logged

    async def test_bad_name_logged_cut_short(self):
        await self.tools.create_note("../" + "x" * 500, "pwned")
        self.assertEqual(len(self.log_entries()[-1]["note"]), 80)

    async def test_overwrite_without_event_call_refused(self):
        (self.inbox / "todo.md").write_text("original")
        out = await self.tools.create_note("todo", "replaced")
        self.assertTrue(out.startswith("Not saved"), out)
        self.assertEqual((self.inbox / "todo.md").read_text(), "original")
        self.assertEqual(self.log_entries()[-1]["action"], "create_note_refused")

    async def test_overwrite_when_user_clicks_cancel(self):
        (self.inbox / "todo.md").write_text("original")

        async def cancel(_event):
            return False

        await self.tools.create_note("todo", "replaced", __event_call__=cancel)
        self.assertEqual((self.inbox / "todo.md").read_text(), "original")

    async def test_overwrite_fails_closed_on_disconnected_browser(self):
        # v0.11.4 returns this dict when no browser session is connected. It is truthy.
        (self.inbox / "todo.md").write_text("original")

        async def disconnected(_event):
            return {"error": "Client session disconnected."}

        out = await self.tools.create_note("todo", "replaced", __event_call__=disconnected)
        self.assertTrue(out.startswith("Not saved"), out)
        self.assertEqual((self.inbox / "todo.md").read_text(), "original")

    async def test_overwrite_when_user_confirms(self):
        (self.inbox / "todo.md").write_text("original")
        seen = []

        async def confirm(event):
            seen.append(event)
            return True

        out = await self.tools.create_note("todo", "replaced", __event_call__=confirm)
        self.assertTrue(out.startswith("Saved"), out)
        self.assertEqual((self.inbox / "todo.md").read_text(), "replaced")
        self.assertEqual(seen[0]["type"], "confirmation")
        self.assertEqual(self.log_entries()[-1]["action"], "overwrite_note")

    async def test_overwrite_symlink_in_inbox_refused(self):
        (self.inbox / "trap.md").symlink_to(self.secret)

        async def confirm(_event):
            return True

        out = await self.tools.create_note("trap", "pwned", __event_call__=confirm)
        self.assertTrue(out.startswith("Refused"), out)
        self.assertEqual(self.secret.read_text(), "TOP SECRET")

    async def test_size_limit(self):
        out = await self.tools.create_note("big", "x" * (self.mod.MAX_NOTE_BYTES + 1))
        self.assertTrue(out.startswith("Refused"), out)
        self.assertFalse((self.inbox / "big.md").exists())

    async def test_rate_limit(self):
        for i in range(self.mod.MAX_WRITES_PER_MINUTE):
            self.assertTrue((await self.tools.create_note(f"n{i}", "x")).startswith("Saved"))
        out = await self.tools.create_note("one-too-many", "x")
        self.assertTrue(out.startswith("Refused"), out)


if __name__ == "__main__":
    unittest.main()
