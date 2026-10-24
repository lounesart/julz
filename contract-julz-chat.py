#!/usr/bin/env python3
"""Contract test of julz-chat against the real Open WebUI (SECURITY.md 136), by hand: it uses
the GPU, so it is not part of the suite. Run it after an Open WebUI upgrade, before trusting
the native chat with the new version.

julz-chat's App runs in this process with user@'s key (chat.env) and a throwaway token; it
makes a probe chat, reads an answer while it grows, sends a follow-up, stops it, checks a few
refusals, retry, edit, archive and unarchive, then deletes its probe chat through julz-chat.

Usage: ./contract-julz-chat.py     exit 0 when every step held
"""
import json
import secrets
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("julz_chat", Path(__file__).resolve().parent / "julz-chat.py")
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)

HOST = "127.0.0.1:8766"
TOKEN = secrets.token_urlsafe(32)
failed = 0


def check(ok, what):
    global failed
    failed += not ok
    print(f"{'ok  ' if ok else 'FAIL'} {what}")
    return ok


def call(app, method, target, body=None):
    h = {"Host": HOST, "Authorization": f"Bearer {TOKEN}"}
    raw = b""
    if body is not None:
        raw = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    status, _, out = app.handle(method, target, h, raw)
    return status, json.loads(out)


def wait(app, cid, limit=180):
    """Polls /last until done; returns (seconds to first words, seconds to done, message)."""
    t0, first = time.time(), None
    while time.time() - t0 < limit:
        status, m = call(app, "GET", f"/api/chats/{cid}/last")
        if status == 200 and m["role"] == "assistant":
            if m["text"] and first is None:
                first = time.time() - t0
            if m["done"]:
                return first, time.time() - t0, m
        time.sleep(0.25)
    return first, None, None


def main():
    key = chat.read_key(chat.KEY_FILE)
    app = chat.App(TOKEN, {HOST}, chat.Upstream(key))

    status, data = call(app, "GET", "/api/chats")
    check(status == 200 and isinstance(data.get("chats"), list), f"list my chats ({len(data.get('chats', []))} on page 1)")

    status, data = call(app, "POST", "/api/chats", {"text": "julz-chat contract probe: say hello in five words."})
    if not check(status == 200, f"new chat -> {status}"):
        return
    cid = data["chat"]
    try:
        first, done, m = wait(app, cid)
        check(done is not None and m["text"].strip(), f"answer streamed: first words {first and round(first, 2)} s, done {done and round(done, 2)} s")

        status, view = call(app, "GET", f"/api/chats/{cid}")
        roles = [x["role"] for x in view.get("messages", [])]
        check(status == 200 and roles == ["user", "assistant"] and not view["busy"], f"the chat holds it: {roles}")

        status, data = call(app, "POST", f"/api/chats/{cid}/messages", {"text": "Now write 300 words about routers."})
        check(status == 200, f"follow-up -> {status}")
        status, _ = call(app, "POST", f"/api/chats/{cid}/messages", {"text": "and another"})
        check(status == 409, f"a second message while it answers -> {status}")
        time.sleep(2)
        status, _ = call(app, "POST", f"/api/chats/{cid}/stop", {})
        check(status == 200, f"stop -> {status}")
        _, _, m = wait(app, cid, limit=20)
        check(m is not None and m["done"], f"stopped answer is done, {len(m['text']) if m else 0} characters kept")

        status, view = call(app, "GET", f"/api/chats/{cid}")
        check([x["role"] for x in view["messages"]] == ["user", "assistant", "user", "assistant"], "the follow-up is on the same branch")

        # v2: retry and edit keep the old version in Open WebUI, the phone shows the newest
        before = {m["id"] for m in view["messages"]}
        status, sent = call(app, "POST", f"/api/chats/{cid}/retry", {})
        check(status == 200, f"retry -> {status}")
        _, _, m = wait(app, cid)
        check(m is not None and m["id"] == sent.get("message"), "the retried answer is the current one")
        status, sent = call(app, "POST", f"/api/chats/{cid}/edit", {"text": "Now say three words about switches."})
        check(status == 200, f"edit -> {status}")
        _, _, m = wait(app, cid)
        status, view = call(app, "GET", f"/api/chats/{cid}")
        stored = chat.Upstream(key)("GET", f"/api/v1/chats/{cid}")["chat"]["history"]["messages"]
        check(before <= set(stored) and len(view["messages"]) == 4,
              f"old versions kept in Open WebUI ({len(stored)} messages), the phone shows one branch")

        status, d = call(app, "POST", f"/api/chats/{cid}/archive", {})
        status2, d2 = call(app, "POST", f"/api/chats/{cid}/archive", {})
        check(status == status2 == 200 and d2 == {"archived": True}, "archive twice stays archived")
        _, lst = call(app, "GET", "/api/chats")
        _, arch = call(app, "GET", "/api/chats/archived")
        check(cid not in [c["id"] for c in lst["chats"]] and cid in [c["id"] for c in arch["chats"]],
              "it leaves my chats and shows in archived")
        status, d = call(app, "POST", f"/api/chats/{cid}/unarchive", {})
        _, lst = call(app, "GET", "/api/chats")
        check(d == {"archived": False} and cid in [c["id"] for c in lst["chats"]], "unarchive brings it back")

        for method, target in (("DELETE", "/api/chats"), ("GET", "/api/v1/users/"), ("POST", "/api/chats/all"),
                               ("POST", "/api/chats/archive/all")):
            status, _ = call(app, method, target, {} if method == "POST" else None)
            check(status in (404, 405), f"{method} {target} refused -> {status}")
        for method, path in (("DELETE", "/api/v1/chats/"), ("POST", "/api/v1/chats/archive/all"),
                             ("POST", f"/api/v1/chats/{cid}/share")):
            try:
                chat.Upstream(key)(method, path)
                check(False, f"the client refuses {method} {path}")
            except chat.UpstreamError as e:
                check(e.status == 0, f"the client refuses {method} {path} before any request")
    finally:
        # julz-chat deletes its own probe chat (v2); the key is the fallback if that failed
        status, d = call(app, "DELETE", f"/api/chats/{cid}")
        if not check(status == 200 and d == {"deleted": True}, "julz-chat deleted the probe chat"):
            req = urllib.request.Request(f"{chat.BACKEND}/api/v1/chats/{cid}", method="DELETE",
                                         headers={"Authorization": f"Bearer {key}"})
            urllib.request.urlopen(req, timeout=30).close()
    print(f"\n{'all held' if not failed else f'{failed} failed'}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
