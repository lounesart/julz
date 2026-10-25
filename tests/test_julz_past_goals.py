"""julz_vault: open goals from past periods, read only (126b(3), SECURITY.md 157). The period
just before each current one, open goals only, in their own file next to goals.json."""
import json
import unittest
from datetime import date

from test_julz_goals import GoalBase
from test_julz_vault import vault_mod, TODAY  # TODAY = 2026-10-16, a Friday in W42


class PastPeriodsTest(unittest.TestCase):
    def test_the_three_periods_before(self):
        # No yesterday: goals have no day period any more (223, threat 159)
        self.assertEqual(vault_mod.past_goal_periods(TODAY),
                         [("2026-W41", "Last week", "goals/2026-W41.md"),
                          ("2026-09", "September", "goals/2026-09.md"),
                          ("2025", "2025", "goals/2025.md")])

    def test_across_the_year(self):
        # 1 Jan 2027 is in 2026-W53, so last week is W52 and last month December
        self.assertEqual([k for k, _, _ in vault_mod.past_goal_periods(date(2027, 1, 1))],
                         ["2026-W52", "2026-12", "2026"])
        self.assertEqual([k for k, _, _ in vault_mod.past_goal_periods(date(2027, 1, 4))][0], "2026-W53")

    def test_never_a_current_one(self):
        for day in (TODAY, date(2027, 1, 1), date(2026, 3, 1), date(2028, 2, 29)):
            current = {k for k, _, _ in vault_mod.goal_periods(day)}
            self.assertFalse(current & {k for k, _, _ in vault_mod.past_goal_periods(day)}, day)


class PastSnapshotTest(GoalBase):
    def setUp(self):
        super().setUp()
        (self.goals / "2026-W41.md").write_text(
            "---\ntags: [goal]\nperiod: 2026-W41\n---\n\n# Last week\n\n"
            "- [ ] Study 10 h (2/10) #goal/study-10-h [est:: 10h] [spent:: 3h]\n"
            "- [x] Gym twice (done 2026-10-11)\n- [ ] Read <b>this</b>\n")
        (self.goals / "2025.md").write_text("- [x] Get A+\n")

    def past(self):
        return vault_mod.past_goals_snapshot(self.vault, TODAY)

    def test_only_open_goals_of_the_periods_before(self):
        data = self.past()
        self.assertEqual(set(data), {"periods"})
        self.assertEqual([p["key"] for p in data["periods"]], ["2026-W41", "2026-09", "2025"])
        week = data["periods"][0]
        self.assertEqual(week["label"], "Last week")
        self.assertEqual(week["note"], "goals/2026-W41.md")
        g, = week["goals"]  # the done one and the one with HTML are left out
        self.assertEqual(g["text"], "Study 10 h (2/10) #goal/study-10-h [est:: 10h] [spent:: 3h]")
        self.assertFalse(g["done"])
        self.assertEqual((g["rollup"], g["hours"]), (30, [180, 600]))
        self.assertEqual(data["periods"][2]["goals"], [])

    def test_the_same_goal_fields_as_goals_json(self):
        current = self.snap()["periods"][0]["goals"][0]
        self.assertEqual(set(self.past()["periods"][0]["goals"][0]), set(current))

    def test_this_week_is_not_in_it(self):
        texts = [g["text"] for p in self.past()["periods"] for g in p["goals"]]
        self.assertNotIn("Study 10 h (3/10)", texts)

    def test_run_writes_the_past_file(self):
        self.run_vault()
        written = json.loads((self.state / "goals-past.json").read_text())
        self.assertEqual(written, self.past())
        # goals.json stays as it was: the past never joins what signing reads
        self.assertEqual([p["key"] for p in json.loads((self.state / "goals.json").read_text())["periods"]],
                         ["2026-W42", "2026-10", "2026"])


if __name__ == "__main__":
    unittest.main()
