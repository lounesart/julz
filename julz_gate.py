"""Gate between julz and Claude Code: approve specs by hand, run approved ones once.

Host side only, never mounted into a container. Security model: SECURITY.md threats 21 to 29.
- a spec is untrusted text written by a maybe injected julz; check_spec allows only three
  plain fields, no hidden or control characters (LLM01, CWE-150)
- approval stores the exact bytes I saw under their sha256, outside every container mount;
  the runner rechecks the hash, so a swap after approval is refused (CWE-367)
- each spec runs once: it moves to done/ before the run starts, so a crash never loops
- the report is untrusted too: too big or holding a secret, it goes to quarantine, not Outbox
- a blocked run ends with a `need:` block; the task waits on the host for my signed answer,
  then a continuation runs in the same work copy. Max 3 continuations, 24 h to answer,
  task state lives here and never in the report (SECURITY.md threats 37, 38, 40)
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
SPEC_NAME = re.compile(r"\A[a-z0-9][a-z0-9-]{0,60}\.md\Z")
APPROVED_NAME = re.compile(r"\A[0-9a-f]{64}\.md\Z")
PROJECT_NAME = re.compile(r"\A[a-z0-9][a-z0-9-]{0,39}\Z")
FIELD_LINE = re.compile(r"^([a-z_]+):[ \t]*(.*)$")
# Control, format (zero width, bidi), private use, surrogates, unassigned
BAD_CATEGORIES = {"Cc", "Cf", "Co", "Cs", "Cn"}
# \A and \Z, not ^ and $: $ also takes a trailing newline, and most uses are .match (222)
HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
CONT_FIELDS = ("continue", "step", "need_hash", "answer")
MAX_CONTINUATIONS = 3  # steps 2 to 4; a need at step 4 fails the task
NEED_TTL = 24 * 3600
RUN_WINDOW = 2 * 3600  # the run cap counts runs in this rolling window (threat 28)
MAX_RUNS = 30  # soft cap: first runs in any RUN_WINDOW; a signed override passes it (52)
HARD_MAX = 50  # hard ceiling: runs of any kind in any RUN_WINDOW; nothing passes it
LOG_ROTATE_BYTES = 1_000_000  # runner.log past this becomes an archive (threat 53)
LOG_KEEP = 365 * 86400  # archives are the audit trail, kept a year
ARCHIVE_NAME = re.compile(r"\Arunner-\d{8}T\d{6}Z(-\d+)?\.log\Z")
OVERRIDE_FIELDS = ("override", "used")
OVERRIDE_TTL = 3600  # an override marker the runner did not use within this is ignored
MAX_NEED = 200
MAX_WHY = 300
MAX_ANSWER = 300
MAX_NOTE = 280
NOTE = "note"  # my note on an approval: only in approved text the server built (93)
LINK = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://|\bwww\.")
# Threat 50: an answer that looks like a secret is refused. A guard against my own slip
SECRET_PREFIX = re.compile(r"(?<![A-Za-z0-9])(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|sk-|AKIA|xox[abprs]-)")
KEY_RUN = re.compile(r"[A-Za-z0-9_+=-]{32,}")


class GateError(Exception):
    pass


class SpecError(GateError):
    pass


class GateBusy(GateError):
    pass


class RunStopped(GateError):
    """Raised by a runner when I stopped the run from the phone (threats 47, 48)."""


class Dirs:
    """Where the gate keeps its files. None of these may be mounted into a container,
    except outbox, which julz reads through a read only mount."""

    def __init__(self, base: Path, outbox: Path | None = None):
        base = Path(base)
        self.approved = base / "approved"
        self.done = base / "done"
        self.quarantine = base / "quarantine"
        # Temp files sit in the folder they are linked into: in the approver's systemd
        # sandbox every folder is its own bind mount, and a link across mounts fails (EXDEV).
        # The path unit watches approved/ itself, not this subfolder
        self.tmp = self.approved / ".tmp"
        self.tasks = base / "tasks"
        self.outbox = Path(outbox) if outbox else base / "outbox"
        # Its own folder: the units bind the folder, never the file, because a file bind
        # pins the inode and a rotation would leave a unit writing into the archive (53)
        self.logdir = base / "log"
        self.log = self.logdir / "runner.log"
        self.lockfile = base / "run.lock"
        # What runs now and my stop requests. The approver may read and write here, the
        # container never sees it
        self.control = base / "control"
        self.running = self.control / "running.json"
        # What a Keep may copy, written by the runner at done (julz_keep.py, threat 57)
        self.manifests = base / "manifests"
        # Signed Keep markers, one per task. Not in approved/: that wakes the runner
        self.keep = base / "keep"
        # A stamp from julz-keep: kept notes wait for julz-keep-sync (threat 64)
        self.sync = base / "sync"
        # julz-vault's state: the todo snapshot the approver reads to build a tick (113)
        self.vault_state = base / "vault"

    def ensure(self):
        for d in (self.approved, self.done, self.quarantine, self.tmp, self.tasks, self.control,
                  self.outbox, self.logdir, self.manifests, self.keep, self.sync, self.vault_state):
            d.mkdir(mode=0o700, parents=True, exist_ok=True)


# ---------- spec checks ----------

def check_plain(text: str):
    """No hidden or control characters (newline aside), no HTML comments."""
    for ch in text:
        if ch != "\n" and unicodedata.category(ch) in BAD_CATEGORIES:
            raise SpecError(f"hidden or control character U+{ord(ch):04X}")
    if "<!--" in text:
        raise SpecError("HTML comment")


def parse_fields(text: str, fields: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict:
    """Plain `field: value` lines, each known field exactly once, optional ones at most once,
    nothing else."""
    if len(text.encode()) > MAX_SPEC_BYTES:
        raise SpecError(f"spec is over {MAX_SPEC_BYTES} bytes")
    check_plain(text)
    spec = {}
    for line in text.split("\n"):
        if not line.strip():
            continue
        m = FIELD_LINE.match(line)
        if not m or (m.group(1) not in fields and m.group(1) not in optional):
            raise SpecError(f"not a known field: {line[:40]!r}")
        key, value = m.group(1), m.group(2).strip()
        if key in spec:
            raise SpecError(f"field {key} given twice")
        if not value:
            raise SpecError(f"field {key} is empty")
        spec[key] = value
    missing = [f for f in fields if f not in spec]
    if missing:
        raise SpecError(f"missing fields: {', '.join(missing)}")
    return spec


def check_spec(text: str, projects: set[str], approved: bool = False) -> dict:
    """Parse a spec into its three fields or raise SpecError. Refuses, never cleans up:
    a spec that needs cleaning was written by something I should not trust.
    approved: text the server built after my tap, which may end with my note (93). A spec
    in the inbox is julz's text and may never carry one."""
    spec = parse_fields(text, FIELDS, optional=(NOTE,) if approved else ())
    if not PROJECT_NAME.match(spec["project"]) or spec["project"] not in projects:
        raise SpecError(f"project not in the allowlist: {spec['project'][:40]!r}")
    out = {f: spec[f] for f in FIELDS}
    if NOTE in spec:
        if spec_without_note(text) == text:
            raise SpecError("the note must be the last line")
        out[NOTE] = check_note(spec[NOTE])
    return out


def spec_without_note(text: str) -> str:
    """The spec as julz wrote it: approved text minus my note line, if it ends with one."""
    head, sep, last = text.rstrip("\n").rpartition("\n")
    if sep and last.startswith(NOTE + ":") and text.endswith("\n"):
        return head + "\n"
    return text


def approved_text(spec_text: str, note) -> str:
    """What I sign to approve: the spec exactly as shown, plus my note as the last line.
    No note keeps the text, and so its hash, as it always was."""
    if note is None or (isinstance(note, str) and not note.strip()):
        return spec_text
    note = check_note(note)
    parse_fields(spec_text, FIELDS)  # julz's text: a note line of hers is refused here
    if not spec_text.endswith("\n"):
        raise SpecError("spec must end with a newline to take a note")
    return spec_text + f"{NOTE}: {note}\n"


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
    check_spec(text, projects, approved=True)
    # Run once goes by the spec without my note: two notes do not make two runs (93)
    match = same_spec(dirs, text)
    if match:
        raise SpecError(f"this spec {match}")
    return publish(text, dirs)


def same_spec(dirs: Dirs, text: str) -> str | None:
    """'already ran' or 'is already approved' if the same spec, with or without a note,
    sits in done/ or approved/ under another name."""
    core = sha256(spec_without_note(text))
    for folder, said in ((dirs.done, "already ran"), (dirs.approved, "is already approved")):
        if not folder.is_dir():
            continue
        for path in folder.iterdir():
            if not APPROVED_NAME.match(path.name) or path.name == f"{sha256(text)}.md":
                continue
            try:
                other = decode(read_regular(path, MAX_SPEC_BYTES))
            except SpecError:
                continue
            if sha256(spec_without_note(other)) == core:
                return said
    return None


def publish(text: str, dirs: Dirs) -> str:
    """Put checked, approved text into approved/ under its hash, whole, once."""
    digest = sha256(text)
    # Only what it writes: the approver runs this in a sandbox where any other gate folder
    # may be missing on a read only home, and mkdir there fails (EROFS)
    dirs.tmp.mkdir(mode=0o700, parents=True, exist_ok=True)
    if (dirs.done / f"{digest}.md").exists():
        raise SpecError("this exact spec already ran")
    # Written whole in tmp/, then linked in: a path unit starts the runner the moment a name
    # appears in approved/, so it must never see a half written file (CWE-362). link, like
    # O_EXCL, refuses an existing name
    tmp = dirs.tmp / f"{digest}.{time.time_ns()}"
    write_new(tmp, text, 0o600, SpecError("temp file exists"))
    try:
        os.link(tmp, dirs.approved / f"{digest}.md")
    except FileExistsError:
        raise SpecError("already approved") from None
    finally:
        tmp.unlink()
    log(dirs, "approve", digest, "ok")
    return digest


def approve(path: Path, dirs: Dirs, projects: set[str]) -> str:
    text, _ = load_spec(path, projects)
    return store_approved(text, dirs, projects)


# ---------- needs and tasks (threats 37, 38, 40) ----------

class RunResult:
    """What a runner returns once it parsed Claude's result: the report for Outbox, and the
    need block if the run ended blocked."""

    def __init__(self, report: str, need: dict | None = None):
        self.report, self.need = report, need


def parse_need(result: str) -> dict | None:
    """The need block in Claude's own result, never in the runner's facts. It must be the last
    two non-empty lines, `need:` then `why:`, plain and short. A need line anywhere else fails
    the run: an odd block is refused, never ignored or repaired (threat 38)."""
    lines = [line.strip() for line in result.split("\n") if line.strip()]
    marks = [i for i, line in enumerate(lines) if line.lower().startswith("need:")]
    if not marks:
        return None
    if marks != [len(lines) - 2] or not lines[-2].startswith("need:") \
            or not lines[-1].startswith("why:"):
        raise SpecError("need block must be the last two lines: need:, then why:")
    need, why = lines[-2][5:].strip(), lines[-1][4:].strip()
    if not need or not why:
        raise SpecError("need block has an empty field")
    if len(need) > MAX_NEED or len(why) > MAX_WHY:
        raise SpecError("need block is too long")
    check_plain(need + why)
    return {"need": need, "why": why}


def need_hash(need: dict) -> str:
    return sha256(f"need: {need['need']}\nwhy: {need['why']}\n")


def task_path(dirs: Dirs, root: str) -> Path:
    if not isinstance(root, str) or not HEX64.match(root):
        raise SpecError("bad task id")
    return dirs.tasks / f"{root}.json"


def load_task(dirs: Dirs, root: str) -> dict:
    try:
        task = json.loads(read_regular(task_path(dirs, root), MAX_CONFIG_BYTES))
    except ValueError:
        raise SpecError("task file is broken") from None
    if not isinstance(task, dict) or task.get("root") != root:
        raise SpecError("task file is broken")
    return task


def save_task(dirs: Dirs, task: dict):
    # Only tasks/: the cleaner and julz-keep save tasks in sandboxes where every other gate
    # folder is missing on a read only home, and mkdir there fails (EROFS)
    dirs.tasks.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = task_path(dirs, task["root"])
    # Same folder as the task file, so the rename never crosses a mount (see Dirs.tmp)
    tmp = dirs.tasks / f".{task['root']}.{time.time_ns()}.tmp"
    write_new(tmp, json.dumps(task), 0o600, GateError("temp file exists"))
    os.replace(tmp, path)


def plain_line(value, what: str, limit: int) -> str:
    """One short line I typed on the phone, a value in a text the server builds: it may not
    add lines or markers, and never a secret (threats 50, 51, 93)."""
    if not isinstance(value, str):
        raise SpecError(f"{what} must be text")
    value = value.strip()
    if not value:
        raise SpecError(f"{what} is empty")
    if len(value) > limit:
        raise SpecError(f"{what} is over {limit} characters")
    if "\n" in value:
        raise SpecError(f"{what} must be one line")
    check_plain(value)
    if "<<<" in value or ">>>" in value:
        raise SpecError(f"{what} holds a data marker")
    if looks_secret(value):
        raise SpecError(f"{what} looks like a secret: do that step at the laptop instead")
    return value


def check_answer(answer) -> str:
    """My answer to a need: `done`, or a short line I typed on the phone (threats 50, 51)."""
    return plain_line(answer, "answer", MAX_ANSWER)


def check_note(note) -> str:
    """My note on an approval (threat 93): an answer's rules, shorter, and no links."""
    note = plain_line(note, "note", MAX_NOTE)
    if LINK.search(note):
        raise SpecError("note holds a link")
    return note


def looks_secret(text: str) -> bool:
    """Known token prefixes, a PEM header, or a long run mixing upper case, lower case and
    digits (threat 50). Used for answers and for files a Keep would copy (54)."""
    return bool(SECRET_PREFIX.search(text)) or "-----BEGIN" in text or any(
        re.search("[A-Z]", m) and re.search("[a-z]", m) and re.search("[0-9]", m)
        for m in KEY_RUN.findall(text))


def continuation_text(task: dict, answer: str = "done") -> str:
    """What I sign to answer a need: it names the task, the step, the exact need I saw and
    my answer."""
    return (f"continue: {task['root']}\nstep: {task['step']}\n"
            f"need_hash: {task['need_hash']}\nanswer: {check_answer(answer)}\n")


def check_continuation(text: str) -> dict:
    c = parse_fields(text, CONT_FIELDS)
    if not HEX64.match(c["continue"]) or not HEX64.match(c["need_hash"]):
        raise SpecError("continuation names a bad hash")
    if not c["step"].isdigit() or not 2 <= int(c["step"]) <= 1 + MAX_CONTINUATIONS:
        raise SpecError("continuation step out of range")
    return {"root": c["continue"], "step": int(c["step"]), "need_hash": c["need_hash"],
            "answer": check_answer(c["answer"])}


def waiting_task(dirs: Dirs, cont: dict, now: float) -> dict:
    """The task this continuation answers, if it is still waiting for exactly this answer."""
    task = load_task(dirs, cont["root"])
    if task.get("status") != "waiting":
        raise SpecError("task is not waiting for an answer")
    if task.get("step") != cont["step"] or task.get("need_hash") != cont["need_hash"]:
        raise SpecError("task changed since you saw it")
    if now - task.get("opened", 0) > NEED_TTL:
        raise SpecError("need expired")
    return task


def open_needs(dirs: Dirs, now: float) -> list[dict]:
    """Waiting tasks for the approver page, oldest first, with the text to sign."""
    out = []
    if not dirs.tasks.is_dir():
        return out
    for path in dirs.tasks.iterdir():
        if not (path.suffix == ".json" and HEX64.match(path.stem)):
            continue
        try:
            task = load_task(dirs, path.stem)
        except SpecError:
            continue
        if task.get("status") != "waiting" or now - task.get("opened", 0) > NEED_TTL:
            continue
        text = continuation_text(task)
        out.append({"root": task["root"], "step": task["step"], "project": task["project"],
                    "goal": task["goal"], "need": task["need"], "why": task["why"],
                    "opened": task["opened"], "text": text, "sha256": sha256(text)})
    return sorted(out, key=lambda t: t["opened"])


def store_continuation(text: str, dirs: Dirs, now: float) -> str:
    """I did what Claude needed: queue the next run. Call only after I signed it."""
    cont = check_continuation(text)
    task = waiting_task(dirs, cont, now)
    digest = publish(text, dirs)
    task["status"] = "approved"
    save_task(dirs, task)
    return digest


def stop_task(text: str, dirs: Dirs, now: float):
    """I will not do what Claude needed: the task ends here."""
    cont = check_continuation(text)
    task = waiting_task(dirs, cont, now)
    task["status"] = "stopped"
    save_task(dirs, task)
    log(dirs, "stop", task["root"], "ok", f"step {task['step']}")


def discard_task(text: str, dirs: Dirs, now: float):
    """Delete from the phone: the task ends as discarded. The approver cannot touch work/,
    so the cleaner, started by a path unit on tasks/, removes the work copy."""
    cont = check_continuation(text)
    task = waiting_task(dirs, cont, now)
    task["status"] = "discarded"
    save_task(dirs, task)
    log(dirs, "discard", task["root"], "ok", f"step {task['step']}")


def expire_tasks(dirs: Dirs, now: float) -> int:
    """Needs nobody answered in NEED_TTL end their task. Never approved by timeout (40)."""
    count = 0
    if not dirs.tasks.is_dir():
        return count
    for path in dirs.tasks.iterdir():
        if not (path.suffix == ".json" and HEX64.match(path.stem)):
            continue
        try:
            task = load_task(dirs, path.stem)
        except SpecError:
            continue
        if task.get("status") == "waiting" and now - task.get("opened", 0) > NEED_TTL:
            task["status"] = "expired"
            save_task(dirs, task)
            log(dirs, "expire", task["root"], "ok", f"step {task['step']}")
            count += 1
    return count


def load_job(text: str, dirs: Dirs, projects) -> dict:
    """What the runner gets: a first run from a spec, or a continuation of a task I answered.
    A continuation is rebuilt from host state only: the root spec from done/, the need from
    the task file, Claude's previous report from Outbox."""
    if not text.startswith("continue:"):
        spec = check_spec(text, projects, approved=True)
        return {**spec, "kind": "spec", "root": sha256(text), "step": 1}
    cont = check_continuation(text)
    task = load_task(dirs, cont["root"])
    if task.get("status") != "approved" or task.get("step") != cont["step"] \
            or task.get("need_hash") != cont["need_hash"]:
        raise SpecError("continuation does not match an approved task")
    root_text = decode(read_regular(dirs.done / f"{cont['root']}.md", MAX_SPEC_BYTES))
    if sha256(root_text) != cont["root"]:
        raise SpecError("root spec does not match its hash")
    spec = check_spec(root_text, projects, approved=True)
    last = task.get("last_run", "")
    if not isinstance(last, str) or not HEX64.match(last):
        raise SpecError("task has no previous run")
    if task.get("stopped"):
        previous = "(The run was stopped from the phone before it wrote a report.)"
    else:
        previous = decode(read_regular(dirs.outbox / f"{last}.md", MAX_REPORT_BYTES))
    return {**spec, "kind": "continue", "root": cont["root"], "step": cont["step"],
            "need": task["need"], "why": task["why"], "previous_report": previous,
            "resume": bool(task.get("stopped")), "answer": cont["answer"]}


# ---------- stopping a run from the phone (threats 47, 48) ----------

HALT_FIELDS = ("halt", "started")
RUN_STALE = 20 * 60  # longer than the runner's timeout: an older running.json is left over


def set_running(dirs: Dirs, digest: str, job: dict):
    dirs.ensure()
    data = {"sha256": digest, "root": job["root"], "step": job["step"],
            "project": job["project"], "goal": job["goal"],
            "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    tmp = dirs.control / f".running.{time.time_ns()}.tmp"
    write_new(tmp, json.dumps(data), 0o600, GateError("temp file exists"))
    os.replace(tmp, dirs.running)


def clear_running(dirs: Dirs):
    dirs.running.unlink(missing_ok=True)


def current_run(dirs: Dirs, now: float) -> dict | None:
    """What runs now, for the approver page, or None. A file left by a killed runner is
    ignored once it is older than any run can be."""
    try:
        run = json.loads(read_regular(dirs.running, MAX_CONFIG_BYTES))
        started = datetime.fromisoformat(run["started"]).timestamp()
    except (SpecError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(run.get("sha256"), str) or not HEX64.match(run["sha256"]) \
            or now - started > RUN_STALE:
        return None
    return run


def halt_text(run: dict) -> str:
    """What I sign to stop a run: the run's hash and when it started."""
    return f"halt: {run['sha256']}\nstarted: {run['started']}\n"


def request_halt(text: str, dirs: Dirs, now: float, channel: str = "phone") -> str:
    """I signed a stop for the run in text. Only the run that is going now can be stopped,
    and only with the exact text built from its running.json. Returns the run's hash."""
    fields = parse_fields(text, HALT_FIELDS)
    run = current_run(dirs, now)
    if run is None or text != halt_text(run) or fields["halt"] != run["sha256"]:
        raise SpecError("that run is not running any more")
    write_new(dirs.control / f"stop-{run['sha256']}", text, 0o600,
              SpecError("stop already requested"))
    log(dirs, "halt", run["sha256"], "ok", channel)
    return run["sha256"]


def stop_requested(dirs: Dirs, digest: str) -> bool:
    """The runner asks this once a second while Claude runs."""
    return os.path.lexists(dirs.control / f"stop-{digest}")


STOPPED_NEED = {"need": "The run was stopped from the phone.",
                "why": "Continue carries on in the same work copy. Delete removes it."}


def settle_task(dirs: Dirs, job: dict, digest: str, status: str, need: dict | None):
    """After a run: open a need, end the task, or nothing (a first run that failed).
    deliver() already dropped the need of a held back or failed run. A run I stopped waits
    like a need, so I can continue or delete it from the phone. A first run that is done
    gets a task file too: a Keep needs somewhere to say the task was kept (threat 57)."""
    stopped = status == "stopped"
    if stopped:
        need = STOPPED_NEED
    if job["kind"] == "continue":
        task = load_task(dirs, job["root"])
    elif need is None and status != "ok":
        return
    else:
        task = {"root": job["root"], "project": job["project"], "goal": job["goal"]}
    task["step"] = job["step"]
    task["stopped"] = stopped
    if need is None:
        task["status"] = "done" if status == "ok" else "failed"
        save_task(dirs, task)
        log(dirs, "task-end", job["root"], task["status"], f"step {job['step']}")
        return
    if job["kind"] == "continue" and not stopped and task.get("need_hash") == need_hash(need):
        # Answered, and Claude asks the very same thing again: another run would only loop (130)
        task["status"] = "failed"
        save_task(dirs, task)
        log(dirs, "task-end", job["root"], "failed", "asked the same again")
        return
    if job["step"] >= 1 + MAX_CONTINUATIONS:
        task["status"] = "stopped" if stopped else "failed"
        save_task(dirs, task)
        log(dirs, "task-end", job["root"], task["status"], "too many continuations")
        return
    task.update(status="waiting", step=job["step"] + 1, need=need["need"], why=need["why"],
                need_hash=need_hash(need), opened=time.time(), last_run=digest)
    save_task(dirs, task)
    if not stopped:  # a stopped run already got its own push ("run stopped")
        log(dirs, "need", job["root"], "ok", f"step {task['step']}")


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
             max_runs: int, hard_max: int = HARD_MAX) -> str | None:
    """Run the oldest valid approved spec. Returns its hash, or None if nothing ran.
    runner(spec, text) returns the report text or raises."""
    try:
        with lock(dirs):
            return _run_next(dirs, projects, runner, secrets, max_runs, hard_max)
    except GateBusy:
        return None


def _run_next(dirs, projects, runner, secrets, max_runs, hard_max):
    dirs.ensure()
    now = time.time()
    lines = log_lines(dirs, RUN_WINDOW, now)
    if len(window_runs(lines, now)) >= hard_max:
        return None  # the ceiling: nothing runs, override or not (28)
    soft_full = len(window_runs(lines, now, first_only=True)) >= max_runs
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
            job = load_job(text, dirs, projects)
            if job["kind"] == "spec" and same_spec(dirs, text) == "already ran":
                raise SpecError("already ran with another note")
        except SpecError as e:
            quarantine_spec(dirs, path, digest, str(e))
            continue
        # A first run over the soft cap waits in approved/ unless I signed an override.
        # A continuation is my answer to a need and does not count (28, 52)
        if job["kind"] == "spec" and soft_full and not take_override(dirs, digest, now):
            continue
        # Moved before the run: if anything below crashes, this spec never runs again
        os.replace(path, dirs.done / path.name)
        # Logged before the run, so a run that gets killed still leaves a trace (threat 29)
        log(dirs, "start", digest, "ok")
        set_running(dirs, digest, job)
        try:
            status, reason, report_hash, need = deliver(dirs, digest, job, text, runner,
                                                        secrets)
        finally:
            clear_running(dirs)
        log(dirs, "run", digest, status, reason, report_hash,
            continuation=job["kind"] == "continue")
        settle_task(dirs, job, digest, status, need)
        return digest
    return None


def deliver(dirs, digest, job, text, runner, secrets) -> tuple[str, str, str, dict | None]:
    try:
        report = runner(job, text)
    except RunStopped:
        return "stopped", "stopped from the phone", "", None
    except Exception as e:
        # Only the exception type: its message could quote the token or the report
        return "failed", type(e).__name__, "", None
    need = None
    if isinstance(report, RunResult):
        report, need = report.report, report.need
    if not isinstance(report, str):
        return "failed", "runner returned no text", "", None
    report_hash = sha256(report)
    secrets = [s for s in secrets if s]
    if any(s in report for s in secrets):
        reason = "secret in report"
    elif len(report.encode()) > MAX_REPORT_BYTES:
        reason = f"report over {MAX_REPORT_BYTES} bytes"
    else:
        write_new(dirs.outbox / f"{digest}.md", report, 0o644, GateError("report exists"))
        return "ok", "", report_hash, need
    write_new(dirs.quarantine / f"{digest}.md", report, 0o600, GateError("report exists"))
    return "quarantined", reason, report_hash, None


def override_text(digest: str, used: int, max_runs: int = MAX_RUNS) -> str:
    """What I sign to let one approval pass the soft cap: the item and the count I saw."""
    return f"override: {digest}\nused: {used} of {max_runs}\n"


def store_override(text: str, dirs: Dirs, now: float, max_runs: int = MAX_RUNS,
                   hard_max: int = HARD_MAX):
    """I signed Run now for one approval (threat 52). Call only after I signed it. Everything
    is checked again here against the whole log, never taken from the page."""
    digest = parse_fields(text, OVERRIDE_FIELDS)["override"]
    if not HEX64.match(digest):
        raise SpecError("override names a bad hash")
    path = dirs.approved / f"{digest}.md"
    if path.is_symlink() or not path.is_file() or (dirs.done / path.name).exists():
        raise SpecError("that approval is not waiting any more")
    lines = log_lines(dirs, RUN_WINDOW, now)
    used = len(window_runs(lines, now, first_only=True))
    if len(window_runs(lines, now)) >= hard_max:
        raise SpecError("the hard ceiling is reached, nothing can run now")
    if used < max_runs:
        raise SpecError("the run cap is not full, it will run anyway")
    if text != override_text(digest, used, max_runs):
        raise SpecError("changed since you saw it: reload")
    write_new(dirs.approved / f"override-{digest}", text, 0o600,
              SpecError("override already signed"))
    log(dirs, "override", digest, "ok", f"{used} of {max_runs}")


def take_override(dirs: Dirs, digest: str, now: float) -> bool:
    """The runner uses an override marker once. A link, or one older than OVERRIDE_TTL,
    does not count."""
    path = dirs.approved / f"override-{digest}"
    try:
        st = path.lstat()
    except FileNotFoundError:
        return False
    fresh = stat.S_ISREG(st.st_mode) and now - st.st_mtime < OVERRIDE_TTL
    path.unlink()
    return fresh


def quarantine_spec(dirs: Dirs, path: Path, digest: str, reason: str):
    # rename moves a symlink itself, never its target
    os.replace(path, dirs.quarantine / f"{path.name}.{time.time_ns()}.refused")
    log(dirs, "refuse", digest, "refused", reason)


def window_runs(lines: list[str], now: float, first_only: bool = False) -> list[float]:
    """Times of the runs in the last RUN_WINDOW seconds, oldest first. A rolling window, so
    no burst at a reset (28). A run line whose time cannot be read counts as now, and one
    without the continuation mark counts as a first run: the caps fail closed."""
    times = []
    for line in lines:
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict) or entry.get("action") != "run":
            continue
        if first_only and entry.get("continuation") is True:
            continue
        try:
            when = datetime.fromisoformat(entry["time"]).timestamp()
        except (KeyError, TypeError, ValueError):
            when = now
        if now - when < RUN_WINDOW:
            times.append(when)
    return sorted(times)


def runs_in_window(dirs: Dirs, now: float) -> int:
    return len(window_runs(log_lines(dirs, RUN_WINDOW, now), now))


def next_slot(times: list[float], max_runs: int = MAX_RUNS) -> float | None:
    """When the cap lets the next run start, from window_runs. None means it may start now."""
    if len(times) < max_runs:
        return None
    return times[len(times) - max_runs] + RUN_WINDOW


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


def _read_lines(path: Path) -> list[str]:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as f:
        return f.read().decode("utf-8").splitlines()


def archives(dirs: Dirs) -> list[Path]:
    """Rotated logs, oldest first. The name carries the UTC time, so name order is time order."""
    try:
        names = os.listdir(dirs.logdir)
    except FileNotFoundError:
        return []
    return [dirs.logdir / n for n in sorted(names) if ARCHIVE_NAME.match(n)]


def log_lines(dirs: Dirs, since: float, now: float) -> list[str]:
    """runner.log plus every archive written to in the last `since` seconds, oldest first.
    A line inside a window sits in a file touched inside it, so a rotation never frees a cap
    (threat 53). A link, or an archive that cannot be read, raises: the caps fail closed."""
    lines = []
    for path in archives(dirs):
        if now - path.lstat().st_mtime < since:
            lines += _read_lines(path)
    try:
        lines += _read_lines(dirs.log)
    except FileNotFoundError:
        pass
    return lines


def rotate(dirs: Dirs, now: float, max_bytes: int = LOG_ROTATE_BYTES,
           keep: float = LOG_KEEP) -> str | None:
    """Call only while holding lock(dirs). A runner.log past max_bytes becomes an archive in
    the same folder: a new name for the same file, never an edit, and log() opens the file
    for every line, so no line is lost. Archives older than keep go, links as links.
    Returns the archive name, or None."""
    for path in archives(dirs):
        if now - path.lstat().st_mtime > keep:
            path.unlink()
    try:
        st = dirs.log.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(st.st_mode):
        raise GateError("runner.log is not a regular file")
    if st.st_size < max_bytes:
        return None
    stamp = datetime.fromtimestamp(now, timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    for n in range(100):
        target = dirs.logdir / (f"runner-{stamp}.log" if n == 0 else f"runner-{stamp}-{n}.log")
        try:
            os.link(dirs.log, target, follow_symlinks=False)  # fails if taken: never clobbers
            break
        except FileExistsError:
            continue
    else:
        raise GateError("no free archive name")
    os.unlink(dirs.log)
    log(dirs, "rotate", "", "ok", target.name)
    return target.name


def log(dirs: Dirs, action: str, digest: str, status: str, reason: str = "",
        report_hash: str = "", continuation: bool = False):
    """Host side action log (threat 29). Never holds report text; a refusal reason may
    quote up to 40 characters of a spec line."""
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "action": action, "sha256": digest, "status": status}
    if reason:
        entry["reason"] = reason
    if report_hash:
        entry["report_sha256"] = report_hash
    if continuation:
        entry["continuation"] = True
    dirs.log.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(dirs.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
