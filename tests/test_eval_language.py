"""Tests for eval-language.py's judging (202). Nothing reaches Open WebUI: answers are faked.
A reply counts as Russian when most of its letters outside code are Cyrillic: commands, paths
and terms like SSH stay Latin in a Russian answer and must not fail it."""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lang = load("eval_language", "eval-language.py")


class Share(unittest.TestCase):
    def test_russian_prose(self):
        self.assertGreater(lang.cyrillic_share("Порт SSH по умолчанию 22."), 0.5)

    def test_english_prose(self):
        self.assertLess(lang.cyrillic_share("SSH listens on port 22 by default."), 0.5)

    def test_code_block_is_ignored(self):
        text = "Сделай так:\n```\nsudo systemctl restart sshd && journalctl -u sshd -f\n```\n"
        self.assertEqual(lang.cyrillic_share(text), 1.0)

    def test_inline_code_is_ignored(self):
        text = "Открой `/etc/ssh/sshd_config_with_a_long_path` и поменяй порт."
        self.assertEqual(lang.cyrillic_share(text), 1.0)

    def test_no_letters_is_zero(self):
        self.assertEqual(lang.cyrillic_share("```\nls\n```\n22"), 0.0)

    def test_english_with_one_russian_word_is_english(self):
        self.assertFalse(lang.is_russian("Sure, here is the plan for today. Удачи!"))

    def test_russian_with_terms_is_russian(self):
        self.assertTrue(lang.is_russian("Nmap сканирует TCP порты, а UDP медленнее и нужен -sU."))


class RunCase(unittest.TestCase):
    def test_every_try_must_be_russian(self):
        answers = iter(["Это порт 22.", "It is port 22."])
        ok, shares = lang.run_case({"q": "Какой порт у SSH?"}, lambda msgs: next(answers), tries=2)
        self.assertFalse(ok)
        self.assertEqual(len(shares), 2)

    def test_all_russian_passes(self):
        ok, _ = lang.run_case({"q": "Какой порт у SSH?"}, lambda msgs: "Порт 22.", tries=2)
        self.assertTrue(ok)

    def test_history_goes_before_the_question(self):
        seen = []
        case = {"q": "А дальше?", "history": [["user", "Привет"], ["assistant", "Hi there"]]}
        lang.run_case(case, lambda msgs: seen.append(msgs) or "Дальше так.", tries=1)
        self.assertEqual(seen[0], [{"role": "user", "content": "Привет"},
                                   {"role": "assistant", "content": "Hi there"},
                                   {"role": "user", "content": "А дальше?"}])

    def test_mode_reaches_the_ask(self):
        seen = []
        lang.run_case({"q": "Как работает DNS?", "mode": "learn"},
                      lambda msgs, mode=None: seen.append(mode) or "Что ты уже знаешь?", tries=1)
        self.assertEqual(seen, ["learn"])

    def test_modes_are_julz_chats_own(self):
        # The eval must send the words julz-chat sends, not a copy that drifts
        self.assertIn("learn", lang.MODES)
        self.assertIn("Learning mode", lang.MODES["learn"])


if __name__ == "__main__":
    unittest.main()
