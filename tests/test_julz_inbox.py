"""julz_vault: the Inbox on the phone, SECURITY.md 116 and 117. The snapshot julz-vault writes,
the text I sign for moves and deletes, and the requests that come out of it."""
import hashlib
import json
import unittest

from test_julz_vault import VaultBase, vault_mod


class InboxBase(VaultBase):
    def setUp(self):
        super().setUp()
        self.inbox = self.vault / "Inbox"
        (self.inbox / "claude").mkdir()
        (self.inbox / "claude" / "spec.md").write_text("goal: x\n")
        (self.inbox / "draft.md").write_text("# Draft\nA thought about DNS.\n")
        (self.inbox / "shop list.md").write_text("- [ ] milk\n")
        (self.study / "network-plus").mkdir()
        (self.vault / "daily" / "done").mkdir(parents=True)
        (self.vault / "daily" / "week.md").write_text("- [ ] walk\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "inbox fixture")

    def snap(self):
        return vault_mod.inbox_snapshot(self.vault)


class InboxSnapshotTest(InboxBase):
    """116: what the phone may see of my Inbox."""

    def test_top_level_inbox_notes_with_hash_and_preview(self):
        s = self.snap()
        self.assertRegex(s["id"], r"^[0-9a-f]{64}$")
        notes = {n["note"]: n for n in s["notes"]}
        self.assertEqual(sorted(notes), ["Inbox/draft.md", "Inbox/shop list.md"])  # not claude/
        d = notes["Inbox/draft.md"]
        self.assertEqual(d["name"], "draft")
        self.assertEqual(d["sha256"], hashlib.sha256((self.inbox / "draft.md").read_bytes()).hexdigest())
        self.assertEqual(d["preview"], "# Draft\nA thought about DNS.\n")
        self.assertEqual(set(d), {"name", "note", "sha256", "size", "modified", "preview"})

    def test_folders_a_note_may_go_to(self):
        self.assertEqual(self.snap()["folders"], ["daily", "study", "study/network-plus"])  # no daily/done

    def test_hidden_and_bidi_characters_become_a_mark(self):
        (self.inbox / "planted.md").write_text("safe \u202eevil\u202c text\u200b and a\ttab\n")
        p = next(n for n in self.snap()["notes"] if n["name"] == "planted")["preview"]
        self.assertEqual(p, "safe �evil� text� and a\ttab\n")

    def test_preview_and_count_are_capped(self):
        (self.inbox / "long.md").write_text("x" * 5000)
        for i in range(25):
            (self.inbox / f"n{i:02d}.md").write_text("y\n")
        s = self.snap()
        self.assertEqual(len(s["notes"]), vault_mod.MAX_INBOX_NOTES)
        long = next(n for n in s["notes"] if n["name"] == "long")
        self.assertEqual(len(long["preview"]), vault_mod.MAX_PREVIEW)

    def test_links_and_odd_names_are_left_out(self):
        (self.inbox / ".hidden.md").write_text("x\n")
        (self.inbox / "link.md").symlink_to(self.outside)
        names = [n["name"] for n in self.snap()["notes"]]
        self.assertNotIn(".hidden", names)
        self.assertNotIn("link", names)

    def test_id_follows_the_notes(self):
        one = self.snap()["id"]
        self.assertEqual(self.snap()["id"], one)
        (self.inbox / "draft.md").write_text("changed\n")
        self.assertNotEqual(self.snap()["id"], one)

    def test_run_writes_the_inbox_snapshot(self):
        self.run_vault()
        data = json.loads((self.state / "inbox.json").read_text())
        self.assertEqual(data["id"], self.snap()["id"])


class InboxTextTest(InboxBase):
    """117: the text I sign, built from the snapshot only, and what comes out of it."""

    def test_text_and_ops_from_the_snapshot(self):
        s = self.snap()
        text = vault_mod.inbox_text(s, [{"note": "Inbox/shop list.md", "do": "move", "to": "daily"},
                                        {"note": "Inbox/draft.md", "do": "delete"}])
        self.assertEqual(text, f"inbox: {s['id']}\n"
                               "delete: Inbox/draft.md\n"
                               "move: Inbox/shop list.md -> daily/shop list.md\n")
        sha = {n["note"]: n["sha256"] for n in s["notes"]}
        self.assertEqual(vault_mod.inbox_requests(text, s), [
            {"op": "delete", "note": "Inbox/draft.md", "sha256": sha["Inbox/draft.md"]},
            {"op": "move", "note": "Inbox/shop list.md", "to": "daily/shop list.md",
             "sha256": sha["Inbox/shop list.md"]}])

    def test_refusals(self):
        s = self.snap()
        ok = {"note": "Inbox/draft.md", "do": "delete"}
        for name, picks in {
            "unknown note": [{"note": "Inbox/nope.md", "do": "delete"}],
            "spec folder": [{"note": "Inbox/claude/spec.md", "do": "delete"}],
            "unlisted folder": [{"note": "Inbox/draft.md", "do": "move", "to": "Claude"}],
            "done folder": [{"note": "Inbox/draft.md", "do": "move", "to": "daily/done"}],
            "path as folder": [{"note": "Inbox/draft.md", "do": "move", "to": "daily/x.md"}],
            "move without folder": [{"note": "Inbox/draft.md", "do": "move"}],
            "delete with folder": [{**ok, "to": "daily"}],
            "unknown do": [{"note": "Inbox/draft.md", "do": "edit"}],
            "repeat": [ok, ok],
            "same note twice": [ok, {"note": "Inbox/draft.md", "do": "move", "to": "daily"}],
            "none": [],
            "not a list": ok,
            "extra key": [{**ok, "x": 1}],
            "number": [{"note": 5, "do": "delete"}],
            # The cap of 20 survives mutation: the snapshot holds at most 20 notes, so 21
            # picks always repeat one or name one not there. Kept as a bound on the loop
            "too many": [ok] * 21,
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.inbox_text(s, picks)

    def test_another_snapshot_at_finish_is_refused(self):
        s = self.snap()
        text = vault_mod.inbox_text(s, [{"note": "Inbox/draft.md", "do": "delete"}])
        (self.inbox / "draft.md").write_text("changed after I saw it\n")
        with self.assertRaises(vault_mod.Refused):
            vault_mod.inbox_requests(text, self.snap())

    def test_requests_refuse_what_inbox_text_did_not_build(self):
        s = self.snap()
        head = f"inbox: {s['id']}\n"
        for bad in ("", head, head + "delete: Inbox/draft.md",  # no last newline
                    head + "delete: Inbox/nope.md\n", head + "erase: Inbox/draft.md\n",
                    head + "move: Inbox/draft.md -> Claude/draft.md\n",
                    head + "move: Inbox/draft.md -> daily/other.md\n",
                    head + "delete: Inbox/draft.md -> daily/draft.md\n",
                    "inbox: " + "a" * 64 + "\ndelete: Inbox/draft.md\n"):
            with self.subTest(bad=bad[:50]):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.inbox_requests(bad, s)

    def test_requests_go_through_the_vault(self):
        s = self.snap()
        text = vault_mod.inbox_text(s, [{"note": "Inbox/shop list.md", "do": "move", "to": "daily"},
                                        {"note": "Inbox/draft.md", "do": "delete"}])
        for req in vault_mod.inbox_requests(text, s):
            vault_mod.write_request(self.requests, req)
        self.assertEqual([r[1] for r in self.run_vault()], ["ok", "ok"])
        self.assertFalse((self.inbox / "draft.md").exists())
        self.assertTrue((self.vault / "daily" / "shop list.md").exists())

    def test_the_vault_refuses_a_note_changed_after_signing(self):
        s = self.snap()
        text = vault_mod.inbox_text(s, [{"note": "Inbox/draft.md", "do": "delete"}])
        req, = vault_mod.inbox_requests(text, s)
        (self.inbox / "draft.md").write_text("changed\n")
        vault_mod.write_request(self.requests, req)
        self.assertEqual(self.run_vault()[0][1], "refused")
        self.assertTrue((self.inbox / "draft.md").exists())



class NotesSnapshotTest(InboxBase):
    """118: every folder and its notes, read only, for the notes browser."""

    def setUp(self):
        super().setUp()
        (self.vault / "Templates").mkdir()
        (self.vault / "Templates" / "todo.md").write_text("template\n")
        (self.vault / ".obsidian").mkdir()
        (self.vault / ".obsidian" / "x.md").write_text("x\n")
        (self.vault / "Claude" / "network-plus" / "abc" / "labs").mkdir(parents=True)
        (self.vault / "Claude" / "network-plus" / "abc" / "labs" / "01-osi.md").write_text("# OSI\n")
        (self.vault / "daily" / "done" / "gym.md").write_text("- [x] shoes\n")

    def folders(self):
        return {f["folder"]: f["notes"] for f in vault_mod.notes_snapshot(self.vault)["folders"]}

    def test_folders_and_their_notes(self):
        f = self.folders()
        self.assertEqual(sorted(f), ["Claude", "Claude/network-plus/abc/labs", "Inbox", "daily", "daily/done", "study"])
        self.assertEqual([n["name"] for n in f["Inbox"]], ["draft", "shop list"])  # never Inbox/claude/
        self.assertEqual([n["name"] for n in f["study"]], ["dhcp", "osi"])
        osi = f["Claude/network-plus/abc/labs"][0]
        self.assertEqual(osi["note"], "Claude/network-plus/abc/labs/01-osi.md")
        self.assertEqual(osi["text"], "# OSI\n")
        self.assertEqual(set(osi), {"name", "note", "modified", "size", "text", "tags"})

    def test_templates_settings_specs_and_links_stay_out(self):
        (self.study / "link.md").symlink_to(self.outside)
        (self.study / "away").symlink_to(self.outside.parent)  # a linked folder: nothing under it
        notes = [n["note"] for ns in self.folders().values() for n in ns]
        for bad in ("Templates/todo.md", ".obsidian/x.md", "Inbox/claude/spec.md", "study/link.md"):
            self.assertNotIn(bad, notes)
        self.assertFalse(any(n.startswith("Inbox/.requests") or n.startswith("study/away") for n in notes))

    def test_text_is_capped_and_hidden_characters_marked(self):
        (self.study / "long.md").write_text("x" * 5000)
        (self.study / "planted.md").write_text("ok \u202eevil\n")
        f = {n["name"]: n for n in self.folders()["study"]}
        self.assertEqual(len(f["long"]["text"]), vault_mod.MAX_NOTE_TEXT)
        self.assertEqual(f["planted"]["text"], "ok \ufffdevil\n")

    def test_the_number_of_notes_is_capped(self):
        for i in range(vault_mod.MAX_NOTES_SHOWN + 5):
            (self.study / f"n{i:03d}.md").write_text("y\n")
        self.assertEqual(sum(len(n) for n in self.folders().values()), vault_mod.MAX_NOTES_SHOWN)

    def tags_of(self, text):
        (self.study / "t.md").write_text(text)
        return {n["name"]: n for n in self.folders()["study"]}["t"]["tags"]

    def test_tags_from_front_matter_and_text(self):
        # 212, threat 149: the tags a tap on the phone looks for
        self.assertEqual(self.tags_of("---\ntags: [Net, study/dns]\n---\nAbout #dhcp and #Сеть, again #net.\n"),
                         ["net", "study/dns", "dhcp", "сеть"])
        self.assertEqual(self.tags_of("---\ntags:\n  - ccna\n  - '#lab'\n---\n#first line\n"), ["ccna", "lab", "first"])

    def test_tags_skip_what_is_not_a_tag(self):
        text = ("# Heading\n## Two\nhttp://x.org/a#frag a#b #2026 #_x #-y\n`#code` and\n```\n#block\n```\n"
                "#a\u202eb #ok.\n")
        self.assertEqual(self.tags_of(text), ["a", "ok"])  # the planted one stops at the bidi mark
        self.assertEqual(self.tags_of("---\ntags: [a b, x:y, " + "l" * 41 + ", \u202eq]\n---\n"), [])
        self.assertEqual(self.tags_of("#" + "l" * 41 + "\n"), [])

    def test_tags_are_capped(self):
        self.assertEqual(self.tags_of(" ".join(f"#t{i}" for i in range(15))),
                         [f"t{i}" for i in range(vault_mod.MAX_NOTE_TAGS)])
        for i in range(30):
            (self.study / f"m{i:02d}.md").write_text(" ".join(f"#n{i}x{j}" for j in range(10)))
        seen = {t for ns in self.folders().values() for n in ns for t in n["tags"]}
        self.assertEqual(len(seen), vault_mod.MAX_TAGS)

    def test_run_writes_the_notes_snapshot(self):
        self.run_vault()
        data = json.loads((self.state / "notes.json").read_text())
        self.assertIn("study", [f["folder"] for f in data["folders"]])


if __name__ == "__main__":
    unittest.main()
