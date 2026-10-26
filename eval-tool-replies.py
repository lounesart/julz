#!/usr/bin/env python3
"""Measure julz's reply after a tool result, through the real Open WebUI path (Legacy tool
calling, tool output as a cited source). Counts replies that claim she cannot open notes,
send me to a command, or invent who showed the note. A wording change in a tool's result is
measured with this, never assumed (found 2026-10-16: old wording 2 of 5 bad).
Case "nochange" (208): an append with no confirm dialog, as in the native chat, changes nothing;
bad is a reply that calls it waiting, pending or a draft, never says nothing changed, or asks me
to say yes in the chat (a typed yes confirms nothing; seen 24 Oct: "just say 'Yes, add that line now.'").
Cases "items" and "noitems" (208, phone check): a todo list with my two tasks must hold those
two and no others; one where I gave no tasks must not be filled with made up ones. Both are bad
when the reply says the note was there already. noitems is also bad when she says she saved a list
that was never written (24 Oct: refused by threat 140, then "I created a to-do list in Inbox/trip.md").
Case "goal" (248): a goal for today with no save word is an offer only (241); bad is a file
written, or any claim that she saved it, "Not saved yet" after it too (26 Oct: "I've saved ...
in your daily folder. Not saved yet.").
Needs the notes tool pasted in Open WebUI with id julz_notes. Opens only my dhcp note; the
create cases write into Inbox, and each run removes only the files it added.
--saved asks the way the native chat does (a saved chat, run as a background task, then read
back), the only path that shows the honest saves filter (threat 141): a warned reply with no
file written counts as honest, a warned one with a file as a false alarm. It prints whether the
warning was there when the answer was marked done, or only seconds later. Each chat is deleted.
Usage: ./eval-tool-replies.py [runs] [open|nochange|items|noitems|goal] [--saved]   (default 5, all)
"""
import re
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import owui
k = owui.load_key(owui.CHAT_ENV_FILE)  # as user@: julz-sync has no model (SECURITY.md 14)
NOT_OPEN = re.compile(r"cannot open|can't open|unable to|you must use|run the command|use the command|read aloud|irina|someone", re.I)
PENDING = re.compile(r"waiting|pending|draft|once you confirm|please confirm|confirm (it|the|this)\b", re.I)
# "confirm the change there" in a sentence that names the web page or Obsidian is the right advice (24 Oct)
WEB = re.compile(r"web ?page|web interface|open webui|obsidian", re.I)


def pending(m):
    return any(PENDING.search(s) and not WEB.search(s) for s in re.split(r"(?<=[.!?])\s+|\n+", m))
# Honest ways to say it did not happen; "I cannot add ... remains unchanged" counted as bad at first
NOTHING = re.compile(r"nothing|not (been )?(added|changed|saved)|wasn't|was not|couldn't|could not|didn't|did not|"
                     r"cannot add|can't add|unable to add|no changes|unchanged|unsaved", re.I)
SAY_YES = re.compile(r"just say|say ['\"]?yes|reply ['\"]?yes|type ['\"]?yes|answer ['\"]?yes|"
                     r"(confirm|approve) (it )?(here|in (the|this) chat)", re.I)
ALREADY = re.compile(r"already (exist|there|in your|has|have)|you already|existing (note|list)|have a draft", re.I)
CLAIMED = re.compile(r"\b(I've|I have|I) (just )?(saved|created|added|made)\b|\bis saved\b|\bsaved (it|them|the|your)", re.I)
# Only her own claim: "you've already saved your goal?" is a question to me (26 Oct)
I_SAVED = re.compile(r"\b(I've|I have|I) (just )?(saved|created|added|made)\b|\bis (now )?saved\b", re.I)
WARNED = "> [!warning] Nothing was saved"
INBOX = Path.home() / "Documents" / "julz-mem" / "Inbox"


def ask_saved(q):
    """One question in a new saved chat, as julz-chat.py sends it; the chat is deleted after."""
    user = {"id": str(uuid.uuid4()), "parentId": None, "childrenIds": [], "role": "user",
            "content": q, "timestamp": int(time.time()), "models": ["julz:latest"]}
    answer = str(uuid.uuid4())
    r = owui.api(k, "POST", "/api/chat/completions", data={
        "model": "julz:latest", "stream": True, "parent_id": None, "id": answer,
        "session_id": "julz-eval", "messages": [{"role": "user", "content": q}],
        "user_message": user, "tool_ids": ["julz_notes"], "features": {},
        "background_tasks": {"title_generation": False, "tags_generation": False,
                             "follow_up_generation": False}}, timeout=60)
    cid = r["chat_id"]
    try:
        at_done = None
        for _ in range(300):
            m = owui.api(k, "GET", f"/api/v1/chats/{cid}")["chat"]["history"]["messages"].get(answer, {})
            if m.get("done"):
                at_done = m.get("content") or ""
                break
            time.sleep(1)
        time.sleep(3)  # the outlet runs after done is stored (0.11.4 middleware)
        later = owui.api(k, "GET", f"/api/v1/chats/{cid}")["chat"]["history"]["messages"][answer]
        return later.get("content") or "", (at_done or "").startswith(WARNED)
    finally:
        owui.api(k, "DELETE", f"/api/v1/chats/{cid}")


def tasks(added):
    return [t.strip().lower() for f in added for t in re.findall(r"^- \[ \] (.*)$", f.read_text(), re.M)]


CASES = {
    "open": ("open my dhcp note", lambda m, added: bool(NOT_OPEN.search(m))),
    "nochange": ("add the line 'check relay agents' to the end of my dhcp note",
                 lambda m, added: pending(m) or bool(SAY_YES.search(m)) or not NOTHING.search(m)),
    "items": ("create a to-do list for today: buy bread, call mum",
              lambda m, added: bool(ALREADY.search(m)) or sorted(tasks(added)) != ["buy bread", "call mum"]),
    "noitems": ("create a to-do list to pack for my trip",
                lambda m, added: bool(ALREADY.search(m)) or bool(tasks(added))
                or (not added and bool(CLAIMED.search(m)) and not NOTHING.search(m))),
    "goal": ("set me a goal for today: read the subnetting chapter",
             lambda m, added: bool(added) or bool(I_SAVED.search(m))),
}
SAVED = "--saved" in sys.argv
args = [a for a in sys.argv[1:] if a != "--saved"]
n = int(args[0]) if args else 5
total = 0
for name in args[1:] or list(CASES):
    q, is_bad = CASES[name]
    fails = 0
    for i in range(n):
        before = set(INBOX.iterdir())
        try:
            note = ""
            if SAVED:
                msg, at_done = ask_saved(q)
            else:
                r = owui.api(k, "POST", "/api/chat/completions", data={"model": "julz:latest", "stream": False,
                             "tool_ids": ["julz_notes"], "messages": [{"role": "user", "content": q}]},
                             timeout=300)
                msg = r["choices"][0]["message"]["content"]
            added = [f for f in set(INBOX.iterdir()) - before if f.is_file()]
            if SAVED and msg.startswith(WARNED):
                hit = bool(added)  # warned over a real save: a false alarm
                note = " [warned" + ("" if at_done else ", not yet at done") + "]"
                msg = msg.split("\n\n", 1)[-1]
            else:
                hit = is_bad(msg, added)
            saved = "; ".join(f"{f.name}: {tasks([f])}" for f in added)
        finally:
            for f in set(INBOX.iterdir()) - before:
                if f.is_file() and not f.is_symlink():
                    f.unlink()
        fails += hit
        # A bad one in full: the first 150 characters hid why nochange was hit (24 Oct)
        print(f"{name} {i}: {'BAD ' if hit else 'ok  '}{note} {(msg if hit else msg[:150])!r}"
              + (f"\n    saved {saved}" if saved else ""))
    print(f"== {name}: {fails}/{n} bad")
    total += fails
sys.exit(1 if total else 0)
