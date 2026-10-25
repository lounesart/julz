#!/usr/bin/env python3
"""Push short notices to my phone through ntfy. SECURITY.md threat 39.

Notices go only to the self hosted ntfy on this laptop, which the Julz app reads over
Tailscale; ntfy.sh was retired on 2026-10-18. The channel is still treated as untrusted both
ways: anyone who could post to the topic could send fake ones. So every message comes from a fixed template holding
counts, action names and the first 8 characters of a hash, never spec or report text. The log's
reason field can quote a spec line, so it is never sent. A fake push can only make me open the
approver page, which shows the real state.
~/.config/julz/notify/local.env names that server (threat 86): loopback only, the write only
notify token, the kind as a tag, never a link. Without it nothing is sent.
Triggered by systemd path units (systemd/): a change in the inbox runs --inbox, a change in
runner.log runs --log.
Usage:
  ./julz-notify.py --new-topic   make the random topic for the self hosted server
  ./julz-notify.py --test        send one test message
  ./julz-notify.py --inbox       "N specs waiting", at most once per INBOX_EVERY seconds
  ./julz-notify.py --log         one message per new runner.log line worth knowing
  ./julz-notify.py --weekly      "N notes in Inbox", Sundays (julz-notify-weekly.timer)
  ./julz-notify.py --due         "N notes due for review" when 3 or more, daily (julz-notify-due.timer)
  ./julz-notify.py --todos       my open tasks to my own server only, when they changed (threat 100)
  ./julz-notify.py --notes       "N new notes" when one lands in Inbox/ or daily/ (209, threat 142)
  ./julz-notify.py --cards       "N cards waiting" when Julz asks for a change (221, threat 160)
"""
import fcntl
import hashlib
import json
import os
import http.client
import re
import secrets
import socket
import sys
import time
import unicodedata
import urllib.request
from contextlib import contextmanager
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402
import julz_vault as vault  # noqa: E402

HOME = Path.home()
TOPIC_FILE = HOME / ".config" / "julz" / "notify" / "ntfy.env"
STATE_FILE = HOME / ".local" / "share" / "julz" / "notify" / "state.json"
INBOX = HOME / "Documents" / "julz-mem" / "Inbox" / "claude"
NOTES_INBOX = HOME / "Documents" / "julz-mem" / "Inbox"
# Written by julz-vault, which has no network. This side never reads a note
DUE_FILE = HOME / ".local" / "share" / "julz" / "vault" / "due.json"
DUE_PUSH_AT = 3
MAX_DUE = 10_000
LOG = HOME / ".local" / "share" / "julz" / "log" / "runner.log"
LOCAL_ENV = HOME / ".config" / "julz" / "notify" / "local.env"
# The token travels in plain http, so the server must be this machine and nothing else
LOCAL_URL = "http://127.0.0.1:8090"
LOCAL_TOKEN = re.compile(r"tk_[a-z0-9]{29}")
# What the phone app groups and mutes by; it drops any other kind
KINDS = ("approval", "todo", "inbox", "run", "review", "change", "warning")
TOPIC = re.compile(r"^julz-[0-9a-f]{32}$")
HASH = gate.HEX64
INBOX_EVERY = 300
# New notes (209, threat 142): julz-vault writes notes.json, this counts names it has not seen
NOTES_FILE = HOME / ".local" / "share" / "julz" / "vault" / "notes.json"
NOTES_EVERY = 60
MAX_LOG_READ = 1_000_000
# Cards Julz asks for (221, threat 160): the container writes these names, so only the ones
# Approve would show are counted, with the approver's limits (a test keeps them equal)
CARDS = NOTES_INBOX / ".proposals"
MAX_PROPOSALS = 10
MAX_PROPOSAL_SCAN = 200
PROPOSAL_TTL = 86_400
PROPOSAL_SKEW = 300


class Notice:
    """One push message. Only ASCII from the templates below goes in."""

    def __init__(self, title: str, body: str, priority: str = "default", tags: str = "",
                 kind: str = "change"):
        self.title, self.body, self.priority, self.tags = title, body, priority, tags
        self.kind = kind

    def __eq__(self, other):
        return (self.title, self.body, self.priority, self.tags) == \
            (other.title, other.body, other.priority, other.tags)

    def __repr__(self):
        return f"Notice({self.title!r}, {self.body!r})"


def short(digest) -> str:
    return digest[:8] if isinstance(digest, str) and HASH.match(digest) else "?"


# ---------- templates ----------

def inbox_notice(count: int) -> Notice:
    word = "spec" if count == 1 else "specs"
    return Notice(f"Julz: {count} {word} waiting", "Read it in Approve in Julz before you approve.",
                  tags="inbox_tray", kind="approval")


def cards_notice(count: int) -> Notice:
    word = "card" if count == 1 else "cards"
    return Notice(f"Julz: {count} {word} waiting", "Read it in Approve in Julz before you sign.",
                  tags="inbox_tray", kind="approval")


def inbox_notes(inbox: Path) -> int:
    """julz's drafts waiting in Inbox/: top level .md files only. Specs in Inbox/claude/
    have their own push, hidden files and links do not count."""
    if not inbox.is_dir():
        return 0
    return sum(1 for e in os.scandir(inbox) if e.name.endswith(".md")
               and not e.name.startswith(".") and e.is_file(follow_symlinks=False))


def notes_notice(new: int, in_inbox: int) -> Notice:
    word = "note" if new == 1 else "notes"
    waiting = "note waits" if in_inbox == 1 else "notes wait"
    return Notice(f"Julz: {new} new {word}", f"In Inbox or daily. {in_inbox} {waiting} in Inbox.",
                  tags="inbox_tray", kind="inbox")


def _new_note_keys(data) -> tuple[set, int] | None:
    """Hashed names of the notes in Inbox/ (top) and daily/ (not done/), and the Inbox count.
    By name, so a note sorted from Inbox to daily is not news. None if the snapshot is odd."""
    if not isinstance(data, dict) or not isinstance(data.get("folders"), list):
        return None
    keys, in_inbox = set(), 0
    for folder in data["folders"]:
        if not isinstance(folder, dict) or not isinstance(folder.get("notes"), list):
            return None
        for n in folder["notes"]:
            note = n.get("note") if isinstance(n, dict) else None
            if not isinstance(note, str):
                return None
            parts = note.split("/")
            if parts[0] == "Inbox" and len(parts) == 2:
                in_inbox += 1
            elif parts[0] != "daily" or parts[1:2] == ["done"] or len(parts) < 2:
                continue
            keys.add(hashlib.sha256(parts[-1].encode()).hexdigest()[:16])
    return keys, in_inbox


def check_notes(path: Path, state: dict, now: float, send):
    """One card when new notes land, at most once per NOTES_EVERY: julz can write Inbox/.
    The first run only records. A note held back by the limit stays new for the next card."""
    try:
        # In bytes from the snapshot's own caps, no symlink (213): a cut mid JSON read as nothing
        found = _new_note_keys(json.loads(gate.read_regular(path, vault.MAX_NOTES_JSON)))
    except (gate.SpecError, OSError, ValueError):
        return
    if found is None:
        return
    keys, in_inbox = found
    if "notes_seen" not in state:
        state["notes_seen"] = sorted(keys)
        return
    seen = set(state["notes_seen"])
    new = keys - seen
    if new and now - state.get("notes_sent", 0) >= NOTES_EVERY:
        send(notes_notice(len(new), in_inbox))
        state["notes_sent"] = now
        seen = keys
    state["notes_seen"] = sorted(seen & keys if new else keys)


def check_weekly(inbox: Path, send):
    """Sunday nudge to empty the Inbox. The count only: names come from Julz (B11)."""
    count = inbox_notes(inbox)
    if count:
        word = "note" if count == 1 else "notes"
        send(Notice(f"Julz: {count} {word} in Inbox", "Sort them in Inbox in Julz: move each to its "
                    "folder or delete it, one fingerprint applies your picks.",
                    tags="inbox_tray", kind="inbox"))


def check_due(path: Path, today: str, send):
    """A push when DUE_PUSH_AT or more notes are due today. Only a fresh, well formed count
    is trusted: anything else stays quiet."""
    try:
        data = json.loads(path.read_text()[:1000])
    except (OSError, ValueError):
        return
    if not isinstance(data, dict) or set(data) != {"date", "due"} or data["date"] != today:
        return
    due = data["due"]
    if type(due) is not int or not DUE_PUSH_AT <= due <= MAX_DUE:
        return
    send(Notice(f"Julz: {due} notes due for review", "Say \"quiz me\" to Julz. She asks one "
                "question at a time and marks what you know.", tags="brain", kind="review"))


# Todo snapshot (threat 100): julz-vault writes todos.json, this posts it to my own server only
TODOS_FILE = HOME / ".local" / "share" / "julz" / "vault" / "todos.json"
TODO_LIST_SEP, TODO_FIELD_SEP = "\u241e", "\u241f"
TODO_NAME = re.compile(r"\w[\w .-]{0,39}")
TODO_NOT_PLAIN = re.compile(r"!\[|\]\(|<[A-Za-z!?/]|://|(?i:\bwww\.)")
MAX_TODO_LISTS, MAX_TODO_ITEMS, MAX_TODO_TEXT = 8, 20, 80
MAX_TODO_DONE = 10
MAX_TODO_BYTES = 4000  # under ntfy's 4096 byte message limit
TODO_ID = re.compile(r"[0-9a-f]{64}")
TODO_NOTE = re.compile(r"(?:Inbox|daily)(?:/\w[\w .-]{0,99})+\.md")


def _todo_text_ok(t) -> bool:
    return (isinstance(t, str) and 0 < len(t) <= MAX_TODO_TEXT and not any(unicodedata.category(c) in gate.BAD_CATEGORIES for c in t)
            and TODO_LIST_SEP not in t and TODO_FIELD_SEP not in t and not TODO_NOT_PLAIN.search(t))


def todo_message(data) -> str | None:
    """The snapshot as one message, or None if anything in it is off: julz-vault wrote it, but
    the file is checked again here as if anyone could have. v3 (threats 113, 127): a head record
    with the snapshot id, then per list name, done, total, how many open, how many in progress,
    the open tasks, those in progress and the done ones. Note paths stay on the laptop. Over
    MAX_TODO_BYTES, done tasks go first."""
    if not isinstance(data, dict) or set(data) != {"date", "id", "lists"} \
            or not isinstance(data["lists"], list) or not isinstance(data["id"], str) \
            or not TODO_ID.fullmatch(data["id"]):
        return None
    lists = data["lists"]
    if len(lists) > MAX_TODO_LISTS:
        return None
    rows, items, dones = [], 0, 0
    for l in lists:
        if not isinstance(l, dict) or set(l) != {"name", "note", "done", "total", "open", "doing", "done_items"}:
            return None
        name, done, total, open_, done_ = l["name"], l["done"], l["total"], l["open"], l["done_items"]
        doing = l["doing"]
        if not isinstance(name, str) or not TODO_NAME.fullmatch(name) or not _todo_text_ok(name):
            return None
        if not isinstance(l["note"], str) or not TODO_NOTE.fullmatch(l["note"]):
            return None
        if type(done) is not int or type(total) is not int or not 0 <= done <= total <= 1000:
            return None
        if not isinstance(open_, list) or not isinstance(doing, list) or not (open_ or doing) \
                or not all(_todo_text_ok(t) for t in open_ + doing):
            return None
        if not isinstance(done_, list) or len(done_) > done or not all(_todo_text_ok(t) for t in done_):
            return None
        items += len(open_) + len(doing)
        dones += len(done_)
        rows.append([name, done, total, list(open_), list(doing), list(done_)])
    if items > MAX_TODO_ITEMS or dones > MAX_TODO_DONE:
        return None
    if not rows:
        return ""

    def build():
        return TODO_LIST_SEP.join([TODO_FIELD_SEP.join(["v3", data["id"]])] + [
            TODO_FIELD_SEP.join([n, str(d), str(tot), str(len(o)), str(len(g)), *o, *g, *dn]) for n, d, tot, o, g, dn in rows])
    message = build()
    # Done tasks first, then open ones, then those in progress, from the end: the counts stay true, a tick of a task
    # left out is simply not offered
    for which in (5, 3, 4):
        while len(message.encode()) > MAX_TODO_BYTES and any(r[which] for r in rows):
            next(r for r in reversed(rows) if r[which])[which].pop()
            message = build()
    return message


def check_todos(path: Path, state: dict, local: dict | None, topic: str):
    """Post the open tasks to my own server when they changed. Never to ntfy.sh."""
    if local is None:
        return
    try:
        data = json.loads(path.read_text()[:64_000])
    except (OSError, ValueError):
        return
    message = todo_message(data)
    if message is None:
        return
    digest = hashlib.sha256(message.encode()).hexdigest()
    if state.get("todos") == digest:
        return
    count = sum(len(l["open"]) + len(l["doing"]) for l in data["lists"])
    title = "Julz: no open todos" if count == 0 else f"Julz: {count} open {'todo' if count == 1 else 'todos'}"
    notice = Notice(title, message or "none", tags="clipboard", kind="todo")
    _post(f"{local['url']}/{topic}", notice, {"Title": notice.title, "Priority": "low", "Markdown": "no",
                                                "Tags": "k_todo", "Authorization": f"Bearer {local['token']}"})
    state["todos"] = digest


def log_notice(entry: dict) -> Notice | None:
    """The notice for one runner.log entry with its kind for the phone app, or None."""
    notice = _log_notice(entry)
    if notice is None:
        return None
    if entry.get("action") == "need":  # waits for me, like a spec
        notice.kind = "approval"
    elif notice.priority in ("high", "urgent"):
        notice.kind = "warning"
    elif entry.get("action") == "run" and entry.get("status") == "ok":
        notice.kind = "run"
    return notice


def _log_notice(entry: dict) -> Notice | None:
    """Turn one runner.log entry into a notice, or None. Never reads entry['reason'] except
    to compare it with the fixed channel name."""
    action, status, h = entry.get("action"), entry.get("status"), short(entry.get("sha256"))
    if action in ("goal", "goal-signed"):
        # The Goals tab shows a saved change; a refused one says so, never which (123)
        if action == "goal" and status != "ok":
            return Notice(f"Julz: goal change refused {h}", "Nothing in your notes changed. Reload Goals.", tags="x")
        return None
    if action in ("feedback", "feedback-signed"):
        # A saved note shows in the app's list; a refused one says so, never which or why (120)
        if action == "feedback" and status != "ok":
            return Notice(f"Julz: feedback refused {h}", "Nothing was saved. Try plain words "
                          "without links.", tags="x")
        return None
    if action in ("start", "start-signed"):
        # As a tick: the list shows a good start; a refused one says so, never which (127)
        if action == "start" and status != "ok":
            return Notice(f"Julz: start refused {h}", "That task is not open any more, or "
                          "the list changed. Nothing in your notes changed.", tags="x")
        return None
    if action in ("tick", "tick-signed"):
        # A good tick shows in the next todo snapshot; a refused one says so, never which (113)
        if action == "tick" and status != "ok":
            return Notice(f"Julz: tick refused {h}", "That task is not open any more, or "
                          "the list changed. Nothing in your notes changed.", tags="x")
        return None
    if action == "approve-channel" and entry.get("reason") == "phone":
        return Notice(f"Julz: approved {h}", "Approved from the phone. It runs now, or Approve in "
                      "Julz says when the run cap lets it.", tags="white_check_mark")
    if action == "override":
        return Notice(f"Julz: cap override {h}", "Run now was signed past the run cap. If this "
                      "was not you, revoke the key that signed it: julz-approve-web.py "
                      "--revoke-device for the phone, --revoke for the passkey.", priority="high", tags="warning")
    if action == "approve":
        return None  # the channel line above says it, or I approved at the terminal myself
    if action == "reject":
        return Notice(f"Julz: rejected {h}", "Rejected, nothing will run.", tags="x")
    if action == "enroll":
        return Notice("Julz: passkey registered",
                      "A new passkey can approve now. If this was not you, run "
                      "julz-approve-web.py --revoke at once.", priority="urgent", tags="warning")
    if action == "need":
        return Notice(f"Julz: Claude needs you {h}", "A task is blocked on something only you "
                      "can do. See what in Approve in Julz, within 24 hours.",
                      priority="high", tags="raising_hand")
    if action == "expire":
        return Notice(f"Julz: task expired {h}", "Nobody answered the need in 24 hours. "
                      "The task ended, nothing more runs.", tags="hourglass")
    if action == "stop":
        return Notice(f"Julz: task stopped {h}", "You stopped the task that waited for you; nothing more runs.",
                      tags="stop_sign")
    if action == "task-end":
        if status == "done":
            return None  # the run done notice already said it
        if entry.get("reason") == "asked the same again":
            # Fixed text picked by the exact reason (130); the reason itself never leaves
            return Notice(f"Julz: task ended {h}", "Claude asked the same thing again after "
                          "your answer, so the task ended. Start a new task with what it needs.",
                          priority="high", tags="warning")
        return Notice(f"Julz: task failed {h}", "A task ended without finishing. "
                      "See runner.log on the laptop.", priority="high", tags="warning")
    if action == "clean-warn":
        return Notice(f"Julz: work copy {h} goes in 24 h", "Merge anything you want to keep "
                      "from it before then.", tags="wastebasket")
    if action == "keep":
        # Fixed text only: the topic and the file names never go to ntfy.sh (B11)
        if status == "ok":
            return Notice(f"Julz: kept {h}", "Claude's notes are in julz-mem/Claude; Julz "
                          "can use them once the sync says so. If this was not you, "
                          "julz-approve-web.py --revoke-device for the phone, --revoke for the passkey.", tags="books")
        return Notice(f"Julz: Keep failed {h}", "Nothing was copied. See runner.log on the "
                      "laptop.", priority="high", tags="warning")
    if action == "sync":
        if status == "ok":
            return Notice("Julz: kept notes ready", "Julz can use them now in chats that have "
                          "the julz-claude collection.", tags="books")
        return Notice("Julz: notes sync failed", "Kept notes are safe on disk, but Julz cannot "
                      "see them yet. It retries every 10 minutes. Is Open WebUI running?",
                      priority="high", tags="warning")
    if action == "mem-sync":
        # A good sync is quiet: every edited note would buzz otherwise (143)
        if status == "ok":
            return None
        return Notice("Julz: memory sync failed", "Your notes are safe on disk, but Julz "
                      "still answers from the last good sync. It retries every 15 minutes. "
                      "Is Open WebUI running?", priority="high", tags="warning")
    if action == "note":
        # Fixed text only: the note name and the text never go to ntfy.sh (B11, threat 65)
        if status == "ok":
            return Notice(f"Julz: note added {h}", "Julz added a dated block to one of your "
                          "notes; git show in ~/Documents/julz-mem shows it. If you did not "
                          "ask for it, git revert it.", tags="memo")
        return Notice(f"Julz: note refused {h}", "Nothing in your notes changed. See "
                      "runner.log on the laptop.", tags="x")
    if action == "note-move":
        if status == "ok":
            return Notice(f"Julz: note moved {h}", "Julz moved one of your notes; git show in "
                          "~/Documents/julz-mem shows where.", tags="file_folder")
        return Notice(f"Julz: move refused {h}", "Nothing moved. See runner.log on the laptop.",
                      tags="x")
    if action == "note-delete":
        if status == "ok":
            return Notice(f"Julz: note deleted {h}", "Julz deleted one of your notes. If you "
                          "did not ask for it, git -C ~/Documents/julz-mem checkout the commit "
                          "before it to get it back.", priority="high", tags="wastebasket")
        return Notice(f"Julz: delete refused {h}", "Nothing deleted. See runner.log on the "
                      "laptop.", tags="x")
    if action == "feedback-solved":
        # Threat 85: a solve I did not make is a complaint hidden from Claude Code
        if status == "ok":
            return Notice(f"Julz: feedback solved {h}", "One feedback note moved to feedback/"
                          "done. If you did not say solved, git revert it in "
                          "~/Documents/julz-mem.", tags="white_check_mark")
        return Notice(f"Julz: solve refused {h}", "No feedback moved. See runner.log on the "
                      "laptop.", tags="x")
    if action == "reviewed":
        if status == "ok":
            return None  # a review date is not worth a buzz
        return Notice(f"Julz: review refused {h}", "Nothing saved. See runner.log on the laptop.", tags="x")
    if action == "vault-commit":
        return Notice("Julz: vault commit blocked", "A change in julz-mem was not committed, "
                      "gitleaks may have found a secret. Run git -C ~/Documents/julz-mem "
                      "status.", priority="high", tags="warning")
    if action == "refuse":
        return Notice(f"Julz: spec refused {h}", "An approved spec failed the runner checks. "
                      "See runner.log on the laptop.", priority="high", tags="warning")
    if action == "run":
        if status == "ok":
            return Notice(f"Julz: run done {h}", "The report is in Outbox and its Keep card is on Approve in "
                          "Julz. Ask Julz about it.",
                          tags="robot")
        if status == "quarantined":
            return Notice(f"Julz: report held back {h}", "The run's report was held back. If runner.log says "
                          "secret in report, rotate the Claude token.", priority="urgent",
                          tags="rotating_light")
        if status == "stopped":
            return Notice(f"Julz: run stopped {h}", "You stopped the running step. The work copy "
                          "stays for you to look at.", tags="stop_sign")
        return Notice(f"Julz: run failed {h}", "See runner.log on the laptop.", priority="high",
                      tags="warning")
    return None


# ---------- state ----------

def load_state(path: Path) -> dict:
    try:
        data = json.loads(gate.read_private_file(path, 0o077))
        return data if isinstance(data, dict) else {}
    except (gate.GateError, ValueError):
        return {}


@contextmanager
def state_lock(path: Path):
    """One notifier at a time between load_state and save_state: since 209 one refresh starts
    --todos and --notes together, and the later save would drop the other's change."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path.with_name("state.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC,
                 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def save_state(path: Path, state: dict):
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    gate.write_new(tmp, json.dumps(state), 0o600, gate.GateError("temp file exists"))
    os.replace(tmp, path)


# ---------- the two triggers ----------

# Both update state in place, so whatever was sent before a failed send stays recorded

def check_inbox(inbox: Path, state: dict, now: float, send):
    """Count spec files (by name only, the text is never read) and ring at most once per
    INBOX_EVERY seconds: julz can write the inbox, so it must not be able to spam me."""
    count = 0
    if inbox.is_dir():
        count = sum(1 for p in inbox.iterdir() if gate.SPEC_NAME.match(p.name))
    last = state.get("inbox_sent", 0)
    if count and count != state.get("inbox_count") and now - last >= INBOX_EVERY:
        send(inbox_notice(count))
        state["inbox_sent"] = now
    state["inbox_count"] = count


def count_cards(folder: Path, now: float) -> int:
    """The cards Approve can show, by name only: the file is never opened (threat 160)."""
    try:
        with os.scandir(folder) as it:
            entries = sorted(it, key=lambda e: e.name)[:MAX_PROPOSAL_SCAN]
    except OSError:
        return 0
    count = 0
    for e in entries:
        if (vault.REQUEST_NAME.fullmatch(e.name) and e.is_file(follow_symlinks=False)
                and -PROPOSAL_SKEW <= now - int(e.name[:10]) <= PROPOSAL_TTL):
            count += 1
    return min(count, MAX_PROPOSALS)


def check_cards(folder: Path, state: dict, now: float, send):
    """Ring when the count rises, at most once per INBOX_EVERY; my own signing never rings."""
    count = count_cards(folder, now)
    if count > state.get("cards_count", 0) and now - state.get("cards_sent", 0) >= INBOX_EVERY:
        send(cards_notice(count))
        state["cards_sent"] = now
    state["cards_count"] = count


def _send_lines(path: Path, state: dict, send) -> bool:
    """Send notices from state["log_offset"] on. True when the end of the file was reached."""
    with open(path, "rb") as f:
        f.seek(state["log_offset"])
        data = f.read(MAX_LOG_READ)
    for line in data.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            return False  # half written line: next time
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        notice = log_notice(entry) if isinstance(entry, dict) else None
        if notice:
            send(notice)
        state["log_offset"] += len(line)
    return len(data) < MAX_LOG_READ


def _archive_with_inode(log: Path, inode: int) -> Path | None:
    for path in sorted(log.parent.iterdir()):
        if gate.ARCHIVE_NAME.match(path.name) and path.lstat().st_ino == inode:
            return path
    return None


def check_log(log: Path, state: dict, send):
    """Send a notice for each new log line worth one. The first run starts at the end of the
    log, so old history is never pushed. A line is marked sent only after it was sent.
    After a rotation (threat 53) the old file, now an archive with the same inode, is read
    to its end first, then the new runner.log from 0, so no line is skipped."""
    try:
        st = log.stat()
    except FileNotFoundError:
        state["log_offset"] = 0
        state.pop("log_inode", None)
        return
    offset, inode = state.get("log_offset"), state.get("log_inode")
    if isinstance(offset, int) and isinstance(inode, int) and inode != st.st_ino:
        old = _archive_with_inode(log, inode)
        if old is not None and not _send_lines(old, state, send):
            return  # more of the archive next time
        offset = 0
    elif not isinstance(offset, int) or offset > st.st_size:  # first run, or truncated
        offset = st.st_size if offset is None else 0
    state["log_offset"], state["log_inode"] = offset, st.st_ino
    _send_lines(log, state, send)


# ---------- ntfy ----------

def load_topic(path: Path) -> str:
    data = gate.read_private_file(path, 0o077).decode("utf-8", "replace").strip()
    topic = data.removeprefix("NTFY_TOPIC=")
    if not TOPIC.match(topic):
        raise gate.GateError(f"{path} must hold NTFY_TOPIC=julz-<32 hex>")
    return topic


def new_topic(path: Path) -> str:
    topic = f"julz-{secrets.token_hex(16)}"  # 128 random bits: the topic is the only lock
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    gate.write_new(path, f"NTFY_TOPIC={topic}\n", 0o600,
                   gate.GateError(f"{path} exists: delete it first to make a new topic"))
    return topic


def load_local(path: Path) -> dict | None:
    """The phone app's server, or None while it is not set up. Loopback only (threat 86)."""
    if not os.path.lexists(path):
        return None
    values = {}
    for line in gate.read_private_file(path, 0o077).decode("utf-8", "replace").splitlines():
        key, sep, value = line.partition("=")
        if not sep or key not in ("NTFY_URL", "NTFY_TOKEN") or key in values:
            raise gate.GateError(f"{path}: unexpected line")
        values[key] = value
    if values.get("NTFY_URL") != LOCAL_URL or not LOCAL_TOKEN.fullmatch(values.get("NTFY_TOKEN", "")):
        raise gate.GateError(f"{path} must hold NTFY_URL={LOCAL_URL} and a notify token")
    return {"url": values["NTFY_URL"], "token": values["NTFY_TOKEN"]}


# julz-ntfy's private socket: the notify units may open unix sockets only (132)
PUSH_SOCKET = Path(f"/run/user/{os.getuid()}/julz-push/ntfy.sock")


class _UnixHTTP(http.client.HTTPConnection):
    def __init__(self, path: Path, timeout: float):
        super().__init__("localhost", timeout=timeout)
        self.path = path

    def connect(self):
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        try:
            s.connect(str(self.path))
        except OSError:
            s.close()
            raise
        self.sock = s


def _send(req: urllib.request.Request, timeout: float = 10, sock: Path | None = None):
    """POST the request over the private socket; anything but 2xx raises, so the caller
    keeps its progress and retries."""
    conn = _UnixHTTP(sock or PUSH_SOCKET, timeout)
    try:
        conn.request("POST", req.selector, body=req.data, headers=dict(req.header_items()))
        r = conn.getresponse()
        r.read()
        if not 200 <= r.status < 300:
            raise OSError(f"push server answered {r.status}")
    finally:
        conn.close()


def _post(url: str, notice: Notice, headers: dict):
    _send(urllib.request.Request(url, data=notice.body.encode(), headers=headers, method="POST"))


def make_sender(topic: str, local: dict | None):
    """Every notice goes to my own server only, for the app (86). ntfy.sh was retired on
    2026-10-18 (B11): no public copy, no link to the page. Without the local config nothing is
    sent and the error is raised, so the caller keeps its progress and retries."""
    def send(notice: Notice):
        if not local:
            raise gate.GateError("no local ntfy config: nothing sent")
        if notice.kind not in KINDS:
            raise gate.GateError(f"unknown kind {notice.kind!r}")
        headers = {"Title": notice.title, "Priority": notice.priority, "Markdown": "no",
                   "Tags": f"k_{notice.kind}", "Authorization": f"Bearer {local['token']}"}
        _post(f"{local['url']}/{topic}", notice, headers)
    return send


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    try:
        if mode == "--new-topic":
            topic = new_topic(TOPIC_FILE)
            print(f"topic for the self hosted ntfy (local.env): {topic}")
            return
        if mode == "--todos":
            with state_lock(STATE_FILE):
                state = load_state(STATE_FILE)
                check_todos(TODOS_FILE, state, load_local(LOCAL_ENV), load_topic(TOPIC_FILE))
                save_state(STATE_FILE, state)
            return
        if mode not in ("--test", "--inbox", "--log", "--weekly", "--due", "--notes", "--cards"):
            sys.exit(__doc__)
        send = make_sender(load_topic(TOPIC_FILE), load_local(LOCAL_ENV))
        if mode == "--test":
            send(Notice("Julz: test", "Notifications work."))
            print("sent")
            return
        if mode == "--weekly":
            check_weekly(NOTES_INBOX, send)
            return
        if mode == "--due":
            check_due(DUE_FILE, date.today().isoformat(), send)
            return
        with state_lock(STATE_FILE):
            state = load_state(STATE_FILE)
            try:
                if mode == "--inbox":
                    check_inbox(INBOX, state, time.time(), send)
                elif mode == "--notes":
                    check_notes(NOTES_FILE, state, time.time(), send)
                elif mode == "--cards":
                    check_cards(CARDS, state, time.time(), send)
                else:
                    check_log(LOG, state, send)
            finally:
                save_state(STATE_FILE, state)  # keep what was sent even if a later send failed
    except gate.GateError as e:
        sys.exit(str(e))
    except OSError as e:
        sys.exit(f"ntfy unreachable: {type(e).__name__}")


if __name__ == "__main__":
    main()
