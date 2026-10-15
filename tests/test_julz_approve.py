"""Tests for julz-approve.py and the project allowlist in julz_gate.py (SECURITY.md 21 to 23).
Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = load("julz_gate", "julz_gate.py")
approve_cli = load("julz_approve", "julz-approve.py")

GOOD = ("goal: add a usage line to the README\n"
        "project: julz-sandbox\n"
        "done_when: README has a Usage section\n")
PROJECTS = {"julz-sandbox": "/srv/julz/julz-sandbox"}


class ProjectsConfigTest(unittest.TestCase):
    """The allowlist decides where Claude may write, so it must be mine and not writable by others."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "projects.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data, mode=0o600):
        self.path.write_text(data if isinstance(data, str) else json.dumps(data))
        os.chmod(self.path, mode)

    def refused(self):
        with self.assertRaises(gate.GateError):
            gate.load_projects(self.path)

    def test_good_config_loads(self):
        self.write(PROJECTS)
        self.assertEqual(gate.load_projects(self.path), PROJECTS)

    def test_world_writable_refused(self):
        self.write(PROJECTS, 0o666)
        self.refused()

    def test_group_writable_refused(self):
        self.write(PROJECTS, 0o620)
        self.refused()

    def test_symlink_refused(self):
        real = Path(self.tmp.name) / "real.json"
        real.write_text(json.dumps(PROJECTS))
        os.chmod(real, 0o600)
        self.path.symlink_to(real)
        self.refused()

    def test_bad_name_refused(self):
        self.write({"../x": "/srv/julz/x"})
        self.refused()

    def test_relative_path_refused(self):
        self.write({"julz-sandbox": "Projects/sandbox/julz-sandbox"})
        self.refused()

    def test_dotdot_path_refused(self):
        self.write({"julz-sandbox": "/srv/julz/../../root/.ssh"})
        self.refused()

    def test_not_an_object_refused(self):
        self.write(["julz-sandbox"])
        self.refused()


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.inbox = base / "Inbox" / "claude"
        self.inbox.mkdir(parents=True)
        self.dirs = gate.Dirs(base / "gate")
        self.lines = []
        self.asked = 0

    def tearDown(self):
        self.tmp.cleanup()

    def review(self, answer):
        def ask(prompt):
            self.asked += 1
            return answer
        return approve_cli.review(self.inbox, self.dirs, PROJECTS, ask, self.lines.append)

    def output(self):
        return "\n".join(self.lines)

    def test_yes_approves_and_clears_inbox(self):
        (self.inbox / "fix-readme.md").write_text(GOOD)
        digests = self.review("y")
        self.assertEqual(digests, [gate.sha256(GOOD)])
        self.assertTrue((self.dirs.approved / f"{digests[0]}.md").exists())
        self.assertFalse((self.inbox / "fix-readme.md").exists())

    def test_shows_exact_text_and_hash(self):
        (self.inbox / "fix-readme.md").write_text(GOOD)
        self.review("y")
        self.assertIn(GOOD.strip(), self.output())
        self.assertIn(gate.sha256(GOOD), self.output())

    def test_anything_but_yes_is_no(self):
        (self.inbox / "fix-readme.md").write_text(GOOD)
        for answer in ("", "n", "yes please", "ok", " "):
            self.assertEqual(self.review(answer), [])
        self.assertTrue((self.inbox / "fix-readme.md").exists())
        self.assertFalse(self.dirs.approved.exists() and any(self.dirs.approved.iterdir()))

    def test_refused_spec_is_never_asked(self):
        (self.inbox / "fix-readme.md").write_text(GOOD.replace("add", "a​dd"))
        self.assertEqual(self.review("y"), [])
        self.assertEqual(self.asked, 0)
        self.assertIn("refused", self.output())
        self.assertTrue((self.inbox / "fix-readme.md").exists())

    def test_odd_file_name_printed_escaped(self):
        (self.inbox / "evil\x1b[2J.md").write_text(GOOD)
        self.review("y")
        self.assertNotIn("\x1b", self.output())
        self.assertEqual(self.asked, 0)

    def test_one_question_per_spec(self):
        (self.inbox / "one.md").write_text(GOOD)
        (self.inbox / "two.md").write_text(GOOD.replace("Usage", "Install"))
        self.assertEqual(len(self.review("y")), 2)
        self.assertEqual(self.asked, 2)

    def test_no_terminal_refused(self):
        with self.assertRaises(SystemExit):
            approve_cli.require_tty(io.StringIO("y\n"))


if __name__ == "__main__":
    unittest.main()
