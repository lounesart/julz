#!/usr/bin/env python3
"""Push short notices to my phone through ntfy. SECURITY.md threat 39.

The push channel is untrusted both ways: ntfy.sh and Google see every message, and anyone who
learns the topic can post fake ones. So every message comes from a fixed template holding
counts, action names and the first 8 characters of a hash, never spec or report text. The log's
reason field can quote a spec line, so it is never sent. A fake push can only make me open the
approver page, which shows the real state.
Triggered by systemd path units (systemd/): a change in the inbox runs --inbox, a change in
runner.log runs --log.
Usage:
  ./julz-notify.py --new-topic   make the random topic, print how to subscribe
  ./julz-notify.py --test        send one test message
  ./julz-notify.py --inbox       "N specs waiting", at most once per INBOX_EVERY seconds
  ./julz-notify.py --log         one message per new runner.log line worth knowing
"""
import json
import os
import re
import secrets
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402

HOME = Path.home()
TOPIC_FILE = HOME / ".config" / "julz" / "notify" / "ntfy.env"
STATE_FILE = HOME / ".local" / "share" / "julz" / "notify" / "state.json"
INBOX = HOME / "Documents" / "julz-mem" / "Inbox" / "claude"
LOG = HOME / ".local" / "share" / "julz" / "runner.log"
APPROVER_CONFIG = HOME / ".config" / "julz" / "approver.json"
SERVER = "https://ntfy.sh"
TOPIC = re.compile(r"^julz-[0-9a-f]{32}$")
HASH = re.compile(r"^[0-9a-f]{64}$")
INBOX_EVERY = 300
MAX_LOG_READ = 1_000_000


class Notice:
    """One push message. Only ASCII from the templates below goes in."""

    def __init__(self, title: str, body: str, priority: str = "default", tags: str = ""):
        self.title, self.body, self.priority, self.tags = title, body, priority, tags

    def __eq__(self, other):
        return vars(self) == vars(other)

    def __repr__(self):
        return f"Notice({self.title!r}, {self.body!r})"


def short(digest) -> str:
    return digest[:8] if isinstance(digest, str) and HASH.match(digest) else "?"


# ---------- templates ----------

def inbox_notice(count: int) -> Notice:
    word = "spec" if count == 1 else "specs"
    return Notice(f"julz: {count} {word} waiting", "Open the approver to read it before you approve.",
                  tags="inbox_tray")


def log_notice(entry: dict) -> Notice | None:
    """Turn one runner.log entry into a notice, or None. Never reads entry['reason'] except
    to compare it with the fixed channel name."""
    action, status, h = entry.get("action"), entry.get("status"), short(entry.get("sha256"))
    if action == "approve-channel" and entry.get("reason") == "phone":
        return Notice(f"julz: approved {h}", "Approved from the phone. The run starts now.",
                      tags="white_check_mark")
    if action == "approve":
        return None  # the channel line above says it, or I approved at the terminal myself
    if action == "reject":
        return Notice(f"julz: rejected {h}", "Rejected, nothing will run.", tags="x")
    if action == "enroll":
        return Notice("julz: passkey registered",
                      "A new passkey can approve now. If this was not you, run "
                      "julz-approve-web.py --revoke at once.", priority="urgent", tags="warning")
    if action == "need":
        return Notice(f"julz: Claude needs you {h}", "A task is blocked on something only you "
                      "can do. Open the approver to see what, within 24 hours.",
                      priority="high", tags="raising_hand")
    if action == "expire":
        return Notice(f"julz: task expired {h}", "Nobody answered the need in 24 hours. "
                      "The task ended, nothing more runs.", tags="hourglass")
    if action == "stop":
        return Notice(f"julz: task stopped {h}", "Stopped from the phone, nothing more runs.",
                      tags="stop_sign")
    if action == "task-end":
        if status == "done":
            return None  # the run done notice already said it
        return Notice(f"julz: task failed {h}", "A task ended without finishing. "
                      "See runner.log on the laptop.", priority="high", tags="warning")
    if action == "refuse":
        return Notice(f"julz: refused {h}", "An approved spec failed the runner checks. "
                      "See runner.log on the laptop.", priority="high", tags="warning")
    if action == "run":
        if status == "ok":
            return Notice(f"julz: run done {h}", "Report is in Outbox. Ask julz about it.",
                          tags="robot")
        if status == "quarantined":
            return Notice(f"julz: QUARANTINE {h}", "The report was held back. If runner.log says "
                          "secret in report, rotate the Claude token.", priority="urgent",
                          tags="rotating_light")
        return Notice(f"julz: run failed {h}", "See runner.log on the laptop.", priority="high",
                      tags="warning")
    return None


# ---------- state ----------

def load_state(path: Path) -> dict:
    try:
        data = json.loads(gate.read_private_file(path, 0o077))
        return data if isinstance(data, dict) else {}
    except (gate.GateError, ValueError):
        return {}


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


def check_log(log: Path, state: dict, send):
    """Send a notice for each new log line worth one. The first run starts at the end of the
    log, so old history is never pushed. A line is marked sent only after it was sent."""
    try:
        size = log.stat().st_size
    except FileNotFoundError:
        state["log_offset"] = 0
        return
    offset = state.get("log_offset")
    if not isinstance(offset, int) or offset > size:  # first run, or the log was rotated
        offset = size if offset is None else 0
    state["log_offset"] = offset
    with open(log, "rb") as f:
        f.seek(offset)
        data = f.read(MAX_LOG_READ)
    for line in data.splitlines(keepends=True):
        if not line.endswith(b"\n"):
            break  # half written line: next time
        try:
            entry = json.loads(line)
        except ValueError:
            entry = None
        notice = log_notice(entry) if isinstance(entry, dict) else None
        if notice:
            send(notice)
        state["log_offset"] += len(line)


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


def make_sender(topic: str, click: str | None):
    def send(notice: Notice):
        headers = {"Title": notice.title, "Priority": notice.priority, "Markdown": "no"}
        if notice.tags:
            headers["Tags"] = notice.tags
        if click:
            headers["Click"] = click
        req = urllib.request.Request(f"{SERVER}/{topic}", data=notice.body.encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
    return send


def approver_url() -> str | None:
    try:
        return json.loads(gate.read_private_file(APPROVER_CONFIG, 0o077))["origin"]
    except (gate.GateError, ValueError, KeyError, TypeError):
        return None


def main():
    mode = sys.argv[1] if len(sys.argv) == 2 else ""
    try:
        if mode == "--new-topic":
            topic = new_topic(TOPIC_FILE)
            print(f"ntfy app: + , Subscribe to topic: {topic}\nserver: {SERVER} (default)")
            return
        if mode not in ("--test", "--inbox", "--log"):
            sys.exit(__doc__)
        send = make_sender(load_topic(TOPIC_FILE), approver_url())
        if mode == "--test":
            send(Notice("julz: test", "Notifications work."))
            print("sent")
            return
        state = load_state(STATE_FILE)
        try:
            if mode == "--inbox":
                check_inbox(INBOX, state, time.time(), send)
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
