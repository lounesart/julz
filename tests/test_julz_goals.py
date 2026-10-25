"""julz_vault: goals next to todos, SECURITY.md 123. Periods, the snapshot with progress from
linked todos, the text I sign, and the vault's goal, progress and tick ops in goals/."""
import json
import unittest
from datetime import date

from test_julz_vault import VaultBase, vault_mod, TODAY  # TODAY = 2026-10-16, a Friday


class GoalBase(VaultBase):
    def setUp(self):
        super().setUp()
        self.goals = self.vault / "goals"
        self.goals.mkdir()
        (self.goals / "2026-W42.md").write_text(
            "---\ntags: [goal]\nperiod: 2026-W42\n---\n\n# This week\n\n"
            "- [ ] Study 10 h (3/10)\n- [ ] Pass the Net+ practice exam #goal/net-plus-exam\n- [x] Gym twice\n")
        (self.vault / "daily").mkdir()
        (self.vault / "daily" / "study.md").write_text(
            "- [x] DNS lab #goal/net-plus-exam\n- [ ] Subnetting drill #goal/net-plus-exam\n- [ ] unrelated\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "goals fixture")

    def snap(self):
        return vault_mod.goals_snapshot(self.vault, TODAY)

    def period(self, key):
        return next(p for p in self.snap()["periods"] if p["key"] == key)


class PeriodsTest(unittest.TestCase):
    def test_the_three_current_periods(self):
        # No day period: today's goal work is a todo tied with #goal/<id> (223, threat 159)
        self.assertEqual([(k, rel) for k, _, rel in vault_mod.goal_periods(TODAY)],
                         [("2026-W42", "goals/2026-W42.md"), ("2026-10", "goals/2026-10.md"), ("2026", "goals/2026.md")])
        self.assertEqual([label for _, label, _ in vault_mod.goal_periods(TODAY)], ["This week", "October", "2026"])
        self.assertEqual(vault_mod.goal_periods(date(2027, 1, 1))[0][0], "2026-W53")  # ISO week of the old year


class GoalSnapshotTest(GoalBase):
    def test_goals_with_progress_and_linked_todos(self):
        g = {x["text"]: x for x in self.period("2026-W42")["goals"]}
        self.assertEqual(g["Study 10 h (3/10)"]["progress"], [3, 10])
        exam = g["Pass the Net+ practice exam #goal/net-plus-exam"]
        self.assertEqual(exam["goal"], "net-plus-exam")
        self.assertEqual(exam["linked"], [1, 2])  # one of two tagged todos ticked
        self.assertTrue(g["Gym twice"]["done"])
        self.assertEqual(self.period("2026-10")["goals"], [])  # no note yet: an empty card
        self.assertRegex(self.snap()["id"], r"^[0-9a-f]{64}$")

    def test_a_goal_that_may_not_travel_is_left_out(self):
        (self.goals / "2026.md").write_text("- [ ] see https://evil.example\n- [ ] a\u202eb\n- [ ] Learn C\n")
        self.assertEqual([x["text"] for x in self.period("2026")["goals"]], ["Learn C"])

    def test_a_stray_day_note_is_no_period(self):
        # A hand written goals/<date>.md never becomes a card or a period to sign (threat 159)
        before = self.snap()
        (self.goals / "2026-10-16.md").write_text("- [ ] Read the DNS chapter\n")
        self.assertEqual(self.snap(), before)
        self.assertNotIn("2026-10-16", [p["key"] for p in self.snap()["periods"]])

    def test_run_writes_the_goals_snapshot(self):
        self.run_vault()
        self.assertEqual(json.loads((self.state / "goals.json").read_text())["id"], self.snap()["id"])


class GoalTextTest(GoalBase):
    def test_add_tick_and_bump_from_the_snapshot(self):
        s = self.snap()
        text = vault_mod.goal_text(s, [{"do": "add", "period": "2026-10", "text": "Read the DNS chapter"},
                                       {"do": "bump", "period": "2026-W42", "item": "Study 10 h (3/10)"},
                                       {"do": "tick", "period": "2026-W42", "item": "Pass the Net+ practice exam #goal/net-plus-exam"}])
        self.assertEqual(text, f"goal: {s['id']}\n"
                               "add: 2026-10 Read the DNS chapter #goal/read-the-dns-chapter\n"
                               "bump: 2026-W42 Study 10 h (3/10)\n"
                               "tick: 2026-W42 Pass the Net+ practice exam #goal/net-plus-exam\n")
        self.assertEqual(vault_mod.goal_requests(text, s), [
            {"op": "goal", "note": "goals/2026-10.md", "item": "Read the DNS chapter #goal/read-the-dns-chapter"},
            {"op": "progress", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)"},
            {"op": "tick", "note": "goals/2026-W42.md", "item": "Pass the Net+ practice exam #goal/net-plus-exam"}])

    def test_refusals(self):
        s = self.snap()
        for name, picks in {
            "unknown period": [{"do": "add", "period": "2026-W41", "text": "x"}],
            "a day at add": [{"do": "add", "period": "2026-10-16", "text": "x"}],
            "a day at tick": [{"do": "tick", "period": "2026-10-16", "item": "Study 10 h (3/10)"}],
            "a day at link": [{"do": "link", "period": "2026-10-16", "item": "Pass the Net+ practice exam #goal/net-plus-exam",
                               "list": "study", "todo": "unrelated"}],
            "a link": [{"do": "add", "period": "2026", "text": "see https://evil.example"}],
            "a tag of my own": [{"do": "add", "period": "2026", "text": "x #goal/other"}],
            "too long": [{"do": "add", "period": "2026", "text": "y" * 121}],
            "not open": [{"do": "tick", "period": "2026-W42", "item": "Gym twice"}],
            "not there": [{"do": "tick", "period": "2026-W42", "item": "Swim"}],
            "bump without numbers": [{"do": "bump", "period": "2026-W42", "item": "Pass the Net+ practice exam #goal/net-plus-exam"}],
            "unknown do": [{"do": "delete", "period": "2026", "item": "x"}],
            "repeat": [{"do": "bump", "period": "2026-W42", "item": "Study 10 h (3/10)"}] * 2,
            "extra key": [{"do": "add", "period": "2026", "text": "x", "note": "study/x.md"}],
            "none": [], "too many": [{"do": "add", "period": "2026", "text": f"g{i}"} for i in range(21)],
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_text(s, picks)

    def test_bump_at_the_target_is_refused(self):
        (self.goals / "2026-W42.md").write_text("- [ ] Gym (3/3)\n")
        with self.assertRaises(vault_mod.Refused):
            vault_mod.goal_text(self.snap(), [{"do": "bump", "period": "2026-W42", "item": "Gym (3/3)"}])

    def test_requests_refuse_a_period_the_snapshot_has_not(self):
        # A signed text names only current periods; a day or an old week is no goal line (159)
        s = self.snap()
        for line in ("add: 2026-10-16 Walk #goal/walk", "tick: 2026-W41 Gym twice", "add: 2026-10-16"):
            with self.subTest(line=line):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_requests(f"goal: {s['id']}\n{line}\n", s)

    def test_requests_refuse_another_snapshot(self):
        s = self.snap()
        text = vault_mod.goal_text(s, [{"do": "bump", "period": "2026-W42", "item": "Study 10 h (3/10)"}])
        (self.goals / "2026-W42.md").write_text("- [ ] Study 10 h (4/10)\n")
        with self.assertRaises(vault_mod.Refused):
            vault_mod.goal_requests(text, self.snap())


class GoalOpsTest(GoalBase):
    def test_add_creates_the_period_note_once_then_appends(self):
        for item in ("Read the DNS chapter #goal/read-the-dns-chapter", "Walk #goal/walk"):
            self.request({"op": "goal", "note": "goals/2026-10.md", "item": item})
        self.assertEqual([r[1] for r in self.run_vault()], ["ok", "ok"])
        text = (self.goals / "2026-10.md").read_text()
        self.assertTrue(text.startswith("---\ntags:\n  - goal\nperiod: 2026-10\n---\n"))
        self.assertIn("- [ ] Read the DNS chapter #goal/read-the-dns-chapter\n- [ ] Walk #goal/walk\n", text)

    def test_progress_counts_one_up_on_the_exact_line(self):
        self.request({"op": "progress", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [ ] Study 10 h (4/10)\n", (self.goals / "2026-W42.md").read_text())

    def test_progress_and_goal_refusals(self):
        (self.goals / "2026.md").write_text("- [ ] Gym (3/3)\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "x")
        for req in ({"op": "progress", "note": "goals/2026.md", "item": "Gym (3/3)"},     # at the target
                    {"op": "progress", "note": "goals/2026.md", "item": "Gym"},           # no numbers
                    {"op": "progress", "note": "daily/study.md", "item": "unrelated"},    # not goals/
                    {"op": "goal", "note": "daily/x.md", "item": "x"},                    # not goals/
                    {"op": "goal", "note": "goals/2026.md", "item": "see https://evil.example"},
                    {"op": "goal", "note": "goals/2026.md", "item": "see https://evil.example #goal/x"},
                    {"op": "progress", "note": "goals/2026.md", "item": "Swim (1/5)"},       # not in the note
                    {"op": "goal", "note": "goals/2026.md", "item": "two\nlines"}):
            self.request(req)
        self.assertTrue(all(r[1] == "refused" for r in self.run_vault()))

    def test_the_goal_ops_root_is_checked_in_add_goal_too(self):
        # add_goal checks goals/ itself, so the op table's roots are a second lock, not the only one
        with self.assertRaises(vault_mod.Refused):
            vault_mod.add_goal(self.vault, {"op": "goal", "note": "daily/x.md", "item": "x #goal/x"})

    def test_tick_works_in_goals(self):
        self.request({"op": "tick", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [x] Study 10 h (3/10) (done 2026-10-16)", (self.goals / "2026-W42.md").read_text())



class GoalTargetLinkTest(GoalBase):
    """124: setting a goal's target and linking a todo to it."""

    def todos(self):
        return vault_mod.todo_snapshot(self.vault)

    def test_target_and_link_in_the_signed_text(self):
        s = self.snap()
        text = vault_mod.goal_text(s, [
            {"do": "target", "period": "2026-W42", "item": "Pass the Net+ practice exam #goal/net-plus-exam", "target": "5"},
            {"do": "link", "period": "2026-W42", "item": "Pass the Net+ practice exam #goal/net-plus-exam",
             "list": "study", "todo": "unrelated"}], self.todos())
        self.assertEqual(text, f"goal: {s['id']}\n"
                               "target: 2026-W42 5 Pass the Net+ practice exam #goal/net-plus-exam\n"
                               "link: 2026-W42 net-plus-exam daily/study.md: unrelated\n")
        self.assertEqual(vault_mod.goal_requests(text, s), [
            {"op": "target", "note": "goals/2026-W42.md", "item": "Pass the Net+ practice exam #goal/net-plus-exam", "target": 5},
            {"op": "link", "note": "daily/study.md", "item": "unrelated", "goal": "net-plus-exam"}])

    def test_target_and_link_refusals(self):
        s, todos = self.snap(), self.todos()
        exam = "Pass the Net+ practice exam #goal/net-plus-exam"
        for name, pick in {
            "already counted": {"do": "target", "period": "2026-W42", "item": "Study 10 h (3/10)", "target": "5"},
            "zero": {"do": "target", "period": "2026-W42", "item": exam, "target": "0"},
            "a word": {"do": "target", "period": "2026-W42", "item": exam, "target": "ten"},
            "huge": {"do": "target", "period": "2026-W42", "item": exam, "target": "10000"},
            "goal without id": {"do": "link", "period": "2026-W42", "item": "Study 10 h (3/10)", "list": "study", "todo": "unrelated"},
            "todo not open": {"do": "link", "period": "2026-W42", "item": exam, "list": "study", "todo": "DNS lab #goal/net-plus-exam"},
            "already linked": {"do": "link", "period": "2026-W42", "item": exam, "list": "study", "todo": "Subnetting drill #goal/net-plus-exam"},
            "unknown list": {"do": "link", "period": "2026-W42", "item": exam, "list": "gym", "todo": "unrelated"},
            "todo not in the list": {"do": "link", "period": "2026-W42", "item": exam, "list": "study", "todo": "never written"},
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_text(s, [pick], todos)

    def test_requests_refuse_a_link_line_goal_text_did_not_build(self):
        s = self.snap()
        head = f"goal: {s['id']}\n"
        for bad in ("link: 2026-W42 Bad-Id daily/study.md: unrelated\n", "link: 2026-W42 exam ../x.md: unrelated\n",
                    "link: 2026-W42 exam goals/2026.md: x\n", "link: 2026-W42 exam daily/study.md unrelated\n",
                    "target: 2026-W42 0 Exam\n", "target: 2026-W42 five Exam\n"):
            with self.subTest(bad=bad[:40]):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_requests(head + bad, s)

    def test_the_vault_sets_a_target_before_the_tag(self):
        self.request({"op": "target", "note": "goals/2026-W42.md", "item": "Pass the Net+ practice exam #goal/net-plus-exam", "target": 5})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [ ] Pass the Net+ practice exam (0/5) #goal/net-plus-exam\n", (self.goals / "2026-W42.md").read_text())

    def test_the_vault_links_a_todo_once(self):
        self.request({"op": "link", "note": "daily/study.md", "item": "unrelated", "goal": "net-plus-exam"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [ ] unrelated #goal/net-plus-exam\n", (self.vault / "daily" / "study.md").read_text())
        self.request({"op": "link", "note": "daily/study.md", "item": "unrelated #goal/net-plus-exam", "goal": "net-plus-exam"})
        self.assertEqual(self.run_vault()[0][1], "refused")  # never twice

    def test_vault_refusals(self):
        for req in ({"op": "target", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)", "target": 5},   # already counted
                    {"op": "target", "note": "goals/2026-W42.md", "item": "Gym twice", "target": 5},          # done, not open
                    {"op": "target", "note": "goals/2026-W42.md", "item": "Pass the Net+ practice exam #goal/net-plus-exam", "target": "5"},
                    {"op": "target", "note": "daily/study.md", "item": "unrelated", "target": 5},             # not goals/
                    {"op": "link", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)", "goal": "x"},   # an open goal, not a todo note
                    {"op": "link", "note": "daily/study.md", "item": "unrelated", "goal": "Bad Id"},
                    {"op": "link", "note": "daily/study.md", "item": "not there", "goal": "net-plus-exam"}):
            self.request(req)
        self.assertTrue(all(r[1] == "refused" for r in self.run_vault()))



class GoalTreeTest(GoalBase):
    """125: the goal tree, its roll up and nesting a goal under another."""

    def setUp(self):
        super().setUp()
        (self.goals / "2026.md").write_text("- [ ] Pass CPTS #goal/pass-cpts\n")
        (self.goals / "2026-10.md").write_text(
            "- [ ] Net+ first #goal/net-plus [in:: pass-cpts]\n- [x] Linux basics #goal/linux [in:: pass-cpts]\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "tree")

    def goal(self, key, text):
        return next(g for g in self.period(key)["goals"] if g["text"] == text)

    def test_roll_up_from_child_goals_and_linked_todos(self):
        # Net+ has two linked todos, one done: 50. Linux is done: 100. CPTS: the mean, 75
        self.assertEqual(self.goal("2026-10", "Net+ first #goal/net-plus [in:: pass-cpts]")["parent"], "pass-cpts")
        (self.vault / "daily" / "study.md").write_text("- [x] A #goal/net-plus\n- [ ] B #goal/net-plus\n")
        cpts = self.goal("2026", "Pass CPTS #goal/pass-cpts")
        self.assertEqual((cpts["rollup"], cpts["parts"]), (75, 2))
        self.assertEqual(self.goal("2026-10", "Net+ first #goal/net-plus [in:: pass-cpts]")["rollup"], 50)

    def test_a_child_without_an_id_counts_by_its_own_progress(self):
        # Linux done (1), Net+ no parts yet (0), the id-less child at 2/2 (1): mean 67; without it 50
        (self.goals / "2026-W42.md").write_text("- [ ] Study (2/2) [in:: pass-cpts]\n")
        self.assertEqual(self.goal("2026", "Pass CPTS #goal/pass-cpts")["rollup"], 67)

    def test_a_hand_made_cycle_and_a_deep_chain_end(self):
        (self.goals / "2026.md").write_text("- [ ] A #goal/a [in:: b]\n- [ ] B #goal/b [in:: a]\n")
        self.assertIsNotNone(self.snap())  # no endless loop
        chain = "".join(f"- [ ] G{i} #goal/g{i} [in:: g{i + 1}]\n" for i in range(12))
        (self.goals / "2026.md").write_text(chain)
        self.assertIsNotNone(self.snap())

    def test_nest_in_the_signed_text(self):
        s = self.snap()
        text = vault_mod.goal_text(s, [{"do": "nest", "period": "2026-W42", "item": "Study 10 h (3/10)", "under": "pass-cpts"}])
        self.assertTrue(text.endswith("nest: 2026-W42 pass-cpts Study 10 h (3/10)\n"))
        self.assertEqual(vault_mod.goal_requests(text, s),
                         [{"op": "nest", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)", "under": "pass-cpts"}])

    def test_nest_refusals(self):
        s = self.snap()
        for name, pick in {
            "under itself": {"do": "nest", "period": "2026", "item": "Pass CPTS #goal/pass-cpts", "under": "pass-cpts"},
            "under its own child": {"do": "nest", "period": "2026", "item": "Pass CPTS #goal/pass-cpts", "under": "net-plus"},
            "unknown parent": {"do": "nest", "period": "2026-W42", "item": "Study 10 h (3/10)", "under": "nope"},
            "bad id": {"do": "nest", "period": "2026-W42", "item": "Study 10 h (3/10)", "under": "Bad Id"},
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_text(s, [pick])

    def test_the_vault_writes_one_parent_and_replaces_an_old_one(self):
        self.request({"op": "nest", "note": "goals/2026-10.md", "item": "Net+ first #goal/net-plus [in:: pass-cpts]", "under": "linux"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [ ] Net+ first #goal/net-plus [in:: linux]\n", (self.goals / "2026-10.md").read_text())
        self.request({"op": "nest", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)", "under": "Bad Id"})
        self.assertEqual(self.run_vault()[0][1], "refused")



class GoalBatchTest(GoalBase):
    """Found 18 Oct on the phone: +1 and Put under on the same goal in one Apply lost the +1,
    because each request carried the line as signed and the vault ran them in any order."""

    def test_changes_to_one_goal_chain_its_line(self):
        s = self.snap()
        study = "Study 10 h (3/10)"
        text = vault_mod.goal_text(s, [{"do": "bump", "period": "2026-W42", "item": study},
                                       {"do": "nest", "period": "2026-W42", "item": study, "under": "net-plus-exam"},
                                       {"do": "tick", "period": "2026-W42", "item": study}])
        reqs = vault_mod.goal_requests(text, s)
        self.assertEqual([r["item"] for r in reqs],
                         [study, "Study 10 h (4/10)", "Study 10 h (4/10) [in:: net-plus-exam]"])

    def test_a_tick_picked_first_still_goes_last(self):
        s = self.snap()
        study = "Study 10 h (3/10)"
        text = vault_mod.goal_text(s, [{"do": "tick", "period": "2026-W42", "item": study},
                                       {"do": "bump", "period": "2026-W42", "item": study}])
        self.assertEqual([r["op"] for r in vault_mod.goal_requests(text, s)], ["progress", "tick"])

    def test_one_batch_lands_whole_in_the_vault(self):
        s = self.snap()
        study = "Study 10 h (3/10)"
        for req in vault_mod.goal_requests(vault_mod.goal_text(s, [
                {"do": "bump", "period": "2026-W42", "item": study},
                {"do": "nest", "period": "2026-W42", "item": study, "under": "net-plus-exam"}]), s):
            vault_mod.write_request(self.requests, req)
        self.assertEqual([r[1] for r in self.run_vault()], ["ok", "ok"])
        self.assertIn("- [ ] Study 10 h (4/10) [in:: net-plus-exam]\n", (self.goals / "2026-W42.md").read_text())

    def test_requests_of_one_batch_keep_their_order(self):
        names = []
        for i in range(20):
            vault_mod.write_request(self.requests, {"op": "tick", "note": "daily/study.md", "item": f"t{i}"})
        items = [json.loads(p.read_text())["item"] for p in sorted(self.requests.iterdir())]
        self.assertEqual(items, [f"t{i}" for i in range(20)])


class GoalDueTest(GoalBase):
    """126: milestones, a goal with [due:: YYYY-MM-DD]."""

    STUDY = "Study 10 h (3/10)"

    def setUp(self):
        super().setUp()
        (self.goals / "2026.md").write_text(
            "- [ ] Pass CPTS #goal/pass-cpts [due:: 2027-03-01]\n- [ ] Old one #goal/old [due:: 2026-01-01]\n"
            "- [x] Done one #goal/done1 [due:: 2026-11-01]\n- [ ] Odd date #goal/odd [due:: 2026-02-30]\n")
        (self.goals / "2027.md").write_text("- [ ] Net+ #goal/net [in:: pass-cpts] [due:: 2026-12-01]\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "due")

    def pick(self, due, item=STUDY, period="2026-W42"):
        return {"do": "due", "period": period, "item": item, "due": due}

    def test_due_in_the_snapshot_and_the_milestones(self):
        year = {g["goal"]: g for g in self.period("2026")["goals"]}
        self.assertEqual(year["pass-cpts"]["due"], "2027-03-01")
        self.assertIsNone(year["odd"]["due"])  # not a real day: no date at all
        self.assertIsNone({g["text"]: g for g in self.period("2026-W42")["goals"]}[self.STUDY]["due"])
        ms = self.snap()["milestones"]
        # Open goals with a date from all of goals/, soonest first; a late one stays, a done one goes
        self.assertEqual([(m["goal"], m["due"]) for m in ms],
                         [("old", "2026-01-01"), ("net", "2026-12-01"), ("pass-cpts", "2027-03-01")])
        self.assertEqual(set(ms[0]), {"goal", "text", "due", "rollup"})
        self.assertEqual(ms[1]["text"], "Net+ #goal/net [in:: pass-cpts] [due:: 2026-12-01]")

    def test_a_milestone_that_may_not_travel_is_left_out(self):
        (self.goals / "2027.md").write_text("- [ ] see https://evil.example #goal/evil [due:: 2026-12-01]\n")
        self.assertNotIn("evil", [m["goal"] for m in self.snap()["milestones"]])

    def test_due_in_the_signed_text(self):
        s = self.snap()
        text = vault_mod.goal_text(s, [self.pick("2026-10-30")], today=TODAY)
        self.assertTrue(text.endswith("due: 2026-W42 2026-10-30 Study 10 h (3/10)\n"))
        self.assertEqual(vault_mod.goal_requests(text, s),
                         [{"op": "due", "note": "goals/2026-W42.md", "item": self.STUDY, "due": "2026-10-30"}])

    def test_due_refusals(self):
        s = self.snap()
        long_goal = "x" * 170
        (self.goals / "2026-10.md").write_text(f"- [ ] {long_goal}\n")
        s2 = self.snap()
        for name, (snap, pick) in {
            "not a date": (s, self.pick("soon")),
            "not a real day": (s, self.pick("2026-02-30")),
            "short form": (s, self.pick("2026-1-5")),
            "compact form": (s, self.pick("20261030")),  # fromisoformat takes it from 3.11; the regex does not
            "text after it": (s, self.pick("2026-10-30] x")),
            "in the past": (s, self.pick("2026-10-15")),
            "eleven years ahead": (s, self.pick("2037-10-16")),
            "a number": (s, {**self.pick("x"), "due": 20261030}),
            "too long a line": (s2, self.pick("2026-10-30", item=long_goal, period="2026-10")),
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_text(snap, [pick], today=TODAY)
        vault_mod.goal_text(s, [self.pick("2026-10-16")], today=TODAY)  # today itself is fine
        vault_mod.goal_text(s, [self.pick("2036-10-16")], today=TODAY)  # ten years is the edge

    def test_requests_refuse_a_due_line_goal_text_did_not_build(self):
        s = self.snap()
        for bad in ("due: 2026-W42 2026-02-30 Study 10 h (3/10)\n", "due: 2026-W42 soon Study 10 h (3/10)\n",
                    "due: 2026-W42 2026-10-30\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_requests(f"goal: {s['id']}\n" + bad, s)

    def test_the_vault_writes_one_due_and_replaces_an_old_one(self):
        self.request({"op": "due", "note": "goals/2026-W42.md", "item": self.STUDY, "due": "2026-10-30"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [ ] Study 10 h (3/10) [due:: 2026-10-30]\n", (self.goals / "2026-W42.md").read_text())
        self.request({"op": "due", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10) [due:: 2026-10-30]", "due": "2026-11-05"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertIn("- [ ] Study 10 h (3/10) [due:: 2026-11-05]\n", (self.goals / "2026-W42.md").read_text())

    def test_vault_due_refusals(self):
        for req in ({"op": "due", "note": "goals/2026-W42.md", "item": self.STUDY, "due": "2026-10-15"},      # past
                    {"op": "due", "note": "goals/2026-W42.md", "item": self.STUDY, "due": "2026-10-30] x"},
                    {"op": "due", "note": "goals/2026-W42.md", "item": self.STUDY, "due": "2037-10-16"},
                    {"op": "due", "note": "goals/2026-W42.md", "item": self.STUDY, "due": 20261030},
                    {"op": "due", "note": "goals/2026-W42.md", "item": self.STUDY, "due": "20261030"},
                    {"op": "due", "note": "goals/2026-W42.md", "item": "Gym twice", "due": "2026-10-30"},       # done
                    {"op": "due", "note": "daily/study.md", "item": "unrelated", "due": "2026-10-30"},         # not goals/
                    {"op": "due", "note": "goals/2026-W42.md", "item": "x" * 170, "due": "2026-10-30"}):      # not there
            self.request(req)
        self.assertTrue(all(r[1] == "refused" for r in self.run_vault()))
        self.assertNotIn("[due::", (self.goals / "2026-W42.md").read_text())

    def test_the_vault_refuses_a_line_grown_too_long(self):
        long_goal = "x" * 170
        (self.goals / "2026-10.md").write_text(f"- [ ] {long_goal}\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "long")
        self.request({"op": "due", "note": "goals/2026-10.md", "item": long_goal, "due": "2026-10-30"})
        self.assertEqual(self.run_vault()[0][1], "refused")

    def test_due_chains_with_other_changes(self):
        s = self.snap()
        text = vault_mod.goal_text(s, [self.pick("2026-10-30"), {"do": "bump", "period": "2026-W42", "item": self.STUDY}], today=TODAY)
        reqs = vault_mod.goal_requests(text, s)
        self.assertEqual([(r["op"], r["item"]) for r in reqs], [("progress", self.STUDY), ("due", "Study 10 h (4/10)")])


class GoalUnlinkTest(GoalBase):
    """128: undo a wrong link from the phone (a physio task counted toward study, found 18 Oct)."""

    EXAM = "Pass the Net+ practice exam #goal/net-plus-exam"
    DRILL = "Subnetting drill #goal/net-plus-exam"

    def pick(self, todo=DRILL, item=EXAM, lst="study"):
        return {"do": "unlink", "period": "2026-W42", "item": item, "list": lst, "todo": todo}

    def test_unlink_in_the_signed_text(self):
        s, todos = self.snap(), vault_mod.todo_snapshot(self.vault)
        text = vault_mod.goal_text(s, [self.pick()], todos)
        self.assertTrue(text.endswith("unlink: 2026-W42 net-plus-exam daily/study.md: Subnetting drill #goal/net-plus-exam\n"))
        self.assertEqual(vault_mod.goal_requests(text, s),
                         [{"op": "unlink", "note": "daily/study.md", "item": self.DRILL, "goal": "net-plus-exam"}])

    def test_a_task_in_progress_unlinks_too(self):
        (self.vault / "daily" / "study.md").write_text("- [/] Subnetting drill #goal/net-plus-exam\n")
        s, todos = self.snap(), vault_mod.todo_snapshot(self.vault)
        vault_mod.goal_text(s, [self.pick()], todos)

    def test_unlink_refusals(self):
        s, todos = self.snap(), vault_mod.todo_snapshot(self.vault)
        for name, pick in {
            "not linked": self.pick(todo="unrelated"),
            "not in the snapshot": self.pick(todo="Made up #goal/net-plus-exam"),
            "a goal without an id": self.pick(item="Study 10 h (3/10)"),
            "unknown list": self.pick(lst="gym"),
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_text(s, [pick], todos)

    def test_the_vault_removes_one_tag_and_keeps_the_others(self):
        (self.vault / "daily" / "study.md").write_text("- [/] Drill #goal/net-plus-exam #goal/net-plus\n- [ ] x\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "two tags")
        self.request({"op": "unlink", "note": "daily/study.md", "item": "Drill #goal/net-plus-exam #goal/net-plus", "goal": "net-plus"})
        self.assertEqual(self.run_vault()[0][1], "ok")
        self.assertEqual((self.vault / "daily" / "study.md").read_text(), "- [/] Drill #goal/net-plus-exam\n- [ ] x\n")

    def test_the_vault_refuses_a_doubled_tag_and_a_bad_id_even_on_the_line(self):
        (self.vault / "daily" / "study.md").write_text("- [ ] A #goal/x #goal/x\n- [ ] B #goal/Bad Id\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "odd tags")
        self.request({"op": "unlink", "note": "daily/study.md", "item": "A #goal/x #goal/x", "goal": "x"})
        self.request({"op": "unlink", "note": "daily/study.md", "item": "B #goal/Bad Id", "goal": "Bad Id"})
        self.assertEqual([r[1] for r in self.run_vault()], ["refused", "refused"])

    def test_a_longer_tag_is_not_the_same_link(self):
        # Found 18 Oct: "#goal/net-plus" in the text of "#goal/net-plus-exam" read as linked
        with open(self.goals / "2026-W42.md", "a") as f:
            f.write("- [ ] Net+ #goal/net-plus\n")
        s, todos = self.snap(), vault_mod.todo_snapshot(self.vault)
        text = vault_mod.goal_text(s, [{"do": "link", "period": "2026-W42", "item": "Net+ #goal/net-plus",
                                        "list": "study", "todo": self.DRILL}], todos)
        self.assertIn("link: 2026-W42 net-plus daily/study.md: Subnetting drill #goal/net-plus-exam\n", text)
        with self.assertRaises(vault_mod.Refused):  # and it is not linked, so no unlink
            vault_mod.goal_text(s, [{"do": "unlink", "period": "2026-W42", "item": "Net+ #goal/net-plus",
                                     "list": "study", "todo": self.DRILL}], todos)

    def test_vault_unlink_refusals(self):
        study = (self.vault / "daily" / "study.md").read_text()
        for req in ({"op": "unlink", "note": "daily/study.md", "item": "unrelated", "goal": "net-plus-exam"},       # no tag
                    {"op": "unlink", "note": "daily/study.md", "item": "DNS lab #goal/net-plus-exam", "goal": "net-plus-exam"},  # ticked
                    {"op": "unlink", "note": "daily/study.md", "item": self.DRILL, "goal": "net-plus"},           # a prefix of the tag
                    {"op": "unlink", "note": "daily/study.md", "item": self.DRILL, "goal": "Bad Id"},
                    {"op": "unlink", "note": "goals/2026-W42.md", "item": self.EXAM, "goal": "net-plus-exam"}):
            self.request(req)
        self.assertTrue(all(r[1] == "refused" for r in self.run_vault()))
        self.assertEqual((self.vault / "daily" / "study.md").read_text(), study)


class GoalHoursTest(GoalBase):
    """129: estimates and logged hours, held as whole minutes."""

    EXAM = "Pass the Net+ practice exam #goal/net-plus-exam"

    def setUp(self):
        super().setUp()
        (self.goals / "2026.md").write_text("- [ ] Pass CPTS #goal/pass-cpts [est:: 100h] [spent:: 2h]\n")
        (self.goals / "2026-10.md").write_text(
            "- [ ] Nmap (5/12) #goal/nmap [in:: pass-cpts] [est:: 6h] [spent:: 1.5h]\n"
            "- [ ] Web basics [in:: pass-cpts] [spent:: 0.25h]\n")
        (self.vault / "daily" / "study.md").write_text(
            "- [x] DNS lab #goal/nmap [est:: 1h] [spent:: 0.75h]\n- [ ] Subnetting drill #goal/net-plus-exam\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "hours")

    def goal(self, key, gid):
        return next(g for g in self.period(key)["goals"] if g["goal"] == gid)

    def pick(self, do, value, item=EXAM):
        return {"do": do, "period": "2026-W42", "item": item, "hours": value}

    def test_own_and_rolled_up_hours_in_minutes(self):
        nmap = self.goal("2026-10", "nmap")
        self.assertEqual((nmap["est"], nmap["spent"]), (360, 90))
        self.assertEqual(nmap["hours"], [90 + 45, 360 + 60])  # with its linked todo
        cpts = self.goal("2026", "pass-cpts")
        # own 2 h of 100 h, Nmap's rolled 135 of 420 min, the id-less Web basics 15 min
        self.assertEqual(cpts["hours"], [120 + 135 + 15, 6000 + 420])
        self.assertIsNone(self.goal("2026-W42", "net-plus-exam")["hours"])  # no hours anywhere

    def test_a_goal_with_an_estimate_is_measured_by_hours(self):
        # Decided 24 Oct (126b): hours logged is the measure, not a count or the todos ticked
        self.assertEqual(self.goal("2026-10", "nmap")["rollup"], round(135 * 100 / 420))  # not 5/12, not its todo
        self.assertEqual(self.goal("2026", "pass-cpts")["rollup"], round(270 * 100 / 6420))
        (self.goals / "2026.md").write_text("- [ ] Over #goal/over [est:: 1h] [spent:: 3h]\n"
                                            "- [ ] Counted (2/10) #goal/counted\n"
                                            "- [x] Done early #goal/early [est:: 4h] [spent:: 1h]\n"
                                            "- [ ] Solo #goal/solo [est:: 4h] [spent:: 1h]\n")
        (self.goals / "2026-10.md").write_text("- [ ] No id [in:: over] [est:: 2h] [spent:: 0.5h]\n"
                                               "- [ ] Alone [est:: 2h] [spent:: 0.5h]\n"
                                               "- [x] Ticked alone [est:: 2h] [spent:: 0.5h]\n")
        self.assertEqual(self.goal("2026", "over")["rollup"], 100)  # past the estimate stops at 100
        self.assertEqual(self.goal("2026", "early")["rollup"], 100)  # ticked is finished
        counted = self.goal("2026", "counted")
        self.assertEqual((counted["rollup"], counted["progress"]), (None, [2, 10]))  # no hours: the count stays
        alone = next(g for g in self.period("2026-10")["goals"] if g["text"].startswith("Alone"))
        self.assertEqual(alone["rollup"], 25)
        self.assertEqual(self.goal("2026", "solo")["rollup"], 25)  # an id, an estimate, nothing under it
        ticked = next(g for g in self.period("2026-10")["goals"] if g["text"].startswith("Ticked alone"))
        self.assertEqual(ticked["rollup"], 100)

    def test_odd_hours_in_a_note_are_no_hours(self):
        (self.goals / "2026.md").write_text("- [ ] A #goal/a [est:: lots] [spent:: -1h]\n- [ ] B #goal/b [est:: 99999h]\n"
                                            "- [ ] C #goal/c [est:: 0h] [spent:: 9999.75h]\n")
        a, b, c = self.goal("2026", "a"), self.goal("2026", "b"), self.goal("2026", "c")
        self.assertEqual((a["est"], a["spent"], b["est"], c["est"], c["spent"]), (None,) * 5)

    def test_hours_stop_at_a_cycle(self):
        (self.goals / "2026.md").write_text("- [ ] A #goal/a [in:: b] [spent:: 1h]\n- [ ] B #goal/b [in:: a] [spent:: 1h]\n")
        self.assertIsNotNone(self.goal("2026", "a")["hours"])

    def test_estimate_and_log_in_the_signed_text(self):
        s = self.snap()
        text = vault_mod.goal_text(s, [self.pick("est", "6"), self.pick("log", "1.5")])
        self.assertIn("est: 2026-W42 6h Pass the Net+ practice exam #goal/net-plus-exam\n", text)
        self.assertIn("log: 2026-W42 1.5h Pass the Net+ practice exam #goal/net-plus-exam\n", text)
        reqs = vault_mod.goal_requests(text, s)
        self.assertEqual(reqs, [{"op": "est", "note": "goals/2026-W42.md", "item": self.EXAM, "minutes": 360},
                                {"op": "log", "note": "goals/2026-W42.md", "item": self.EXAM + " [est:: 6h]", "minutes": 90}])

    def test_hours_refusals(self):
        s = self.snap()
        for name, picks in {
            "text": [self.pick("est", "six")],
            "negative": [self.pick("log", "-1")],
            "zero": [self.pick("log", "0")],
            "not a quarter": [self.pick("est", "1.1")],
            "a thousand hours": [self.pick("est", "1000")],
            "a 25 hour log": [self.pick("log", "25")],
            "a unit typed": [self.pick("log", "1h")],
            "two logs": [self.pick("log", "1"), self.pick("log", "2")],
            "a number": [{**self.pick("log", "1"), "hours": 1}],
        }.items():
            with self.subTest(name=name):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_text(s, picks)
        (self.goals / "2026.md").write_text("- [ ] Big #goal/big [spent:: 9990h]\n")
        with self.assertRaises(vault_mod.Refused):  # past 9999 h in all
            vault_mod.goal_text(self.snap(), [{"do": "log", "period": "2026", "item": "Big #goal/big [spent:: 9990h]", "hours": "10"}])

    def test_a_log_onto_unreadable_hours_or_a_full_line_is_refused(self):
        long_goal = "x" * 170  # 184 with " [spent:: 1h]", past 180
        (self.goals / "2026.md").write_text(f"- [ ] Odd #goal/odd [spent:: 0h]\n- [ ] {long_goal}\n")
        s = self.snap()
        for item in ("Odd #goal/odd [spent:: 0h]", long_goal):
            with self.subTest(item=item[:10]):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_text(s, [{"do": "log", "period": "2026", "item": item, "hours": "1"}])
        self.git("add", "-A"); self.git("commit", "-q", "-m", "odd")
        self.request({"op": "log", "note": "goals/2026.md", "item": "Odd #goal/odd [spent:: 0h]", "minutes": 60})
        self.request({"op": "est", "note": "daily/study.md", "item": "Subnetting drill #goal/net-plus-exam", "minutes": 60})
        self.assertEqual([r[1] for r in self.run_vault()], ["refused", "refused"])

    def test_requests_refuse_hours_goal_text_did_not_build(self):
        s = self.snap()
        for bad in ("est: 2026-W42 6 Study 10 h (3/10)\n", "log: 2026-W42 1.1h Study 10 h (3/10)\n",
                    "log: 2026-W42 abch Study 10 h (3/10)\n", "est: 2026-W42 6h\n"):
            with self.subTest(bad=bad):
                with self.assertRaises(vault_mod.Refused):
                    vault_mod.goal_requests(f"goal: {s['id']}\n" + bad, s)

    def test_the_vault_sets_an_estimate_and_adds_up_hours(self):
        item = "Study 10 h (3/10)"
        self.request({"op": "est", "note": "goals/2026-W42.md", "item": item, "minutes": 600})
        self.request({"op": "log", "note": "goals/2026-W42.md", "item": item + " [est:: 10h]", "minutes": 90})
        self.request({"op": "log", "note": "goals/2026-W42.md", "item": item + " [est:: 10h] [spent:: 1.5h]", "minutes": 45})
        self.request({"op": "est", "note": "goals/2026-W42.md", "item": item + " [est:: 10h] [spent:: 2.25h]", "minutes": 720})
        self.assertEqual([r[1] for r in self.run_vault()], ["ok"] * 4)
        self.assertIn("- [ ] Study 10 h (3/10) [est:: 12h] [spent:: 2.25h]\n", (self.goals / "2026-W42.md").read_text())

    def test_vault_hours_refusals(self):
        item = "Study 10 h (3/10)"
        for req in ({"op": "est", "note": "goals/2026-W42.md", "item": item, "minutes": 0},
                    {"op": "est", "note": "goals/2026-W42.md", "item": item, "minutes": 61},          # not a quarter
                    {"op": "est", "note": "goals/2026-W42.md", "item": item, "minutes": 999 * 60 + 15},
                    {"op": "log", "note": "goals/2026-W42.md", "item": item, "minutes": 25 * 60},
                    {"op": "log", "note": "goals/2026-W42.md", "item": item, "minutes": "60"},
                    {"op": "log", "note": "goals/2026-W42.md", "item": item, "minutes": True},
                    {"op": "log", "note": "goals/2026-W42.md", "item": "Gym twice", "minutes": 60},  # done
                    {"op": "log", "note": "daily/study.md", "item": "Subnetting drill #goal/net-plus-exam", "minutes": 60}):
            self.request(req)
        self.assertTrue(all(r[1] == "refused" for r in self.run_vault()))
        self.assertNotIn("[est::", (self.goals / "2026-W42.md").read_text())
        self.assertNotIn("[spent::", (self.goals / "2026-W42.md").read_text())

    def test_the_vault_refuses_a_total_past_9999_hours(self):
        (self.goals / "2026.md").write_text("- [ ] Big #goal/big [spent:: 9990h]\n")
        self.git("add", "-A"); self.git("commit", "-q", "-m", "big")
        self.request({"op": "log", "note": "goals/2026.md", "item": "Big #goal/big [spent:: 9990h]", "minutes": 600})
        self.assertEqual(self.run_vault()[0][1], "refused")


if __name__ == "__main__":
    unittest.main()
