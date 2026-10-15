"""Tests for julz-run.py: the bwrap sandbox around `claude -p` (SECURITY.md threats 24 to 26).
The sandbox tests run real bwrap with a fake claude (a shell script), so no subscription is used.
Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOME = Path.home()


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


run = load("julz_run", "julz-run.py")
# The very module julz-run imported, so its GateError is the class we catch
gate = run.gate

# Built at runtime so no token shaped literal sits in the repo for scanners to flag
TOKEN = "sk-ant-oat01-" + "fake_token_for_tests_" * 4
GOOD = ("goal: add hello.txt\n"
        "project: julz-sandbox\n"
        "done_when: hello.txt exists\n")
HAVE_BWRAP = shutil.which("bwrap") is not None


def flag_value(argv, flag):
    return argv[argv.index(flag) + 1]


def bind_pairs(argv):
    pairs = []
    for i, a in enumerate(argv):
        if a in ("--bind", "--ro-bind", "--dev-bind", "--bind-try", "--ro-bind-try"):
            pairs.append((argv[i + 1], argv[i + 2]))
    return pairs


class ArgvTest(unittest.TestCase):
    def setUp(self):
        self.work = HOME / ".local/share/julz/work/abc"
        self.binary = HOME / ".local/share/claude/versions/9.9.9"
        self.argv = run.full_argv(self.work, self.binary)

    def test_namespaces_and_lifetime(self):
        for flag in ("--unshare-all", "--share-net", "--die-with-parent", "--new-session"):
            self.assertIn(flag, self.argv)

    def test_only_work_and_binary_come_from_home(self):
        # Threat 25: nothing else under $HOME (ssh, pocket, vault, configs) is visible
        for src, dst in bind_pairs(self.argv):
            if src.startswith(str(HOME)):
                self.assertIn(src, (str(self.work), str(self.binary)))
            self.assertFalse(dst.startswith(str(HOME)), dst)

    def test_no_runtime_sockets(self):
        # ssh-agent, gpg-agent, dbus, docker live under /run
        for src, _ in bind_pairs(self.argv):
            self.assertFalse(src.startswith(("/run", "/var/run")), src)

    def test_work_is_the_only_writable_bind(self):
        rw = [s for i, a in enumerate(self.argv) if a == "--bind" for s in [self.argv[i + 1]]]
        self.assertEqual(rw, [str(self.work)])

    def test_tool_allowlist(self):
        # Threat 24: no Bash, WebFetch, WebSearch, so no egress of Claude's own
        self.assertEqual(flag_value(self.argv, "--tools"), "Read,Edit,Write,Glob,Grep")
        for flag in ("--restricted", "--strict-mcp-config", "--no-session-persistence",
                     "--disable-slash-commands"):
            self.assertIn(flag, self.argv)
        self.assertEqual(flag_value(self.argv, "--permission-prompts"), "none")

    def test_no_bypass(self):
        joined = " ".join(self.argv)
        self.assertNotIn("dangerously", joined)
        self.assertNotIn("bypassPermissions", joined)

    def test_token_not_in_argv(self):
        # argv is world readable in /proc/<pid>/cmdline, environ is not (CWE-214)
        self.assertNotIn(TOKEN, " ".join(run.full_argv(self.work, self.binary)))

    def test_env_is_minimal(self):
        os.environ["SSH_AUTH_SOCK"] = "/run/user/1000/ssh-agent.socket"
        try:
            env = run.sandbox_env(TOKEN)
        finally:
            del os.environ["SSH_AUTH_SOCK"]
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], TOKEN)
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertLessEqual(set(env), run.ENV_KEYS)


class WorkdirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project = base / "project"
        (self.project / ".git").mkdir(parents=True)
        (self.project / ".git" / "config").write_text("[core]\n")
        (self.project / "sub").mkdir()
        (self.project / "a.txt").write_text("a\n")
        (self.project / "sub" / "b.txt").write_text("b\n")
        self.outside = base / "outside.txt"
        self.outside.write_text("secret\n")
        (self.project / "link").symlink_to(self.outside)
        self.work = base / "work"

    def tearDown(self):
        self.tmp.cleanup()

    def test_copy_skips_git(self):
        # A .git in the work copy could carry hooks or fsmonitor that run on MY host later
        run.prepare_workdir(self.project, self.work)
        self.assertTrue((self.work / "a.txt").exists())
        self.assertTrue((self.work / "sub" / "b.txt").exists())
        self.assertFalse((self.work / ".git").exists())

    def test_symlink_copied_as_link_not_content(self):
        run.prepare_workdir(self.project, self.work)
        self.assertTrue((self.work / "link").is_symlink())

    def test_existing_work_dir_refused(self):
        self.work.mkdir()
        with self.assertRaises(FileExistsError):
            run.prepare_workdir(self.project, self.work)

    def test_changed_files(self):
        run.prepare_workdir(self.project, self.work)
        (self.work / "a.txt").write_text("changed\n")
        (self.work / "c.txt").write_text("new\n")
        (self.work / "sub" / "b.txt").unlink()
        self.assertEqual(run.changed_files(self.project, self.work),
                         ["added c.txt", "changed a.txt", "deleted sub/b.txt"])

    def test_odd_names_escaped(self):
        run.prepare_workdir(self.project, self.work)
        (self.work / "x\x1b[2J").write_text("x")
        self.assertNotIn("\x1b", "".join(run.changed_files(self.project, self.work)))


class ParseTest(unittest.TestCase):
    def test_result_text(self):
        out = json.dumps({"type": "result", "is_error": False, "result": "done"})
        self.assertEqual(run.parse_result(out), "done")

    def test_error_result_raises(self):
        out = json.dumps({"type": "result", "is_error": True, "result": "auth failed"})
        with self.assertRaises(RuntimeError):
            run.parse_result(out)

    def test_garbage_raises(self):
        with self.assertRaises(RuntimeError):
            run.parse_result("not json")


class TokenFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "claude-token.env"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, text, mode=0o600):
        self.path.write_text(text)
        os.chmod(self.path, mode)

    def test_reads_token(self):
        self.write(f"CLAUDE_CODE_OAUTH_TOKEN={TOKEN}\n")
        self.assertEqual(run.read_token(self.path), TOKEN)

    def test_group_readable_refused(self):
        self.write(f"CLAUDE_CODE_OAUTH_TOKEN={TOKEN}\n", 0o640)
        with self.assertRaises(gate.GateError):
            run.read_token(self.path)

    def test_malformed_token_refused(self):
        # A pasted browser code or a token cut at a line wrap fails here, before a spec is spent
        for bad in ("1kJwARwmna1nt#abc", "sk-ant-oat01-short", "sk-ant-oat01-" + "a" * 40 + "!"):
            self.write(f"CLAUDE_CODE_OAUTH_TOKEN={bad}\n")
            with self.assertRaises(gate.GateError):
                run.read_token(self.path)

    def test_missing_token_refused(self):
        self.write("OTHER=1\n")
        with self.assertRaises(gate.GateError):
            run.read_token(self.path)


FAKE_CLAUDE = r"""#!/bin/sh
# Fake claude: does the task, then tries everything a hijacked one would
cat > /work/prompt.txt
printf '%s\n' "$@" > /work/argv.txt
printf '%s\n' "$CLAUDE_CODE_OAUTH_TOKEN" > /work/token.txt
echo hello > /work/hello.txt
{
  ls -a "$HOME_ON_HOST"/.ssh 2>&1
  ls /run/user 2>&1
  ls "$HOME_ON_HOST"/Documents 2>&1
  touch /usr/pwned 2>&1
  env
} > /work/probe.txt
printf '{"type":"result","is_error":false,"result":"made hello.txt"}'
"""


@unittest.skipUnless(HAVE_BWRAP, "bwrap not installed")
class SandboxTest(unittest.TestCase):
    """Full runner through real bwrap, with the fake claude above."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project = base / "project"
        self.project.mkdir()
        (self.project / "README.md").write_text("# sandbox\n")
        self.binary = base / "fake-claude"
        # The fake learns the host home only through the prompt env, to probe it
        self.binary.write_text(FAKE_CLAUDE.replace("$HOME_ON_HOST", str(HOME)))
        self.binary.chmod(0o700)
        self.work_root = base / "work"
        self.runner = run.make_runner({"julz-sandbox": str(self.project)}, self.work_root,
                                      self.binary, TOKEN, timeout=30)
        self.spec = gate.check_spec(GOOD, {"julz-sandbox"})

    def tearDown(self):
        self.tmp.cleanup()

    def work(self):
        return self.work_root / gate.sha256(GOOD)

    def test_report_has_result_and_changes(self):
        report = self.runner(self.spec, GOOD)
        self.assertIn("made hello.txt", report)
        self.assertIn("added hello.txt", report)
        self.assertEqual((self.work() / "hello.txt").read_text(), "hello\n")

    def test_project_itself_untouched(self):
        self.runner(self.spec, GOOD)
        self.assertEqual(sorted(p.name for p in self.project.iterdir()), ["README.md"])

    def test_prompt_comes_through_stdin(self):
        self.runner(self.spec, GOOD)
        prompt = (self.work() / "prompt.txt").read_text()
        self.assertIn("add hello.txt", prompt)
        self.assertIn("hello.txt exists", prompt)

    def test_probes_find_nothing(self):
        self.runner(self.spec, GOOD)
        probe = (self.work() / "probe.txt").read_text()
        self.assertIn(f"ls: cannot access '{HOME}/.ssh'", probe)
        self.assertIn("ls: cannot access '/run/user'", probe)
        self.assertIn(f"ls: cannot access '{HOME}/Documents'", probe)
        self.assertIn("touch: cannot touch '/usr/pwned'", probe)
        self.assertNotIn("SSH_AUTH_SOCK", probe)
        self.assertNotIn("DBUS_SESSION_BUS_ADDRESS", probe)

    def test_timeout_kills_run(self):
        self.binary.write_text("#!/bin/sh\nsleep 60\n")
        runner = run.make_runner({"julz-sandbox": str(self.project)}, self.work_root,
                                 self.binary, TOKEN, timeout=1)
        with self.assertRaises(subprocess.TimeoutExpired):
            runner(self.spec, GOOD)

    def test_token_in_env_not_argv(self):
        self.runner(self.spec, GOOD)
        self.assertEqual((self.work() / "token.txt").read_text().strip(), TOKEN)
        self.assertNotIn(TOKEN, (self.work() / "argv.txt").read_text())

    def test_failed_exit_raises(self):
        # Valid output but a failing exit code still counts as failed
        self.binary.write_text("#!/bin/sh\nprintf '{\"is_error\":false,\"result\":\"ok\"}'\nexit 3\n")
        with self.assertRaises(RuntimeError):
            self.runner(self.spec, GOOD)


if __name__ == "__main__":
    unittest.main()
