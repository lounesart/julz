"""Notes v2 in tools/julz_notes.py: list, due, mark reviewed, append (SECURITY.md 65 to 68).
The tool never writes a note in study/. It only drops a request for julz-vault."""
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

from test_julz_notes import load_tool_module

TODAY = date(2026, 10, 16)


def note(front: str, body: str) -> str:
    return f"---\n{front}\n---\n\n{body}" if front else body


# My message asking for the save (threat 161)
ASKED = [{"role": "user", "content": "save this"}]


class NotesV2Test(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.vault = base / "vault"
        self.inbox = self.vault / "Inbox"
        self.requests = self.inbox / ".requests"
        study = self.vault / "study"
        study.mkdir(parents=True)
        self.inbox.mkdir()
        (self.vault / "Claude" / "network-plus").mkdir(parents=True)
        (self.vault / "Outbox").mkdir()
        self.log = base / "actions.log"
        self.secret = base / "secret.md"
        self.secret.write_text("TOP SECRET")
        (study / "dhcp.md").write_text(note(
            "tags: [network-plus, dhcp]\nstatus: learning\nreviewed: 2026-10-10",
            "# DHCP\nDORA, UDP 67 and 68.\n"))
        (study / "dns.md").write_text(note(
            "tags: [network-plus]\nstatus: solid\nreviewed: 2026-10-01", "# DNS\nPort 53.\n"))
        (study / "stride.md").write_text(note(
            "tags: [security-plus]\nstatus: review\nreviewed: 2026-10-14", "# STRIDE\nSix.\n"))
        (study / "osi.md").write_text("# OSI model\nSeven layers.\n")  # no front matter
        (self.vault / "Claude" / "network-plus" / "acls.md").write_text("# ACLs\nImplicit deny.\n")
        (self.vault / "Outbox" / "abc.md").write_text("Run report.\n")
        os.environ.update(JULZ_VAULT=str(self.vault), JULZ_INBOX=str(self.inbox),
                          JULZ_LOG=str(self.log))
        self.mod = load_tool_module()
        self.tools = self.mod.Tools()
        self.tools._today = lambda: TODAY

    def tearDown(self):
        self.tmp.cleanup()

    def requests_written(self):
        if not self.requests.exists():
            return []
        return [json.loads(p.read_text()) for p in sorted(self.requests.glob("*.json"))]

    def study_unchanged(self):
        return {p.name: p.read_text() for p in (self.vault / "study").iterdir()}

    # ----- titles skip front matter -----

    async def test_title_is_the_heading_not_the_front_matter(self):
        out = await self.tools.search_notes("dhcp")
        self.assertIn("DHCP", out)
        out = await self.tools.read_note("dhcp")
        self.assertIn("DORA", out)
        found, _ = self.tools._find("dhcp")
        self.assertEqual(found[0][1], "# DHCP")

    # ----- create_note shows what it saved -----

    async def test_create_answers_with_the_saved_text(self):
        # The user cannot see Inbox from the chat (asked for 2026-10-16), so the answer
        # carries the exact text, and the place to find it
        out = await self.tools.create_note("physio", "I need to write a review to my physio.", __messages__=ASKED)
        self.assertIn("Inbox/physio.md", out)
        self.assertIn("I need to write a review to my physio.", out)

    async def test_inbox_can_be_listed(self):
        (self.inbox / "physio.md").write_text("# Physio\n")
        out = await self.tools.list_notes("inbox")
        self.assertIn("Inbox/physio.md", out)
        self.assertIn("julz wrote", out)

    # ----- list_notes -----

    async def test_list_all_shows_folder_who_title_and_status(self):
        out = await self.tools.list_notes()
        for part in ("study/dhcp.md", "# DHCP", "learning", "study/osi.md",
                     "Claude/network-plus/acls.md", "Claude wrote", "Outbox/abc.md"):
            self.assertIn(part, out)

    async def test_list_by_topic_uses_folder_and_tags(self):
        out = await self.tools.list_notes("network-plus")
        self.assertIn("study/dhcp.md", out)  # by tag
        self.assertIn("study/dns.md", out)
        self.assertIn("Claude/network-plus/acls.md", out)  # by folder
        self.assertNotIn("stride", out)
        self.assertNotIn("osi", out)

    async def test_list_skips_hidden_and_symlinks(self):
        (self.vault / "study" / "link.md").symlink_to(self.secret)
        self.requests.mkdir()
        (self.requests / "x.md").write_text("hidden")
        out = await self.tools.list_notes()
        self.assertNotIn("link.md", out)
        self.assertNotIn(".requests", out)

    async def test_list_unknown_topic(self):
        out = await self.tools.list_notes("kubernetes")
        self.assertIn("No notes", out)

    # ----- due_notes -----

    async def test_due_picks_overdue_study_notes_most_overdue_first(self):
        out = await self.tools.due_notes()
        # dhcp: learning, 6 days ago, every 3 -> due. dns: solid, 15 days, every 30 -> not.
        # stride: review, 2 days, every 7 -> not. osi: never reviewed -> due first.
        self.assertIn("study/dhcp.md", out)
        self.assertIn("study/osi.md", out)
        self.assertNotIn("dns.md", out)
        self.assertNotIn("stride", out)
        self.assertLess(out.index("osi.md"), out.index("dhcp.md"))
        self.assertNotIn("acls", out)  # only my own notes are quizzed

    async def test_nothing_due(self):
        self.tools._today = lambda: date(2026, 10, 1)
        for p in (self.vault / "study").iterdir():
            p.write_text(note("status: solid\nreviewed: 2026-10-01", "# X\n"))
        out = await self.tools.due_notes()
        self.assertIn("Nothing is due", out)

    async def test_bad_review_date_counts_as_never_reviewed(self):
        (self.vault / "study" / "dns.md").write_text(note("reviewed: someday", "# DNS\n"))
        out = await self.tools.due_notes()
        self.assertIn("study/dns.md", out)

    # ----- mark_reviewed -----

    async def test_mark_reviewed_writes_a_request_without_text(self):
        out = await self.tools.mark_reviewed("dhcp")
        self.assertIn("study/dhcp.md", out)
        self.assertEqual(self.requests_written(), [{"op": "reviewed", "note": "study/dhcp.md"}])
        self.assertEqual(self.log_entries()[-1]["action"], "mark_reviewed")

    async def test_mark_reviewed_only_my_notes(self):
        before = self.study_unchanged()
        for target in ("Claude/network-plus/acls.md", "Outbox/abc.md", "../secret.md", "acls"):
            out = await self.tools.mark_reviewed(target)
            self.assertTrue(out.startswith(("Refused", "No note")), f"{target} -> {out}")
        self.assertEqual(self.requests_written(), [])
        self.assertEqual(self.study_unchanged(), before)

    # ----- append_note -----

    async def test_append_asks_me_and_writes_a_request_only(self):
        before = self.study_unchanged()
        seen = []

        async def confirm(event):
            seen.append(event)
            return True

        out = await self.tools.append_note("dhcp", "Relay agents forward to another subnet.",
                                           __event_call__=confirm, __messages__=ASKED)
        self.assertIn("study/dhcp.md", out)
        self.assertEqual(seen[0]["type"], "confirmation")
        self.assertIn("study/dhcp.md", seen[0]["data"]["message"])
        self.assertIn("Relay agents", seen[0]["data"]["message"])
        self.assertEqual(self.requests_written(), [{
            "op": "append", "note": "study/dhcp.md",
            "text": "Relay agents forward to another subnet."}])
        self.assertEqual(self.study_unchanged(), before)  # the host unit does the write
        entry = self.log_entries()[-1]
        self.assertEqual(entry["action"], "append_note")
        self.assertNotIn("Relay", json.dumps(entry))  # content never logged

    async def test_append_without_my_click_writes_nothing(self):
        async def cancel(_event):
            return False

        async def disconnected(_event):
            return {"error": "Client session disconnected."}

        for call in (None, cancel, disconnected):
            out = await self.tools.append_note("dhcp", "text", __event_call__=call, __messages__=ASKED)
            self.assertTrue(out.startswith("Not added"), out)
        self.assertEqual(self.requests_written(), [])

    async def test_append_refuses_other_folders_and_escapes(self):
        async def confirm(_event):
            return True

        for target in ("Claude/network-plus/acls.md", "Outbox/abc.md", "Inbox/x.md",
                       "../secret.md", "/etc/passwd", "study/missing.md", "acls"):
            out = await self.tools.append_note(target, "x", __event_call__=confirm, __messages__=ASKED)
            self.assertTrue(out.startswith(("Refused", "No note")), f"{target} -> {out}")
        self.assertEqual(self.requests_written(), [])

    async def test_append_needs_one_clear_note(self):
        (self.vault / "study" / "dhcp-lab.md").write_text("# DHCP lab\n")

        async def confirm(_event):
            return True

        (self.vault / "study" / "dhcp.md").rename(self.vault / "study" / "dhcp-notes.md")
        out = await self.tools.append_note("dhcp", "x", __event_call__=confirm, __messages__=ASKED)
        self.assertIn("Several notes", out)
        self.assertEqual(self.requests_written(), [])

    async def test_append_size_and_empty_text(self):
        async def confirm(_event):
            return True

        for text in ("", "   \n", "x" * (self.mod.MAX_APPEND_CHARS + 1)):
            out = await self.tools.append_note("dhcp", text, __event_call__=confirm, __messages__=ASKED)
            self.assertTrue(out.startswith("Refused"), out)
        self.assertEqual(self.requests_written(), [])

    async def test_append_refuses_links_html_and_hidden_chars_before_asking(self):
        asked = []

        async def confirm(event):
            asked.append(event)
            return True

        for text in ("see [docs](https://evil.example)", "![x](https://e.example/a.png)",
                     "<img src=x>", "go to https://evil.com/?d=1", "www.evil.com",
                     "zero\u200bwidth", "bidi\u202eflip"):
            out = await self.tools.append_note("dhcp", text, __event_call__=confirm, __messages__=ASKED)
            self.assertTrue(out.startswith("Refused"), f"{text!r} -> {out}")
        self.assertEqual(asked, [])
        self.assertEqual(self.requests_written(), [])

    async def test_append_rate_limit_shared_with_create(self):
        async def confirm(_event):
            return True

        for i in range(self.mod.MAX_WRITES_PER_MINUTE):
            await self.tools.create_note(f"n{i}", "x", __messages__=ASKED)
        out = await self.tools.append_note("dhcp", "x", __event_call__=confirm, __messages__=ASKED)
        self.assertTrue(out.startswith("Refused"), out)

    async def test_request_appears_whole(self):
        async def confirm(_event):
            return True

        await self.tools.append_note("dhcp", "x", __event_call__=confirm, __messages__=ASKED)
        names = [p.name for p in self.requests.iterdir()]
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], r"^\d{10}-[0-9a-f]{8}\.json$")  # no .tmp left behind

    def log_entries(self):
        return [json.loads(l) for l in self.log.read_text().splitlines()]


if __name__ == "__main__":
    unittest.main()
