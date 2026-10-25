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
        self.assertIn("tools/julz_notes.py changed: ./deploy.py --tools", out)
        self.assertIn("sudo", out)
        self.assertIn("run-webui.sh", out)
        self.commit("run.py", "print('v3')\n")
        self.git("tag", "v3")
        out = self.deploy()
        self.assertNotIn("--tools", out)
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


class FakeOpenWebUI:
    """Open WebUI 0.11.4's tools, functions and auth routes, as deploy.py calls them."""
    def __init__(self, store, password="right"):
        self.store = store  # {"tools/julz_notes": {"name":..., "content":..., "meta":...}}
        self.password = password
        self.calls = []
        self.tokens = set()
        self.mangle = False  # the server stores something other than what was sent

    def __call__(self, method, path, token=None, data=None):
        self.calls.append((method, path, token, data))
        if path == "/api/v1/auths/signin":
            if data["password"] != self.password:
                raise deploy.HttpError(400, "wrong password")
            self.tokens.add("tok")
            return {"token": "tok"}
        if token not in self.tokens:
            raise deploy.HttpError(401, "not signed in")
        if path == "/api/v1/auths/signout":
            self.tokens.discard(token)
            return {"status": True}
        kind, _, tid = path.removeprefix("/api/v1/").partition("/id/")
        tid, _, action = tid.partition("/")
        key = f"{kind}/{tid}"
        if key not in self.store:
            raise deploy.HttpError(404 if kind == "tools" else 401, "not found")
        if method == "GET":
            return {"id": tid, **self.store[key]}
        content = data["content"] + ("#x" if self.mangle else "")
        self.store[key] = {**self.store[key], "name": data["name"], "content": content,
                           "meta": data["meta"]}
        return {"id": tid, **self.store[key]}


class PushToolsTest(unittest.TestCase):
    """deploy.py --tools: plan then apply, from the release, checked by hash (threat 147)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.release = base / "lib" / "releases" / "abc123abc123"
        (self.release / "tools").mkdir(parents=True)
        (self.release / "functions").mkdir()
        (self.release / "tools" / "julz_notes.py").write_text("new notes\n")
        (self.release / "tools" / "notes.fish").write_text("not a tool\n")
        (self.release / "functions" / "julz_saves.py").write_text("saves\n")
        self.lib = base / "lib"
        meta = {"description": "d", "manifest": {"title": "t"}}
        self.owui = FakeOpenWebUI({
            "tools/julz_notes": {"name": "Notes", "content": "old notes\n", "meta": meta,
                                 "access_grants": [{"group": "phone"}]},
            "functions/julz_saves": {"name": "Saves", "content": "saves\n", "meta": meta},
        })
        self.asked = []
        self.answer = True

    def tearDown(self):
        self.tmp.cleanup()

    def confirm(self, name, diff):
        self.asked.append((name, diff))
        return self.answer

    def push(self, password="right"):
        return deploy.push_tools(self.release, self.lib, self.owui, "me@julz.local", password,
                                 self.confirm)

    def updates(self):
        return [c for c in self.owui.calls if c[1].endswith("/update")]

    def test_changed_tool_is_pushed_after_a_yes(self):
        out = self.push()
        self.assertEqual(self.owui.store["tools/julz_notes"]["content"], "new notes\n")
        self.assertEqual([a[0] for a in self.asked], ["tools/julz_notes"])
        self.assertIn("-old notes", self.asked[0][1])
        self.assertIn("+new notes", self.asked[0][1])
        self.assertIn("pushed: tools/julz_notes", out)
        self.assertIn("same: functions/julz_saves", out)

    def test_same_hash_pushes_nothing_and_asks_nothing(self):
        (self.release / "tools" / "julz_notes.py").write_text("old notes\n")
        self.push()
        self.assertEqual(self.updates(), [])
        self.assertEqual(self.asked, [])

    def test_a_no_keeps_the_live_copy(self):
        self.answer = False
        out = self.push()
        self.assertEqual(self.updates(), [])
        self.assertEqual(self.owui.store["tools/julz_notes"]["content"], "old notes\n")
        self.assertIn("kept live: tools/julz_notes", out)

    def test_name_and_meta_go_back_as_they_are_and_grants_are_never_sent(self):
        self.push()
        (_, path, token, data), = self.updates()
        self.assertEqual(path, "/api/v1/tools/id/julz_notes/update")
        self.assertEqual(data["name"], "Notes")
        self.assertEqual(data["meta"], {"description": "d", "manifest": {"title": "t"}})
        self.assertEqual(data["id"], "julz_notes")
        self.assertNotIn("access_grants", data)

    def test_only_python_files_are_tools(self):
        out = self.push()
        self.assertFalse(any(c[1].startswith("/api/v1/tools/id/notes") for c in self.owui.calls))
        self.assertNotIn("tools/notes", out)

    def test_sign_in_without_a_token_is_refused(self):
        def no_token(method, path, token=None, data=None):
            self.owui.calls.append((method, path, token, data))
            return {"id": "u1"} if path == "/api/v1/auths/signin" else self.fail(path)
        with self.assertRaises(deploy.DeployError):
            deploy.push_tools(self.release, self.lib, no_token, "me@julz.local", "right",
                              self.confirm)
        self.assertEqual(len(self.owui.calls), 1)

    def test_a_server_error_stops_instead_of_reading_as_unknown(self):
        real = self.owui.__call__
        def broken(method, path, token=None, data=None):
            if path.startswith("/api/v1/functions/id/"):
                raise deploy.HttpError(500, "boom")
            return real(method, path, token, data)
        with self.assertRaises(deploy.HttpError):
            deploy.push_tools(self.release, self.lib, broken, "me@julz.local", "right",
                              self.confirm)
        self.assertEqual(self.owui.tokens, set())

    def test_unknown_id_is_refused_and_the_rest_goes_on(self):
        (self.release / "tools" / "julz_new.py").write_text("brand new\n")
        (self.release / "functions" / "julz_new2.py").write_text("brand new\n")
        out = self.push()
        self.assertIn("not in Open WebUI: tools/julz_new", out)
        self.assertIn("not in Open WebUI: functions/julz_new2", out)
        self.assertNotIn("tools/julz_new", self.owui.store)
        self.assertEqual(self.owui.store["tools/julz_notes"]["content"], "new notes\n")

    def test_rewritten_import_is_refused_before_sign_in(self):
        for bad in ("from utils.misc import x\n", "from config import y\n",
                    "from apps.z import q\n", "from main import app\n"):
            (self.release / "functions" / "julz_saves.py").write_text(bad)
            self.owui.calls.clear()
            with self.assertRaises(deploy.DeployError):
                self.push()
            self.assertEqual(self.owui.calls, [])

    def test_hash_mismatch_after_the_push_stops_and_signs_out(self):
        self.owui.mangle = True
        with self.assertRaises(deploy.DeployError) as e:
            self.push()
        self.assertIn("does not match", str(e.exception))
        self.assertEqual(self.owui.calls[-1][1], "/api/v1/auths/signout")
        self.assertEqual(self.owui.tokens, set())

    def test_failed_sign_in_is_refused(self):
        with self.assertRaises(deploy.DeployError):
            self.push(password="wrong")
        self.assertEqual(self.updates(), [])

    def test_sign_out_runs_after_an_error(self):
        def boom(name, diff):
            raise KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            deploy.push_tools(self.release, self.lib, self.owui, "me@julz.local", "right", boom)
        self.assertEqual(self.owui.calls[-1][1], "/api/v1/auths/signout")
        self.assertEqual(self.owui.tokens, set())

    def test_push_is_logged_without_the_password_and_not_in_the_deploy_log(self):
        self.push()
        log = (self.lib / "tools.log").read_text()
        entry = json.loads(log.splitlines()[-1])
        self.assertEqual(entry["tool"], "tools/julz_notes")
        self.assertEqual(entry["commit"], "abc123abc123")
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertNotIn("right", log)
        self.assertFalse((self.lib / "deploys.log").exists())

    def test_tools_come_from_the_live_release(self):
        self.assertEqual(deploy.tools_release(self.lib), None)
        deploy.switch(self.lib, self.release)
        self.assertEqual(deploy.tools_release(self.lib), self.release)

    def test_only_localhost(self):
        self.assertTrue(deploy.OWUI.startswith("http://127.0.0.1:"))


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
