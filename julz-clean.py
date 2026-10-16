#!/usr/bin/env python3
"""Remove what delegation leaves behind, on a schedule. SECURITY.md threats 44 to 46.

Builds a plan first, then applies it (or only prints it with --dry-run). Every deletion is
one line in runner.log.
- never follows a link: only direct children of its own folders, each checked with lstat; a
  link is removed as a link; trees go through shutil.rmtree, which works through file
  descriptors on Linux; a top folder that is itself a link is refused (threat 44)
- never deletes what a control reads: done/ names stay forever (run once, threat 22), only
  their text is emptied; runner.log is never touched; a waiting or approved task keeps its
  work copy and its approval (threat 45)
- only names it knows (hashes); anything else is left alone and listed
- never renames across folders: in a systemd sandbox each folder is its own mount (EXDEV)
Usage: ./julz-clean.py [--dry-run]     (systemd: julz-clean.timer, daily)
"""
import json
import os
import shutil
import stat
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402

HOME = Path.home()
GATE_DIR = HOME / ".local" / "share" / "julz"
WORK_ROOT = GATE_DIR / "work"
INBOX = HOME / "Documents" / "julz-mem" / "Inbox" / "claude"
OUTBOX = HOME / "Documents" / "julz-mem" / "Outbox"

HOUR = 3600
DAY = 24 * HOUR
WORK_KEEP = 7 * DAY
WORK_WARN = 6 * DAY  # push once, 24 h before the work copy goes
STDERR_KEEP = 7 * DAY
INBOX_KEEP = 7 * DAY
APPROVED_KEEP = DAY
TMP_KEEP = HOUR
OUTBOX_KEEP = 30 * DAY
QUARANTINE_KEEP = 30 * DAY
DONE_EMPTY = 30 * DAY
TASK_KEEP = 30 * DAY
ACTIVE = ("waiting", "approved")


class Action:
    """kind: delete (file, link or tree), empty (truncate a done/ file), spend (mark an
    approval as run and remove it), warn (push before a work copy goes)."""

    def __init__(self, kind: str, path: Path, reason: str, digest: str = ""):
        self.kind, self.path, self.reason, self.digest = kind, Path(path), reason, digest

    def __repr__(self):
        return f"{self.kind:6} {self.path}  ({self.reason})"


def age(path: Path, now: float) -> float:
    return now - path.lstat().st_mtime


def safe_folder(path: Path) -> bool:
    """A top folder we may clean: exists, a real directory, not a link."""
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def children(path: Path) -> list[Path]:
    return sorted(path.iterdir()) if safe_folder(path) else []


def log_entries(dirs: gate.Dirs) -> list[dict]:
    if not dirs.log.exists():
        return []
    out = []
    for line in dirs.log.read_text(errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            out.append(entry)
    return out


def root_of(dirs: gate.Dirs, digest: str) -> str:
    """A continuation's run is filed under its own hash; its work copy is its task's root."""
    try:
        text = gate.decode(gate.read_regular(dirs.done / f"{digest}.md", gate.MAX_SPEC_BYTES))
    except gate.SpecError:
        return digest
    first = text.split("\n", 1)[0]
    if first.startswith("continue:"):
        root = first[len("continue:"):].strip()
        if gate.HEX64.match(root):
            return root
    return digest


def last_runs(dirs: gate.Dirs, entries: list[dict]) -> dict[str, float]:
    """Root hash -> time of the last run of that task, from runner.log."""
    last = {}
    for e in entries:
        digest = e.get("sha256", "")
        if e.get("action") != "run" or not isinstance(digest, str) \
                or not gate.HEX64.match(digest):
            continue
        try:
            t = datetime.fromisoformat(e["time"]).timestamp()
        except (KeyError, TypeError, ValueError):
            continue
        root = root_of(dirs, digest)
        last[root] = max(last.get(root, 0), t)
    return last


def task_states(dirs: gate.Dirs) -> dict[str, str]:
    states = {}
    for path in children(dirs.tasks):
        if path.suffix == ".json" and gate.HEX64.match(path.stem):
            try:
                states[path.stem] = gate.load_task(dirs, path.stem).get("status", "")
            except gate.SpecError:
                states[path.stem] = "broken"
    return states


def plan(dirs: gate.Dirs, inbox: Path, work_root: Path, now: float) -> tuple[list, list]:
    """(actions, notes). notes are things left alone on purpose, for the dry run."""
    actions, notes = [], []
    entries = log_entries(dirs)
    runs = last_runs(dirs, entries)
    states = task_states(dirs)
    active = {root for root, s in states.items() if s in ACTIVE}
    warned = {e.get("sha256") for e in entries if e.get("action") == "clean-warn"}

    for top in (work_root, inbox, dirs.approved, dirs.done, dirs.quarantine, dirs.outbox,
                dirs.tasks):
        if top.exists() and not safe_folder(top):
            notes.append(f"refused {top}: not a real directory (link?)")

    # work copies and their stderr files
    for p in children(work_root):
        name = p.name
        if p.is_symlink():
            actions.append(Action("delete", p, "link in work/, removed as a link"))
        elif gate.HEX64.match(name) and stat.S_ISDIR(p.lstat().st_mode):
            if name in active:
                notes.append(f"kept {p}: task is {states[name]}")
                continue
            idle = now - runs.get(name, p.lstat().st_mtime)
            if idle > WORK_KEEP:
                actions.append(Action("delete", p, "work copy, 7 days after its last run", name))
            elif idle > WORK_WARN and name not in warned:
                actions.append(Action("warn", p, "work copy goes in 24 hours", name))
        elif name.endswith(".stderr") and gate.HEX64.match(name[:-7]):
            if age(p, now) > STDERR_KEEP:
                actions.append(Action("delete", p, "stderr, 7 days", name[:-7]))
        else:
            notes.append(f"unknown {p}, left alone")

    # specs julz wrote that I never approved
    for p in children(inbox):
        if (p.is_symlink() or p.is_file()) and age(p, now) > INBOX_KEEP:
            actions.append(Action("delete", p, "unapproved spec, 7 days"))

    # approvals that never ran: spent, never run late (fail closed)
    for p in children(dirs.approved):
        if gate.APPROVED_NAME.match(p.name) and not p.is_symlink():
            if age(p, now) > APPROVED_KEEP:
                actions.append(Action("spend", p, "approved but not run in 24 hours",
                                      p.name[:-3]))
        elif p.name == ".tmp" and not p.is_symlink():
            for t in children(p):
                if age(t, now) > TMP_KEEP:
                    actions.append(Action("delete", t, "interrupted write, 1 hour"))
        elif p.is_symlink():
            actions.append(Action("delete", p, "link in approved/, removed as a link"))
    # interrupted task writes
    for p in children(dirs.tasks):
        if p.name.endswith(".tmp") and age(p, now) > TMP_KEEP:
            actions.append(Action("delete", p, "interrupted write, 1 hour"))
        elif p.suffix == ".json" and gate.HEX64.match(p.stem) and p.stem not in active \
                and age(p, now) > TASK_KEEP:
            actions.append(Action("delete", p, "finished task, 30 days", p.stem))

    # stop requests and interrupted writes in control/; running.json is the runner's own
    for p in children(dirs.control):
        known = (p.name.startswith("stop-") and gate.HEX64.match(p.name[5:])) \
            or (p.name.startswith(".running.") and p.name.endswith(".tmp"))
        if known and age(p, now) > TMP_KEEP:
            actions.append(Action("delete", p, "stop request or interrupted write, 1 hour"))

    # done/: the names are the run once record, kept forever; only the text goes
    for p in children(dirs.done):
        if gate.APPROVED_NAME.match(p.name) and not p.is_symlink() \
                and p.lstat().st_size > 0 and age(p, now) > DONE_EMPTY:
            actions.append(Action("empty", p, "done spec text, 30 days (name kept)", p.stem))

    for p in children(dirs.quarantine):
        if age(p, now) > QUARANTINE_KEEP:
            actions.append(Action("delete", p, "quarantine, 30 days"))

    for p in children(dirs.outbox):
        if gate.APPROVED_NAME.match(p.name) and age(p, now) > OUTBOX_KEEP:
            actions.append(Action("delete", p, "report, 30 days", p.stem))
    return actions, notes


def root_of_approval(path: Path) -> str:
    try:
        text = gate.decode(gate.read_regular(path, gate.MAX_SPEC_BYTES))
    except gate.SpecError:
        return ""
    first = text.split("\n", 1)[0]
    if first.startswith("continue:"):
        return first[len("continue:"):].strip()
    return gate.sha256(text)


def remove(path: Path):
    """Delete a file, link or tree without ever following a link."""
    st = path.lstat()
    if stat.S_ISDIR(st.st_mode):
        if not shutil.rmtree.avoids_symlink_attacks:
            raise gate.GateError("this platform's rmtree can follow links: refusing")
        shutil.rmtree(path)
    else:
        path.unlink()  # a link is removed itself, never its target


def apply(actions: list[Action], dirs: gate.Dirs, now: float) -> int:
    done = 0
    for a in actions:
        try:
            if a.kind == "delete":
                remove(a.path)
            elif a.kind == "empty":
                fd = os.open(a.path, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC)
                os.close(fd)
            elif a.kind == "spend":
                spend(a.path, a.digest, dirs, now)
            elif a.kind == "warn":
                pass  # the log line below is the warning; julz-notify pushes it
        except (OSError, gate.GateError) as e:
            gate.log(dirs, "clean", a.digest, "failed", f"{a.kind} {type(e).__name__}")
            continue
        action = "clean-warn" if a.kind == "warn" else "clean"
        gate.log(dirs, action, a.digest, "ok", f"{a.kind}: {a.reason}")
        done += 1
    return done


def spend(path: Path, digest: str, dirs: gate.Dirs, now: float):
    """An approval that never ran: record it in done/ (so it can never run late) and remove
    it. An empty marker, not a rename, so it works across mounts."""
    root = root_of_approval(path)
    marker = dirs.done / f"{digest}.md"
    if not marker.exists():
        gate.write_new(marker, "", 0o600, gate.GateError("marker exists"))
    path.unlink()
    if root != digest and gate.HEX64.match(root):
        try:
            task = gate.load_task(dirs, root)
        except gate.SpecError:
            return
        if task.get("status") == "approved":
            task["status"] = "expired"
            gate.save_task(dirs, task)
            gate.log(dirs, "expire", root, "ok", "approval not run in 24 hours")


def main():
    dry = "--dry-run" in sys.argv[1:]
    dirs = gate.Dirs(GATE_DIR, outbox=OUTBOX)
    now = time.time()
    actions, notes = plan(dirs, INBOX, WORK_ROOT, now)
    for a in actions:
        print(("would " if dry else "") + repr(a))
    for n in notes:
        print(n)
    if dry:
        print(f"{len(actions)} actions planned, nothing changed")
        return
    print(f"{apply(actions, dirs, now)} of {len(actions)} actions done")


if __name__ == "__main__":
    main()
