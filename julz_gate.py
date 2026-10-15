"""Gate between julz and Claude Code: approve specs by hand, run approved ones once.

Host side only, never mounted into a container. Security model: SECURITY.md threats 21 to 29.
- a spec is untrusted text written by a maybe injected julz; check_spec allows only three
  plain fields, no hidden or control characters (LLM01, CWE-150)
- approval stores the exact bytes I saw under their sha256, outside every container mount;
  the runner rechecks the hash, so a swap after approval is refused (CWE-367)
- each spec runs once: it moves to done/ before the run starts, so a crash never loops
- the report is untrusted too: too big or holding a secret, it goes to quarantine, not Outbox
The runner itself (sandboxed `claude -p`) is passed in, so the tests use a fake.
"""
import fcntl
import hashlib
import json
import os
import re
import stat
import time
import unicodedata
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MAX_SPEC_BYTES = 4096
MAX_REPORT_BYTES = 50_000
MAX_CONFIG_BYTES = 64_000
FIELDS = ("goal", "project", "done_when")
SPEC_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}\.md$")
APPROVED_NAME = re.compile(r"^[0-9a-f]{64}\.md$")
PROJECT_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
FIELD_LINE = re.compile(r"^([a-z_]+):[ \t]*(.*)$")
# Control, format (zero width, bidi), private use, surrogates, unassigned
BAD_CATEGORIES = {"Cc", "Cf", "Co", "Cs", "Cn"}


class GateError(Exception):
    pass


class SpecError(GateError):
    pass


class GateBusy(GateError):
    pass


class Dirs:
    """Where the gate keeps its files. None of these may be mounted into a container,
    except outbox, which julz reads through a read only mount."""

    def __init__(self, base: Path, outbox: Path | None = None):
        base = Path(base)
        self.approved = base / "approved"
        self.done = base / "done"
        self.quarantine = base / "quarantine"
        self.outbox = Path(outbox) if outbox else base / "outbox"
        self.log = base / "runner.log"
        self.lockfile = base / "run.lock"

    def ensure(self):
        for d in (self.approved, self.done, self.quarantine, self.outbox):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)


# ---------- spec checks ----------

def check_spec(text: str, projects: set[str]) -> dict:
    """Parse a spec into its three fields or raise SpecError. Refuses, never cleans up:
    a spec that needs cleaning was written by something I should not trust."""
    if len(text.encode()) > MAX_SPEC_BYTES:
        raise SpecError(f"spec is over {MAX_SPEC_BYTES} bytes")
    for ch in text:
        if ch != "\n" and unicodedata.category(ch) in BAD_CATEGORIES:
            raise SpecError(f"hidden or control character U+{ord(ch):04X}")
    if "<!--" in text:
        raise SpecError("HTML comment in spec")
    spec = {}
    for line in text.split("\n"):
        if not line.strip():
            continue
        m = FIELD_LINE.match(line)
        if not m or m.group(1) not in FIELDS:
            raise SpecError(f"not a known field: {line[:40]!r}")
        key, value = m.group(1), m.group(2).strip()
        if key in spec:
            raise SpecError(f"field {key} given twice")
        if not value:
            raise SpecError(f"field {key} is empty")
        spec[key] = value
    missing = [f for f in FIELDS if f not in spec]
    if missing:
        raise SpecError(f"missing fields: {', '.join(missing)}")
    if not PROJECT_NAME.match(spec["project"]) or spec["project"] not in projects:
        raise SpecError(f"project not in the allowlist: {spec['project'][:40]!r}")
    return {f: spec[f] for f in FIELDS}


def read_private_file(path: Path, deny_mask: int) -> bytes:
    """Read a config or secret file that must be mine, not a symlink, and have none of the
    deny_mask permission bits (0o022: nobody else writes it, 0o077: nobody else reads it)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as e:
        raise GateError(f"cannot open {path}: {e.strerror}") from None
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise GateError(f"{path} is not a regular file")
        if st.st_uid != os.getuid():
            raise GateError(f"{path} is not owned by me")
        if st.st_mode & deny_mask:
            raise GateError(f"{path} is open to group or others: chmod 600 it")
        data = f.read(MAX_CONFIG_BYTES + 1)
    if len(data) > MAX_CONFIG_BYTES:
        raise GateError(f"{path} is over {MAX_CONFIG_BYTES} bytes")
    return data


def load_projects(path: Path) -> dict[str, str]:
    """Allowlist of projects Claude may work on, {name: absolute path}. It decides where
    Claude can write, so it must be my own file and not writable by anyone else (A05)."""
    data = read_private_file(path, 0o022)
    try:
        projects = json.loads(data)
    except ValueError:
        raise GateError(f"{path} is not valid JSON") from None
    if not isinstance(projects, dict) or not projects:
        raise GateError(f"{path} must be a non empty object of name: path")
    for name, folder in projects.items():
        if not PROJECT_NAME.match(name):
            raise GateError(f"bad project name: {name[:40]!r}")
        if not isinstance(folder, str) or not os.path.isabs(folder) \
                or os.path.normpath(folder) != folder:
            raise GateError(f"project {name}: path must be absolute and normalized")
    return projects


def read_regular(path: Path, max_bytes: int) -> bytes:
    """Read a regular file without following a symlink, at most max_bytes."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as e:
        raise SpecError(f"cannot open {path.name}: {e.strerror}") from None
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode):
            raise SpecError(f"{path.name} is not a regular file")
        data = f.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise SpecError(f"{path.name} is over {max_bytes} bytes")
    return data


def decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise SpecError("spec is not valid UTF-8") from None


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ---------- approval ----------

def load_spec(path: Path, projects: set[str]) -> tuple[str, dict]:
    """Read and check an inbox spec. The CLI shows me exactly this text."""
    path = Path(path)
    if not SPEC_NAME.match(path.name):
        raise SpecError(f"bad spec file name: {path.name[:70]!r}")
    text = decode(read_regular(path, MAX_SPEC_BYTES))
    return text, check_spec(text, projects)


def store_approved(text: str, dirs: Dirs, projects: set[str]) -> str:
    """Store the text I approved under its hash. Call only after I said yes."""
    check_spec(text, projects)
    digest = sha256(text)
    dirs.ensure()
    if (dirs.done / f"{digest}.md").exists():
        raise SpecError("this exact spec already ran")
    write_new(dirs.approved / f"{digest}.md", text, 0o600, SpecError("already approved"))
    log(dirs, "approve", digest, "ok")
    return digest


def approve(path: Path, dirs: Dirs, projects: set[str]) -> str:
    text, _ = load_spec(path, projects)
    return store_approved(text, dirs, projects)


# ---------- running ----------

@contextmanager
def lock(dirs: Dirs):
    """One runner at a time. flock is released by the kernel even if the runner dies."""
    dirs.lockfile.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(dirs.lockfile, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise GateBusy("another runner is working") from None
        yield
    finally:
        os.close(fd)


def run_next(dirs: Dirs, projects: set[str], runner, secrets: list[str],
             max_per_day: int) -> str | None:
    """Run the oldest valid approved spec. Returns its hash, or None if nothing ran.
    runner(spec, text) returns the report text or raises."""
    try:
        with lock(dirs):
            return _run_next(dirs, projects, runner, secrets, max_per_day)
    except GateBusy:
        return None


def _run_next(dirs, projects, runner, secrets, max_per_day):
    dirs.ensure()
    if runs_today(dirs) >= max_per_day:
        return None
    candidates = [p for p in dirs.approved.iterdir() if APPROVED_NAME.match(p.name)]
    candidates.sort(key=lambda p: p.lstat().st_mtime)
    for path in candidates:
        digest = path.name[:-3]
        if (dirs.done / path.name).exists():
            quarantine_spec(dirs, path, digest, "already ran")
            continue
        try:
            text = decode(read_regular(path, MAX_SPEC_BYTES))
            if sha256(text) != digest:
                raise SpecError("hash does not match the approved text")
            spec = check_spec(text, projects)
        except SpecError as e:
            quarantine_spec(dirs, path, digest, str(e))
            continue
        # Moved before the run: if anything below crashes, this spec never runs again
        os.replace(path, dirs.done / path.name)
        # Logged before the run, so a run that gets killed still leaves a trace (threat 29)
        log(dirs, "start", digest, "ok")
        status, reason, report_hash = deliver(dirs, digest, spec, text, runner, secrets)
        log(dirs, "run", digest, status, reason, report_hash)
        return digest
    return None


def deliver(dirs, digest, spec, text, runner, secrets) -> tuple[str, str, str]:
    try:
        report = runner(spec, text)
    except Exception as e:
        # Only the exception type: its message could quote the token or the report
        return "failed", type(e).__name__, ""
    if not isinstance(report, str):
        return "failed", "runner returned no text", ""
    report_hash = sha256(report)
    secrets = [s for s in secrets if s]
    if any(s in report for s in secrets):
        reason = "secret in report"
    elif len(report.encode()) > MAX_REPORT_BYTES:
        reason = f"report over {MAX_REPORT_BYTES} bytes"
    else:
        write_new(dirs.outbox / f"{digest}.md", report, 0o644, GateError("report exists"))
        return "ok", "", report_hash
    write_new(dirs.quarantine / f"{digest}.md", report, 0o600, GateError("report exists"))
    return "quarantined", reason, report_hash


def quarantine_spec(dirs: Dirs, path: Path, digest: str, reason: str):
    # rename moves a symlink itself, never its target
    os.replace(path, dirs.quarantine / f"{path.name}.{time.time_ns()}.refused")
    log(dirs, "refuse", digest, "refused", reason)


def runs_today(dirs: Dirs) -> int:
    if not dirs.log.exists():
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    count = 0
    for line in dirs.log.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("action") == "run" and str(entry.get("time", "")).startswith(today):
            count += 1
    return count


# ---------- files and log ----------

def write_new(path: Path, text: str, mode: int, exists_error: Exception):
    """Create a new file, never overwrite, never follow a planted symlink."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     mode)
    except FileExistsError:
        raise exists_error from None
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def log(dirs: Dirs, action: str, digest: str, status: str, reason: str = "",
        report_hash: str = ""):
    """Host side action log (threat 29). Never holds report text; a refusal reason may
    quote up to 40 characters of a spec line."""
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "action": action, "sha256": digest, "status": status}
    if reason:
        entry["reason"] = reason
    if report_hash:
        entry["report_sha256"] = report_hash
    dirs.log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(dirs.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
