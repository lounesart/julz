"""Tests for julz-run.py: the bwrap sandbox around `claude -p` (SECURITY.md threats 24 to 26).
The sandbox tests run real bwrap with a fake claude (a shell script), so no subscription is used.
Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import time
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

    def test_run_caps(self):
        # Threat 28: 30 first runs in any 2 hours (soft, a signed override passes it) and 50
        # runs of any kind (hard). Raised from 5 a day, then 10, on 2026-10-16
        self.assertEqual((gate.MAX_RUNS, gate.HARD_MAX, gate.RUN_WINDOW), (30, 50, 7200))

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
        out = self.runner(self.spec, GOOD)
        report = out.report
        self.assertIsNone(out.need)
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

    def keep_runner(self, manifests):
        return run.make_runner({"julz-sandbox": str(self.project)}, self.work_root,
                               self.binary, TOKEN, timeout=30, manifests=manifests)

    def test_done_writes_keep_manifest(self):
        # The fake writes the token into token.txt and env into probe.txt: both must stay out
        manifests = Path(self.tmp.name) / "manifests"
        self.keep_runner(manifests)(self.spec, GOOD)
        path = manifests / f"{gate.sha256(GOOD)}.json"
        m = json.loads(path.read_text())
        self.assertEqual(m["task"], gate.sha256(GOOD))
        self.assertIn("hello.txt", [f["path"] for f in m["keep"]])
        rejected = {f["path"]: f["reason"] for f in m["rejected"]}
        self.assertIn("token.txt", rejected)
        self.assertIn("probe.txt", rejected)
        self.assertNotIn("README.md", rejected)  # unchanged, mine
        self.assertNotIn(TOKEN, path.read_text())
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_need_writes_no_manifest(self):
        manifests = Path(self.tmp.name) / "manifests"
        self.fake_result("stopped\nneed: install python-requests\nwhy: import fails")
        self.keep_runner(manifests)(self.spec, GOOD)
        self.assertFalse(manifests.exists() and any(manifests.iterdir()))

    def test_manifest_failure_keeps_the_run(self):
        blocked = Path(self.tmp.name) / "manifests"
        blocked.write_text("a file where the folder should be\n")
        out = self.keep_runner(blocked)(self.spec, GOOD)
        self.assertIn("made hello.txt", out.report)

    def fake_result(self, result):
        # A quoted heredoc passes the JSON through the shell untouched
        self.binary.write_text("#!/bin/sh\ncat > /work/prompt.txt\ncat <<'EOF'\n"
                               + json.dumps({"is_error": False, "result": result})
                               + "\nEOF\n")

    def test_prompt_explains_need_block(self):
        self.runner(self.spec, GOOD)
        prompt = (self.work() / "prompt.txt").read_text()
        self.assertIn("need: <what the owner must do", prompt)

    def test_need_block_parsed(self):
        self.fake_result("stopped\nneed: install python-requests\nwhy: import fails")
        out = self.runner(self.spec, GOOD)
        self.assertEqual(out.need, {"need": "install python-requests", "why": "import fails"})

    def test_odd_need_block_fails_run(self):
        self.fake_result("need: sudo rm -rf /\nwhy: cleanup\nand then some more text")
        with self.assertRaises(gate.SpecError):
            self.runner(self.spec, GOOD)

    def continuation(self, **extra):
        return {**self.spec, "kind": "continue", "root": gate.sha256(GOOD), "step": 2,
                "need": "install python-requests", "why": "import fails",
                "previous_report": "I stopped before hello2.txt", **extra}

    def test_continuation_reuses_work_copy(self):
        self.runner(self.spec, GOOD)
        (self.work() / "from-run-1.txt").write_text("kept")
        cont_text = "continue: x"  # only its hash names the stderr file
        out = self.runner(self.continuation(), cont_text)
        self.assertEqual((self.work() / "from-run-1.txt").read_text(), "kept")
        prompt = (self.work() / "prompt.txt").read_text()
        self.assertIn("Last time you stopped and asked the owner: install python-requests", prompt)
        self.assertIn("I stopped before hello2.txt", prompt)
        self.assertIn("step 2 of task", out.report)
        self.assertEqual(sorted(p.name for p in self.work_root.iterdir() if p.is_dir()),
                         [gate.sha256(GOOD)])

    def test_stop_kills_everything_in_the_sandbox(self):
        # Threat 48: after a stop nothing may keep working in the copy. The fake ticks into
        # a file from a background child, which must die with bwrap too
        self.binary.write_text("#!/bin/sh\ncat > /dev/null\n"
                               "( while true; do echo t >> /work/ticks; sleep 0.2; done ) &\n"
                               "while true; do echo t >> /work/ticks; sleep 0.2; done\n")
        start = time.monotonic()
        runner = run.make_runner({"julz-sandbox": str(self.project)}, self.work_root,
                                 self.binary, TOKEN, timeout=30,
                                 stop_check=lambda d: time.monotonic() - start > 1.5)
        with self.assertRaises(gate.RunStopped):
            runner(self.spec, GOOD)
        self.assertLess(time.monotonic() - start, 10)
        ticks = (self.work() / "ticks").read_text().count("t")
        self.assertGreater(ticks, 3)
        time.sleep(1)
        self.assertEqual((self.work() / "ticks").read_text().count("t"), ticks)

    def test_stop_asked_for_this_run_only(self):
        seen = []
        runner = run.make_runner({"julz-sandbox": str(self.project)}, self.work_root,
                                 self.binary, TOKEN, timeout=30,
                                 stop_check=lambda d: seen.append(d) or False)
        self.binary.write_text("#!/bin/sh\ncat > /dev/null\nsleep 1.5\n"
                               "printf '{\"is_error\":false,\"result\":\"ok\"}'\n")
        runner(self.spec, GOOD)
        self.assertTrue(seen)
        self.assertEqual(set(seen), {gate.sha256(GOOD)})

    def test_resume_after_stop_says_so(self):
        self.runner(self.spec, GOOD)
        self.runner(self.continuation(resume=True, previous_report="(stopped)"), "continue: y")
        prompt = (self.work() / "prompt.txt").read_text()
        self.assertIn("The owner stopped your last run before it finished", prompt)
        self.assertNotIn("The owner says this is done now", prompt)

    def test_done_answer_keeps_old_wording(self):
        self.runner(self.spec, GOOD)
        self.runner(self.continuation(answer="done"), "continue: x")
        prompt = (self.work() / "prompt.txt").read_text()
        self.assertIn("The owner says this is done now", prompt)
        self.assertNotIn("<<<owner answer", prompt)

    def test_typed_answer_fed_as_data(self):
        # Threat 51: my typed line sits between markers, and no "done" claim is added
        self.runner(self.spec, GOOD)
        self.runner(self.continuation(answer="use port 8080"), "continue: x")
        prompt = (self.work() / "prompt.txt").read_text()
        self.assertIn("<<<owner answer\nuse port 8080\n>>>owner answer\n", prompt)
        self.assertNotIn("The owner says this is done now", prompt)

    def test_my_note_is_fed_as_data_in_every_prompt(self):
        # Threat 93: the note from the approval sits between markers, labelled as mine
        noted = {**self.spec, "root": gate.sha256(GOOD), "note": "use port 8080"}
        self.runner(noted, GOOD + "note: use port 8080\n")
        prompt = (self.work() / "prompt.txt").read_text()
        self.assertIn("<<<owner note\nuse port 8080\n>>>owner note\n", prompt)
        for resume in (False, True):
            self.runner({**self.continuation(resume=resume, previous_report="r"), "note": "use port 8080"},
                        f"continue: z{resume}")
            prompt = (self.work() / "prompt.txt").read_text()
            self.assertIn("<<<owner note\nuse port 8080\n>>>owner note\n", prompt)

    def test_no_note_no_note_block(self):
        self.runner(self.spec, GOOD)
        self.assertNotIn("owner note", (self.work() / "prompt.txt").read_text())

    def test_typed_answer_after_stop(self):
        self.runner(self.spec, GOOD)
        self.runner(self.continuation(resume=True, previous_report="(stopped)",
                                      answer="skip the tests"), "continue: y")
        prompt = (self.work() / "prompt.txt").read_text()
        self.assertIn("The owner stopped your last run", prompt)
        self.assertIn("<<<owner answer\nskip the tests\n>>>owner answer\n", prompt)

    def test_continuation_without_work_copy_fails(self):
        with self.assertRaises(RuntimeError):
            self.runner(self.continuation(), "continue: x")

    def test_continuation_work_copy_symlink_refused(self):
        elsewhere = Path(self.tmp.name) / "elsewhere"
        elsewhere.mkdir()
        self.work_root.mkdir()
        self.work().symlink_to(elsewhere)
        with self.assertRaises(RuntimeError):
            self.runner(self.continuation(), "continue: x")


if __name__ == "__main__":
    unittest.main()
