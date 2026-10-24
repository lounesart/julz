"""julz_vault: tick a task, archive finished todos, feedback notes (SECURITY.md 80, 81)."""
import unittest

from test_julz_vault import VaultBase, vault_mod

TODO = ("---\ntags:\n  - todo\ncreated: 2026-10-14\n---\n\n# Physio\n\n"
        "- [ ] book physio\n- [x] call the clinic (done 2026-10-15)\n")


class VaultTasksTest(VaultBase):
    def setUp(self):
        super().setUp()
        self.daily = self.vault / "daily"
        self.daily.mkdir()
        self.physio = self.daily / "physio.md"
        self.physio.write_text(TODO)
        (self.vault / "feedback").mkdir()
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "tasks fixture")

    # ----- tick -----

    def test_tick_marks_done_with_date(self):
        (self.daily / "week.md").write_text(TODO.replace("call the clinic (done 2026-10-15)", "x")
                                            + "- [ ] gym\n")
        self.request({"op": "tick", "note": "daily/week.md", "item": "book physio"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        text = (self.daily / "week.md").read_text()
        self.assertIn("- [x] book physio (done 2026-10-16)\n", text)
        self.assertIn("- [ ] gym\n", text)  # nothing else ticked

    def test_tick_refusals(self):
        before = self.physio.read_text()
        for req in ({"op": "tick", "note": "daily/physio.md", "item": "not there"},
                    {"op": "tick", "note": "daily/physio.md", "item": "book"},  # not the whole line
                    {"op": "tick", "note": "daily/physio.md", "item": "call the clinic (done 2026-10-15)"},
                    {"op": "tick", "note": "daily/physio.md", "item": "book physio\n- [ ] x"},
                    {"op": "tick", "note": "daily/physio.md", "item": 5},
                    {"op": "tick", "note": "study/dhcp.md", "item": "x"},
                    {"op": "tick", "note": "daily/physio.md", "item": "x" * 300}):
            self.request(req)
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertEqual(self.physio.read_text(), before)

    def test_tick_needs_exactly_one_line(self):
        self.physio.write_text(TODO + "- [ ] book physio\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "dup")
        self.request({"op": "tick", "note": "daily/physio.md", "item": "book physio"})
        self.assertEqual(self.run_vault()[0][1], "refused")

    # ----- archive -----

    def test_last_tick_archives_the_note(self):
        self.request({"op": "tick", "note": "daily/physio.md", "item": "book physio"})
        self.run_vault()
        self.assertFalse(self.physio.exists())
        done = self.daily / "done" / "physio.md"
        text = done.read_text()
        self.assertIn("completed: 2026-10-16\n", text)
        self.assertIn("- [x] book physio (done 2026-10-16)", text)
        self.assertTrue(any(c.startswith("vault: finished todo") for c in self.commits()))

    def test_my_own_ticks_in_obsidian_archive_too(self):
        self.physio.write_text(TODO.replace("- [ ] book physio", "- [x] book physio"))
        self.run_vault()
        self.assertTrue((self.daily / "done" / "physio.md").exists())

    def test_only_finished_todo_notes_move(self):
        (self.daily / "notes.md").write_text("# Notes\n\n- [x] a checkbox in a plain note\n")
        (self.daily / "empty.md").write_text("---\ntags:\n  - todo\n---\n\n# Empty\n")
        self.run_vault()
        self.assertTrue(self.physio.exists())  # one box still open
        self.assertTrue((self.daily / "notes.md").exists())  # not tagged todo
        self.assertTrue((self.daily / "empty.md").exists())  # no box at all

    def test_archive_never_overwrites(self):
        (self.daily / "done").mkdir()
        (self.daily / "done" / "physio.md").write_text("OLD\n")
        self.physio.write_text(TODO.replace("- [ ] book physio", "- [x] book physio"))
        self.run_vault()
        self.assertEqual((self.daily / "done" / "physio.md").read_text(), "OLD\n")
        self.assertTrue((self.daily / "done" / "physio 2.md").exists())

    def test_inbox_todos_archive_into_daily_done(self):
        (self.vault / "Inbox" / "shop.md").write_text(
            "---\ntags:\n  - todo\n---\n\n# Shop\n\n- [x] milk\n")
        self.run_vault()
        self.assertTrue((self.daily / "done" / "shop.md").exists())

    # ----- feedback -----

    def test_feedback_create_only(self):
        self.request({"op": "create", "note": "feedback/2026-10-16 too-long.md",
                      "text": "---\ntags:\n  - feedback\n---\n\n# Feedback\n\nToo long.\n"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        f = "feedback/2026-10-16 too-long.md"
        self.request({"op": "append", "note": f, "text": "more"})
        self.request({"op": "delete", "note": f,
                      "sha256": "0" * 64})
        self.request({"op": "create", "note": "feedback/sub/x.md", "text": "x"})
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertTrue((self.vault / f).exists())

    # ----- found by the mutation check: each case where only one check can refuse -----

    def test_tick_checks_hold_even_when_the_line_exists(self):
        long_item = "x" * 300
        self.physio.write_text(TODO + "- [ ] a\n- [ ] b\n- [ ] " + long_item
                               + "\n- [ ] zero\u200bwidth\n")
        (self.study / "plan.md").write_text("---\ntags:\n  - todo\n---\n\n- [ ] x\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "lines")
        before = self.physio.read_text()
        for req in ({"op": "tick", "note": "daily/physio.md", "item": "a\n- [ ] b"},  # two lines
                    {"op": "tick", "note": "daily/physio.md", "item": long_item},
                    {"op": "tick", "note": "daily/physio.md", "item": "zero\u200bwidth"},
                    {"op": "tick", "note": "study/plan.md", "item": "x"}):  # study has no tasks
            self.request(req)
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertEqual(self.physio.read_text(), before)
        self.assertIn("- [ ] x", (self.study / "plan.md").read_text())

    def test_archived_note_stays_put(self):
        (self.daily / "done").mkdir()
        done = self.daily / "done" / "gym.md"
        done.write_text("---\ntags:\n  - todo\ncompleted: 2026-10-12\n---\n\n- [x] shoes\n")
        self.run_vault()
        self.run_vault()
        self.assertTrue(done.exists())
        self.assertEqual(sorted(p.name for p in (self.daily / "done").iterdir()), ["gym.md"])

    # ----- todo snapshot for the phone (threat 100) -----

    def test_snapshot_lists_open_tasks_with_counts(self):
        (self.daily / "week.md").write_text("# Week\n\n- [x] gym\n- [ ] walk 10k\n- [ ] book the exam\n")
        snap = vault_mod.todo_snapshot(self.vault)
        lists = {l["name"]: l for l in snap["lists"]}
        self.assertEqual(lists["physio"], {"name": "physio", "note": "daily/physio.md", "done": 1,
                                           "total": 2, "open": ["book physio"], "doing": [],
                                           "done_items": ["call the clinic"]})
        self.assertEqual(lists["week"]["open"], ["walk 10k", "book the exam"])
        self.assertEqual((lists["week"]["done"], lists["week"]["total"]), (1, 3))

    def test_snapshot_leaves_out_what_must_not_travel(self):
        (self.daily / "x.md").write_text(
            "- [ ] see https://evil.example\n- [ ] zero\u200bwidth\n- [ ] " + "y" * 81 + "\n"
            "- [ ] a \u241e b\n- [ ] token ghp_" + "A1b2" * 10 + "\n- [ ] fine one\n")
        (self.vault / "Claude").mkdir(exist_ok=True)
        (self.vault / "Claude" / "c.md").write_text("- [ ] not my list\n")
        (self.daily / "done").mkdir(exist_ok=True)
        (self.daily / "done" / "old.md").write_text("- [ ] archived\n")
        snap = vault_mod.todo_snapshot(self.vault)
        items = [i for l in snap["lists"] for i in l["open"]]
        self.assertIn("fine one", items)
        for bad in ("evil", "zero", "y" * 81, "\u241e", "ghp_", "not my list", "archived"):
            self.assertFalse(any(bad in i for i in items), bad)

    def test_snapshot_caps_the_number_of_lists(self):
        for n in range(12):  # many short lists: only the list cap stops them
            (self.daily / f"l{n:02d}.md").write_text(f"- [ ] task {n}\n")
        snap = vault_mod.todo_snapshot(self.vault)
        self.assertEqual(len(snap["lists"]), vault_mod.MAX_TODO_LISTS)

    def test_snapshot_caps_the_number_of_tasks(self):
        self.physio.unlink()
        (self.daily / "long.md").write_text("".join(f"- [ ] task {i}\n" for i in range(25)))
        snap = vault_mod.todo_snapshot(self.vault)  # one long list: only the trim stops it
        self.assertEqual(len(snap["lists"][0]["open"]), vault_mod.MAX_TODO_ITEMS)

    def test_run_writes_the_snapshot(self):
        self.run_vault()
        import json
        data = json.loads((self.state / "todos.json").read_text())
        self.assertEqual(data["date"], "2026-10-16")
        self.assertEqual(data["lists"][0]["open"], ["book physio"])

    # ----- ticking from the phone (threat 113) -----

    def test_snapshot_has_an_id_that_follows_the_tasks(self):
        one = vault_mod.todo_snapshot(self.vault)
        self.assertRegex(one["id"], r"^[0-9a-f]{64}$")
        self.assertEqual(vault_mod.todo_snapshot(self.vault)["id"], one["id"])
        self.physio.write_text(TODO + "- [ ] stretch\n")
        self.assertNotEqual(vault_mod.todo_snapshot(self.vault)["id"], one["id"])

    def test_snapshot_done_items_newest_first_capped(self):
        self.physio.write_text("- [ ] left\n" + "".join(
            f"- [x] old {i} (done 2026-10-0{i})\n" for i in range(1, 6)) + "- [x] undated\n")
        l, = vault_mod.todo_snapshot(self.vault)["lists"]
        self.assertEqual(l["done_items"], ["old 5", "old 4", "old 3"])
        self.assertEqual(l["done"], 6)  # the count stays the whole truth

    def test_snapshot_done_items_follow_the_travel_rules(self):
        self.physio.write_text("- [ ] left\n- [x] see https://evil.example (done 2026-10-16)\n"
                               "- [x] fine (done 2026-10-15)\n")
        l, = vault_mod.todo_snapshot(self.vault)["lists"]
        self.assertEqual(l["done_items"], ["fine"])

    def snap_with_week(self):
        (self.daily / "week.md").write_text("- [ ] walk 10k\n- [ ] book the exam\n")
        return vault_mod.todo_snapshot(self.vault)

    def test_tick_text_is_built_from_the_snapshot_in_its_order(self):
        snap = self.snap_with_week()
        text = vault_mod.tick_text(snap, [{"list": "week", "item": "book the exam"},
                                          {"list": "physio", "item": "book physio"}])
        self.assertEqual(text, f"tick: {snap['id']}\n"
                               "daily/physio.md: book physio\ndaily/week.md: book the exam\n")
        self.assertEqual(vault_mod.ticks_of(text), [("daily/physio.md", "book physio"),
                                                    ("daily/week.md", "book the exam")])

    def test_tick_text_refusals(self):
        snap = self.snap_with_week()
        ok = {"list": "week", "item": "walk 10k"}
        for name, picks in {
            "not open": [{"list": "week", "item": "swim"}],
            "done already": [{"list": "physio", "item": "call the clinic"}],
            "unknown list": [{"list": "gym", "item": "walk 10k"}],
            "repeat": [ok, ok],
            "none": [],
            "not a list": ok,
            "extra key": [{**ok, "note": "study/x.md"}],
            "a path as list": [{"list": "daily/week.md", "item": "walk 10k"}],
            "number": [{"list": "week", "item": 5}],
            # The cap of 20 survives mutation: the snapshot holds at most 20 open tasks, so 21
            # picks always repeat one or name one not open. Kept as a bound on the loop
            "too many": [ok] * 21,
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.tick_text(snap, picks)

    def test_tick_text_refuses_a_list_name_two_notes_share(self):
        (self.vault / "Inbox").mkdir(exist_ok=True)
        (self.vault / "Inbox" / "physio.md").write_text("- [ ] book physio\n")
        snap = vault_mod.todo_snapshot(self.vault)
        with self.assertRaises(vault_mod.Refused):
            vault_mod.tick_text(snap, [{"list": "physio", "item": "book physio"}])

    def test_ticks_of_refuses_what_it_did_not_build(self):
        good = f"tick: {'a' * 64}\ndaily/physio.md: book physio\n"
        self.assertEqual(vault_mod.ticks_of(good), [("daily/physio.md", "book physio")])
        for bad in ("", "tick: short\ndaily/physio.md: x\n", f"tick: {'a' * 64}\n",
                    f"approve: {'a' * 64}\ndaily/physio.md: x\n",
                    f"tick: {'a' * 64}\nno separator\n",
                    f"tick: {'a' * 64}\ndaily/physio.md: book physio",  # no last newline
                    f"tick: {'a' * 64}\n../x.md: y\n", f"tick: {'a' * 64}\nstudy/x.md: y\n",
                    f"tick: {'a' * 64}\ndaily/a.md: see https://evil.example\n",
                    f"tick: {'a' * 64}\n" + "daily/a.md: x\n" * 21):
            with self.subTest(bad=bad[:40]):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.ticks_of(bad)

    def test_a_request_from_the_approver_ticks_like_one_from_the_tool(self):
        folder = self.vault / "Inbox" / ".requests"
        vault_mod.write_request(folder, {"op": "tick", "note": "daily/physio.md", "item": "book physio"})
        names = [p.name for p in folder.iterdir()]
        self.assertEqual(len(names), 1)
        self.assertRegex(names[0], vault_mod.REQUEST_NAME.pattern)
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [x] book physio (done 2026-10-16)",
                      (self.daily / "done" / "physio.md").read_text())

    def test_a_tick_logs_as_a_tick(self):
        self.request({"op": "tick", "note": "daily/physio.md", "item": "book physio"})
        self.run_vault()
        self.assertEqual(self.log()[0]["action"], "tick")

    # ----- the Done tab: a week of ticked tasks (threat 114) -----

    def test_done_week_has_dated_ticks_of_seven_days_archived_too(self):
        from datetime import date
        self.physio.write_text("- [ ] left\n- [x] old (done 2026-10-09)\n- [x] edge (done 2026-10-10)\n"
                               "- [x] today (done 2026-10-16)\n- [x] undated\n")
        (self.daily / "done").mkdir()
        (self.daily / "done" / "gym.md").write_text("---\ncompleted: 2026-10-14\n---\n\n- [x] shoes (done 2026-10-14)\n")
        week = vault_mod.done_week(self.vault, date(2026, 10, 16))
        self.assertEqual(week["date"], "2026-10-16")
        self.assertEqual([d["date"] for d in week["days"]], ["2026-10-16", "2026-10-14", "2026-10-10"])
        self.assertEqual(week["days"][0]["items"], [{"list": "physio", "item": "today"}])
        self.assertEqual(week["days"][1]["items"], [{"list": "gym", "item": "shoes"}])
        flat = [i["item"] for d in week["days"] for i in d["items"]]
        self.assertNotIn("old", flat)       # 7 days: the 10th is the oldest
        self.assertNotIn("undated", flat)   # no date, no day to put it on

    def test_done_week_follows_the_travel_rules_and_cap(self):
        from datetime import date
        self.physio.write_text("- [x] see https://evil.example (done 2026-10-16)\n- [x] zero\u200bwidth (done 2026-10-16)\n"
                               + "".join(f"- [x] t{i} (done 2026-10-15)\n" for i in range(80)))
        (self.vault / "Claude").mkdir(exist_ok=True)
        (self.vault / "Claude" / "c.md").write_text("- [x] not mine (done 2026-10-16)\n")
        week = vault_mod.done_week(self.vault, date(2026, 10, 16))
        flat = [i["item"] for d in week["days"] for i in d["items"]]
        self.assertEqual(len(flat), vault_mod.MAX_DONE_WEEK)
        for bad in ("evil", "zero", "not mine"):
            self.assertFalse(any(bad in i for i in flat), bad)

    def test_run_writes_the_done_week(self):
        import json
        self.request({"op": "tick", "note": "daily/physio.md", "item": "book physio"})
        self.run_vault()
        week = json.loads((self.state / "done-week.json").read_text())
        self.assertEqual(week["days"][0], {"date": "2026-10-16", "items": [{"list": "physio", "item": "book physio"}]})

    # ----- solve feedback (threat 85) -----

    def feedback(self, name="a.md", text="# Feedback\n\nToo long.\n"):
        f = self.vault / "feedback" / name
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "feedback fixture")
        return f

    def test_solve_moves_feedback_to_done_with_a_line(self):
        f = self.feedback()
        self.request({"op": "resolve", "note": "feedback/a.md"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertFalse(f.exists())
        done = (self.vault / "feedback" / "done" / "a.md").read_text()
        self.assertTrue(done.startswith("# Feedback\n\nToo long.\n"))
        self.assertTrue(done.endswith("\nSolved 2026-10-16 by me\n"))
        self.assertIn("julz: solved feedback/a.md", self.commits()[0])
        self.assertEqual(self.log()[-1]["action"], "feedback-solved")

    def test_solve_never_overwrites(self):
        self.feedback()
        old = self.feedback("done/a.md", "OLD\n")
        self.request({"op": "resolve", "note": "feedback/a.md"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertEqual(old.read_text(), "OLD\n")
        self.assertIn("Too long.", (self.vault / "feedback" / "done" / "a 2.md").read_text())

    def test_solve_refusals(self):
        # Each request is valid but for one thing, and each target exists
        self.feedback()
        self.feedback("done/b.md")
        self.feedback("sub/c.md")
        (self.vault / "feedback" / "l.md").symlink_to(self.outside)
        for req in ({"op": "resolve", "note": "daily/physio.md"},  # not feedback
                    {"op": "resolve", "note": "feedback/done/b.md"},  # solved already
                    {"op": "resolve", "note": "feedback/sub/c.md"},  # too deep
                    {"op": "resolve", "note": "feedback/l.md"},  # a link
                    {"op": "resolve", "note": "feedback/../daily/physio.md"},
                    {"op": "resolve", "note": "feedback/a.md", "sha256": "0" * 64}):  # extra key
            self.request(req)
        results = self.run_vault()
        self.assertEqual([r[1] for r in results], ["refused"] * 6, results)
        self.assertTrue((self.vault / "feedback" / "a.md").exists())
        self.assertTrue(self.physio.exists())
        self.assertEqual(self.outside.read_text(), "OUTSIDE\n")
        self.assertEqual(sorted(p.name for p in (self.vault / "feedback" / "done").iterdir()),
                         ["b.md"])

    def test_solve_refuses_a_linked_done_folder(self):
        self.feedback()
        elsewhere = self.vault.parent / "elsewhere"
        elsewhere.mkdir()
        (self.vault / "feedback" / "done").symlink_to(elsewhere)
        self.request({"op": "resolve", "note": "feedback/a.md"})
        self.assertEqual(self.run_vault()[0][1], "refused")
        self.assertEqual(list(elsewhere.iterdir()), [])
        self.assertTrue((self.vault / "feedback" / "a.md").exists())


if __name__ == "__main__":
    unittest.main()
