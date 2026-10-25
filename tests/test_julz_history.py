"""Tests for functions/julz_history.py: a long chat kept inside the model's window (26k).
Run: python3 -m unittest discover -s tests -v"""
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("julz_history", ROOT / "functions" / "julz_history.py")
hist = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hist)

SYSTEM = {"role": "system", "content": "You are Julz."}


def chat(*texts):
    roles = ["user", "assistant"]
    return [copy.deepcopy(SYSTEM)] + [{"role": roles[i % 2], "content": t} for i, t in enumerate(texts)]


def contents(msgs):
    return [m["content"] for m in msgs]


def history_size(msgs):
    return sum(hist.size(m) for m in msgs if m["role"] != "system")


class TrimTest(unittest.TestCase):
    def test_short_chat_unchanged(self):
        msgs = chat("hi", "Hello!", "what is DNS?")
        self.assertEqual(hist.trim(copy.deepcopy(msgs), 100), msgs)

    def test_long_chat_fits_the_budget(self):
        msgs = chat(*[f"{i}" * 30 for i in range(10)])
        out = hist.trim(msgs, 100)
        self.assertLessEqual(history_size(out), 100)

    def test_system_kept_first(self):
        msgs = chat(*["x" * 30 for _ in range(9)])
        out = hist.trim(msgs, 50)
        self.assertEqual(out[0], SYSTEM)
        self.assertEqual(sum(m["role"] == "system" for m in out), 1)

    def test_newest_kept_middle_dropped(self):
        msgs = chat("a" * 40, "b" * 40, "c" * 40, "d" * 40, "e" * 40)
        self.assertEqual(contents(hist.trim(msgs, 170)), ["You are Julz.", "a" * 40, "c" * 40, "d" * 40, "e" * 40])

    def test_order_kept(self):
        msgs = chat("1" * 10, "2" * 10, "3" * 10, "4" * 10, "5" * 10, "6" * 10, "7" * 10)
        out = contents(hist.trim(msgs, 45))
        self.assertEqual(out, sorted(out, key=lambda c: (c != "You are Julz.", c)))

    def test_huge_last_message_keeps_its_end(self):
        last = "start " + "x" * 200 + " question?"
        out = hist.trim(chat("hi", "Hello!", last), 50)
        self.assertEqual(out[0], SYSTEM)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[1]["content"], last[-50:])
        self.assertTrue(out[1]["content"].endswith("question?"))

    def test_input_not_changed(self):
        msgs = chat("hi", "Hello!", "y" * 200)
        before = copy.deepcopy(msgs)
        hist.trim(msgs, 50)
        self.assertEqual(msgs, before)

    def test_my_whole_turn_kept(self):
        # Learn mode appends its words as a user message after mine (135)
        msgs = chat("a" * 40, "b" * 40, "my question") + [{"role": "user", "content": "mode words"}]
        out = contents(hist.trim(msgs, 30))
        self.assertEqual(out[-2:], ["my question", "mode words"])

    def test_turn_over_budget_cuts_my_message_not_the_words(self):
        msgs = chat("hi", "Hello!", "z" * 100) + [{"role": "user", "content": "mode words"}]
        out = contents(hist.trim(msgs, 40))
        self.assertEqual(out[1:], ["z" * 30, "mode words"])

    def test_continue_keeps_her_last_answer(self):
        msgs = chat("a" * 40, "b" * 40, "c" * 40, "partial answer")
        self.assertEqual(contents(hist.trim(msgs, 60))[-1], "partial answer")

    def test_window_starts_on_my_message(self):
        # b would fit, but a window that opens on her answer drops it
        msgs = chat("a" * 40, "b" * 10, "c" * 10, "d" * 10, "e" * 10)
        out = hist.trim(msgs, 45)
        self.assertEqual(contents(out), ["You are Julz.", "c" * 10, "d" * 10, "e" * 10])

    def test_first_message_pinned_when_it_fits(self):
        msgs = chat("quiz key", "b" * 40, "c" * 20, "d" * 20, "e" * 10)
        out = contents(hist.trim(msgs, 70))
        self.assertEqual(out, ["You are Julz.", "quiz key", "c" * 20, "d" * 20, "e" * 10])

    def test_first_message_not_pinned_when_too_big(self):
        msgs = chat("q" * 61, "b" * 40, "c" * 40, "d" * 40, "e" * 10)
        self.assertNotIn("q" * 60, contents(hist.trim(msgs, 70)))

    def test_first_message_pinned_only_if_mine(self):
        msgs = [SYSTEM, {"role": "assistant", "content": "greeting"}] + chat(
            "b" * 40, "c" * 40, "d" * 40)[1:]
        self.assertNotIn("greeting", contents(hist.trim(msgs, 50)))

    def test_first_message_not_doubled(self):
        msgs = chat("first", "b" * 40, "c")
        out = contents(hist.trim(msgs, 46))
        self.assertEqual(out.count("first"), 1)

    def test_her_old_answer_never_cut(self):
        # Only my current turn may be cut; her answer before it goes whole or not at all
        out = contents(hist.trim(chat("hi", "a" * 100, "q"), 20))
        self.assertEqual(out, ["You are Julz.", "hi", "q"])

    def test_older_message_over_room_left_out(self):
        msgs = chat("A" * 50, "b" * 10, "c" * 10, "d" * 10, "e" * 10, "f" * 10, "g" * 10)
        out = hist.trim(msgs, 47)
        self.assertEqual(contents(out), ["You are Julz.", "e" * 10, "f" * 10, "g" * 10])

    def test_no_gaps_past_a_big_message(self):
        msgs = chat("A" * 100, "b" * 5, "c" * 5, "D" * 100, "e" * 5, "f" * 5, "g" * 5)
        self.assertEqual(contents(hist.trim(msgs, 30)), ["You are Julz.", "e" * 5, "f" * 5, "g" * 5])

    def test_odd_content_refused(self):
        with self.assertRaises(TypeError):
            hist.size({"role": "user", "content": {"a": 1}})

    def test_list_content_counted_and_not_cut(self):
        image = {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:,"}}, {"type": "text", "text": "w" * 80}]}
        self.assertEqual(hist.size(image), 80)
        out = hist.trim([SYSTEM, image], 20)
        self.assertEqual(out[1], image)

    def test_output_items_counted(self):
        # A stored answer may carry structured output items beside its text
        m = {"role": "assistant", "content": "ok", "output": [{"type": "x", "text": "o" * 100}]}
        self.assertGreaterEqual(hist.size(m), 100)


class InletTest(unittest.TestCase):
    def setUp(self):
        self.f = hist.Filter()

    def test_budget_applied(self):
        body = {"messages": chat(*["m" * 1000 for _ in range(40)]), "model": "julz:latest"}
        out = self.f.inlet(body)
        self.assertLessEqual(history_size(out["messages"]), hist.HISTORY_CHARS)
        self.assertEqual(out["messages"][0], SYSTEM)
        self.assertEqual(out["model"], "julz:latest")

    def test_short_body_unchanged(self):
        body = {"messages": chat("hi", "Hello!", "what is DNS?")}
        self.assertEqual(self.f.inlet(copy.deepcopy(body)), body)

    def test_odd_bodies_do_not_crash(self):
        for b in ({}, {"messages": None}, {"messages": [None, 5]}, {"messages": "x"},
                  {"messages": [{"role": "user", "content": None}]},
                  {"messages": [{"role": "user", "content": {"a": 1}}]}):
            self.assertEqual(self.f.inlet(copy.deepcopy(b)), b)


if __name__ == "__main__":
    unittest.main()
