"""Notes, host side: apply julz's requests to my notes and keep the vault in git.

julz never writes study/ or daily/. Her tool drops a request into Inbox/.requests/ after I
click confirm in the chat, and julz-vault.py runs this. Security model: SECURITY.md 65 to 76.
- a request is untrusted input (B16): exact JSON keys per op, fixed name pattern, size limit,
  validate and reject, never sanitize. The container could write one without my click, so
  every check of the tool is made again here. Every request file is removed once read
- each op has its roots: append, edit, move, delete in Inbox/, study/, daily/; create in
  study/ and daily/; reviewed in study/ only. Claude/, Outbox/, Templates/ never, and no
  subfolder of Inbox/ (Inbox/claude/ holds specs for my phone). Names from fixed patterns,
  at most one folder below a root, no links, nothing hidden (CWE-22, CWE-59)
- text is checked like a Keep: no hidden characters, links, images, HTML, secrets (LLM04)
- edit, move and delete carry the hash of the note as the tool showed it to me; a note that
  changed since is refused (CWE-367). A move never replaces a note: link, then unlink
- "resolve" moves feedback/<name>.md to feedback/done/ after I said solved (85)
- "reviewed" takes no text: the date comes from here, into the reviewed: line only
- a tick from the phone (113): the approver builds the signed text with tick_text() from the
  snapshot here, then drops the same tick requests the tool does; every check still runs here
- my own changes are committed first, then one commit per request, so git says who wrote
  what (70). A commit the gitleaks hook blocks is logged once (69)
- index notes (kind: moc) per study/ folder are built here from paths and headings (76)
- the runner log gets the request hash and a fixed reason, never a note name or text
"""
import fcntl
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import time
import unicodedata
from collections import Counter
from contextlib import contextmanager
from datetime import date, timedelta
from pathlib import Path

import julz_gate as gate
import julz_keep as keep

MINE = "study"
EDITABLE = ("Inbox", "study", "daily")
SUBFOLDERS_IN = ("study", "daily")
FOLDER = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
NAME = re.compile(r"\w[\w .-]{0,99}")  # a note's file name without .md, as the tool allows
REQUEST_NAME = re.compile(r"\d{10}-[0-9a-f]{8}\.json")
TMP_NAME = re.compile(r"\.tmp-\d{10}-[0-9a-f]{8}\.json")
TMP_GRACE = 60  # seconds a half written request may sit before it counts as junk
MAX_REQUEST_BYTES = 16_384
MAX_APPEND_CHARS = 4000
MAX_NOTE_BYTES = 100_000
MAX_CREATE_CHARS = 12_000
MAX_PER_RUN = 20
MAX_WAITING = 200
MAX_TITLE = 80
FRONT_MATTER_MAX = 2000
OPS = {
    "append": ({"op", "note", "text"}, EDITABLE),
    "reviewed": ({"op", "note"}, (MINE,)),
    "replace": ({"op", "note", "old", "new", "sha256"}, EDITABLE),
    "move": ({"op", "note", "to", "sha256"}, EDITABLE),
    "delete": ({"op", "note", "sha256"}, EDITABLE),
    # Inbox for answers saved from the chat (139): never synced into Julz's knowledge
    "create": ({"op", "note", "text"}, ("study", "daily", "feedback", "Inbox")),
    "tick": ({"op", "note", "item"}, ("Inbox", "daily", "goals")),
    "start": ({"op", "note", "item"}, ("Inbox", "daily")),
    "goal": ({"op", "note", "item"}, ("goals",)),
    "progress": ({"op", "note", "item"}, ("goals",)),
    "target": ({"op", "note", "item", "target"}, ("goals",)),
    "link": ({"op", "note", "item", "goal"}, ("Inbox", "daily")),
    "unlink": ({"op", "note", "item", "goal"}, ("Inbox", "daily")),
    "est": ({"op", "note", "item", "minutes"}, ("goals",)),
    "log": ({"op", "note", "item", "minutes"}, ("goals",)),
    "nest": ({"op", "note", "item", "under"}, ("goals",)),
    "due": ({"op", "note", "item", "due"}, ("goals",)),
    "resolve": ({"op", "note"}, ("feedback",)),
}
MAX_ITEM = 200
LOG_ACTION = {"reviewed": "reviewed", "move": "note-move", "delete": "note-delete",
              "resolve": "feedback-solved", "tick": "tick", "start": "start", "goal": "goal", "progress": "goal",
              "target": "goal", "link": "goal", "nest": "goal", "due": "goal", "unlink": "goal", "est": "goal", "log": "goal"}
# Days between reviews by status, the same as the tool's (a test keeps them equal)
REVIEW_DAYS = {"learning": 3, "review": 7, "solid": 30}
DEFAULT_REVIEW_DAYS = 7
GIT_TIMEOUT = 60


class Refused(Exception):
    """A request that fails a check. The message is a fixed reason, safe for the log."""


# ---------- front matter ----------

def front(text: str) -> tuple[dict, str]:
    """key: value lines between --- at the top, and the body. Tags as [a, b] or - a lines."""
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1 or end > FRONT_MATTER_MAX:
        return {}, text
    meta, key = {}, None
    for line in text[4:end].splitlines():
        if line.lstrip().startswith("- ") and key:
            meta[key] = (meta[key] + ", " + line.strip()[2:]).strip(", ")
            continue
        key, sep, value = line.partition(":")
        key = key.strip().lower() if sep else None
        if key:
            meta[key] = value.strip()
    return meta, text[end + 4:]


def tags(meta: dict) -> list[str]:
    return [t.strip().lower() for t in meta.get("tags", "").strip("[]").split(",") if t.strip()]


def hidden(text: str) -> bool:
    return any(ch not in "\n\t" and unicodedata.category(ch) in gate.BAD_CATEGORIES
               for ch in text)


# ---------- paths ----------

def check_path(note, roots, case: bool = False) -> list[str]:
    """The parts of a note path julz may use: a root, at most one safe folder (study/ and
    daily/ only, or exactly feedback/eval/ for a new eval case, 153), a safe name ending in .md."""
    if not isinstance(note, str) or not note or len(note) > 200 or "\x00" in note:
        raise Refused("bad note path")
    parts = note.split("/")
    if note.startswith("/") or parts[0] not in roots or len(parts) < 2:
        raise Refused("not in a folder julz may change")
    deep = parts[0] in SUBFOLDERS_IN or (case and tuple(parts[:2]) == CASE_FOLDER)
    if len(parts) > (3 if deep else 2):
        raise Refused("folder too deep")
    if any(not FOLDER.fullmatch(p) for p in parts[1:-1]):
        raise Refused("bad folder name")
    name = parts[-1]
    if not name.endswith(".md") or not NAME.fullmatch(name[:-3]) or ".." in name:
        raise Refused("hidden part or not a .md note")
    return parts


def target_of(vault: Path, note, roots=(MINE,)) -> Path:
    """An existing note julz may change."""
    parts = check_path(note, roots)
    path = vault / note
    # The control: links on the way (a linked folder included) end up outside the root
    if not path.resolve().is_relative_to((vault / parts[0]).resolve()):
        raise Refused("path leaves its folder")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise Refused("no such note") from None
    if not stat.S_ISREG(st.st_mode):
        raise Refused("not a regular file")
    if st.st_size > MAX_NOTE_BYTES:
        raise Refused("note too big")
    return path


def new_target(vault: Path, note, roots, case: bool = False) -> Path:
    """A path for a new note: nothing there yet, every existing folder on the way real."""
    parts = check_path(note, roots, case)
    for i in range(1, len(parts)):
        p = vault.joinpath(*parts[:i])
        if os.path.lexists(p) and (os.path.islink(p) or not p.is_dir()):
            raise Refused("a folder on the way is a link or a file")
    # Every existing folder on the way is a real folder and no part can be "..", so the path
    # cannot leave its root
    path = vault / note
    if os.path.lexists(path):
        raise Refused("note exists, never overwritten")
    return path


def not_an_index(path: Path) -> None:
    head = path.read_text(encoding="utf-8", errors="replace")[:FRONT_MATTER_MAX + 10]
    if front(head)[0].get("kind") == "moc":
        raise Refused("an index note, rebuilt by julz-vault")


def read_note(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "rb") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise Refused("not a regular file")
        return f.read(MAX_NOTE_BYTES + 1)


def same_as_shown(data: bytes, digest) -> None:
    if hashlib.sha256(data).hexdigest() != digest:
        raise Refused("note changed since I confirmed")


def checked_text(text, limit: int, allow_empty: bool = False) -> str:
    if not isinstance(text, str):
        raise Refused("text is not a string")
    if not text.strip() and not allow_empty:
        raise Refused("empty text")
    if len(text) > limit:
        raise Refused("text too long")
    if text:
        reason = keep.check_text(text)
        if reason:
            raise Refused(reason)
    return text


# ---------- requests ----------

def check_request(raw: bytes) -> dict:
    """The request's shape: JSON, a known op, exactly its keys. The op checks come later."""
    if len(raw) > MAX_REQUEST_BYTES:
        raise Refused("request too big")
    try:
        req = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise Refused("not JSON") from None
    if not isinstance(req, dict) or req.get("op") not in OPS:
        raise Refused("unknown op")
    if set(req) != OPS[req["op"]][0]:
        raise Refused("wrong fields")
    return req


def _read_request(p: Path) -> bytes:
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise Refused("request is not a regular file")
        if st.st_size > MAX_REQUEST_BYTES:
            raise Refused("request too big")
        return os.read(fd, MAX_REQUEST_BYTES + 1)
    finally:
        os.close(fd)


# ---------- changes to a note ----------

def append(path: Path, text: str, today: date):
    fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC)
    with os.fdopen(fd, "r+b") as f:
        if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
            raise Refused("not a regular file")
        size = os.fstat(f.fileno()).st_size
        ends_newline = True
        if size:
            f.seek(size - 1)
            ends_newline = f.read(1) == b"\n"
        lead = "\n" if ends_newline else "\n\n"
        block = f"{lead}## Added by julz, {today.isoformat()}\n\n{text.strip()}\n"
        f.write(block.encode("utf-8"))


def with_reviewed(text: str, today: date) -> str:
    return with_field(text, "reviewed", today.isoformat())


def with_field(text: str, key: str, value: str) -> str:
    """The note with one front matter line set, front matter added when missing."""
    line = f"{key}: {value}"
    end = text.find("\n---", 3) if text.startswith("---\n") else -1
    if end == -1 or end > FRONT_MATTER_MAX:
        return f"---\n{line}\n---\n\n{text}"
    lines = text[4:end].split("\n") if end > 4 else []
    for i, l in enumerate(lines):
        if l.split(":", 1)[0].strip().lower() == key:
            lines[i] = line
            break
    else:
        lines.append(line)
    return "---\n" + "\n".join(lines) + text[end:]


def write_over(path: Path, new: str):
    """Replace the note with new text: written beside it and renamed over it."""
    mode = stat.S_IMODE(os.lstat(path).st_mode)
    tmp = path.with_name(f".tmp-{path.name}.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(new.encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def set_reviewed(path: Path, today: date):
    old = read_note(path).decode("utf-8")
    new = with_reviewed(old, today)
    if new != old:
        write_over(path, new)


def replace(path: Path, req: dict):
    data = read_note(path)
    same_as_shown(data, req["sha256"])
    old = checked_text(req["old"], MAX_APPEND_CHARS)
    new = checked_text(req["new"], MAX_APPEND_CHARS, allow_empty=True)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise Refused("note is not UTF-8") from None
    if text.count(old) != 1:
        raise Refused("passage not found exactly once")
    write_over(path, text.replace(old, new, 1))


def move(vault: Path, path: Path, req: dict) -> Path:
    same_as_shown(read_note(path), req["sha256"])
    dest = new_target(vault, req["to"], EDITABLE)
    dest.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.link(path, dest, follow_symlinks=False)  # fails if dest appeared: never overwrites
    os.unlink(path)
    return dest


def create(vault: Path, req: dict) -> Path:
    text = checked_text(req["text"], MAX_CREATE_CHARS)
    dest = new_target(vault, req["note"], OPS["create"][1], case=True)
    dest.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write(text.encode("utf-8"))
    return dest


def tick(path: Path, req: dict, today: date):
    """Tick exactly one open or in progress task line, named in full, and date it."""
    item = req["item"]
    if not isinstance(item, str) or not item.strip() or len(item) > MAX_ITEM or "\n" in item \
            or hidden(item):
        raise Refused("bad task text")
    text = read_note(path).decode("utf-8")
    pattern = re.compile(r"^(\s*[-*] )\[[ /]\] " + re.escape(item) + r"\s*$", re.M)
    if len(pattern.findall(text)) != 1:
        raise Refused("task not found exactly once")
    write_over(path, pattern.sub(lambda m: f"{m.group(1)}[x] {item} (done {today.isoformat()})",
                                 text, count=1))


def start(path: Path, req: dict) -> None:
    """Mark exactly one open task line, named in full, in progress: `[ ]` to `[/]` (127)."""
    item = req["item"]
    if not isinstance(item, str) or not item.strip() or len(item) > MAX_ITEM or "\n" in item \
            or hidden(item):
        raise Refused("bad task text")
    text = read_note(path).decode("utf-8")
    pattern = re.compile(r"^(\s*[-*] )\[ \] " + re.escape(item) + r"[ \t]*$", re.M)
    if len(pattern.findall(text)) != 1:
        raise Refused("task not found exactly once")
    write_over(path, pattern.sub(lambda m: f"{m.group(1)}[/] {item}", text, count=1))


def resolve(vault: Path, path: Path, today: date) -> Path:
    """A feedback note I said is solved moves to feedback/done/ with a dated last line. Only
    feedback/<name>.md (check_path keeps it one level), never over a name (threat 85)."""
    text = read_note(path).decode("utf-8", errors="replace")
    done = vault / "feedback" / "done"
    if os.path.lexists(done) and (done.is_symlink() or not done.is_dir()):
        raise Refused("feedback/done is a link or a file")
    done.mkdir(mode=0o755, exist_ok=True)
    dest, n = done / path.name, 2
    while os.path.lexists(dest):
        dest, n = done / f"{path.stem} {n}.md", n + 1
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    with os.fdopen(fd, "wb") as f:
        f.write((text.rstrip("\n") + f"\n\nSolved {today.isoformat()} by me\n").encode("utf-8"))
    os.unlink(path)
    return dest


OPEN_BOX = re.compile(r"^\s*[-*] \[[ /]\] ", re.M)  # in progress is not finished (127)
DONE_BOX = re.compile(r"^\s*[-*] \[[xX]\] ", re.M)


def archive_done(vault: Path, today: date) -> list[tuple[str, str]]:
    """Todo notes in Inbox/ and daily/ with every box ticked move to daily/done/, stamped
    completed. Mine from Obsidian too. Never overwrites: a taken name gets " 2", " 3"."""
    moved = []
    candidates = []
    for root in ("Inbox", "daily"):
        base = vault / root
        if base.is_dir() and not base.is_symlink():
            candidates += base.glob("*.md") if root == "Inbox" else base.rglob("*.md")
    for p in sorted(candidates):
        rel = p.relative_to(vault)
        if rel.parts[:2] == ("daily", "done") or any(x.startswith(".") for x in rel.parts) \
                or p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_NOTE_BYTES:
            continue
        text = read_note(p).decode("utf-8", errors="replace")
        meta, body = front(text)
        if "todo" not in tags(meta) or OPEN_BOX.search(body) or not DONE_BOX.search(body):
            continue
        done = vault / "daily" / "done"
        done.mkdir(mode=0o755, parents=True, exist_ok=True)
        dest, n = done / p.name, 2
        while os.path.lexists(dest):
            dest, n = done / f"{p.stem} {n}.md", n + 1
        fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(with_field(text, "completed", today.isoformat()).encode("utf-8"))
        os.unlink(p)
        moved.append((str(rel), str(dest.relative_to(vault))))
    return moved


# ---------- index notes ----------

def _title(body: str, stem: str) -> str:
    first = next((l.strip() for l in body.splitlines() if l.strip()), "")
    title = first.lstrip("#").strip()
    if not title or len(title) > MAX_TITLE or hidden(title) or any(c in title for c in "[]|"):
        return stem
    return title


def update_indexes(vault: Path) -> list[str]:
    """One index note per study/ folder: its notes, and notes elsewhere tagged with its name.
    Built only from paths and first headings. A note of mine with that name is left alone."""
    study = vault / MINE
    if not study.is_dir() or study.is_symlink():
        return []
    notes = []
    for p in sorted(study.rglob("*.md")):
        rel = p.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts) or p.is_symlink() \
                or not p.is_file() \
                or p.stat().st_size > MAX_NOTE_BYTES:
            continue
        meta, body = front(p.read_text(encoding="utf-8", errors="replace"))
        if meta.get("kind") == "moc":
            continue
        folder = rel.parts[1] if len(rel.parts) == 3 else None
        notes.append((rel.with_suffix("").as_posix(), _title(body, p.stem), tags(meta), folder))
    written = []
    for d in sorted(e for e in study.iterdir()
                    if e.is_dir() and not e.is_symlink() and FOLDER.fullmatch(e.name)):
        here = [n for n in notes if n[3] == d.name]
        tagged = [n for n in notes if d.name in n[2] and n[3] != d.name]
        index = d / f"{d.name}.md"
        if not here and not tagged:
            continue
        if os.path.lexists(index):
            if index.is_symlink() or not index.is_file():
                continue
            if front(index.read_text(encoding="utf-8", errors="replace"))[0].get("kind") != "moc":
                continue  # my own note of that name
        lines = ["---", "kind: moc", "---", "", f"# {d.name}", "",
                 "Made by julz-vault from this folder and the tags. Changes here are replaced.", ""]
        if here:
            lines += ["## In this folder", *[f"- [[{r}|{t}]]" for r, t, _, _ in here], ""]
        if tagged:
            lines += [f"## Tagged {d.name} elsewhere", *[f"- [[{r}|{t}]]" for r, t, _, _ in tagged], ""]
        text = "\n".join(lines)
        if index.exists() and index.read_text(encoding="utf-8", errors="replace") == text:
            continue
        if index.exists():
            write_over(index, text)
        else:
            fd = os.open(index, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
            with os.fdopen(fd, "wb") as f:
                f.write(text.encode("utf-8"))
        written.append(str(index.relative_to(vault)))
    return written


# ---------- due count for the push ----------

def due_count(vault: Path, today: date) -> int:
    """How many of my study notes are due for review, by the tool's rules. Written for
    julz-notify, so the unit that talks to ntfy.sh never reads a note."""
    study = vault / MINE
    if not study.is_dir() or study.is_symlink():
        return 0
    count = 0
    for p in study.rglob("*.md"):
        rel = p.relative_to(vault)
        if any(part.startswith(".") for part in rel.parts) or p.is_symlink() \
                or not p.is_file() or p.stat().st_size > MAX_NOTE_BYTES:
            continue
        meta, _ = front(p.read_text(encoding="utf-8", errors="replace"))
        if meta.get("kind") == "moc":
            continue
        every = REVIEW_DAYS.get(meta.get("status", "").lower(), DEFAULT_REVIEW_DAYS)
        try:
            due = (today - date.fromisoformat(meta.get("reviewed", ""))).days >= every
        except ValueError:
            due = True  # never reviewed
        count += due
    return count



# ---------- todo snapshot for the phone (threat 100) ----------

MAX_TODO_LISTS = 8
MAX_TODO_ITEMS = 20
MAX_TODO_TEXT = 80
MAX_TODO_DONE = 10  # done tasks in the whole snapshot (113)
MAX_DONE_PER_LIST = 3
TODO_SEPARATORS = ("\u241e", "\u241f")  # the message format's separators never inside a task
OPEN_ITEM = re.compile(r"^\s*[-*] \[ \] (.+?)\s*$", re.M)
DOING_ITEM = re.compile(r"^\s*[-*] \[/\] (.+?)\s*$", re.M)  # in progress, the Obsidian Tasks mark (127)
DONE_ITEM = re.compile(r"^\s*[-*] \[[xX]\] ", re.M)
# A ticked task and the date tick() wrote after it, if any
DONE_TEXT = re.compile(r"^\s*[-*] \[[xX]\] (.+?)(?: \(done (\d{4}-\d{2}-\d{2})\))?\s*$", re.M)
LIST_NAME = re.compile(r"\w[\w .-]{0,39}")
# The notes tool's plain text rule: nothing a renderer could turn into a link or an image
NOT_PLAIN = re.compile(r"!\[|\]\(|<[A-Za-z!?/]|://|(?i:\bwww\.)")


def _travels(text: str) -> bool:
    """A task or list name may go to the phone: short, plain, no link, secret or hidden mark."""
    try:
        checked_text(text, MAX_TODO_TEXT)
    except Refused:
        return False
    return not any(sep in text for sep in TODO_SEPARATORS) and not NOT_PLAIN.search(text)


def todo_snapshot(vault: Path) -> dict:
    """My open tasks from Inbox/ and daily/ (not daily/done/), for julz-notify to post to my
    own server. Written here, where there is no network, so the unit that posts never reads a
    note. Tasks that may not travel are left out; at most MAX_TODO_LISTS and MAX_TODO_ITEMS."""
    candidates = []
    for root in ("Inbox", "daily"):
        base = vault / root
        if base.is_dir() and not base.is_symlink():
            candidates += base.glob("*.md") if root == "Inbox" else base.rglob("*.md")
    lists, items, done_shown = [], 0, 0
    for p in sorted(candidates):
        rel = p.relative_to(vault)
        if rel.parts[:2] == ("daily", "done") or any(x.startswith(".") for x in rel.parts) \
                or p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_NOTE_BYTES:
            continue
        name = p.stem
        if not LIST_NAME.fullmatch(name) or not _travels(name):
            continue
        body = read_note(p).decode("utf-8", errors="replace")
        open_items, doing_items = OPEN_ITEM.findall(body), DOING_ITEM.findall(body)
        if not open_items and not doing_items:
            continue
        done = len(DONE_ITEM.findall(body))
        doing = [t for t in doing_items if _travels(t)][:MAX_TODO_ITEMS - items]
        shown = [t for t in open_items if _travels(t)][:MAX_TODO_ITEMS - items - len(doing)]
        if not shown and not doing:
            continue
        # Newest first by the date tick() wrote; undated ones (ticked in Obsidian) last
        ticked = sorted(((d or "", t) for t, d in DONE_TEXT.findall(body) if _travels(t)),
                        key=lambda x: x[0], reverse=True)
        done_items = [t for _, t in ticked][:min(MAX_DONE_PER_LIST, MAX_TODO_DONE - done_shown)]
        done_shown += len(done_items)
        lists.append({"name": name, "note": str(rel), "done": done, "total": done + len(open_items) + len(doing_items),
                      "open": shown, "doing": doing, "done_items": done_items})
        items += len(shown) + len(doing)
        if len(lists) == MAX_TODO_LISTS or items == MAX_TODO_ITEMS:
            break
    return {"id": snapshot_id(lists), "lists": lists}


DONE_DAYS = 7
MAX_DONE_WEEK = 60


def done_week(vault: Path, today: date) -> dict:
    """Tasks ticked in the last DONE_DAYS days, finished lists in daily/done/ too, newest day
    first, for the app's Done tab (threat 114). Only ticks with the date tick() wrote, only what
    may travel, at most MAX_DONE_WEEK."""
    first = (today - timedelta(days=DONE_DAYS - 1)).isoformat()
    candidates = []
    for root in ("Inbox", "daily"):
        base = vault / root
        if base.is_dir() and not base.is_symlink():
            candidates += base.glob("*.md") if root == "Inbox" else base.rglob("*.md")
    found = []
    for p in sorted(candidates):
        rel = p.relative_to(vault)
        if any(x.startswith(".") for x in rel.parts) or p.is_symlink() or not p.is_file() \
                or p.stat().st_size > MAX_NOTE_BYTES:
            continue
        name = p.stem
        if not LIST_NAME.fullmatch(name) or not _travels(name):
            continue
        body = read_note(p).decode("utf-8", errors="replace")
        found += [(d, name, t) for t, d in DONE_TEXT.findall(body)
                  if first <= d <= today.isoformat() and _travels(t)]  # undated: "" < first
    found.sort(key=lambda x: x[0], reverse=True)  # stable: notes and lines keep their order
    days: list[dict] = []
    for d, name, item in found[:MAX_DONE_WEEK]:
        if not days or days[-1]["date"] != d:
            days.append({"date": d, "items": []})
        days[-1]["items"].append({"list": name, "item": item})
    return {"date": today.isoformat(), "days": days}


# ---------- the Inbox on the phone (threats 116, 117) ----------

MAX_INBOX_NOTES = 20
MAX_PREVIEW = 2000
INBOX_HEAD = re.compile(r"inbox: ([0-9a-f]{64})")


def _shown(text: str) -> str:
    """Text for a phone screen: hidden, control and bidi characters become U+FFFD, so the
    screen cannot say something else than the file (Trojan Source). Newlines and tabs stay."""
    return "".join("\ufffd" if c not in "\n\t" and unicodedata.category(c) in gate.BAD_CATEGORIES
                   else c for c in text)


def inbox_id(notes: list, folders: list) -> str:
    return hashlib.sha256(json.dumps({"notes": notes, "folders": folders}, sort_keys=True,
                                     ensure_ascii=False).encode()).hexdigest()


def inbox_snapshot(vault: Path) -> dict:
    """My top level Inbox notes with their hash and a preview, and the folders a note may move
    to, for the app (116). Never Inbox/claude/ or .requests/, never a link."""
    notes = []
    inbox = vault / "Inbox"
    if inbox.is_dir() and not inbox.is_symlink():
        for p in sorted(inbox.glob("*.md")):
            if len(notes) == MAX_INBOX_NOTES:
                break
            if p.is_symlink() or not p.is_file() or not NAME.fullmatch(p.stem) \
                    or p.stat().st_size > MAX_NOTE_BYTES:
                continue
            data = read_note(p)
            notes.append({"name": p.stem, "note": f"Inbox/{p.name}",
                          "sha256": hashlib.sha256(data).hexdigest(), "size": len(data),
                          "modified": date.fromtimestamp(p.stat().st_mtime).isoformat(),
                          "preview": _shown(data.decode("utf-8", errors="replace")[:MAX_PREVIEW])})
    folders = []
    for root in ("daily", "study"):
        base = vault / root
        if not base.is_dir() or base.is_symlink():
            continue
        folders.append(root)
        folders += [f"{root}/{e.name}" for e in sorted(os.scandir(base), key=lambda e: e.name)
                    if e.is_dir(follow_symlinks=False) and FOLDER.fullmatch(e.name)
                    and f"{root}/{e.name}" != "daily/done"]
    return {"id": inbox_id(notes, folders), "notes": notes, "folders": folders}


MAX_NOTES_SHOWN = 300
MAX_NOTE_TEXT = 4000
NOTES_ROOTS = ("study", "daily", "Inbox", "Claude", "Outbox", "feedback")
# Tags for the notes browser (212, threat 149): a letter first, then letters, digits, _ - /
MAX_TAG_CHARS = 40
TAG = re.compile(rf"[\w/-]{{1,{MAX_TAG_CHARS}}}")
INLINE_TAG = re.compile(r"(?<!\S)#([\w/-]+)")
CODE = re.compile(r"```.*?(```|\Z)|`[^`\n]*`", re.S)
MAX_NOTE_TAGS = 10
MAX_TAGS = 200
# The most notes.json can hold: 300 notes of 4000 characters, 6 bytes a letter once JSON
# escapes it, plus room for names and keys and the most tags (149). Its readers cap at this,
# less and a full vault reads as empty (148) or cut (213)
MAX_NOTES_JSON = MAX_NOTES_SHOWN * (MAX_NOTE_TEXT * 6 + 1000 + MAX_NOTE_TAGS * (MAX_TAG_CHARS * 6 + 4))


def is_tag(t) -> bool:
    return isinstance(t, str) and bool(TAG.fullmatch(t)) and t[0].isalpha() and t == t.lower()


def note_tags(text: str, known: set) -> list[str]:
    """The tags of a note, front matter first, then each #tag in the text outside code, lower
    case. At most MAX_NOTE_TAGS a note; a tag new to [known] only while it holds fewer than
    MAX_TAGS, and it is added there. Anything not shaped like a tag is left out."""
    meta, body = front(text)
    found = [t.strip("'\" ").lstrip("#").lower() for t in tags(meta)]
    found += [m.group(1).lower() for m in INLINE_TAG.finditer(CODE.sub(" ", body))]
    out = []
    for t in found:
        if len(out) == MAX_NOTE_TAGS:
            break
        if is_tag(t) and t not in out and (t in known or len(known) < MAX_TAGS):
            known.add(t)
            out.append(t)
    return out


def notes_snapshot(vault: Path) -> dict:
    """Every folder I may browse on the phone, with its notes and their text, read only (118).
    Inbox only at its top (never claude/ or .requests/); no Templates, settings, links or
    hidden names. Text capped, hidden and bidi characters marked (116)."""
    by_folder: dict[str, list] = {}
    count = 0
    known: set = set()
    for root in NOTES_ROOTS:
        base = vault / root
        if not base.is_dir() or base.is_symlink():
            continue
        paths = base.glob("*.md") if root == "Inbox" else base.rglob("*.md")
        for p in sorted(paths):
            rel = p.relative_to(vault)
            if count == MAX_NOTES_SHOWN:
                break
            if any(x.startswith(".") for x in rel.parts) or p.is_symlink() or not p.is_file() \
                    or not NAME.fullmatch(p.stem) or p.stat().st_size > MAX_NOTE_BYTES \
                    or any((vault / q).is_symlink() for q in rel.parents):  # rglob follows linked folders before Python 3.13
                continue
            data = read_note(p)
            text = data.decode("utf-8", errors="replace")
            folder = str(rel.parent)
            by_folder.setdefault(folder, []).append({
                "name": p.stem, "note": str(rel), "size": len(data),
                "modified": date.fromtimestamp(p.stat().st_mtime).isoformat(),
                "text": _shown(text[:MAX_NOTE_TEXT]), "tags": note_tags(text, known)})
            count += 1
    return {"folders": [{"folder": f, "notes": by_folder[f]} for f in sorted(by_folder)]}


def inbox_text(snapshot: dict, picks) -> str:
    """The text I sign to move or delete Inbox notes from the phone, built from the snapshot
    only, in its order (117). A move keeps the file name and goes to a listed folder."""
    if not isinstance(picks, list) or not 1 <= len(picks) <= MAX_INBOX_NOTES:
        raise Refused(f"pick 1 to {MAX_INBOX_NOTES} notes")
    known = {n["note"] for n in snapshot["notes"]}
    wanted = {}
    for p in picks:
        keys = {"note", "do", "to"} if isinstance(p, dict) and p.get("do") == "move" else {"note", "do"}
        if not isinstance(p, dict) or set(p) != keys or not all(isinstance(v, str) for v in p.values()):
            raise Refused("a pick is a note, delete or move, and a folder for a move")
        if p["do"] not in ("delete", "move"):
            raise Refused("delete or move only")
        if p["note"] not in known:
            raise Refused("not in this Inbox snapshot: reload")
        if p["do"] == "move" and p["to"] not in snapshot["folders"]:
            raise Refused("not a folder a note may go to")
        if p["note"] in wanted:
            raise Refused("a note picked twice")
        wanted[p["note"]] = p
    lines = []
    for n in snapshot["notes"]:
        p = wanted.get(n["note"])
        if p is None:
            continue
        name = n["note"].split("/", 1)[1]
        lines.append(f"delete: {n['note']}\n" if p["do"] == "delete"
                     else f"move: {n['note']} -> {p['to']}/{name}\n")
    return f"inbox: {snapshot['id']}\n" + "".join(lines)


def inbox_requests(text: str, snapshot: dict) -> list[dict]:
    """The vault requests for a signed inbox text, each with the note's hash from the snapshot
    it was built from: another snapshot, or a line inbox_text() could not have built, refuses."""
    if not isinstance(text, str) or not text.endswith("\n"):
        raise Refused("not an inbox text")
    head, *lines = text[:-1].split("\n")
    m = INBOX_HEAD.fullmatch(head)
    if not m or not 1 <= len(lines) <= MAX_INBOX_NOTES:
        raise Refused("not an inbox text")
    if m.group(1) != snapshot["id"]:
        raise Refused("the Inbox changed since I signed: reload")
    sha = {n["note"]: n["sha256"] for n in snapshot["notes"]}
    out = []
    for line in lines:
        do, sep, rest = line.partition(": ")
        note, arrow, dest = rest.partition(" -> ")
        if not sep or note not in sha or do not in ("delete", "move") or bool(arrow) != (do == "move"):
            raise Refused("not an inbox line")
        if do == "delete":
            out.append({"op": "delete", "note": note, "sha256": sha[note]})
            continue
        folder, _, name = dest.rpartition("/")
        if folder not in snapshot["folders"] or name != note.split("/", 1)[1]:
            raise Refused("not an inbox line")
        out.append({"op": "move", "note": note, "to": dest, "sha256": sha[note]})
    return out


# ---------- feedback written in the app (threat 120) ----------

FEEDBACK_KINDS = ("bug", "idea", "change")
MAX_FEEDBACK = 2000
MAX_FEEDBACK_OPEN = 50
MAX_FEEDBACK_DONE = 20
MAX_FEEDBACK_PREVIEW = 600


def feedback_text(kind, text) -> str:
    """The text I sign to leave feedback from the phone: the kind, then my words, checked like
    a Keep (no links, images, HTML, secrets or hidden characters)."""
    if kind not in FEEDBACK_KINDS:
        raise Refused("bug, idea or change")
    return f"feedback: {kind}\n{_feedback_body(text)}\n"


def _feedback_body(text) -> str:
    """Plain words only: the Keep check, and no address at all, since Claude reads these (120)."""
    body = checked_text(text, MAX_FEEDBACK).strip()
    if NOT_PLAIN.search(body):
        raise Refused("plain text, no links or markup")
    return body


def feedback_request(signed: str, now) -> dict:
    """The vault's own create request for a signed feedback text, as the chat's save_feedback
    writes it (81), with the kind and state for the list. A name with the time is never taken."""
    if not isinstance(signed, str) or not signed.endswith("\n"):
        raise Refused("not a feedback text")
    head, _, body = signed[:-1].partition("\n")
    kind = head.removeprefix("feedback: ")
    if head == kind or kind not in FEEDBACK_KINDS:
        raise Refused("not a feedback text")
    body = _feedback_body(body)
    slug = "-".join(re.findall(r"[a-z0-9]+", body.lower())[:5])[:40] or "note"
    day = now.strftime("%Y-%m-%d")
    return {"op": "create", "note": f"feedback/{day} {slug} {now:%H%M%S}.md",
            "text": f"---\ntags:\n  - feedback\ncreated: {day}\nkind: {kind}\nstate: new\nfrom: phone\n---\n\n"
                    f"# Feedback {day}\n\n{body}\n"}


MAX_SAVE = 3800  # the app shows and signs at most 4096 characters (109)
SAVE_HEAD = "save: chat answer"
SAVE_CUT = "(cut here: the whole answer stays in the chat)"


SAVE_IMAGE = re.compile(r"!\[([^\]\n]*)\]\([^)\n]*\)")
SAVE_LINK = re.compile(r"\[([^\]\n]+)\]\(([^)\s]*)\)")


def defang(text: str) -> str:
    """Web addresses readable but never working, as a SOC shares a bad URL: no scheme, no www.
    The vault keeps no working address (the Keep check); images become a label."""
    text = SAVE_IMAGE.sub(lambda m: f"[image: {m.group(1).strip() or 'image'}]", text)
    text = SAVE_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", text)

    def bare(m):
        url = m.group()
        cut = len(url.rstrip(keep.URL_TAIL))
        core = re.sub(r"(?i)^(?:[a-z][a-z0-9+.-]*://)?(?:www\.)?", "", url[:cut])
        return core + url[cut:]
    return keep.URL.sub(bare, text)


def save_text(text) -> str:
    """The text I sign to save a chat answer into Inbox (139): a fixed head, then the answer
    as Julz wrote it, Markdown kept, addresses defanged, checked like a Keep, cut at MAX_SAVE."""
    if not isinstance(text, str):
        raise Refused("text is not a string")
    body = defang(text).strip()
    if len(body) > MAX_SAVE:
        body = body[:MAX_SAVE].rstrip() + "\n\n" + SAVE_CUT
    return f"{SAVE_HEAD}\n{checked_text(body, MAX_SAVE + 2 + len(SAVE_CUT))}\n"


def save_request(signed: str, now) -> dict:
    """The vault's own create request for a signed save text: a new note in Inbox, named by
    the time and the answer's first words, never overwritten."""
    if not isinstance(signed, str) or not signed.endswith("\n"):
        raise Refused("not a save text")
    head, _, body = signed[:-1].partition("\n")
    if head != SAVE_HEAD:
        raise Refused("not a save text")
    body = checked_text(body, MAX_SAVE + 2 + len(SAVE_CUT)).strip()
    slug = "-".join(re.findall(r"[a-z0-9]+", body.lower())[:5])[:40] or "answer"
    day = now.strftime("%Y-%m-%d")
    return {"op": "create", "note": f"Inbox/{day} {slug} {now:%H%M%S}.md",
            "text": f"---\ntags:\n  - chat\ncreated: {day}\nfrom: julz chat\n---\n\n"
                    f"# Saved from the chat {day}\n\n{body}\n"}


# ---------- a bad answer kept as an eval case (threat 153) ----------

CASE_HEAD = "case: bad answer"
CASE_MODES = ("none", "learn", "unknown")
CASE_FOLDER = ("feedback", "eval")
MAX_CASE_Q = 1200
MAX_CASE_A = 2400
CASE_CUT = "(cut here: the whole text stays in the chat)"
CASE_LEN = re.compile(r"[1-9][0-9]{0,4}")


def _case_part(text, cap: int) -> str:
    if not isinstance(text, str):
        raise Refused("text is not a string")
    body = defang(text).strip()
    if len(body) > cap:
        body = body[:cap].rstrip() + "\n\n" + CASE_CUT
    return checked_text(body, cap + 2 + len(CASE_CUT))


def case_text(question, answer, mode) -> str:
    """The text I sign to keep a bad answer as an eval case (153): a fixed head, the mode as a
    fixed word, my question with its length, her answer; each defanged, checked, cut at its cap."""
    if mode not in CASE_MODES:
        raise Refused("unknown mode")
    q, a = _case_part(question, MAX_CASE_Q), _case_part(answer, MAX_CASE_A)
    return f"{CASE_HEAD}\nmode: {mode}\nquestion: {len(q)}\n{q}\nanswer:\n{a}\n"


def case_request(signed: str, now) -> dict:
    """The vault's own create request for a signed case: a new note in feedback/eval/, never
    synced into Julz's knowledge, named by the time and the question's first words."""
    if not isinstance(signed, str) or not signed.endswith("\n"):
        raise Refused("not a case text")
    lines = signed.split("\n", 3)
    if len(lines) != 4 or lines[0] != CASE_HEAD or not lines[1].startswith("mode: ") \
            or lines[1][6:] not in CASE_MODES or not lines[2].startswith("question: ") \
            or not CASE_LEN.fullmatch(lines[2][10:]):
        raise Refused("not a case text")
    mode, n, rest = lines[1][6:], int(lines[2][10:]), lines[3]
    q, a = rest[:n], rest[n:]
    if not a.startswith("\nanswer:\n"):
        raise Refused("not a case text")
    q = checked_text(q, MAX_CASE_Q + 2 + len(CASE_CUT))
    a = checked_text(a[9:-1], MAX_CASE_A + 2 + len(CASE_CUT))
    if q != q.strip() or a != a.strip():
        raise Refused("not a case text")
    slug = "-".join(re.findall(r"[a-z0-9]+", q.lower())[:5])[:40] or "case"
    day = now.strftime("%Y-%m-%d")
    return {"op": "create", "note": f"{'/'.join(CASE_FOLDER)}/{day} {slug} {now:%H%M%S}.md",
            "text": f"---\ntags:\n  - eval-case\ncreated: {day}\nfrom: phone\nmode: {mode}\n"
                    f"state: new\nquestion_chars: {n}\n---\n\n# Bad answer {day}\n\n"
                    f"## Question\n\n{q}\n\n## Answer\n\n{a}\n"}


def feedback_snapshot(vault: Path) -> dict:
    """Open and done feedback, newest first, with the state and place Claude Code wrote into
    each note when sorting it into BACKLOG.md, for the app's list (120)."""
    items = []
    for done, folder, cap in ((False, vault / "feedback", MAX_FEEDBACK_OPEN),
                              (True, vault / "feedback" / "done", MAX_FEEDBACK_DONE)):
        if not folder.is_dir() or folder.is_symlink():
            continue
        found = [p for p in sorted(folder.glob("*.md"), reverse=True)
                 if not p.name.startswith(".") and not p.is_symlink() and p.is_file()
                 and NAME.fullmatch(p.stem) and p.stat().st_size <= MAX_NOTE_BYTES]
        for p in found[:cap]:
            meta, body = front(read_note(p).decode("utf-8", errors="replace"))
            lines = [l for l in body.strip().splitlines() if not l.startswith("# Feedback")]
            items.append({"name": p.stem, "done": done, "created": meta.get("created", ""),
                          "kind": meta.get("kind", "") if meta.get("kind", "") in FEEDBACK_KINDS else "",
                          "state": "done" if done else (meta.get("state") or "new")[:20],
                          "where": meta.get("where", "")[:60],
                          "text": _shown("\n".join(lines).strip()[:MAX_FEEDBACK_PREVIEW])})
    return {"items": items}


# ---------- goals next to todos (threat 123) ----------

MAX_GOALS = 20
MAX_GOAL_TEXT = 120
GOAL_LINE = re.compile(r"^\s*[-*] \[([ xX])\] (.+?)\s*$", re.M)
TASK_LINE = re.compile(r"^\s*[-*] \[([ xX/])\] (.+?)\s*$", re.M)
GOAL_TAG = re.compile(r"#goal/([a-z0-9][a-z0-9-]{0,39})")
GOAL_COUNT = re.compile(r"\((\d{1,4})/(\d{1,4})\)")
GOAL_HEAD = re.compile(r"goal: ([0-9a-f]{64})")
GOAL_DONE_DATE = re.compile(r" \(done \d{4}-\d{2}-\d{2}\)$")
GOAL_IN = re.compile(r"\[in:: ([a-z0-9][a-z0-9-]{0,39})\]")
GOAL_DUE = re.compile(r"\[due:: (\d{4}-\d{2}-\d{2})\]")
DUE_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
MAX_DUE_DAYS = 3653  # ten years
MAX_MILESTONES = 20
# Hours (129): quarter hours, held as whole minutes, written by code as a plain number and h
GOAL_EST = re.compile(r"\[est:: (\d{1,4}(?:\.\d{1,2})?)h\]")
GOAL_SPENT = re.compile(r"\[spent:: (\d{1,4}(?:\.\d{1,2})?)h\]")
HOURS_IN = re.compile(r"\d{1,3}(?:\.(?:0|25|5|75))?")
MAX_EST_MIN, MAX_LOG_MIN, MAX_SPENT_MIN = 999 * 60, 24 * 60, 9999 * 60
MAX_GOAL_FILES = 60
MAX_TREE_DEPTH = 6


def goal_periods(today: date) -> list[tuple[str, str, str]]:
    """(key, label, note) for today, this ISO week, this month and this year."""
    iso = today.isocalendar()
    week = f"{iso[0]}-W{iso[1]:02d}"
    return [(today.isoformat(), "Today", f"goals/{today.isoformat()}.md"),
            (week, "This week", f"goals/{week}.md"),
            (today.strftime("%Y-%m"), today.strftime("%B"), f"goals/{today:%Y-%m}.md"),
            (str(today.year), str(today.year), f"goals/{today.year}.md")]


def _goal_plain(text: str, limit: int) -> bool:
    try:
        checked_text(text, limit)
    except Refused:
        return False
    return not NOT_PLAIN.search(text)


def goals_snapshot(vault: Path, today: date) -> dict:
    """The goals of the four current periods for the app (123), each with its own (n/m) and,
    when it has a #goal/<id> tag, the progress of todos carrying that tag, computed here."""
    linked: dict[str, list[int]] = {}
    linked_hours: dict[str, list[int]] = {}  # goal id -> [spent, estimate] minutes of its todos (129)
    for root in ("Inbox", "daily"):
        base = vault / root
        if not base.is_dir() or base.is_symlink():
            continue
        for p in (base.glob("*.md") if root == "Inbox" else base.rglob("*.md")):
            if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_NOTE_BYTES:
                continue
            # A task in progress ([/]) counts toward the goal as not done yet (127)
            for mark, line in TASK_LINE.findall(read_note(p).decode("utf-8", errors="replace")):
                for gid in set(GOAL_TAG.findall(line)):
                    c = linked.setdefault(gid, [0, 0])
                    c[1] += 1
                    c[0] += mark in "xX"
                    h = linked_hours.setdefault(gid, [0, 0])
                    h[0] += _minutes_of(line, GOAL_SPENT) or 0
                    h[1] += _minutes_of(line, GOAL_EST) or 0
    # The whole tree, from every note in goals/: id -> done, own count, parent (125)
    nodes: dict[str, dict] = {}
    anonymous: dict[str, list[float]] = {}  # children without an id: parent -> their own progress
    anonymous_hours: dict[str, list[int]] = {}  # and their own [spent, estimate] minutes
    gdir = vault / "goals"
    if gdir.is_dir() and not gdir.is_symlink():
        for p in sorted(gdir.glob("*.md"))[:MAX_GOAL_FILES]:
            if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_NOTE_BYTES:
                continue
            for mark, text in GOAL_LINE.findall(read_note(p).decode("utf-8", errors="replace")):
                tag = GOAL_TAG.search(text)
                count = GOAL_COUNT.search(text)
                parent = GOAL_IN.search(text)
                if tag and tag.group(1) not in nodes:
                    nodes[tag.group(1)] = {"done": mark in "xX", "parent": parent.group(1) if parent else None,
                                           "count": (int(count.group(1)), int(count.group(2))) if count else None,
                                           "due": _due_of(text), "text": GOAL_DONE_DATE.sub("", text),
                                           "spent": _minutes_of(text, GOAL_SPENT) or 0, "est": _minutes_of(text, GOAL_EST) or 0}
                elif not tag and parent:
                    own = 1.0 if mark in "xX" else (min(int(count.group(1)) / int(count.group(2)), 1.0)
                                                   if count and int(count.group(2)) else 0.0)
                    anonymous.setdefault(parent.group(1), []).append(own)
                    h = anonymous_hours.setdefault(parent.group(1), [0, 0])
                    h[0] += _minutes_of(text, GOAL_SPENT) or 0
                    h[1] += _minutes_of(text, GOAL_EST) or 0
    children: dict[str, list[str]] = {}
    for gid, n in nodes.items():
        if n["parent"]:
            children.setdefault(n["parent"], []).append(gid)

    def parts_of(gid: str, depth: int, seen: frozenset) -> list[float]:
        """Each part of a goal as 0 to 1: child goals by their own progress, linked todos 0 or 1.
        A cycle or a chain deeper than MAX_TREE_DEPTH ends (CWE-835)."""
        if gid in seen or depth > MAX_TREE_DEPTH:
            return []
        out = [fraction(c, depth + 1, seen | {gid}) or 0.0 for c in children.get(gid, [])] + anonymous.get(gid, [])
        d, total = linked.get(gid, [0, 0])
        return out + [1.0] * d + [0.0] * (total - d)

    def fraction(gid: str, depth: int, seen: frozenset) -> float | None:
        n = nodes.get(gid)
        if n is None or gid in seen or depth > MAX_TREE_DEPTH:
            return None
        if n["done"]:
            return 1.0
        # An estimate makes hours logged the measure, not its count or todos (126b)
        spent, est = hours_of(gid, depth, seen)
        if est:
            return min(spent / est, 1.0)
        parts = parts_of(gid, depth, seen)
        if n["count"] and n["count"][1]:
            parts.append(min(n["count"][0] / n["count"][1], 1.0))
        return sum(parts) / len(parts) if parts else None

    def hours_of(gid: str, depth: int, seen: frozenset) -> list[int]:
        """[spent, estimate] minutes: the goal's own, its linked todos', its children's, with the
        same cycle and depth guard as the roll up (129)."""
        n = nodes.get(gid)
        if n is None or gid in seen or depth > MAX_TREE_DEPTH:
            return [0, 0]
        out = [n["spent"] + linked_hours.get(gid, [0, 0])[0] + anonymous_hours.get(gid, [0, 0])[0],
               n["est"] + linked_hours.get(gid, [0, 0])[1] + anonymous_hours.get(gid, [0, 0])[1]]
        for c in children.get(gid, []):
            s, e = hours_of(c, depth + 1, seen | {gid})
            out = [out[0] + s, out[1] + e]
        return out

    periods = []
    for key, label, rel in goal_periods(today):
        p = vault / rel
        goals = []
        if p.is_file() and not p.is_symlink() and p.stat().st_size <= MAX_NOTE_BYTES:
            for mark, text in GOAL_LINE.findall(read_note(p).decode("utf-8", errors="replace")):
                text = GOAL_DONE_DATE.sub("", text)
                if len(goals) == MAX_GOALS or not _goal_plain(text, MAX_GOAL_TEXT + 60):
                    continue
                count = GOAL_COUNT.search(text)
                tag = GOAL_TAG.search(text)
                parent = GOAL_IN.search(text)
                gid = tag.group(1) if tag else None
                parts = len(parts_of(gid, 0, frozenset())) if gid else 0
                own = [_minutes_of(text, GOAL_SPENT), _minutes_of(text, GOAL_EST)]
                hours = hours_of(gid, 0, frozenset()) if gid else [own[0] or 0, own[1] or 0]
                if gid and parts:
                    f = fraction(gid, 0, frozenset())
                else:  # nothing under it: its hours are the measure, if it has an estimate (126b)
                    f = (1.0 if mark in "xX" else min(hours[0] / hours[1], 1.0)) if hours[1] else None
                goals.append({"text": text, "done": mark in "xX",
                              "progress": [int(count.group(1)), int(count.group(2))] if count else None,
                              "goal": gid, "linked": linked.get(gid) if gid else None,
                              "parent": parent.group(1) if parent else None,
                              "rollup": round(f * 100) if f is not None else None, "parts": parts,
                              "due": _due_of(text), "spent": own[0], "est": own[1],
                              "hours": hours if any(hours) else None})
        periods.append({"key": key, "label": label, "note": rel, "goals": goals})
    tree = {gid: n["parent"] for gid, n in nodes.items()}
    # Milestones: open goals with a date, from all of goals/, soonest first (126)
    milestones = []
    for gid, n in sorted(nodes.items(), key=lambda kv: (kv[1]["due"] or "", kv[0])):
        if n["due"] and not n["done"] and _goal_plain(n["text"], MAX_GOAL_TEXT + 60) and len(milestones) < MAX_MILESTONES:
            f = fraction(gid, 0, frozenset())
            milestones.append({"goal": gid, "text": n["text"], "due": n["due"],
                               "rollup": round(f * 100) if f is not None else None})
    return {"id": hashlib.sha256(json.dumps([periods, tree, milestones], sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            "periods": periods, "tree": tree, "milestones": milestones}


def _minutes_of(text: str, field: re.Pattern) -> int | None:
    """A goal's or todo's [est:: ] or [spent:: ] as whole minutes, when it is a sane number."""
    m = field.search(text)
    if not m:
        return None
    minutes = round(float(m.group(1)) * 60)
    return minutes if 0 < minutes <= MAX_SPENT_MIN else None


def _hours(value, cap: int) -> int:
    """Hours from the phone: quarter hours as text, 0.25 up to the cap, as whole minutes (129)."""
    if not isinstance(value, str) or not HOURS_IN.fullmatch(value):
        raise Refused("hours are a number in quarter hours, like 1.5")
    minutes = round(float(value) * 60)
    if not 15 <= minutes <= cap:
        raise Refused(f"hours are from 0.25 to {cap // 60}")
    return minutes


def _fmt_hours(minutes: int) -> str:
    return f"{minutes / 60:g}h"


def _set_field(item: str, field: re.Pattern, name: str, minutes: int) -> str:
    """The line with one [name:: Nh], an old one replaced where it stood."""
    new = f"[{name}:: {_fmt_hours(minutes)}]"
    m = field.search(item)
    return item[:m.start()] + new + item[m.end():] if m else f"{item.rstrip()} {new}"


def _with_est(item: str, minutes: int) -> str:
    return _set_field(item, GOAL_EST, "est", minutes)


def _with_spent(item: str, minutes: int) -> str:
    """Hours logged added to what the line has; a field Julz cannot read, or a total past
    9999 h, is refused rather than overwritten."""
    had = _minutes_of(item, GOAL_SPENT) if GOAL_SPENT.search(item) else 0
    if had is None or had + minutes > MAX_SPENT_MIN:
        raise Refused("logged hours would pass 9999 h or the line's hours are unreadable")
    return _set_field(item, GOAL_SPENT, "spent", had + minutes)


def _due_of(text: str) -> str | None:
    """A goal's [due:: ] date when it is a real day, else none."""
    m = GOAL_DUE.search(text)
    try:
        return date.fromisoformat(m.group(1)).isoformat() if m else None
    except ValueError:
        return None


def _due(value, today: date) -> str:
    """A due date from the phone: a real day in ISO form, from today to ten years ahead (126)."""
    if not isinstance(value, str) or not DUE_DAY.fullmatch(value):
        raise Refused("a due date is YYYY-MM-DD")
    try:
        day = date.fromisoformat(value)
    except ValueError:
        raise Refused("not a real day") from None
    if not today <= day <= today + timedelta(days=MAX_DUE_DAYS):
        raise Refused("a due date is from today to ten years ahead")
    return day.isoformat()


GOAL_KEYS = {"add": {"do", "period", "text"}, "tick": {"do", "period", "item"}, "bump": {"do", "period", "item"},
             "target": {"do", "period", "item", "target"}, "link": {"do", "period", "item", "list", "todo"},
             "unlink": {"do", "period", "item", "list", "todo"},
             "est": {"do", "period", "item", "hours"}, "log": {"do", "period", "item", "hours"},
             "nest": {"do", "period", "item", "under"}, "due": {"do", "period", "item", "due"}}
GOAL_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


def _target(value) -> int:
    if not isinstance(value, str) or not value.isdigit() or not 1 <= int(value) <= 9999:
        raise Refused("a target is a whole number from 1 to 9999")
    return int(value)


def goal_text(snapshot: dict, picks, todos: dict | None = None, today: date | None = None) -> str:
    """The text I sign to add, tick or count up goals from the phone, built from the snapshot
    only. An added goal gets its id from its words, made here, so todos can be tagged with it."""
    if not isinstance(picks, list) or not 1 <= len(picks) <= MAX_GOALS:
        raise Refused(f"pick 1 to {MAX_GOALS} changes")
    today = today or date.today()
    periods = {p["key"]: p for p in snapshot["periods"]}
    taken = {g["goal"] for p in snapshot["periods"] for g in p["goals"] if g["goal"]}
    seen, lines = set(), []
    for p in picks:
        if not isinstance(p, dict) or p.get("do") not in GOAL_KEYS or set(p) != GOAL_KEYS[p["do"]] \
                or not all(isinstance(v, str) for v in p.values()) or p["period"] not in periods:
            raise Refused("a change is add, tick, bump, target, link, nest or due, a current period and its words")
        if p["do"] == "add":
            words = p["text"].strip()
            if not words or len(words) > MAX_GOAL_TEXT or not _goal_plain(words, MAX_GOAL_TEXT) or "#" in words:
                raise Refused("a goal is plain words, at most 120 characters, no links or tags")
            slug = "-".join(re.findall(r"[a-z0-9]+", words.lower())[:6])[:40].strip("-") or "goal"
            gid, n = slug, 2
            while gid in taken:
                gid, n = f"{slug[:37]}-{n}", n + 1
            taken.add(gid)
            lines.append(f"add: {p['period']} {words} #goal/{gid}\n")
            continue
        goal = next((g for g in periods[p["period"]]["goals"] if g["text"] == p["item"] and not g["done"]), None)
        if goal is None:
            raise Refused("not an open goal in this snapshot: reload")
        if p["do"] == "bump" and (goal["progress"] is None or goal["progress"][0] >= goal["progress"][1]):
            raise Refused("only a counted goal below its target counts up")
        mark = (p["do"], p["period"], p["item"], p.get("todo", ""))
        if mark in seen:
            raise Refused("a change picked twice")
        seen.add(mark)
        if p["do"] in ("est", "log"):
            # Quarter hours, written by code; one of each per goal per batch (129)
            minutes = _hours(p["hours"], MAX_EST_MIN if p["do"] == "est" else MAX_LOG_MIN)
            new = _with_est(p["item"], minutes) if p["do"] == "est" else _with_spent(p["item"], minutes)
            if len(new) > MAX_GOAL_TEXT + 60:
                raise Refused("this goal's line is too long for hours")
            lines.append(f"{p['do']}: {p['period']} {_fmt_hours(minutes)} {p['item']}\n")
        elif p["do"] == "due":
            # A real day, written by code; a line the snapshot would no longer show is refused (126)
            due = _due(p["due"], today)
            if len(_dued(p["item"], due)) > MAX_GOAL_TEXT + 60:
                raise Refused("this goal's line is too long for a date")
            lines.append(f"due: {p['period']} {due} {p['item']}\n")
        elif p["do"] == "target":
            if goal["progress"] is not None:
                raise Refused("this goal already has a count")
            lines.append(f"target: {p['period']} {_target(p['target'])} {p['item']}\n")
        elif p["do"] == "nest":
            # Under a goal the tree knows, never itself, never one of its own descendants (125)
            tree, child, under = snapshot.get("tree", {}), goal["goal"], p["under"]
            if not GOAL_ID.fullmatch(under) or under not in tree:
                raise Refused("not a goal in the tree: reload")
            # A goal without an id cannot be anyone's parent, so it cannot make a cycle
            walk, steps = under, 0
            while walk is not None and steps <= MAX_TREE_DEPTH + 1:
                if walk == child:
                    raise Refused("a goal cannot sit under itself or its own parts")
                walk, steps = tree.get(walk), steps + 1
            lines.append(f"nest: {p['period']} {under} {p['item']}\n")
        elif p["do"] == "link":
            # Only a goal with an id, only a todo open in the todos snapshot under a list name
            # no other note shares, never twice (124)
            if not goal["goal"]:
                raise Refused("this goal has no id to link to: add #goal/<name> to it in Obsidian")
            lists = (todos or {}).get("lists", [])
            named = [l for l in lists if l["name"] == p["list"]]
            if len(named) != 1 or p["todo"] not in named[0]["open"]:
                raise Refused("not an open todo in the todos snapshot: reload")
            if _has_tag(p["todo"], goal["goal"]):
                raise Refused("this todo is already linked to the goal")
            lines.append(f"link: {p['period']} {goal['goal']} {named[0]['note']}: {p['todo']}\n")
        elif p["do"] == "unlink":
            # As link: a todo open or in progress in the todos snapshot that carries this goal's tag (128)
            if not goal["goal"]:
                raise Refused("this goal has no id")
            named = [l for l in (todos or {}).get("lists", []) if l["name"] == p["list"]]
            if len(named) != 1 or p["todo"] not in named[0]["open"] + named[0].get("doing", []):
                raise Refused("not an open todo in the todos snapshot: reload")
            if not _has_tag(p["todo"], goal["goal"]):
                raise Refused("this todo is not linked to the goal")
            lines.append(f"unlink: {p['period']} {goal['goal']} {named[0]['note']}: {p['todo']}\n")
        else:
            lines.append(f"{p['do']}: {p['period']} {p['item']}\n")
    # Changes that edit a goal's line first, a tick last: a ticked line is no longer open
    order = {"add": 0, "target": 1, "bump": 2, "nest": 3, "due": 4, "est": 4, "log": 4, "link": 5, "unlink": 5, "tick": 6}
    lines.sort(key=lambda line: order[line.split(":", 1)[0]])
    return f"goal: {snapshot['id']}\n" + "".join(lines)


def goal_requests(text: str, snapshot: dict) -> list[dict]:
    """The vault requests for a signed goal text; another snapshot than the one it was built
    from refuses, so nothing lands on a goal that changed."""
    if not isinstance(text, str) or not text.endswith("\n"):
        raise Refused("not a goal text")
    head, *lines = text[:-1].split("\n")
    m = GOAL_HEAD.fullmatch(head)
    if not m or not 1 <= len(lines) <= MAX_GOALS:
        raise Refused("not a goal text")
    if m.group(1) != snapshot["id"]:
        raise Refused("the goals changed since I signed: reload")
    notes = {p["key"]: p["note"] for p in snapshot["periods"]}
    out = []
    current: dict[tuple[str, str], str] = {}  # a goal's line as the batch so far leaves it

    def now(note: str, item: str) -> str:
        return current.get((note, item), item)
    for line in lines:
        do, sep, rest = line.partition(": ")
        key, _, item = rest.partition(" ")
        if not sep or key not in notes or not item or do not in GOAL_KEYS:
            raise Refused("not a goal line")
        if do == "nest":
            under, _, goal_item = item.partition(" ")
            if not GOAL_ID.fullmatch(under) or not goal_item:
                raise Refused("not a goal line")
            cur = now(notes[key], goal_item)
            out.append({"op": "nest", "note": notes[key], "item": cur, "under": under})
            current[(notes[key], goal_item)] = _nested(cur, under)
        elif do in ("est", "log"):
            amount, _, goal_item = item.partition(" ")
            if not amount.endswith("h") or not goal_item:
                raise Refused("not a goal line")
            minutes = _hours(amount[:-1], MAX_EST_MIN if do == "est" else MAX_LOG_MIN)
            cur = now(notes[key], goal_item)
            out.append({"op": do, "note": notes[key], "item": cur, "minutes": minutes})
            current[(notes[key], goal_item)] = _with_est(cur, minutes) if do == "est" else _with_spent(cur, minutes)
        elif do == "due":
            due, _, goal_item = item.partition(" ")
            if not DUE_DAY.fullmatch(due) or _due_of(f"[due:: {due}]") != due or not goal_item:
                raise Refused("not a goal line")
            cur = now(notes[key], goal_item)
            out.append({"op": "due", "note": notes[key], "item": cur, "due": due})
            current[(notes[key], goal_item)] = _dued(cur, due)
        elif do == "target":
            n, _, goal_item = item.partition(" ")
            if not goal_item:
                raise Refused("not a goal line")
            cur = now(notes[key], goal_item)
            out.append({"op": "target", "note": notes[key], "item": cur, "target": _target(n)})
            current[(notes[key], goal_item)] = _targeted(cur, _target(n))
        elif do in ("link", "unlink"):
            gid, _, rest2 = item.partition(" ")
            note, sep2, todo = rest2.partition(": ")
            if not GOAL_ID.fullmatch(gid) or not sep2 or not todo or not TICK_NOTE.fullmatch(note):
                raise Refused("not a goal line")
            out.append({"op": do, "note": note, "item": todo, "goal": gid})
        else:
            cur = now(notes[key], item) if do != "add" else item
            out.append({"op": {"add": "goal", "tick": "tick", "bump": "progress"}[do], "note": notes[key], "item": cur})
            if do == "bump":
                current[(notes[key], item)] = _bumped(cur)
    return out


def add_goal(vault: Path, req: dict) -> None:
    """One goal line at the end of a period's note, the note made first if it is not there."""
    item = req["item"]
    if not isinstance(item, str) or "\n" in item or not _goal_plain(item, MAX_GOAL_TEXT + 60) \
            or not GOAL_TAG.search(item):
        raise Refused("a goal is one plain line with its #goal tag")
    parts = check_path(req["note"], ("goals",))
    folder = vault / parts[0]
    if os.path.lexists(folder) and (folder.is_symlink() or not folder.is_dir()):
        raise Refused("goals is a link or a file")
    folder.mkdir(mode=0o755, exist_ok=True)
    path = vault / req["note"]
    line = f"- [ ] {item}\n"
    if not os.path.lexists(path):
        period = Path(parts[-1]).stem
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"---\ntags:\n  - goal\nperiod: {period}\n---\n\n# Goals {period}\n\n{line}")
        return
    path = target_of(vault, req["note"], ("goals",))
    text = read_note(path).decode("utf-8")
    write_over(path, text + ("" if text.endswith("\n") else "\n") + line)


def progress(path: Path, req: dict) -> None:
    """Count a goal one up: (n/m) to (n+1/m) on its exact open line, never past m."""
    item = req["item"]
    count = GOAL_COUNT.search(item) if isinstance(item, str) else None
    if not count or "\n" in item:
        raise Refused("only a counted goal counts up")
    n, m = int(count.group(1)), int(count.group(2))
    if n >= m:
        raise Refused("already at its target")
    text = read_note(path).decode("utf-8")
    pattern = re.compile(r"^(\s*[-*] )\[ \] " + re.escape(item) + r"[ \t]*$", re.M)
    if len(pattern.findall(text)) != 1:
        raise Refused("goal not found exactly once")
    new = _bumped(item)
    write_over(path, pattern.sub(lambda mm: f"{mm.group(1)}[ ] {new}", text, count=1))


def _bumped(item: str) -> str:
    count = GOAL_COUNT.search(item)
    n, m = int(count.group(1)), int(count.group(2))
    return item[:count.start()] + f"({n + 1}/{m})" + item[count.end():]


def _targeted(item: str, n: int) -> str:
    tag = GOAL_TAG.search(item)
    return f"{item[:tag.start()].rstrip()} (0/{n}) {item[tag.start():]}" if tag else f"{item} (0/{n})"


def _nested(item: str, under: str) -> str:
    return GOAL_IN.sub("", item).rstrip() + f" [in:: {under}]"


def _dued(item: str, due: str) -> str:
    return GOAL_DUE.sub("", item).rstrip() + f" [due:: {due}]"


def _open_line(text: str, item: str) -> re.Pattern:
    # [ \t]* at the end, not \s*: \s would also take the line break of the note's last line
    pattern = re.compile(r"^(\s*[-*] )\[ \] " + re.escape(item) + r"[ \t]*$", re.M)
    if len(pattern.findall(text)) != 1:
        raise Refused("line not found exactly once")
    return pattern


def set_target(path: Path, req: dict) -> None:
    """Make an open goal a counted one: (0/N) before its tag, only when it has no count (124)."""
    item, n = req["item"], req["target"]
    if type(n) is not int or not 1 <= n <= 9999:
        raise Refused("a target is a whole number from 1 to 9999")
    if not isinstance(item, str) or "\n" in item or GOAL_COUNT.search(item):
        raise Refused("this goal already has a count")
    text = read_note(path).decode("utf-8")
    pattern = _open_line(text, item)
    new = _targeted(item, n)
    write_over(path, pattern.sub(lambda m: f"{m.group(1)}[ ] {new}", text, count=1))


def set_parent(path: Path, req: dict) -> None:
    """Put an open goal under another: one [in:: id] at the end of its line, an old one
    replaced; the id is the only text written (125)."""
    item, under = req["item"], req["under"]
    if not isinstance(under, str) or not GOAL_ID.fullmatch(under):
        raise Refused("bad goal id")
    if not isinstance(item, str) or "\n" in item:
        raise Refused("not one line")
    text = read_note(path).decode("utf-8")
    pattern = _open_line(text, item)
    new = _nested(item, under)
    write_over(path, pattern.sub(lambda m: f"{m.group(1)}[ ] {new}", text, count=1))


def set_hours(path: Path, req: dict) -> None:
    """An estimate set, or hours logged added up, on an open goal's exact line (129)."""
    item, minutes, est = req["item"], req["minutes"], req["op"] == "est"
    cap = MAX_EST_MIN if est else MAX_LOG_MIN
    if type(minutes) is not int or not 15 <= minutes <= cap or minutes % 15:
        raise Refused("hours are whole quarter hours")
    if not isinstance(item, str) or "\n" in item:
        raise Refused("not one line")
    new = _with_est(item, minutes) if est else _with_spent(item, minutes)
    if len(new) > MAX_GOAL_TEXT + 60:
        raise Refused("this goal's line is too long for hours")
    text = read_note(path).decode("utf-8")
    pattern = _open_line(text, item)
    write_over(path, pattern.sub(lambda m: f"{m.group(1)}[ ] {new}", text, count=1))


def set_due(path: Path, req: dict, today: date) -> None:
    """Give an open goal a due date: one [due:: YYYY-MM-DD] at the end of its line, an old one
    replaced; the date is the only text written (126)."""
    item, due = req["item"], _due(req["due"], today)
    if not isinstance(item, str) or "\n" in item:
        raise Refused("not one line")
    new = _dued(item, due)
    if len(new) > MAX_GOAL_TEXT + 60:
        raise Refused("this goal's line is too long for a date")
    text = read_note(path).decode("utf-8")
    pattern = _open_line(text, item)
    write_over(path, pattern.sub(lambda m: f"{m.group(1)}[ ] {new}", text, count=1))


def link_todo(path: Path, req: dict) -> None:
    """Tie an open todo to a goal: its line gets the goal's tag, once (124)."""
    item, gid = req["item"], req["goal"]
    if not isinstance(gid, str) or not GOAL_ID.fullmatch(gid):
        raise Refused("bad goal id")
    if not isinstance(item, str) or "\n" in item or _has_tag(item, gid):
        raise Refused("already linked or not one line")
    text = read_note(path).decode("utf-8")
    pattern = _open_line(text, item)
    write_over(path, pattern.sub(lambda m: f"{m.group(1)}[ ] {item} #goal/{gid}", text, count=1))


def _tag(gid: str) -> re.Pattern:
    # The whole tag, never a prefix: #goal/net is not in #goal/net-plus
    return re.compile(r"[ \t]*(?<!\S)#goal/" + re.escape(gid) + r"(?![a-z0-9-])")


def _has_tag(text: str, gid: str) -> bool:
    return bool(_tag(gid).search(text))


def unlink_todo(path: Path, req: dict) -> None:
    """Untie a todo open or in progress from a goal: exactly that goal's tag leaves its line (128)."""
    item, gid = req["item"], req["goal"]
    if not isinstance(gid, str) or not GOAL_ID.fullmatch(gid):
        raise Refused("bad goal id")
    if not isinstance(item, str) or "\n" in item or len(_tag(gid).findall(item)) != 1:
        raise Refused("not linked or not one line")
    text = read_note(path).decode("utf-8")
    pattern = re.compile(r"^(\s*[-*] )\[([ /])\] " + re.escape(item) + r"[ \t]*$", re.M)
    if len(pattern.findall(text)) != 1:
        raise Refused("line not found exactly once")
    new = _tag(gid).sub("", item, count=1)
    write_over(path, pattern.sub(lambda m: f"{m.group(1)}[{m.group(2)}] {new}", text, count=1))


def snapshot_id(lists: list) -> str:
    """Names one snapshot: the phone signs against it, so a list changed since is refused."""
    return hashlib.sha256(json.dumps(lists, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------- ticking from the phone (threat 113) ----------

TICK_HEAD = re.compile(r"tick: ([0-9a-f]{64})")
START_HEAD = re.compile(r"start: ([0-9a-f]{64})")
HEADS = {"tick": TICK_HEAD, "start": START_HEAD}  # one head each: a start text is never a tick text (127)
TICK_NOTE = re.compile(r"(?:Inbox|daily)(?:/\w[\w .-]{0,99})+\.md")


def tick_text(snapshot: dict, picks, verb: str = "tick") -> str:
    """The text I sign to tick tasks from the phone, or to start them (127). Built from the
    snapshot only, in its order: the phone gives (list, task) pairs that must be open in it (or
    in progress, for a tick) and never names a path."""
    if verb not in HEADS:
        raise Refused("not a task change")
    if not isinstance(picks, list) or not 1 <= len(picks) <= MAX_TODO_ITEMS:
        raise Refused(f"pick 1 to {MAX_TODO_ITEMS} tasks")
    wanted = set()
    for p in picks:
        if not isinstance(p, dict) or set(p) != {"list", "item"} \
                or not all(isinstance(p[k], str) for k in p):
            raise Refused("a pick is a list name and a task")
        if (p["list"], p["item"]) in wanted:
            raise Refused("a task picked twice")
        wanted.add((p["list"], p["item"]))
    names = Counter(l["name"] for l in snapshot["lists"])
    lines, found = [], set()
    for l in snapshot["lists"]:
        for item in l["open"] + (l.get("doing", []) if verb == "tick" else []):
            pair = (l["name"], item)
            if pair in wanted and pair not in found:
                if names[l["name"]] > 1:
                    raise Refused("two lists share this name: tick it in Obsidian")
                lines.append(f"{l['note']}: {item}\n")
                found.add(pair)
    if found != wanted:
        raise Refused("not an open task in this snapshot: reload")
    return f"{verb}: {snapshot['id']}\n" + "".join(lines)


def ticks_of(text: str, verb: str = "tick") -> list[tuple[str, str]]:
    """(note, task) for each line of a signed tick text, or Refused if it is not one
    tick_text() could have built."""
    if not isinstance(text, str) or not text.endswith("\n"):
        raise Refused("not a tick text")
    head, *lines = text[:-1].split("\n")
    if verb not in HEADS or not HEADS[verb].fullmatch(head) or not 1 <= len(lines) <= MAX_TODO_ITEMS:
        raise Refused("not a tick text")
    out = []
    for line in lines:
        note, sep, item = line.partition(": ")
        if not sep or not TICK_NOTE.fullmatch(note) or not item or not _travels(item):
            raise Refused("not a tick line")
        out.append((note, item))
    return out


_last_stamp = 0


def write_request(folder: Path, payload: dict) -> None:
    """Drop a request as the notes tool does: a hidden name, then a rename, so julz-vault never
    reads half a file. The name sorts in the order requests were written (the second, then a
    microsecond count that only grows here), so one signed batch is applied as signed."""
    global _last_stamp
    now = time.time()
    stamp = max(int(now * 1_000_000), _last_stamp + 1)
    _last_stamp = stamp
    name = f"{stamp // 1_000_000}-{stamp % 16 ** 8:08x}.json"
    tmp = folder / f".tmp-{name}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.rename(tmp, folder / name)


# ---------- git ----------

def git(vault: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(vault), *args], capture_output=True, text=True,
                          timeout=GIT_TIMEOUT)


def commit_all(vault: Path, dirs: gate.Dirs, state: dict) -> None:
    """Commit whatever changed in the vault since the last commit, named by top folder."""
    if git(vault, "add", "-A").returncode != 0:
        raise gate.GateError("git add failed")
    names = git(vault, "diff", "--cached", "--name-only", "-z").stdout.split("\0")
    names = [n for n in names if n]
    if not names:
        state.pop("blocked", None)
        return
    tops = Counter(n.split("/", 1)[0] if "/" in n else "top" for n in names)
    message = "vault: changes in " + ", ".join(f"{k} ({v})" for k, v in sorted(tops.items()))
    if git(vault, "commit", "-q", "-m", message).returncode == 0:
        state.pop("blocked", None)
        return
    tree = git(vault, "write-tree").stdout.strip()
    if state.get("blocked") != tree:  # once per state of the vault, not every 15 minutes
        state["blocked"] = tree
        gate.log(dirs, "vault-commit", hashlib.sha256(tree.encode()).hexdigest(), "failed",
                 "commit blocked, gitleaks may have found a secret")


def commit_paths(vault: Path, paths: list[str], message: str) -> bool:
    if git(vault, "add", "-A", "--", *paths).returncode != 0:
        return False
    if git(vault, "diff", "--cached", "--quiet", "--", *paths).returncode == 0:
        return True  # nothing changed, like a second review the same day
    return git(vault, "commit", "-q", "-m", message, "--", *paths).returncode == 0


# ---------- the run ----------

@contextmanager
def lock(state_dir: Path, wait: bool = False):
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(state_dir / "vault.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise gate.GateBusy("julz-vault is already running") from None
        yield
    finally:
        os.close(fd)


def _load_state(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: Path, data: dict):
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)


_save_state = _write_json


def _requests(folder: Path, now: float) -> list[Path]:
    """Request files in name order. Stale temp files are removed on the way."""
    found = []
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name)
    except FileNotFoundError:
        return []
    for e in entries:
        if TMP_NAME.fullmatch(e.name) and e.is_file(follow_symlinks=False):
            if now - e.stat(follow_symlinks=False).st_mtime > TMP_GRACE:
                os.unlink(e.path)
            continue
        found.append(Path(e.path))
    return found


def _remove(p: Path):
    try:
        os.unlink(p)
    except FileNotFoundError:
        pass
    except IsADirectoryError:
        shutil.rmtree(p, ignore_errors=True)


def _apply(vault: Path, req: dict, today: date) -> tuple[list[str], str]:
    """Check and apply one request. Returns the changed paths and the commit verb."""
    op, roots = req["op"], OPS[req["op"]][1]
    if op == "create":
        dest = create(vault, req)
        return [str(dest.relative_to(vault))], f"created {dest.relative_to(vault)}"
    if op == "goal":
        add_goal(vault, req)
        return [req["note"]], f"added a goal to {req['note']}"
    path = target_of(vault, req["note"], roots)
    not_an_index(path)
    rel = req["note"]
    if op == "append":
        append(path, checked_text(req["text"], MAX_APPEND_CHARS), today)
        return [rel], f"added to {rel}"
    if op == "reviewed":
        set_reviewed(path, today)
        return [rel], f"reviewed {rel}"
    if op == "replace":
        replace(path, req)
        return [rel], f"edited {rel}"
    if op == "tick":
        tick(path, req, today)
        return [rel], f"ticked a task in {rel}"
    if op == "start":
        start(path, req)
        return [rel], f"started a task in {rel}"
    if op == "progress":
        progress(path, req)
        return [rel], f"counted a goal up in {rel}"
    if op == "target":
        set_target(path, req)
        return [rel], f"set a goal's target in {rel}"
    if op == "unlink":
        unlink_todo(path, req)
        return [rel], f"unlinked a todo from a goal in {rel}"
    if op == "link":
        link_todo(path, req)
        return [rel], f"linked a todo to a goal in {rel}"
    if op == "nest":
        set_parent(path, req)
        return [rel], f"put a goal under another in {rel}"
    if op in ("est", "log"):
        set_hours(path, req)
        return [rel], f"{'set an estimate on' if op == 'est' else 'logged hours on'} a goal in {rel}"
    if op == "due":
        set_due(path, req, today)
        return [rel], f"set a goal's due date in {rel}"
    if op == "resolve":
        dest = str(resolve(vault, path, today).relative_to(vault))
        return [rel, dest], f"solved {rel}"
    if op == "move":
        dest = str(move(vault, path, req).relative_to(vault))
        return [rel, dest], f"moved {rel} to {dest}"
    same_as_shown(read_note(path), req["sha256"])  # delete
    os.unlink(path)
    return [rel], f"deleted {rel}"


def _handle(vault: Path, dirs: gate.Dirs, p: Path, today: date) -> tuple[str, str, str]:
    raw, action = b"", "note"
    try:
        if not REQUEST_NAME.fullmatch(p.name):
            raise Refused("bad request name")
        try:
            raw = _read_request(p)
        except OSError:  # a link (O_NOFOLLOW), a fifo, gone: never a valid request
            raise Refused("unreadable request") from None
        _remove(p)
        req = check_request(raw)
        action = LOG_ACTION.get(req["op"], "note")
        if req["op"] == "create" and str(req.get("note", "")).startswith("feedback/"):
            action = "feedback"  # the app's list confirms it; a push only when refused (120)
        digest = hashlib.sha256(raw).hexdigest()
        paths, verb = _apply(vault, req, today)
    except Refused as e:
        digest = hashlib.sha256(raw or p.name.encode()).hexdigest()
        _remove(p)
        gate.log(dirs, action, digest, "refused", str(e))
        return digest[:8], "refused", str(e)
    except (OSError, UnicodeDecodeError):
        digest = hashlib.sha256(raw or p.name.encode()).hexdigest()
        _remove(p)
        gate.log(dirs, action, digest, "failed", "could not read or write")
        return digest[:8], "failed", "could not read or write"
    if not commit_paths(vault, paths, f"julz: {verb} (request {digest[:8]})"):
        gate.log(dirs, action, digest, "failed", "applied but the commit failed")
        return digest[:8], "failed", "applied but the commit failed"
    gate.log(dirs, action, digest, "ok")
    return digest[:8], "ok", ""


def _write_snapshots(vault: Path, state_dir: Path, today: date):
    """What the phone reads, built from the vault as it is now."""
    _write_json(state_dir / "due.json",
                {"date": today.isoformat(), "due": due_count(vault, today)})
    _write_json(state_dir / "todos.json", {"date": today.isoformat(), **todo_snapshot(vault)})
    _write_json(state_dir / "done-week.json", done_week(vault, today))
    _write_json(state_dir / "inbox.json", inbox_snapshot(vault))
    _write_json(state_dir / "notes.json", notes_snapshot(vault))
    _write_json(state_dir / "feedback.json", feedback_snapshot(vault))
    _write_json(state_dir / "goals.json", goals_snapshot(vault, today))


def refresh(vault: Path, state_dir: Path, today: date) -> None:
    """Only the snapshots, seconds after a save in Inbox/ or daily/ (209, threat 142): no commit,
    no request, nothing written in the vault. Waits for a full run rather than miss a save."""
    with lock(state_dir, wait=True):
        _write_snapshots(vault, state_dir, today)


def run(vault: Path, dirs: gate.Dirs, state_dir: Path, today: date,
        now: float | None = None) -> list[tuple[str, str, str]] | None:
    """Commit my changes, apply up to MAX_PER_RUN requests, rebuild the index notes.
    None if already running."""
    now = time.time() if now is None else now
    try:
        with lock(state_dir):
            state_file = state_dir / "state.json"
            state = _load_state(state_file)
            commit_all(vault, dirs, state)
            pending = _requests(vault / "Inbox" / ".requests", now)
            if len(pending) > MAX_WAITING:
                for p in pending[MAX_WAITING:]:
                    _remove(p)
                gate.log(dirs, "note", hashlib.sha256(b"flood").hexdigest(), "refused",
                         f"flood: {len(pending) - MAX_WAITING} requests removed unread")
                pending = pending[:MAX_WAITING]
            results = [_handle(vault, dirs, p, today) for p in pending[:MAX_PER_RUN]]
            for src, dest in archive_done(vault, today):
                commit_paths(vault, [src, dest], f"vault: finished todo {src} moved to {dest}")
            indexes = update_indexes(vault)
            if indexes:
                commit_paths(vault, indexes, "vault: index notes updated")
            _save_state(state_file, state)
            _write_snapshots(vault, state_dir, today)
            # Today's commits, a number for the app's Integrations list (122)
            counted = git(vault, "rev-list", "--count", "--since=midnight", "HEAD")
            if counted.returncode == 0 and counted.stdout.strip().isdigit():
                _write_json(state_dir / "vault-status.json",
                            {"date": today.isoformat(), "commits_today": int(counted.stdout.strip())})
            return results
    except gate.GateBusy:
        return None
