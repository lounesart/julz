"""julz_vault: stages, SECURITY.md 127. A todo in progress is `- [/]` (the Obsidian Tasks
mark): the snapshot carries it, the phone starts a task with one fingerprint, a tick takes it,
the archive and the goal roll up treat it as open."""
import unittest

from test_julz_vault import VaultBase, vault_mod

TODO = ("---\ntags:\n  - todo\n---\n\n# Physio\n\n"
        "- [ ] book physio\n- [/] stretch daily\n- [x] call the clinic (done 2026-10-15)\n")


class StagesBase(VaultBase):
    def setUp(self):
        super().setUp()
        self.daily = self.vault / "daily"
        self.daily.mkdir()
        self.physio = self.daily / "physio.md"
        self.physio.write_text(TODO)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "stages fixture")


class SnapshotTest(StagesBase):
    def test_in_progress_tasks_travel_apart_and_count_as_open(self):
        l, = vault_mod.todo_snapshot(self.vault)["lists"]
        self.assertEqual((l["open"], l["doing"], l["done"], l["total"]),
                         (["book physio"], ["stretch daily"], 1, 3))

    def test_a_list_with_only_tasks_in_progress_is_shown(self):
        self.physio.write_text("- [/] stretch daily\n- [x] call the clinic\n")
        l, = vault_mod.todo_snapshot(self.vault)["lists"]
        self.assertEqual((l["open"], l["doing"]), ([], ["stretch daily"]))

    def test_in_progress_tasks_follow_the_travel_rules(self):
        self.physio.write_text("- [ ] a\n- [/] see https://evil.example\n- [/] fine\n")
        l, = vault_mod.todo_snapshot(self.vault)["lists"]
        self.assertEqual(l["doing"], ["fine"])

    def test_starting_a_task_changes_the_snapshot_id(self):
        one = vault_mod.todo_snapshot(self.vault)["id"]
        self.physio.write_text(TODO.replace("- [ ] book physio", "- [/] book physio"))
        self.assertNotEqual(vault_mod.todo_snapshot(self.vault)["id"], one)


class StartTest(StagesBase):
    def test_start_marks_the_task_in_progress(self):
        self.request({"op": "start", "note": "daily/physio.md", "item": "book physio"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [/] book physio\n", self.physio.read_text())
        self.assertEqual(self.log()[0]["action"], "start")

    def test_start_refusals(self):
        before = self.physio.read_text()
        for req in ({"op": "start", "note": "daily/physio.md", "item": "stretch daily"},     # in progress
                    {"op": "start", "note": "daily/physio.md", "item": "call the clinic (done 2026-10-15)"},
                    {"op": "start", "note": "daily/physio.md", "item": "not there"},
                    {"op": "start", "note": "daily/physio.md", "item": "book"},              # not the whole line
                    {"op": "start", "note": "daily/physio.md", "item": "book physio\n- [ ] x"},
                    {"op": "start", "note": "daily/physio.md", "item": 5},
                    {"op": "start", "note": "study/dhcp.md", "item": "x"},
                    {"op": "start", "note": "goals/2026.md", "item": "x"}):
            self.request(req)
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertEqual(self.physio.read_text(), before)

    def test_start_needs_exactly_one_line(self):
        self.physio.write_text(TODO + "- [ ] book physio\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "dup")
        self.request({"op": "start", "note": "daily/physio.md", "item": "book physio"})
        self.assertEqual(self.run_vault()[0][1], "refused")
        self.assertNotIn("[/] book physio", self.physio.read_text())

    def test_start_only_in_inbox_and_daily(self):
        for folder in ("goals", "study"):
            (self.vault / folder).mkdir(exist_ok=True)
            (self.vault / folder / "x.md").write_text("- [ ] Pass CPTS\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "elsewhere")
        for folder in ("goals", "study"):
            self.request({"op": "start", "note": f"{folder}/x.md", "item": "Pass CPTS"})
        self.assertEqual([r[1] for r in self.run_vault()], ["refused", "refused"])
        for folder in ("goals", "study"):
            self.assertEqual((self.vault / folder / "x.md").read_text(), "- [ ] Pass CPTS\n")

    def test_a_tick_takes_a_task_in_progress(self):
        self.request({"op": "tick", "note": "daily/physio.md", "item": "stretch daily"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [x] stretch daily (done 2026-10-16)\n", self.physio.read_text())


class ArchiveTest(StagesBase):
    def test_a_note_with_tasks_in_progress_left_stays(self):
        self.request({"op": "tick", "note": "daily/physio.md", "item": "book physio"})
        self.run_vault()
        self.assertTrue(self.physio.exists())  # stretch daily is still in progress
        self.assertFalse((self.daily / "done" / "physio.md").exists())


class SignedTextTest(StagesBase):
    def snap(self):
        return vault_mod.todo_snapshot(self.vault)

    def test_start_text_from_open_tasks_only(self):
        s = self.snap()
        text = vault_mod.tick_text(s, [{"list": "physio", "item": "book physio"}], verb="start")
        self.assertEqual(text, f"start: {s['id']}\ndaily/physio.md: book physio\n")
        self.assertEqual(vault_mod.ticks_of(text, verb="start"), [("daily/physio.md", "book physio")])
        with self.assertRaises(vault_mod.Refused):
            vault_mod.tick_text(s, [{"list": "physio", "item": "stretch daily"}], verb="start")  # already

    def test_a_tick_text_takes_a_task_in_progress(self):
        s = self.snap()
        text = vault_mod.tick_text(s, [{"list": "physio", "item": "stretch daily"}])
        self.assertEqual(text, f"tick: {s['id']}\ndaily/physio.md: stretch daily\n")

    def test_a_start_text_is_never_a_tick_text(self):
        s = self.snap()
        start = vault_mod.tick_text(s, [{"list": "physio", "item": "book physio"}], verb="start")
        tick = vault_mod.tick_text(s, [{"list": "physio", "item": "book physio"}])
        with self.assertRaises(vault_mod.Refused):
            vault_mod.ticks_of(start)
        with self.assertRaises(vault_mod.Refused):
            vault_mod.ticks_of(tick, verb="start")
        with self.assertRaises(vault_mod.Refused):
            vault_mod.tick_text(s, [{"list": "physio", "item": "book physio"}], verb="delete")


class GoalRollUpTest(StagesBase):
    def test_a_task_in_progress_counts_as_not_done(self):
        (self.vault / "goals").mkdir()
        (self.vault / "goals" / "2026.md").write_text("- [ ] Rehab #goal/rehab\n")
        self.physio.write_text("- [/] stretch daily #goal/rehab\n- [x] call #goal/rehab\n")
        g = next(g for p in vault_mod.goals_snapshot(self.vault, vault_mod.date(2026, 10, 16))["periods"]
                 for g in p["goals"] if g["goal"] == "rehab")
        self.assertEqual((g["linked"], g["rollup"]), ([1, 2], 50))


if __name__ == "__main__":
    unittest.main()
