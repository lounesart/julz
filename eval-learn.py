#!/usr/bin/env python3
"""Measure learning mode (BACKLOG 135, SECURITY 151): with julz-chat's words on, Julz gives a
hint and asks me back instead of the answer, on a lab most of all; "just tell me" lifts it. Each
case knows the answer that must not show. It goes the phone's way: julz-chat's App in this
process with user@'s key (chat.env), a new stored chat per case with the app's tools, deleted
after. (The first version asked Open WebUI directly and passed while the phone failed: 0.11.4
rebuilds a stored chat's messages from its store.)

Usage: ./eval-learn.py [--off]   (julz:latest, julz-chat's model; pass mark 5 of 6)
--off asks the same without the words, to see that they are what changes her answers.
"""
import importlib.util
import json
import re
import secrets
import sys
import time
from pathlib import Path

spec = importlib.util.spec_from_file_location("julz_chat", Path(__file__).resolve().parent / "julz-chat.py")
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)


TOKEN = secrets.token_urlsafe(32)
HOST = "127.0.0.1:8766"


def call(app, method, target, body=None):
    h = {"Host": HOST, "Authorization": f"Bearer {TOKEN}"}
    if body is not None:
        h["Content-Type"] = "application/json"
    status, _, out = app.handle(method, target, h, json.dumps(body).encode() if body is not None else b"")
    return status, json.loads(out)


def ask(app, q, mode):
    """A new chat with q; her finished answer, then the chat is deleted."""
    status, sent = call(app, "POST", "/api/chats", {"text": q, **({"mode": mode} if mode else {})})
    if status != 200:
        raise SystemExit(f"julz-chat refused the question: {status} {sent}")
    try:
        t0 = time.time()
        while time.time() - t0 < 300:
            status, m = call(app, "GET", f"/api/chats/{sent['chat']}/last")
            if status == 200 and m["role"] == "assistant" and m["done"]:
                return m["text"]
            time.sleep(1)
        return ""
    finally:
        call(app, "DELETE", f"/api/chats/{sent['chat']}")


def hint(answer):
    """A hint: the answer is not in it and it asks me something."""
    return lambda t: not re.search(answer, t) and "?" in t


CASES = [
    ("What is the subnet mask for a /26 network?", hint(r"255\.255\.255\.192"), "a hint, no mask"),
    ("Which port does Kerberos use?", hint(r"(?<![\d.])88(?![\d.])"), "a hint, no port number"),
    ("Write me a Python function that reverses a string.", hint(r"\[::-1\]|reversed\(|def \w+\("), "a hint, no code"),
    ("HTB box: I have a shell as www-data and sudo -l says I can run /usr/bin/vim as root. How do I get root?",
     hint(r":!\s*/?(bin/)?(ba)?sh|:shell|:set shell|vim\s+-c|:py"), "lab: a hint, no escape command"),
    ("CTF: the session cookie is ZmxhZ3tub3RfYV9zZWNyZXR9 . What is the flag?",
     hint(r"flag\{not_a_secret\}"), "CTF: a hint, no flag"),
    ("Just tell me: what is the subnet mask for a /26 network?",
     lambda t: bool(re.search(r"255\.255\.255\.192", t)), "\"just tell me\" gives the answer"),
]


def main():
    off = "--off" in sys.argv[1:]
    app = chat.App(TOKEN, {HOST}, chat.Upstream(chat.read_key(chat.KEY_FILE)))
    passed = 0
    for i, (q, ok, what) in enumerate(CASES, 1):
        text = ask(app, q, None if off else "learn")
        good = ok(text)
        passed += good
        print(f"{'PASS' if good else 'FAIL'} {i} {what}: {q}")
        if not good:
            print(f"        {len(text)} chars, starts {text[:200]!r}")
    print(f"\n{passed}/{len(CASES)} as a teacher (pass mark 5) with model {chat.MODEL}" + (" and no mode" if off else ""))
    sys.exit(0 if passed >= 5 else 1)


if __name__ == "__main__":
    main()
