"""functions/julz_tasks.py: code spots a done task in a chatty message, julz decides
(SECURITY.md 82). The filter never ticks anything itself."""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("julz_tasks", ROOT / "functions" / "julz_tasks.py")
tasks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tasks)


def body(text):
    return {"messages": [{"role": "system", "content": "You are Julz."},
                         {"role": "user", "content": text}]}


class TaskHintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        for d in ("daily/done", "Inbox", "Claude", "study"):
            (self.vault / d).mkdir(parents=True)
        (self.vault / "daily" / "week.md").write_text(
            "# Week\n\n- [ ] walk 10k steps\n- [ ] buy milk\n- [x] book physio (done 2026-10-15)\n")
        os.environ["JULZ_VAULT"] = str(self.vault)
        self.f = tasks.Filter()

    def tearDown(self):
        self.tmp.cleanup()

    def hint(self, text):
        out = self.f.inlet(body(text))["messages"][-1]["content"]
        return out[len(text):]

    def test_chatty_message_gets_the_hint(self):
        h = self.hint("cool, also i walked 10k today, legs are dead")
        self.assertIn("walk 10k steps", h)
        self.assertIn("daily/week.md", h)
        self.assertIn("tick_task", h)

    def test_half_the_words_is_enough(self):
        self.assertIn("buy milk", self.hint("got the milk on the way home"))

    def test_no_match_no_hint(self):
        for text in ("what is a VLAN?", "i walked into a wall", ""):
            self.assertEqual(self.hint(text), "", text)

    def test_done_finished_and_read_only_tasks_never_hinted(self):
        (self.vault / "daily" / "done" / "old.md").write_text("- [ ] walk the dog\n")
        (self.vault / "Claude" / "c.md").write_text("- [ ] walk the dog\n")
        (self.vault / "study" / "s.md").write_text("- [ ] walk the dog\n")
        (self.vault / "daily" / ".hidden.md").write_text("- [ ] walk the dog\n")
        self.assertEqual(self.hint("i walked the dog"), "")
        self.assertEqual(self.hint("booked physio"), "")  # already ticked

    def test_symlink_out_of_the_vault_ignored(self):
        outside = Path(self.tmp.name).parent / f"{Path(self.tmp.name).name}-out.md"
        outside.write_text("- [ ] walk the dog\n")
        try:
            (self.vault / "daily" / "link.md").symlink_to(outside)
            self.assertEqual(self.hint("i walked the dog"), "")
        finally:
            outside.unlink()

    def test_hint_is_short_and_plain(self):
        long_task = "walk " + "x" * 300
        (self.vault / "daily" / "long.md").write_text(f"- [ ] {long_task}\n- [ ] walk \u202eevil\n")
        h = self.hint("i walked")
        self.assertLess(len(h), 600)
        self.assertNotIn("\u202e", h)
        self.assertNotIn("x" * 100, h)

    def test_at_most_three_tasks(self):
        (self.vault / "daily" / "many.md").write_text(
            "".join(f"- [ ] milk run {i}\n" for i in range(10)))
        self.assertLessEqual(self.hint("bought milk").count("tick_task"), 1)
        self.assertLessEqual(self.hint("bought milk").count('"'), 2 * 3)

    def test_list_content_and_no_user_message(self):
        b = {"messages": [{"role": "user", "content": [{"type": "text", "text": "walked 10k"}]}]}
        self.assertIn("walk 10k steps", self.f.inlet(b)["messages"][-1]["content"][0]["text"])
        self.assertEqual(self.f.inlet({"messages": []}), {"messages": []})
        self.assertEqual(self.f.inlet("odd"), "odd")


if __name__ == "__main__":
    unittest.main()
