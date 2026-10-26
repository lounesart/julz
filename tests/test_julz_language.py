"""Tests for functions/julz_language.py: code picks the reply language, not the model.
Run: python3 -m unittest discover -s tests -v"""
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("julz_language", ROOT / "functions" / "julz_language.py")
lang = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lang)


def body(*texts):
    roles = ["user", "assistant"]
    return {"messages": [{"role": "system", "content": "You are Julz."}] +
            [{"role": roles[i % 2], "content": t} for i, t in enumerate(texts)]}


class DetectTest(unittest.TestCase):
    def test_english(self):
        self.assertEqual(lang.detect("what is a VLAN?"), "English")

    def test_russian(self):
        self.assertEqual(lang.detect("что такое VLAN?"), "Russian")

    def test_polish_letters(self):
        self.assertEqual(lang.detect("co to jest maska podsieci, proszę?"), "Polish")

    def test_polish_without_letters(self):
        # Phone typing often drops the diacritics
        self.assertEqual(lang.detect("czy mozesz mi powiedziec jak to dziala"), "Polish")

    def test_one_polish_looking_word_stays_english(self):
        self.assertEqual(lang.detect("nie is a word I saw in a log, what is it?"), "English")

    def test_first_line_decides(self):
        self.assertEqual(lang.detect("translate this:\nпривет, как дела у тебя сегодня"), "English")
        self.assertEqual(lang.detect("переведи:\nhello, how are you doing today"), "Russian")

    def test_first_line_without_letters_falls_back(self):
        self.assertEqual(lang.detect("```\n$ ls\n```\nпочему тут пусто?"), "Russian")

    def test_mixed_line_majority(self):
        self.assertEqual(lang.detect("сработало, now continue"), "Russian")
        self.assertEqual(lang.detect("как настроить nftables firewall на arch linux"), "Russian")

    def test_no_letters_is_english(self):
        self.assertEqual(lang.detect("192.168.1.0/24 ?"), "English")
        self.assertEqual(lang.detect(""), "English")


class InletTest(unittest.TestCase):
    def setUp(self):
        self.f = lang.Filter()

    def test_appends_to_last_user_message(self):
        out = self.f.inlet(body("hi", "Hello!", "что такое DNS?"))
        self.assertEqual(out["messages"][-1]["content"], "что такое DNS?\n\n(Reply in Russian.)")

    def test_other_messages_untouched(self):
        b = body("привет", "Привет!", "what is DNS?")
        before = copy.deepcopy(b["messages"][:-1])
        out = self.f.inlet(b)
        self.assertEqual(out["messages"][:-1], before)
        self.assertTrue(out["messages"][-1]["content"].endswith("(Reply in English.)"))

    def test_list_content(self):
        b = {"messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "data:,"}},
            {"type": "text", "text": "co to jest?"}]}]}
        out = self.f.inlet(b)
        parts = out["messages"][0]["content"]
        self.assertEqual(parts[1]["text"], "co to jest?\n\n(Reply in Polish.)")
        self.assertEqual(parts[0]["type"], "image_url")

    def test_only_first_text_part_tagged(self):
        b = {"messages": [{"role": "user", "content": [
            {"type": "text", "text": "what is this?"}, {"type": "text", "text": "pasted"}]}]}
        parts = self.f.inlet(b)["messages"][0]["content"]
        self.assertEqual([p["text"] for p in parts], ["what is this?\n\n(Reply in English.)", "pasted"])

    def test_no_user_message_unchanged(self):
        b = {"messages": [{"role": "system", "content": "x"}]}
        self.assertEqual(self.f.inlet(copy.deepcopy(b)), b)

    def test_odd_bodies_do_not_crash(self):
        for b in ({}, {"messages": None}, {"messages": [None, 5]},
                  {"messages": [{"role": "user", "content": None}]}):
            self.assertEqual(self.f.inlet(copy.deepcopy(b)), b)


# 202: Open WebUI 0.11.4 appends a mode's words as a user turn before the inlet filters
LEARN = "(Learning mode, about my message above: teach me, do not solve it for me.)"


class ModeTurnTest(unittest.TestCase):
    def setUp(self):
        self.f = lang.Filter()

    def test_language_from_my_turn_hint_on_the_mode_turn(self):
        b = body("как работает DNS?")
        b["messages"].append({"role": "user", "content": LEARN})
        out = self.f.inlet(b)
        self.assertEqual(out["messages"][-1]["content"], LEARN + "\n\n(Reply in Russian.)")
        self.assertEqual(out["messages"][-2]["content"], "как работает DNS?")

    def test_looks_past_her_answers_to_my_turn(self):
        b = body("что такое VLAN?", "VLAN это...", "а trunk?")
        b["messages"].append({"role": "user", "content": LEARN})
        out = self.f.inlet(b)
        self.assertTrue(out["messages"][-1]["content"].endswith("(Reply in Russian.)"))

    def test_my_newest_turn_decides(self):
        b = body("what is DNS?", "DNS is...", "а по-русски?")
        b["messages"].append({"role": "user", "content": LEARN})
        self.assertTrue(self.f.inlet(b)["messages"][-1]["content"].endswith("(Reply in Russian.)"))

    def test_list_content_turn_of_mine(self):
        b = {"messages": [{"role": "user", "content": [{"type": "text", "text": "co to jest?"}]},
                          {"role": "user", "content": LEARN}]}
        self.assertTrue(self.f.inlet(b)["messages"][-1]["content"].endswith("(Reply in Polish.)"))

    def test_odd_turn_of_mine_falls_back(self):
        for mine in (None, 5, [None], [{"type": "text", "text": None}]):
            b = {"messages": [{"role": "user", "content": mine}, None, {"role": "user", "content": LEARN}]}
            out = self.f.inlet(b)
            self.assertTrue(out["messages"][-1]["content"].endswith("(Reply in English.)"), mine)

    def test_mode_turn_alone_falls_back(self):
        b = {"messages": [{"role": "user", "content": LEARN}]}
        self.assertTrue(self.f.inlet(b)["messages"][-1]["content"].endswith("(Reply in English.)"))

    def test_my_own_brackets_still_decide(self):
        b = body("привет", "Привет!", "(just tell me, what is DNS?)")
        self.assertTrue(self.f.inlet(b)["messages"][-1]["content"].endswith("(Reply in English.)"))

    def test_every_julz_chat_mode_is_recognised(self):
        # A new mode in julz-chat.py must match, or it would decide the language again
        spec = importlib.util.spec_from_file_location("julz_chat", ROOT / "julz-chat.py")
        chat = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(chat)
        self.assertTrue(chat.MODES)
        for name, words in chat.MODES.items():
            self.assertTrue(lang.is_mode_turn(words), name)


if __name__ == "__main__":
    unittest.main()
