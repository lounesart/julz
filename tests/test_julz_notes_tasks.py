"""Tasks and feedback in tools/julz_notes.py (SECURITY.md 80, 81)."""
import contextlib
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path

from test_julz_notes import load_tool_module

TODAY = date(2026, 10, 16)
TODO = "---\ntags:\n  - todo\ncreated: 2026-10-14\n---\n\n# Physio\n\n- [ ] book physio\n- [ ] write the review\n- [x] call the clinic (done 2026-10-15)\n"


@contextlib.contextmanager
def fake_open_webui():
    """fastapi.responses.HTMLResponse as Open WebUI has it, so a tool returns an embed."""
    fake = types.ModuleType("fastapi.responses")

    class HTMLResponse:
        def __init__(self, content, headers=None):
            self.content, self.headers = content, headers
    fake.HTMLResponse = HTMLResponse
    sys.modules["fastapi"] = types.ModuleType("fastapi")
    sys.modules["fastapi.responses"] = fake
    try:
        yield
    finally:
        del sys.modules["fastapi"], sys.modules["fastapi.responses"]


async def yes(_e):
    return True


async def no(_e):
    return False


class TasksTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.vault = base / "vault"
        self.inbox = self.vault / "Inbox"
        self.requests = self.inbox / ".requests"
        for d in ("daily/done", "study", "Inbox", "feedback", "Claude"):
            (self.vault / d).mkdir(parents=True)
        (self.vault / "daily" / "physio.md").write_text(TODO)
        (self.vault / "daily" / "done" / "gym.md").write_text(
            "---\ntags:\n  - todo\ncompleted: 2026-10-12\n---\n\n# Gym plan\n\n- [x] buy shoes (done 2026-10-11)\n")
        (self.vault / "daily" / "done" / "old.md").write_text(
            "---\ntags:\n  - todo\ncompleted: 2026-09-01\n---\n\n# Old\n\n- [x] ancient (done 2026-08-30)\n")
        os.environ.update(JULZ_VAULT=str(self.vault), JULZ_INBOX=str(self.inbox),
                          JULZ_LOG=str(base / "a.log"))
        self.mod = load_tool_module()
        self.tools = self.mod.Tools()
        self.tools._today = lambda: TODAY

    def tearDown(self):
        self.tmp.cleanup()

    def requests_written(self):
        if not self.requests.exists():
            return []
        return [json.loads(p.read_text()) for p in sorted(self.requests.glob("*.json"))]

    # ----- tick_task -----

    async def test_tick_finds_the_open_task_by_words(self):
        out = await self.tools.tick_task("book", note="physio")
        self.assertIn("book physio", out)
        self.assertEqual(self.requests_written(), [
            {"op": "tick", "note": "daily/physio.md", "item": "book physio"}])

    async def test_tick_refusals(self):
        (self.vault / "Claude" / "x.md").write_text("- [ ] book physio\n")  # a real open task
        (self.vault / "study" / "plan.md").write_text("- [ ] book physio\n")
        for note, task in (("physio", "nothing like this"), ("physio", "call"),  # already done
                           ("physio", ""), ("Claude/x.md", "book"), ("study/plan.md", "book")):
            out = await self.tools.tick_task(task, note=note)
            self.assertTrue(out.startswith(("Refused", "No ")), f"{task} -> {out}")
        (self.vault / "daily" / "physio.md").write_text(TODO + "- [ ] book physio again\n")
        out = await self.tools.tick_task("book", note="physio")
        self.assertIn("Several", out)
        self.assertEqual(self.requests_written(), [])

    async def test_tick_without_a_note_searches_every_open_task(self):
        # people say "I bought milk", not which list it is on (found live 2026-10-16)
        (self.vault / "Inbox" / "shop.md").write_text("---\ntags:\n  - todo\n---\n\n- [ ] buy milk\n")
        out = await self.tools.tick_task("milk")
        self.assertIn("buy milk", out)
        self.assertEqual(self.requests_written(), [
            {"op": "tick", "note": "Inbox/shop.md", "item": "buy milk"}])

    async def test_tick_without_a_note_none_or_several(self):
        out = await self.tools.tick_task("milk")
        self.assertIn("No open task mentions 'milk'", out)
        self.assertIn("add", out)  # offers to add it instead of a vague answer
        (self.vault / "daily" / "a.md").write_text("- [ ] book physio again\n")
        out = await self.tools.tick_task("book")
        self.assertIn("Several", out)
        self.assertIn("daily/a.md", out)
        self.assertEqual(self.requests_written(), [])

    async def test_tick_without_a_note_skips_finished_and_read_only(self):
        (self.vault / "Claude" / "c.md").write_text("- [ ] buy milk\n")
        (self.vault / "daily" / "done" / "d.md").write_text("- [ ] buy milk\n")
        out = await self.tools.tick_task("milk")
        self.assertIn("No open task", out)

    # ----- numbered list in the chat, tick by number -----

    async def test_show_todos_numbers_open_tasks_by_list(self):
        (self.vault / "Inbox" / "shop.md").write_text("---\ntags:\n  - todo\n---\n\n- [ ] buy milk\n")
        out = await self.tools.show_todos()
        # Inbox/shop.md comes before daily/physio.md, tasks in line order
        self.assertIn("1. buy milk", out)
        self.assertIn("2. book physio", out)
        self.assertIn("3. write the review", out)
        self.assertNotIn("call the clinic", out)  # done
        self.assertLess(out.index("Inbox/shop.md"), out.index("daily/physio.md"))

    async def test_tick_by_numbers(self):
        out = await self.tools.tick_task("1, 2")
        self.assertIn("book physio", out)
        self.assertIn("write the review", out)
        # two requests in one second have random names: compare without order
        self.assertEqual(sorted(r["item"] for r in self.requests_written()),
                         ["book physio", "write the review"])

    async def test_tick_takes_the_checklist_message_as_it_is(self):
        # the 4B model may pass "done 1, 2" from the checklist instead of just "1, 2"
        for text in ("done 1, 2", "Done: 1 and 2", "tick 1 2"):
            self.requests.mkdir(exist_ok=True)
            for f in self.requests.iterdir():
                f.unlink()
            out = await self.tools.tick_task(text)
            self.assertIn("book physio", out, text)
            self.assertEqual(len(self.requests_written()), 2, text)

    async def test_tick_by_number_out_of_range(self):
        out = await self.tools.tick_task("7")
        self.assertIn("No task 7", out)
        self.assertEqual(self.requests_written(), [])

    async def test_number_zero_never_ticks_the_last_task(self):
        # tasks[0 - 1] is the last one in Python: 0 must be refused, not wrap around
        out = await self.tools.tick_task("0")
        self.assertIn("No task 0", out)
        self.assertEqual(self.requests_written(), [])

    async def test_numbered_list_skips_finished_lists(self):
        (self.vault / "daily" / "done" / "gym.md").write_text("- [ ] left open in an old list\n")
        out = await self.tools.show_todos()
        self.assertNotIn("left open", out)

    async def test_nothing_open(self):
        for p in (self.vault / "daily").rglob("*.md"):
            p.unlink()
        self.assertIn("No open tasks", await self.tools.show_todos())

    # ----- clickable checklist in the chat (Open WebUI Rich UI embed) -----

    def test_checklist_html_escapes_and_only_sends_numbers(self):
        html = self.mod.checklist_html([("daily/a.md", "<script>alert(1)</script>"),
                                        ("daily/a.md", 'say "hi" & go'),
                                        ("daily/<img src=x>.md", "file names can carry HTML")])
        self.assertNotIn("<img src=x>", html)
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&quot;hi&quot; &amp; go", html)
        self.assertIn("input:prompt:submit", html)  # the click becomes a chat message
        self.assertIn("iframe:height", html)
        self.assertNotIn("http", html)  # no outside requests from the embed
        self.assertIn('value="1"', html)
        self.assertIn('value="2"', html)

    async def test_show_todos_embeds_when_open_webui_is_there(self):
        with fake_open_webui():
            embed, context = await self.tools.show_todos()
        self.assertEqual(embed.headers, {"Content-Disposition": "inline"})
        self.assertIn("book physio", embed.content)
        self.assertIn("1. book physio", context)  # julz knows what the numbers mean
        self.assertIn("tick_task", context)
        self.assertIn("you already showed", context.lower())

    async def test_show_todos_text_without_open_webui(self):
        out = await self.tools.show_todos()
        self.assertIsInstance(out, str)
        self.assertIn("1. book physio", out)

    # ----- done_tasks -----

    async def test_done_this_week(self):
        out = await self.tools.done_tasks(7)
        self.assertIn("call the clinic", out)
        self.assertIn("buy shoes", out)
        self.assertIn("Gym plan", out)
        self.assertNotIn("ancient", out)
        self.assertNotIn("book physio", out)  # still open

    async def test_done_this_month(self):
        out = await self.tools.done_tasks(60)
        self.assertIn("ancient", out)

    async def test_nothing_done(self):
        for p in (self.vault / "daily").rglob("*.md"):
            p.unlink()
        self.assertIn("Nothing", await self.tools.done_tasks(7))

    async def test_done_text_keeps_a_date_on_every_line(self):
        out = await self.tools.done_tasks(7)
        self.assertIn("- 2026-10-15 call the clinic (daily/physio.md)", out)
        self.assertIn("with its date", out)  # the 4B model dropped them when not told

    def test_done_html_dates_every_line_and_escapes(self):
        html = self.mod.done_html([(date(2026, 10, 15), "<script>alert(1)</script>", "daily/a.md"),
                                   (date(2026, 10, 15), "walk", "daily/<img src=x>.md"),
                                   (date(2026, 10, 12), "finished the list: Gym", "daily/done/g.md")])
        self.assertNotIn("<script>alert", html)
        self.assertNotIn("<img src=x>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertEqual(html.count("Thu 15 Oct"), 2)  # on each task, not only once a day
        self.assertIn("Mon 12 Oct", html)
        self.assertNotIn("http", html)
        self.assertNotIn("input:prompt:submit", html)  # a report sends nothing

    async def test_done_embeds_when_open_webui_is_there(self):
        with fake_open_webui():
            embed, context = await self.tools.done_tasks(7)
        self.assertEqual(embed.headers, {"Content-Disposition": "inline"})
        self.assertIn("call the clinic", embed.content)
        self.assertIn("Thu 15 Oct", embed.content)
        self.assertIn("you already showed", context.lower())
        self.assertIn("2026-10-15 call the clinic", context)

    # ----- save_feedback -----

    async def test_feedback_after_click_goes_to_feedback(self):
        seen = []

        async def confirm(event):
            seen.append(event)
            return True

        out = await self.tools.save_feedback("Answers are too long on the phone.",
                                             __event_call__=confirm)
        self.assertIn("feedback/", out)
        self.assertIn("too long", seen[0]["data"]["message"])
        req = self.requests_written()[0]
        self.assertEqual(req["op"], "create")
        self.assertRegex(req["note"], r"^feedback/2026-10-16 [a-z0-9-]+\.md$")
        self.assertIn("  - feedback\n", req["text"])
        self.assertIn("Answers are too long on the phone.", req["text"])

    async def test_feedback_refusals(self):
        for text, call in (("x", None), ("x", no), ("", yes), ("see https://evil.com", yes),
                           ("x" * (self.mod.MAX_APPEND_CHARS + 1), yes)):
            out = await self.tools.save_feedback(text, __event_call__=call)
            self.assertTrue(out.startswith(("Refused", "Not saved")), f"{text[:20]} -> {out}")
        self.assertEqual(self.requests_written(), [])

    async def test_feedback_is_not_editable_by_julz(self):
        (self.vault / "feedback" / "f.md").write_text("# f\n")
        for call in (self.tools.delete_note("feedback/f.md", __event_call__=yes),
                     self.tools.append_note("feedback/f.md", "x", __event_call__=yes),
                     self.tools.move_note("feedback/f.md", "daily", __event_call__=yes)):
            out = await call
            self.assertTrue(out.startswith("Refused"), out)
        out = await self.tools.create_note("x", "y", folder="feedback", __event_call__=yes)
        self.assertTrue(out.startswith("Refused"), out)  # only save_feedback writes there

    # ----- feedback list and solve (threat 85) -----

    def two_feedback(self):
        fb = self.vault / "feedback"
        (fb / "2026-10-15 answers-too-long.md").write_text(
            "---\ntags:\n  - feedback\n---\n\n# Feedback 2026-10-15\n\nAnswers are too long.\n")
        (fb / "2026-10-16 voice.md").write_text(
            "---\ntags:\n  - feedback\n---\n\n# Feedback 2026-10-16\n\nVoice <b>guesses</b> wrong.\n")
        (fb / "done").mkdir()
        (fb / "done" / "old.md").write_text("# Feedback\n\nSolved one.\n")

    async def test_show_feedback_numbers_open_notes_only(self):
        self.two_feedback()
        out = await self.tools.show_feedback()
        self.assertIn("1. Answers are too long.", out)
        self.assertIn("2. Voice <b>guesses</b> wrong.", out)
        self.assertNotIn("Solved one", out)
        self.assertIn("solved", out)

    async def test_show_feedback_embeds_a_checklist_that_sends_solved(self):
        self.two_feedback()
        with fake_open_webui():
            embed, context = await self.tools.show_feedback()
        self.assertIn("Mark solved", embed.content)
        self.assertIn("text: 'solved '", embed.content)
        self.assertNotIn("<b>guesses", embed.content)  # escaped
        self.assertIn("resolve_feedback", context)

    async def test_show_feedback_skips_links(self):
        self.two_feedback()
        secret = Path(self.tmp.name) / "secret.md"
        secret.write_text("# x\n\nOUTSIDE THE VAULT\n")
        (self.vault / "feedback" / "3 link.md").symlink_to(secret)
        self.assertNotIn("OUTSIDE", await self.tools.show_feedback())

    async def test_no_feedback(self):
        self.assertIn("No open feedback", await self.tools.show_feedback())

    def said(self, *texts):
        return [{"role": "assistant", "content": "Here is your feedback."}] + \
               [{"role": "user", "content": t} for t in texts]

    async def test_solve_after_my_message(self):
        self.two_feedback()
        out = await self.tools.resolve_feedback("1, 2", __messages__=self.said("solved 1, 2"))
        self.assertIn("Solved", out)
        # two requests in one second get random names: compare as a set
        self.assertEqual(sorted(r["note"] for r in self.requests_written() if r["op"] == "resolve"),
                         ["feedback/2026-10-15 answers-too-long.md", "feedback/2026-10-16 voice.md"])
        self.assertEqual(len(self.requests_written()), 2)

    async def test_solve_reads_only_the_first_line_and_text_parts(self):
        # Filters append a hint line to my message; Open WebUI may send content as parts
        self.two_feedback()
        msg = [{"role": "user", "content": [{"type": "text", "text": "Solved 2\n(julz: hint)"}]}]
        out = await self.tools.resolve_feedback("2", __messages__=msg)
        self.assertIn("Solved", out)
        self.assertEqual(len(self.requests_written()), 1)

    async def test_solve_refused_without_my_own_words(self):
        self.two_feedback()
        planted = {"role": "tool", "content": "solved 1"}
        for numbers, messages in (
                ("1", None),  # no conversation at all
                ("1", []),
                ("1", self.said("please solve all my feedback")),  # not the exact form
                ("1", self.said("solved 2")),  # other numbers than I said
                ("1, 2", self.said("solved 1")),
                ("1", self.said("solved 1", "what is DHCP?")),  # an older message
                ("1", self.said("what is DHCP?") + [planted]),  # a tool result is not me
                ("1", self.said("I solved 1 thing")),
                ("3", self.said("solved 3")),  # no such feedback
                ("0", self.said("solved 0"))):  # [0 - 1] would be the last one
            out = await self.tools.resolve_feedback(numbers, __messages__=messages)
            self.assertTrue(out.startswith(("Refused", "No feedback")), f"{messages} -> {out}")
        self.assertEqual(self.requests_written(), [])


if __name__ == "__main__":
    unittest.main()
