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


if __name__ == "__main__":
    unittest.main()
