"""Which key file each script reads (SECURITY.md 14): the sync jobs use julz-sync's key in
api.env, the evals ask the model as user@ with chat.env, and no file others can read is used."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import owui  # noqa: E402


class KeyFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.f = Path(self.tmp.name) / "x.env"
        self.f.write_text("OTHER=1\nOPENWEBUI_API_KEY= sk-test \n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_the_file_it_is_given(self):
        os.chmod(self.f, 0o600)
        self.assertEqual(owui.load_key(self.f), "sk-test")

    def test_refuses_a_file_others_can_read(self):
        for mode in (0o644, 0o640, 0o604, 0o620):
            os.chmod(self.f, mode)
            with self.assertRaises(SystemExit, msg=oct(mode)):
                owui.load_key(self.f)

    def test_a_file_without_the_key_exits(self):
        self.f.write_text("OTHER=1\n")
        os.chmod(self.f, 0o600)
        with self.assertRaises(SystemExit):
            owui.load_key(self.f)

    def test_two_files_for_two_jobs(self):
        self.assertEqual(owui.ENV_FILE.name, "api.env")
        self.assertEqual(owui.CHAT_ENV_FILE.name, "chat.env")
        self.assertEqual(owui.ENV_FILE.parent, owui.CHAT_ENV_FILE.parent)

    def test_the_evals_ask_as_user_and_the_sync_jobs_as_julz_sync(self):
        # julz-sync has no model grant, user@ cannot write the collections
        for name in ("eval-recall.py", "eval-tool-replies.py"):
            src = (ROOT / name).read_text()
            self.assertIn("load_key(CHAT_ENV_FILE)" if "from owui" in src else "load_key(owui.CHAT_ENV_FILE)", src, name)
        for name in ("sync-knowledge.py", "julz-keep-sync.py"):
            self.assertNotIn("CHAT_ENV_FILE", (ROOT / name).read_text(), name)


if __name__ == "__main__":
    unittest.main()
