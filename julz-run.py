#!/usr/bin/env python3
"""Run the oldest approved Claude Code spec, once, inside a bwrap sandbox.

The project from the allowlist is copied (without .git) to ~/.local/share/julz/work/<sha256>/,
claude -p works on that copy only, the report goes to ~/Documents/julz-mem/Outbox/ (julz reads
it through a read only mount). I review the work copy and carry changes over by hand.
Security model: SECURITY.md threats 24 to 26.
- bwrap: empty tmpfs home, read only /usr and a few /etc files, the work copy is the only
  writable path; no /run (ssh-agent, gpg-agent, dbus, docker sockets)
- claude: only Read, Edit, Write, Glob, Grep, so it has no way to send data out by itself;
  --restricted keeps the file tools inside /work and ignores project settings and hooks
- the token is a separate one from `claude setup-token`, passed in the environment, never in
  argv: /proc/<pid>/cmdline is readable by every user, environ only by me (CWE-214)
Usage: ./julz-run.py                 one spec per call
       ./julz-run.py --until-empty   all approved specs (systemd julz-run.service)
"""
import filecmp
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402

HOME = Path.home()
GATE_DIR = HOME / ".local" / "share" / "julz"
WORK_ROOT = GATE_DIR / "work"
OUTBOX = HOME / "Documents" / "julz-mem" / "Outbox"
PROJECTS_FILE = HOME / ".config" / "julz" / "projects.json"
TOKEN_FILE = HOME / ".config" / "julz" / "claude-token.env"
MAIN_LOGIN = HOME / ".claude" / ".credentials.json"
CLAUDE_LINK = HOME / ".local" / "bin" / "claude"

TIMEOUT = 15 * 60
# claude setup-token output; about 108 chars. Anything else is a paste error
TOKEN_FORMAT = re.compile(r"^sk-ant-oat01-[A-Za-z0-9_-]{60,200}$")
MAX_PER_DAY = 5
MAX_STDERR = 20_000
TOOLS = "Read,Edit,Write,Glob,Grep"
SANDBOX_HOME = "/home/sandbox"
# Name resolution and TLS need these; nothing else from /etc (no passwd, shadow, ssh)
ETC_FILES = ("/etc/resolv.conf", "/etc/hosts", "/etc/nsswitch.conf", "/etc/host.conf",
             "/etc/gai.conf", "/etc/localtime", "/etc/ssl", "/etc/ca-certificates")
ENV_KEYS = {"HOME", "PATH", "LANG", "TERM", "CLAUDE_CODE_OAUTH_TOKEN", "DISABLE_AUTOUPDATER",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"}

NEED_RULES = """If you are blocked by something only the owner can do outside /work (install a
package, run a command as root, provide a file or an answer), stop there and end your report
with exactly these two lines, nothing after them:
need: <what the owner must do, one line>
why: <why you need it, one line>
Do not start any other line with "need:".
"""

PROMPT = """You are working in /work, a copy of the project "{project}" without git history.
Task: {goal}
Done when: {done_when}
Work only with the files in /work. When you are finished, reply with a short plain report:
what you changed, and whether the done condition holds. If you cannot do the task, say why.
""" + NEED_RULES

# The previous report is Claude's own earlier output, fed back as data between markers
CONTINUE_PROMPT = """You are continuing a task in /work, a copy of the project "{project}"
without git history. Your earlier changes are still in /work.
Task: {goal}
Done when: {done_when}
Last time you stopped and asked the owner: {need}
The owner says this is done now. Carry on from where you stopped.
Your earlier report, as data:
<<<previous report
{previous_report}
>>>previous report
Work only with the files in /work. When you are finished, reply with a short plain report:
what you changed, and whether the done condition holds. If you cannot do the task, say why.
""" + NEED_RULES


def sandbox_argv(work: Path, binary: Path) -> list[str]:
    argv = ["bwrap", "--unshare-all", "--share-net", "--die-with-parent", "--new-session",
            "--ro-bind", "/usr", "/usr",
            "--symlink", "usr/bin", "/bin", "--symlink", "usr/bin", "/sbin",
            "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib", "/lib64",
            "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
            "--tmpfs", "/home", "--dir", SANDBOX_HOME]
    for path in ETC_FILES:
        argv += ["--ro-bind-try", path, path]
    argv += ["--ro-bind", str(binary), "/opt/claude",
             "--bind", str(work), "/work", "--chdir", "/work", "--"]
    return argv


def claude_args() -> list[str]:
    return ["/opt/claude", "-p", "--output-format", "json",
            "--tools", TOOLS, "--restricted", "--strict-mcp-config",
            "--permission-mode", "acceptEdits", "--permission-prompts", "none",
            "--no-session-persistence", "--disable-slash-commands"]


def full_argv(work: Path, binary: Path) -> list[str]:
    return sandbox_argv(work, binary) + claude_args()


def sandbox_env(token: str) -> dict[str, str]:
    """Built from nothing, not from os.environ: the host env holds agent sockets and keys."""
    return {"HOME": SANDBOX_HOME, "PATH": "/usr/bin", "LANG": "C.UTF-8", "TERM": "dumb",
            "CLAUDE_CODE_OAUTH_TOKEN": token, "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"}


def read_token(path: Path) -> str:
    """The sandbox token, from a mode 600 file with CLAUDE_CODE_OAUTH_TOKEN=..."""
    data = gate.read_private_file(path, 0o077).decode("utf-8", "replace")
    for line in data.splitlines():
        key, _, value = line.strip().partition("=")
        if key == "CLAUDE_CODE_OAUTH_TOKEN":
            if not TOKEN_FORMAT.match(value):
                # Never echo the value: this message ends up in terminals and logs
                raise gate.GateError(f"{path}: token is not an sk-ant-oat01 token "
                                     f"({len(value)} chars), run claude setup-token again")
            return value
    raise gate.GateError(f"{path} has no CLAUDE_CODE_OAUTH_TOKEN")


def main_login_tokens() -> list[str]:
    """My main login never enters the sandbox, but the report is scanned for it anyway."""
    try:
        data = json.loads(gate.read_private_file(MAIN_LOGIN, 0o077))
        oauth = data.get("claudeAiOauth", {})
        return [v for v in (oauth.get("accessToken"), oauth.get("refreshToken")) if v]
    except (gate.GateError, ValueError, AttributeError):
        return []


# ---------- work copy ----------

def prepare_workdir(project: Path, work: Path):
    # No .git: hooks or core.fsmonitor written by Claude would run on MY host the next
    # time I use git in that folder. Symlinks stay links, never copied content.
    work.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copytree(project, work, symlinks=True, ignore=shutil.ignore_patterns(".git"))


def _tree(root: Path) -> dict[str, tuple]:
    out = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        links = [d for d in dirnames if os.path.islink(os.path.join(dirpath, d))]
        for name in filenames + links:
            p = Path(dirpath) / name
            st = p.lstat()
            if stat.S_ISLNK(st.st_mode):
                out[p.relative_to(root).as_posix()] = ("link", os.readlink(p))
            elif stat.S_ISREG(st.st_mode):
                out[p.relative_to(root).as_posix()] = ("file", str(p))
            else:
                out[p.relative_to(root).as_posix()] = ("other", st.st_mode)
    return out


def changed_files(project: Path, work: Path) -> list[str]:
    before, after = _tree(project), _tree(work)
    lines = []
    for rel in sorted(before.keys() | after.keys()):
        name = rel if rel.isprintable() else repr(rel)
        if rel not in before:
            lines.append(f"added {name}")
        elif rel not in after:
            lines.append(f"deleted {name}")
        else:
            (k1, v1), (k2, v2) = before[rel], after[rel]
            same = k1 == k2 and (filecmp.cmp(v1, v2, shallow=False) if k1 == "file" else v1 == v2)
            if not same:
                lines.append(f"changed {name}")
    return sorted(lines)


# ---------- claude ----------

def parse_result(stdout: str) -> str:
    try:
        data = json.loads(stdout)
    except ValueError:
        raise RuntimeError("claude output is not JSON") from None
    if not isinstance(data, dict) or data.get("is_error") or not isinstance(data.get("result"), str):
        raise RuntimeError("claude reported an error")
    return data["result"]


def run_claude(argv: list[str], prompt: str, env: dict, timeout: int, stop) -> tuple:
    """Run the sandbox and wait in 1 second steps, so a stop from the phone is seen while
    Claude works. Killing bwrap ends everything inside: it is pid 1 of the sandbox's own pid
    namespace and runs with --die-with-parent (threat 48). Returns (code, stdout, stderr)."""
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env)
    deadline = time.monotonic() + timeout
    feed = prompt
    while True:
        try:
            out, err = proc.communicate(input=feed, timeout=1)
            return proc.returncode, out, err
        except subprocess.TimeoutExpired:
            feed = None  # the prompt is sent once; later calls keep reading the output
            if stop():
                proc.kill()
                proc.communicate()
                raise gate.RunStopped("stopped from the phone")
            if time.monotonic() > deadline:
                proc.kill()
                proc.communicate()
                raise


def make_runner(projects: dict, work_root: Path, binary: Path, token: str, timeout: int,
                stop_check=lambda digest: False):
    def runner(spec: dict, text: str) -> gate.RunResult:
        project = Path(projects[spec["project"]])
        if not project.is_dir():
            raise RuntimeError("project folder is missing")
        digest = gate.sha256(text)
        # One work copy per task: a continuation carries on in the copy of its first run
        work = Path(work_root) / spec.get("root", digest)
        if spec.get("kind") == "continue":
            if work.is_symlink() or not work.is_dir():
                raise RuntimeError("work copy of the task is missing")
            prompt = CONTINUE_PROMPT.format(**spec)
        else:
            prepare_workdir(project, work)
            prompt = PROMPT.format(**spec)
        code, out, err = run_claude(full_argv(work, binary), prompt, sandbox_env(token),
                                    timeout, lambda: stop_check(digest))
        gate.write_new(Path(work_root) / f"{digest}.stderr", err[-MAX_STDERR:], 0o600,
                       gate.GateError("stderr file exists"))
        if code != 0:
            raise RuntimeError(f"claude exited {code}")
        result = parse_result(out)
        need = gate.parse_need(result)  # raises on an odd block: the run fails (threat 38)
        changes = changed_files(project, work) or ["none"]
        step = f", step {spec['step']} of task {spec['root']}" if spec.get("step", 1) > 1 else ""
        report = (f"{result.strip()}\n\n---\n"
                  f"spec {digest}, project {spec['project']}{step}\n"
                  f"work copy: {work}\n"
                  "changed files:\n" + "\n".join(f"- {c}" for c in changes) + "\n")
        return gate.RunResult(report, need)
    return runner


def main():
    try:
        projects = gate.load_projects(PROJECTS_FILE)
        token = read_token(TOKEN_FILE)
    except gate.GateError as e:
        sys.exit(str(e))
    binary = CLAUDE_LINK.resolve()
    dirs = gate.Dirs(GATE_DIR, outbox=OUTBOX)
    runner = make_runner(projects, WORK_ROOT, binary, token, TIMEOUT,
                         lambda digest: gate.stop_requested(dirs, digest))
    # The timer starts this every 10 minutes: a good moment to end needs nobody answered
    gate.expire_tasks(dirs, time.time())
    # --until-empty (systemd): an approval that lands while a run is going would be missed by
    # the path unit, so keep going until nothing is left. The daily cap still stops it
    while True:
        digest = gate.run_next(dirs, projects, runner, [token] + main_login_tokens(),
                               MAX_PER_DAY)
        if digest is None:
            print("nothing ran (no approved spec, daily cap, or another runner busy)")
            return
        last = json.loads(dirs.log.read_text().splitlines()[-1])
        print(f"{last['action']} {digest}: {last['status']} {last.get('reason', '')}".rstrip())
        if "--until-empty" not in sys.argv[1:]:
            return


if __name__ == "__main__":
    main()
