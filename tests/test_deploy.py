"""deploy.py: units run a tested, committed release, never the working tree (SECURITY.md 79).
A throwaway git repo; systemctl and the test run are fakes."""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("deploy", ROOT / "deploy.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)

GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


class DeployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.old_env = {k: os.environ.get(k) for k in GIT_ENV}
        os.environ.update(GIT_ENV)
        self.repo = base / "repo"
        (self.repo / "systemd").mkdir(parents=True)
        (self.repo / "tools").mkdir()
        (self.repo / "run.py").write_text("print('v1')\n")
        (self.repo / "systemd" / "julz-a.service").write_text("[Service]\nExecStart=a\n")
        (self.repo / "tools" / "julz_notes.py").write_text("v1\n")
        self.git("init", "-q", "-b", "main")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "one")
        self.git("tag", "v1")
        self.lib = base / "lib"
        self.units = base / "units"
        self.units.mkdir()
        self.calls = []
        self.tests_pass = True

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    def git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(self.repo), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def run_tests(self, release: Path) -> bool:
        self.calls.append(("tests", release.name))
        return self.tests_pass

    def systemctl(self, *args):
        self.calls.append(("systemctl", *args))

    def deploy(self, **kw):
        return deploy.deploy(self.repo, self.lib, self.units, run_tests=self.run_tests,
                             systemctl=self.systemctl, **kw)

    def commit(self, path, text, message="change"):
        p = self.repo / path
        p.write_text(text)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def live(self) -> str:
        return (self.lib / "current" / "run.py").read_text()

    # ----- the normal path -----

    def test_tagged_main_goes_live(self):
        out = self.deploy()
        head = self.git("rev-parse", "HEAD")
        self.assertEqual(os.readlink(self.lib / "current"), str(self.lib / "releases" / head[:12]))
        self.assertEqual(self.live(), "print('v1')\n")
        self.assertEqual((self.units / "julz-a.service").read_text(), "[Service]\nExecStart=a\n")
        self.assertIn(("systemctl", "--user", "daemon-reload"), self.calls)
        self.assertIn(("systemctl", "--user", "try-restart", "julz-approver.service"), self.calls)
        entry = json.loads((self.lib / "deploys.log").read_text().splitlines()[-1])
        self.assertEqual((entry["commit"], entry["label"]), (head, "v1"))
        self.assertIn("v1", out)

    def test_release_holds_only_committed_files(self):
        (self.repo / "secret.env").write_text("KEY=1\n")  # untracked, like a key file
        with self.assertRaises(deploy.DeployError):  # dirty tree is refused first
            self.deploy()
        os.remove(self.repo / "secret.env")
        self.deploy()
        self.assertFalse((self.lib / "current" / "secret.env").exists())
        self.assertFalse((self.lib / "current" / ".git").exists())

    # ----- refusals -----

    def test_refusals_change_nothing(self):
        self.deploy()
        before = os.readlink(self.lib / "current")
        (self.repo / "run.py").write_text("print('dirty')\n")
        with self.assertRaisesRegex(deploy.DeployError, "uncommitted"):
            self.deploy()
        with self.assertRaisesRegex(deploy.DeployError, "uncommitted"):
            self.deploy(dev=True)  # --dev never takes unreviewed bytes
        self.git("checkout", "-q", "--", "run.py")
        self.commit("run.py", "print('untagged')\n")
        with self.assertRaisesRegex(deploy.DeployError, "tag"):
            self.deploy()
        self.git("checkout", "-q", "-b", "feat/x")
        self.git("tag", "v-branch")
        with self.assertRaisesRegex(deploy.DeployError, "main"):
            self.deploy()
        self.assertEqual(os.readlink(self.lib / "current"), before)

    def test_failing_tests_stop_the_switch(self):
        self.deploy()
        before = os.readlink(self.lib / "current")
        self.commit("run.py", "print('v2')\n")
        self.git("tag", "v2")
        self.tests_pass = False
        with self.assertRaisesRegex(deploy.DeployError, "tests"):
            self.deploy()
        self.assertEqual(os.readlink(self.lib / "current"), before)
        self.assertEqual(self.live(), "print('v1')\n")
        self.assertEqual(sorted(p.name for p in (self.lib / "releases").iterdir()),
                         [Path(before).name])  # the failed export is gone

    # ----- --dev -----

    def test_dev_deploys_a_clean_untagged_branch(self):
        self.git("checkout", "-q", "-b", "feat/x")
        self.commit("run.py", "print('dev')\n")
        out = self.deploy(dev=True)
        self.assertEqual(self.live(), "print('dev')\n")
        entry = json.loads((self.lib / "deploys.log").read_text().splitlines()[-1])
        self.assertEqual(entry["label"], "dev")
        self.assertIn("dev", out)

    # ----- rollback -----

    def test_rollback_goes_to_the_release_before(self):
        self.deploy()
        self.commit("run.py", "print('v2')\n")
        self.commit("systemd/julz-a.service", "[Service]\nExecStart=a2\n")
        self.git("tag", "v2")
        self.deploy()
        self.assertEqual(self.live(), "print('v2')\n")
        deploy.rollback(self.lib, self.units, systemctl=self.systemctl)
        self.assertEqual(self.live(), "print('v1')\n")
        self.assertEqual((self.units / "julz-a.service").read_text(), "[Service]\nExecStart=a\n")
        with self.assertRaisesRegex(deploy.DeployError, "nothing"):
            deploy.rollback(self.lib, self.units, systemctl=self.systemctl)  # one step only

    # ----- what deploy cannot do itself -----

    def test_reminds_what_needs_me(self):
        self.deploy()
        self.commit("tools/julz_notes.py", "v2\n")
        self.commit("run-webui.sh", "docker run\n")
        self.git("tag", "v2")
        out = self.deploy()
        self.assertIn("paste tools/julz_notes.py", out)
        self.assertIn("sudo", out)
        self.assertIn("run-webui.sh", out)
        self.commit("run.py", "print('v3')\n")
        self.git("tag", "v3")
        out = self.deploy()
        self.assertNotIn("paste", out)
        self.assertNotIn("sudo", out)

    def test_new_unit_files_are_named_not_enabled(self):
        self.deploy()
        self.commit("systemd/julz-b.timer", "[Timer]\n")
        self.git("tag", "v2")
        out = self.deploy()
        self.assertTrue((self.units / "julz-b.timer").exists())
        self.assertIn("julz-b.timer", out)
        self.assertFalse([c for c in self.calls if "enable" in c])

    def test_old_releases_are_pruned_but_not_live_or_previous(self):
        for i in range(2, 9):
            self.commit("run.py", f"print('v{i}')\n")
            self.git("tag", f"v{i}")
            self.deploy()
        releases = list((self.lib / "releases").iterdir())
        self.assertEqual(len(releases), deploy.KEEP_RELEASES)
        deploy.rollback(self.lib, self.units, systemctl=self.systemctl)
        self.assertEqual(self.live(), "print('v7')\n")

    def test_prune_never_removes_the_live_release(self):
        # after a rollback or a redeploy of an old commit, the live release can be the oldest
        for i in range(2, 7):
            self.commit("run.py", f"print('v{i}')\n")
            self.git("tag", f"v{i}")
            self.deploy()
        releases = self.lib / "releases"
        oldest = min(releases.iterdir(), key=lambda p: p.stat().st_mtime)
        deploy.switch(self.lib, oldest)
        os.utime(oldest, (1, 1))
        for name in ("aaaaaaaaaaaa", "bbbbbbbbbbbb"):  # newer releases push it past the limit
            (releases / name).mkdir()
        deploy.prune(self.lib)
        self.assertTrue(oldest.is_dir())
        self.assertEqual(deploy.live(self.lib), oldest)
        self.assertEqual(len(list(releases.iterdir())), deploy.KEEP_RELEASES + 1)


class UnitsRunTheReleaseTest(unittest.TestCase):
    """Every unit runs code from the deployed release, never from the working tree."""

    def test_no_unit_points_at_the_repo(self):
        for f in sorted((ROOT / "systemd").glob("julz-*.service")):
            text = f.read_text()
            self.assertNotIn("Projects/products/julz", text, f.name)
            for line in text.splitlines():
                if line.startswith("ExecStart="):
                    self.assertIn("%h/.local/lib/julz/current/", line, f.name)


if __name__ == "__main__":
    unittest.main()


class UninstallListsEveryUnitTest(unittest.TestCase):
    """docs/UNINSTALL.md must stop every unit that can be enabled, and linger (threat 115):
    the list had drifted by five units before this test."""

    def test_every_enabled_unit_is_stopped(self):
        root = Path(__file__).resolve().parent.parent
        text = (root / "docs" / "UNINSTALL.md").read_text()
        stop = text.split("## 1.", 1)[1].split("\n## 2.", 1)[0]
        for unit in sorted((root / "systemd").glob("julz-*")):
            if "[Install]" in unit.read_text():
                with self.subTest(unit=unit.name):
                    self.assertIn(unit.name, stop)
        self.assertIn("loginctl disable-linger", stop)
