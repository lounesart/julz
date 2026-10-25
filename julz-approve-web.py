#!/usr/bin/env python3
"""Approve Claude Code specs from the phone: read the text, tap, touch the fingerprint sensor.

Serves a small page on 127.0.0.1, published to the phone only by `tailscale serve`. Same job
as julz-approve.py, same store (gate.store_approved), with a passkey instead of a terminal.
Security model: SECURITY.md threats 31 to 37 and 43.
- Open WebUI shares the host network, so the container can reach this server: no request
  counts by itself, only an assertion checked by julz_webauthn does (threat 31)
- the page sends the sha256 it showed; the server rereads the spec and refuses if it changed,
  then the passkey signs that text, and the text it signed is what gets stored (threat 32)
- strict CSP, no inline script, spec text only ever set with textContent (threat 34)
- Host and Origin checked on every request, small JSON bodies only (threat 36)
- at most 3 specs shown, one approval per tap, never batch (threat 37)
- one process, one request at a time: challenges live in memory (julz_webauthn.Passkeys)
- ticks from the app (threat 113): the text is built from the todo snapshot julz-vault wrote,
  one signature covers the picked tasks, then the same tick requests the notes tool drops
Usage:
  ./julz-approve-web.py --enroll   print a one time code, then open the page on the phone
  ./julz-approve-web.py --revoke   forget the registered passkey (lost phone, threat 42)
  ./julz-approve-web.py            serve
Config: ~/.config/julz/approver.json  {"origin": "https://<laptop>.<tailnet>.ts.net:8443",
                                       "port": 8765}   (mode 600)
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402
import julz_keep as keep  # noqa: E402
import julz_webauthn as wa  # noqa: E402
import julz_devicekey as dk  # noqa: E402
import julz_vault as vault  # noqa: E402

HOME = Path.home()
INBOX = HOME / "Documents" / "julz-mem" / "Inbox" / "claude"
OUTBOX = HOME / "Documents" / "julz-mem" / "Outbox"
GATE_DIR = HOME / ".local" / "share" / "julz"
PROJECTS_FILE = HOME / ".config" / "julz" / "projects.json"
CONFIG_FILE = HOME / ".config" / "julz" / "approver.json"
# Own folder: saving the sign counter needs a writable directory, and ~/.config/julz holds
# the Claude token and API keys (threat 41)
CRED_FILE = HOME / ".config" / "julz" / "approver" / "passkey.json"
DEVICE_FILE = HOME / ".config" / "julz" / "approver" / "device.json"  # the app's key (107)
ENROLL_FILE = GATE_DIR / "webauthn" / "enroll.json"
STATIC_DIR = Path(__file__).resolve().parent / "approver"
# Ticks (113): the snapshot julz-vault writes, read only, and the folder the notes tool drops
# its requests into, which the container can write anyway
TODOS_FILE = GATE_DIR / "vault" / "todos.json"
REQUESTS = HOME / "Documents" / "julz-mem" / "Inbox" / ".requests"
MAX_TODOS_BYTES = 64_000
MAX_INBOX_BYTES = 256_000
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
INBOX_NOTE = re.compile(r"Inbox/\w[\w .-]{0,99}\.md")
INBOX_FOLDER = re.compile(r"(daily|study)(/[a-z0-9][a-z0-9-]{0,39})?")
INBOX_KEYS = {"name", "note", "sha256", "size", "modified", "preview"}
GOAL_KEY = re.compile(r"\d{4}(-\d{2}(-\d{2})?|-W\d{2})?")
NOTE_KEYS = {"name", "note", "size", "modified", "text"}
# The folders the notes browser may show (118): a root, then plain folder names, never ".."
# One note by its id: the SHA-256 of its path, looked up in notes.json, never a path (148)
NOTE_BY_ID = re.compile(r"/api/notes/([0-9a-f]{64})")
NOTES_FOLDER = re.compile(r"(study|daily|Inbox|Claude|Outbox|feedback)(/\w[\w .-]{0,99})*")
# From the snapshot's own caps: 300 notes of 4000 characters, 6 bytes a letter once JSON
# escapes it, plus room for names and keys. Less, and a full vault reads as empty (148)
MAX_NOTES_BYTES = vault.MAX_NOTES_SHOWN * (vault.MAX_NOTE_TEXT * 6 + 1000)

MAX_BODY = 16_000
MAX_SHOWN = 3
MAX_RECENT = 5
LOG_TAIL = 64_000  # read only the end of runner.log (and of the newest archive)
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/approve.js": ("approve.js", "text/javascript; charset=utf-8"),
          "/approve.css": ("approve.css", "text/css; charset=utf-8")}
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Cache-Control": "no-store",
}


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def load_config(path: Path) -> tuple[str, int]:
    data = gate.read_private_file(path, 0o077)
    try:
        cfg = json.loads(data)
        origin, port = cfg["origin"], cfg["port"]
    except (ValueError, KeyError, TypeError):
        raise gate.GateError(f'{path} must be {{"origin": "https://...:8443", "port": 8765}}') \
            from None
    wa.check_origin(origin)
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise gate.GateError(f"{path}: port must be a number from 1024 to 65535")
    return origin, port


class App:
    """The approver without sockets: handle() takes a request and returns a response."""

    def __init__(self, passkeys: wa.Passkeys, inbox: Path, dirs: gate.Dirs, projects_file: Path,
                 port: int, static: dict[str, bytes], devices: dk.DeviceKeys | None = None):
        self.pk = passkeys
        # The Julz device key: a second way to sign the same actions (107)
        self.devices = devices or dk.DeviceKeys(DEVICE_FILE, passkeys.enroll_file, passkeys.clock)
        self.inbox = Path(inbox)
        self.dirs = dirs
        self.projects_file = projects_file
        self.static = static
        # Names the page files this process serves. An open page whose files are older sees
        # a different value in /api/state and reloads itself
        self.page = gate.sha256("".join(gate.sha256(static[k].decode())
                                        for k in sorted(static)))[:12]
        # Through tailscale serve the browser sends the public name; on the laptop itself,
        # 127.0.0.1. Anything else is DNS rebinding or a confused client (threat 36)
        self.hosts = {urlsplit(passkeys.origin).netloc, f"127.0.0.1:{port}"}
        self.names: dict[str, str] = {}  # nonce -> inbox file name, or task root for a need
        self.todos_file, self.requests = TODOS_FILE, REQUESTS

    # ---------- plumbing ----------

    def handle(self, method: str, path: str, headers: dict, body: bytes):
        """Returns (status, headers, body). Never raises."""
        headers = {k.lower(): v for k, v in headers.items()}
        try:
            if headers.get("host") not in self.hosts:
                raise HTTPError(421, "wrong host")
            gets = {"/api/state": self.state, "/api/done": self.done_week, "/api/inbox": self.inbox_notes,
                    "/api/notes": self.all_notes, "/api/feedback": self.feedback_list,
                    "/api/integrations": self.integrations, "/api/goals": self.goals}
            posts = {"/api/begin": self.begin, "/api/finish": self.finish,
                     "/api/enroll/begin": self.enroll_begin,
                     "/api/enroll/finish": self.enroll_finish,
                     "/api/device/enroll": self.device_enroll}
            if method == "GET" and path in STATIC:
                name, ctype = STATIC[path]
                return self.reply(200, self.static[name], ctype)
            if method == "GET" and path in gets:
                return self.json(200, gets[path]())
            if method == "POST" and path in posts:
                return self.json(200, posts[path](self.read_json(headers, body)))
            one = NOTE_BY_ID.fullmatch(path)
            if method == "GET" and one:
                return self.json(200, self.one_note(one.group(1)))
            if path in STATIC or path in gets or path in posts or one:
                raise HTTPError(405, "method not allowed")
            raise HTTPError(404, "not found")
        except HTTPError as e:
            return self.json(e.status, {"error": str(e)})
        except wa.AuthError as e:
            return self.json(403, {"error": str(e)})
        except gate.GateError as e:
            return self.json(409, {"error": str(e)})
        except Exception as e:
            # Only the type: a message could quote a file path or request bytes
            return self.json(500, {"error": type(e).__name__})

    def read_json(self, headers: dict, body: bytes) -> dict:
        # A browser always sends Origin on POST; a form or page from elsewhere sends its own
        if headers.get("origin") != self.pk.origin:
            raise HTTPError(403, "wrong origin")
        if headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise HTTPError(415, "JSON only")
        if len(body) > MAX_BODY:
            raise HTTPError(413, "request too large")
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400, "bad JSON") from None
        if not isinstance(data, dict):
            raise HTTPError(400, "bad JSON")
        return data

    def reply(self, status: int, body: bytes, ctype: str):
        return status, {**SECURITY_HEADERS, "Content-Type": ctype}, body

    def json(self, status: int, data):
        return self.reply(status, json.dumps(data).encode(), "application/json")

    # ---------- specs ----------

    def specs(self):
        """(shown, refused, waiting): up to MAX_SHOWN valid specs, oldest first."""
        projects = gate.load_projects(self.projects_file)
        shown, refused, waiting = [], [], 0
        if not self.inbox.is_dir():
            return shown, refused, waiting
        paths = [p for p in self.inbox.iterdir() if p.suffix == ".md"]
        paths.sort(key=lambda p: (p.lstat().st_mtime, p.name))
        for path in paths:
            try:
                text, spec = gate.load_spec(path, projects)
            except gate.SpecError as e:
                refused.append({"name": repr(path.name)[:80], "reason": str(e)})
                continue
            if len(shown) >= MAX_SHOWN:
                waiting += 1
                continue
            shown.append({"name": path.name, "sha256": gate.sha256(text),
                          "project": spec["project"], "text": text})
        return shown, refused, waiting

    def spec_path(self, name) -> Path:
        # Check the name before joining it: Path("inbox/../x.md").name is "x.md" (CWE-22)
        if not isinstance(name, str) or not gate.SPEC_NAME.match(name):
            raise HTTPError(400, "bad spec name")
        return self.inbox / name

    def needs(self) -> list[dict]:
        """Tasks waiting for my answer (threats 37, 40), at most MAX_SHOWN."""
        keys = ("root", "step", "project", "goal", "need", "why", "text", "sha256")
        # Claude says /work; on the laptop that is the task's work copy. Shown so I do the
        # step in the right place (found on 2026-10-16, see SECURITY.md step 3)
        work = self.dirs.log.parent / "work"
        out = []
        for n in gate.open_needs(self.dirs, self.pk.clock())[:MAX_SHOWN]:
            try:
                stopped = bool(gate.load_task(self.dirs, n["root"]).get("stopped"))
            except gate.SpecError:
                stopped = False
            out.append({**{k: n[k] for k in keys}, "work": str(work / n["root"]),
                        "stopped": stopped})
        return out

    def goal_of(self, digest: str) -> str:
        """The goal line of a spec in done/, following a continuation to its root."""
        for _ in range(2):
            try:
                text = gate.decode(gate.read_regular(self.dirs.done / f"{digest}.md",
                                                     gate.MAX_SPEC_BYTES))
            except gate.SpecError:
                return ""
            first = text.split("\n", 1)[0]
            if first.startswith("continue:"):
                digest = first[len("continue:"):].strip()
                if not gate.HEX64.match(digest):
                    return ""
                continue
            for line in text.split("\n"):
                if line.startswith("goal:"):
                    return line[5:].strip()
            return ""
        return ""

    def log_tail(self) -> list[str]:
        """The end of runner.log, read once per state. Right after a rotation the file is
        short, so the end of the newest archive from the run window goes in front (53)."""
        lines, whole = self._tail(self.dirs.log)
        if whole:
            arch = gate.archives(self.dirs)
            if arch and self.pk.clock() - arch[-1].lstat().st_mtime < gate.RUN_WINDOW:
                lines = self._tail(arch[-1])[0] + lines
        return lines

    @staticmethod
    def _tail(path: Path) -> tuple[list[str], bool]:
        """(the last lines, whether that is the whole file). Links are not followed."""
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            with os.fdopen(fd, "rb") as f:
                start = max(0, f.seek(0, 2) - LOG_TAIL)
                f.seek(start)
                lines = f.read().decode("utf-8", "replace").splitlines()
        except OSError:
            return [], True
        # Only a read that starts inside the file can begin with half a line
        return (lines[1:] if start else lines), start == 0

    def queued(self, cap: dict) -> list[dict]:
        """Approved and waiting for the runner, oldest first as it runs them, at most
        MAX_SHOWN. Shown so an approval never seems lost. A first run held by a full soft cap
        offers a Run now override to sign (threat 52); the gate checks it all again."""
        found = []
        try:
            for path in self.dirs.approved.iterdir():
                if gate.APPROVED_NAME.match(path.name):
                    found.append((path.lstat().st_mtime, path))
        except OSError:
            return []
        out = []
        for _, path in sorted(found)[:MAX_SHOWN]:
            try:
                text = gate.decode(gate.read_regular(path, gate.MAX_SPEC_BYTES))
            except (gate.SpecError, OSError):
                continue
            try:
                cont = gate.check_continuation(text)
                goal, step, kind = self.goal_of(cont["root"]), cont["step"], "continue"
            except gate.SpecError:
                try:
                    goal, step = gate.parse_fields(text, gate.FIELDS, (gate.NOTE,))["goal"], 1
                    kind = "spec"
                except gate.SpecError:
                    continue
            digest = path.name[:-3]
            overridden = (self.dirs.approved / f"override-{digest}").exists()
            override = None
            if kind == "spec" and not overridden and cap["used"] >= cap["max"] \
                    and cap["all"] < cap["hard"]:
                o_text = gate.override_text(digest, cap["used"])
                override = {"text": o_text, "sha256": gate.sha256(o_text)}
            out.append({"sha256": digest, "goal": goal[:200], "step": step, "kind": kind,
                        "overridden": overridden, "override": override})
        return out

    def cap(self, tail: list[str]) -> dict:
        """The run cap (threat 28) for the page. The runner enforces it from the whole log
        and its archives; the tail can only miss runs if two hours of log were over LOG_TAIL."""
        now = self.pk.clock()
        first = gate.window_runs(tail, now, first_only=True)
        every = gate.window_runs(tail, now)

        def iso(slot):
            return None if slot is None else \
                datetime.fromtimestamp(slot, timezone.utc).isoformat(timespec="seconds")
        return {"used": len(first), "max": gate.MAX_RUNS, "all": len(every),
                "hard": gate.HARD_MAX, "next_slot": iso(gate.next_slot(first, gate.MAX_RUNS)),
                "hard_slot": iso(gate.next_slot(every, gate.HARD_MAX))}

    def recent(self, tail: list[str]) -> list[dict]:
        """The last runs and how they ended, newest first. Text only, from runner.log."""
        runs = []
        for line in reversed(tail):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            digest = e.get("sha256", "") if isinstance(e, dict) else ""
            if e.get("action") != "run" or not isinstance(digest, str) \
                    or not gate.HEX64.match(digest):
                continue
            runs.append({"time": str(e.get("time", ""))[:19].replace("T", " "),
                         "sha256": digest, "status": str(e.get("status", ""))[:20],
                         "goal": self.goal_of(digest)[:200]})
            if len(runs) == MAX_RECENT:
                break
        return runs

    def state(self) -> dict:
        shown, refused, waiting = self.specs()
        tail = self.log_tail()
        cap = self.cap(tail)
        return {"enrolled": wa.load_credential(self.pk.cred_file) is not None,
                "specs": shown, "refused": refused, "waiting": waiting,
                "needs": self.needs(), "running": self.running(), "queued": self.queued(cap),
                "cap": cap, "recent": self.recent(tail), "keeps": self.keeps(),
                "topics": keep.used_topics(self.dirs), "page": self.page,
                "device": self.devices.fingerprint()}

    def keeps(self) -> list[dict]:
        """Done tasks I can Keep. Read from manifests/ only: the approver never sees a work
        copy or the vault (threat 60)."""
        return [{k: c[k] for k in ("root", "goal", "project", "files", "rejected",
                                    "rejected_count", "stopped", "sha256")}
                for c in keep.keep_cards(self.dirs)]

    def running(self) -> dict | None:
        """The run going now, with the text to sign to stop it (threat 47)."""
        run = gate.current_run(self.dirs, self.pk.clock())
        if run is None:
            return None
        text = gate.halt_text(run)
        return {"sha256": run["sha256"], "project": run.get("project", ""),
                "goal": run.get("goal", ""), "step": run.get("step", 1),
                "started": run["started"], "text": text, "text_sha256": gate.sha256(text)}

    def todos(self) -> dict:
        """The todo snapshot as julz-vault wrote it, checked for shape. Missing or off: 404."""
        try:
            data = json.loads(gate.read_regular(self.todos_file, MAX_TODOS_BYTES))
        except (gate.SpecError, OSError, ValueError, UnicodeDecodeError):
            raise HTTPError(404, "no todo snapshot: reload") from None
        lists = data.get("lists") if isinstance(data, dict) else None
        if not isinstance(data.get("id") if isinstance(data, dict) else None, str) \
                or not gate.HEX64.match(data["id"]) or not isinstance(lists, list) \
                or not all(isinstance(l, dict) and isinstance(l.get("name"), str)
                           and isinstance(l.get("note"), str) and isinstance(l.get("open"), list)
                           and isinstance(l.get("doing", []), list)
                           and all(isinstance(i, str) for i in l["open"] + l.get("doing", [])) for l in lists):
            raise HTTPError(404, "no todo snapshot: reload")
        return data

    def done_week(self) -> dict:
        """The Done tab (114): what julz-vault wrote, checked again as if anyone could have.
        Anything off is an empty week, never an error with text in it."""
        empty = {"days": []}
        try:
            data = json.loads(gate.read_regular(self.todos_file.parent / "done-week.json", MAX_TODOS_BYTES))
        except (gate.SpecError, OSError, ValueError, UnicodeDecodeError):
            return empty
        days = data.get("days") if isinstance(data, dict) else None
        if not isinstance(days, list) or len(days) > vault.DONE_DAYS:
            return empty
        count = 0
        for d in days:
            if not isinstance(d, dict) or set(d) != {"date", "items"} or not isinstance(d["date"], str) \
                    or not DAY.fullmatch(d["date"]) or not isinstance(d["items"], list):
                return empty
            for i in d["items"]:
                if not isinstance(i, dict) or set(i) != {"list", "item"} \
                        or not all(isinstance(v, str) and vault._travels(v) for v in i.values()):
                    return empty
                count += 1
        return empty if count > vault.MAX_DONE_WEEK else {"days": days}

    def inbox_notes(self) -> dict:
        """The Inbox for the app (116): what julz-vault wrote, checked again as if anyone could
        have. Anything off is an empty Inbox."""
        empty = {"id": "", "notes": [], "folders": []}
        try:
            data = json.loads(gate.read_regular(self.todos_file.parent / "inbox.json", MAX_INBOX_BYTES))
        except (gate.SpecError, OSError, ValueError, UnicodeDecodeError):
            return empty
        if not isinstance(data, dict) or set(data) != {"id", "notes", "folders"} \
                or not isinstance(data["id"], str) or not gate.HEX64.match(data["id"]) \
                or not isinstance(data["notes"], list) or len(data["notes"]) > vault.MAX_INBOX_NOTES \
                or not isinstance(data["folders"], list):
            return empty
        for n in data["notes"]:
            if not isinstance(n, dict) or set(n) != INBOX_KEYS \
                    or not all(isinstance(n[k], str) for k in INBOX_KEYS - {"size"}) \
                    or type(n["size"]) is not int or not INBOX_NOTE.fullmatch(n["note"]) \
                    or not gate.HEX64.match(n["sha256"]) or not DAY.fullmatch(n["modified"]) \
                    or len(n["preview"]) > vault.MAX_PREVIEW or vault._shown(n["preview"]) != n["preview"]:
                return empty
        if not all(isinstance(f, str) and INBOX_FOLDER.fullmatch(f) for f in data["folders"]):
            return empty
        return data

    def checked_notes(self) -> list:
        """What julz-vault wrote for the notes browser (118), checked again as if anyone could
        have. Anything off is no folders at all."""
        try:
            data = json.loads(gate.read_regular(self.todos_file.parent / "notes.json", MAX_NOTES_BYTES))
        except (gate.SpecError, OSError, ValueError, UnicodeDecodeError):
            return []
        folders = data.get("folders") if isinstance(data, dict) and set(data) == {"folders"} else None
        if not isinstance(folders, list):
            return []
        count = 0
        for f in folders:
            if not isinstance(f, dict) or set(f) != {"folder", "notes"} or not isinstance(f["folder"], str) \
                    or not NOTES_FOLDER.fullmatch(f["folder"]) or f["folder"].startswith("Inbox/") \
                    or not isinstance(f["notes"], list):
                return []
            for n in f["notes"]:
                if not isinstance(n, dict) or set(n) != NOTE_KEYS \
                        or not all(isinstance(n[k], str) for k in NOTE_KEYS - {"size"}) \
                        or type(n["size"]) is not int or n["note"].rpartition("/")[0] != f["folder"] \
                        or not n["note"].endswith(".md") or not DAY.fullmatch(n["modified"]) \
                        or len(n["text"]) > vault.MAX_NOTE_TEXT or vault._shown(n["text"]) != n["text"]:
                    return []
                count += 1
        return [] if count > vault.MAX_NOTES_SHOWN else folders

    def all_notes(self) -> dict:
        """The notes browser: folders and names with an id each, no text, so the reply stays
        small however long the notes are (206). Read only."""
        return {"folders": [{"folder": f["folder"], "notes": [
            {**{k: v for k, v in n.items() if k != "text"}, "id": gate.sha256(n["note"])}
            for n in f["notes"]]} for f in self.checked_notes()]}

    def one_note(self, nid: str) -> dict:
        """One note's text by its id (148). The id only selects among the checked snapshot;
        no vault file is opened for it. Unknown is 404."""
        for f in self.checked_notes():
            for n in f["notes"]:
                if gate.sha256(n["note"]) == nid:
                    return {"note": n["note"], "text": n["text"]}
        raise HTTPError(404, "not found")

    def feedback_list(self) -> dict:
        """Open and done feedback for the app (120): what julz-vault wrote, checked again as if
        anyone could have. Anything off is an empty list."""
        empty = {"items": []}
        try:
            data = json.loads(gate.read_regular(self.todos_file.parent / "feedback.json", MAX_TODOS_BYTES * 2))
        except (gate.SpecError, OSError, ValueError, UnicodeDecodeError):
            return empty
        items = data.get("items") if isinstance(data, dict) and set(data) == {"items"} else None
        if not isinstance(items, list) or len(items) > vault.MAX_FEEDBACK_OPEN + vault.MAX_FEEDBACK_DONE:
            return empty
        keys = {"name", "done", "created", "kind", "state", "where", "text"}
        for i in items:
            if not isinstance(i, dict) or set(i) != keys or type(i["done"]) is not bool \
                    or not all(isinstance(i[k], str) for k in keys - {"done"}) \
                    or not vault.NAME.fullmatch(i["name"]) or not (i["created"] == "" or DAY.fullmatch(i["created"])) \
                    or i["kind"] not in ("",) + vault.FEEDBACK_KINDS or len(i["state"]) > 20 or len(i["where"]) > 60 \
                    or len(i["text"]) > vault.MAX_FEEDBACK_PREVIEW \
                    or any(vault._shown(i[k]) != i[k] for k in ("state", "where", "text")):
                return empty
        return {"items": items}

    def goals(self) -> dict:
        """The four current periods' goals for the app (123), checked again as if anyone could
        have written them. Anything off is no goals at all."""
        empty = {"id": "", "periods": [], "tree": {}, "milestones": []}

        def minutes(m) -> bool:  # own hours: none, or whole minutes up to 9999 h (129)
            return m is None or (type(m) is int and 0 < m <= vault.MAX_SPENT_MIN)

        def day(d) -> bool:  # a due date: none, or a real day in ISO form (126)
            return d is None or (isinstance(d, str) and vault.DUE_DAY.fullmatch(d) is not None and vault._due_of(f"[due:: {d}]") == d)
        try:
            data = json.loads(gate.read_regular(self.todos_file.parent / "goals.json", MAX_TODOS_BYTES))
        except (gate.SpecError, OSError, ValueError, UnicodeDecodeError):
            return empty
        tree = data.get("tree") if isinstance(data, dict) else None
        if not isinstance(tree, dict) or len(tree) > 500 or not all(
                isinstance(k, str) and vault.GOAL_ID.fullmatch(k) and (v is None or (isinstance(v, str) and vault.GOAL_ID.fullmatch(v)))
                for k, v in tree.items()):
            return empty
        if not isinstance(data, dict) or set(data) != {"id", "periods", "tree", "milestones"} or not isinstance(data["id"], str) \
                or not gate.HEX64.match(data["id"]) or not isinstance(data["periods"], list) or len(data["periods"]) > 4 \
                or not isinstance(data["milestones"], list) or len(data["milestones"]) > vault.MAX_MILESTONES:
            return empty
        for m in data["milestones"]:
            if not isinstance(m, dict) or set(m) != {"goal", "text", "due", "rollup"} \
                    or not isinstance(m["goal"], str) or not vault.GOAL_ID.fullmatch(m["goal"]) or m["due"] is None or not day(m["due"]) \
                    or not (m["rollup"] is None or (type(m["rollup"]) is int and 0 <= m["rollup"] <= 100)) \
                    or not isinstance(m["text"], str) or len(m["text"]) > vault.MAX_GOAL_TEXT + 60 \
                    or vault._shown(m["text"]) != m["text"] or vault.NOT_PLAIN.search(m["text"]):
                return empty
        for p in data["periods"]:
            if not isinstance(p, dict) or set(p) != {"key", "label", "note", "goals"} \
                    or not isinstance(p["key"], str) or not GOAL_KEY.fullmatch(p["key"]) \
                    or p["note"] != f"goals/{p['key']}.md" or not isinstance(p["label"], str) or len(p["label"]) > 20 \
                    or not isinstance(p["goals"], list) or len(p["goals"]) > vault.MAX_GOALS:
                return empty
            for g in p["goals"]:
                if not isinstance(g, dict) or set(g) != {"text", "done", "progress", "goal", "linked", "parent", "rollup", "parts",
                                                         "due", "est", "spent", "hours"} \
                        or not day(g["due"]) or not all(minutes(m) for m in (g["est"], g["spent"])) \
                        or not (g["hours"] is None or (isinstance(g["hours"], list) and len(g["hours"]) == 2
                                                       and all(type(m) is int and 0 <= m <= 10 ** 7 for m in g["hours"]))) \
                        or not (g["parent"] is None or (isinstance(g["parent"], str) and vault.GOAL_ID.fullmatch(g["parent"]))) \
                        or not (g["rollup"] is None or (type(g["rollup"]) is int and 0 <= g["rollup"] <= 100)) \
                        or type(g["parts"]) is not int or not 0 <= g["parts"] <= 10000 \
                        or not isinstance(g["text"], str) or len(g["text"]) > vault.MAX_GOAL_TEXT + 60 \
                        or vault._shown(g["text"]) != g["text"] or type(g["done"]) is not bool \
                        or not all(x is None or (isinstance(x, list) and len(x) == 2 and all(type(n) is int for n in x))
                                   for x in (g["progress"], g["linked"])) \
                        or not (g["goal"] is None or (isinstance(g["goal"], str) and vault.GOAL_TAG.fullmatch("#goal/" + g["goal"]))):
                    return empty
        return data

    def integrations(self) -> dict:
        """What Julz runs on its own, for the Links tab (122). The list and its words are fixed
        here; facts are those words with numbers and times from runner.log and julz-vault's
        status file, never text from either. Watch only."""
        now = self.pk.clock()
        try:
            lines = gate.log_lines(self.dirs, 7 * 86400, now)
        except (gate.SpecError, OSError):
            lines = []
        runs = sum(1 for t in self._run_times(lines) if now - t < 7 * 86400)
        last_sync = None
        for line in reversed(lines):
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if isinstance(e, dict) and e.get("action") == "sync":
                last_sync = e
                break
        # "Label: value" for what is data, so the app shows a spec line (22e); still fixed words with
        # numbers and times only (122)
        keep_status, keep_fact = "On", "Last sync: none yet"
        if last_sync is not None:
            when = self._clock_time(last_sync.get("time"))
            m = re.match(r"(\d{1,6}) notes", str(last_sync.get("reason", "")))
            if last_sync.get("status") == "ok":
                keep_fact = f"Last sync: {when}" + (f", {int(m.group(1))} notes" if m else "")
            else:
                keep_status, keep_fact = "Check", f"Last sync: failed {when}, see runner.log on the laptop"
        try:
            st = json.loads(gate.read_regular(self.todos_file.parent / "vault-status.json", 4096))
            commits = st["commits_today"] if isinstance(st, dict) and type(st.get("commits_today")) is int else None
        except (gate.SpecError, OSError, ValueError, UnicodeDecodeError):
            commits = None
        commit_fact = "Commits today: not written yet" if commits is None else f"Commits today: {commits}"

        def item(id_, name, what, status, *facts):
            return {"id": id_, "name": name, "what": what, "status": status, "facts": list(facts)}
        return {"items": [
            item("keep", "Keep sync", "Notes kept from Claude reach Julz", keep_status, keep_fact,
                 "Checks: every 10 minutes", "Your own notes: never touched"),
            item("delegate", "Delegation", "Claude Code runs a spec after your fingerprint", "Gated",
                 f"Runs, 7 days: {runs}", "Each run: waits for the approver"),
            item("vault", "Notes vault", "Changes to your notes after your click", "On", commit_fact,
                 "Per change: one git commit"),
            item("push", "Push server", "ntfy on the laptop, tailnet only", "On",
                 "Reaches: this phone only, by token", "Missed notices: catch up on reconnect"),
            item("voice", "Voice", "Speech to text in the chat", "Check",
                 "Language: Russian only, English and Polish come out wrong", "Feedback: open, BACKLOG 12"),
            item("memlog", "Memory log", "RAM of each part of Julz, every 10 minutes", "On",
                 "Report: julz-memlog.py --report on the laptop"),
            item("ci", "CI checks", "Tests and gitleaks on every push", "Planned", "State: in PLAN.md, not built yet"),
        ]}

    @staticmethod
    def _run_times(lines: list[str]) -> list[float]:
        """When each run in the log happened; a line whose time cannot be read is left out."""
        out = []
        for line in lines:
            try:
                e = json.loads(line)
                if isinstance(e, dict) and e.get("action") == "run":
                    out.append(datetime.fromisoformat(str(e.get("time"))).timestamp())
            except (ValueError, TypeError):
                continue
        return out

    @staticmethod
    def _clock_time(stamp) -> str:
        try:
            return datetime.fromisoformat(str(stamp)).astimezone().strftime("%H:%M")
        except (ValueError, TypeError):
            return "at an unknown time"

    # ---------- signed actions ----------

    def begin(self, data: dict) -> dict:
        action, seen = data.get("action"), data.get("sha256")
        if action in ("approve", "reject"):
            name = data.get("name")
            shown, _, _ = self.specs()
            match = [s for s in shown if s["name"] == self.spec_path(name).name]
            key = name
        elif action in ("continue", "answer", "stop", "discard"):
            # The text to sign is built from host task state, never sent by the page
            key = data.get("root")
            match = [n for n in self.needs() if n["root"] == key]
        elif action == "override":
            # Run now for one queued first run, with the text built from the cap I see
            key = data.get("item")
            match = [q["override"] for q in self.queued(self.cap(self.log_tail()))
                     if q["sha256"] == key and q["override"]]
        elif action == "halt":
            # Only the run going now, with the text built from running.json
            run = self.running()
            key = data.get("run")
            match = [{"text": run["text"], "sha256": run["text_sha256"]}] \
                if run and run["sha256"] == key else []
        elif action == "keep":
            # The page proves which manifest it showed and gives only the topic and the ticked
            # paths. The text to sign is built here, paths in manifest order (threats 55, 57)
            key = data.get("root")
            reason = keep.check_topic(data.get("topic"))
            if reason:
                raise HTTPError(400, reason)
            match = []
            for c in self.keeps():
                if c["root"] == key:
                    try:
                        picked = keep.pick_in_order({"keep": c["files"]}, data.get("pick"))
                    except gate.SpecError as e:
                        raise HTTPError(400, str(e)) from None
                    match = [{"text": keep.keep_text(key, data["topic"], c["sha256"], picked),
                              "sha256": c["sha256"]}]
        elif action in ("tick", "start"):
            # The app proves which snapshot it saw and picks (list, task) pairs. The text, paths
            # included, is built here from the snapshot (113); start the same, its own head (127)
            snap = self.todos()
            key = snap["id"]
            if seen != key:
                raise HTTPError(409, "changed since you saw it: reload")
            try:
                match = [{"text": vault.tick_text(snap, data.get("pick"), verb=action), "sha256": key}]
            except vault.Refused as e:
                raise HTTPError(400, str(e)) from None
        elif action == "feedback":
            # The text to sign is built here from the kind and my words; the app proves it hashed
            # the same words (120)
            words = data.get("text")
            try:
                match = [{"text": vault.feedback_text(data.get("kind"), words),
                          "sha256": gate.sha256(words) if isinstance(words, str) else ""}]
            except vault.Refused as e:
                raise HTTPError(400, str(e)) from None
            key = match[0]["sha256"]
        elif action == "save":
            # A chat answer into Inbox (139): the text to sign is built here from the answer;
            # the app proves it hashed the same words, as for feedback
            words = data.get("text")
            try:
                match = [{"text": vault.save_text(words),
                          "sha256": gate.sha256(words) if isinstance(words, str) else ""}]
            except vault.Refused as e:
                raise HTTPError(400, str(e)) from None
            key = match[0]["sha256"]
        elif action == "goal":
            # As ticks: the app proves which goals it saw; the text is built here (123)
            snap = self.goals()
            key = snap["id"]
            if not key:
                raise HTTPError(404, "no goals snapshot: reload")
            if seen != key:
                raise HTTPError(409, "changed since you saw it: reload")
            try:
                # Links name a todo, so the todos snapshot comes along when it is there (124)
                try:
                    todos = self.todos()
                except HTTPError:
                    todos = None
                match = [{"text": vault.goal_text(snap, data.get("pick"), todos), "sha256": key}]
            except vault.Refused as e:
                raise HTTPError(400, str(e)) from None
        elif action == "inbox":
            # The same way as ticks: the app proves which snapshot it saw and picks notes;
            # the text is built here from inbox.json (117)
            snap = self.inbox_notes()
            key = snap["id"]
            if not key:
                raise HTTPError(404, "no Inbox snapshot: reload")
            if seen != key:
                raise HTTPError(409, "changed since you saw it: reload")
            try:
                match = [{"text": vault.inbox_text(snap, data.get("pick")), "sha256": key}]
            except vault.Refused as e:
                raise HTTPError(400, str(e)) from None
        else:
            raise HTTPError(400, "unknown action")
        if not match:
            raise HTTPError(404, "not in the list: reload")
        if match[0]["sha256"] != seen:
            # Changed after the page showed it. Never sign text I did not see
            raise HTTPError(409, "changed since you saw it: reload")
        text = match[0]["text"]
        if action == "approve":
            # My note, if any, becomes the last line of the text I sign (threat 93)
            try:
                text = gate.approved_text(text, data.get("note"))
            except gate.SpecError as e:
                raise HTTPError(400, str(e)) from None
        if action == "answer":
            # The page gives only the answer value. The rest comes from the need text it
            # just proved it saw (threat 51)
            try:
                cont = gate.check_continuation(text)
                text = gate.continuation_text({"root": cont["root"], "step": cont["step"],
                                               "need_hash": cont["need_hash"]},
                                              data.get("answer"))
            except gate.SpecError as e:
                raise HTTPError(400, str(e)) from None
        if data.get("via") == "device":
            # The app shows this exact text and signs its hash (109)
            begun = self.devices.begin(action, text)
            self.forget_old_names()
            self.names[begun["nonce"]] = key
            return begun
        nonce, options = self.pk.begin(action, text)
        self.forget_old_names()
        self.names[nonce] = key
        return {"nonce": nonce, "publicKey": options["publicKey"]}

    def forget_old_names(self):
        live = set(self.pk.pending) | set(self.devices.pending)
        self.names = {k: v for k, v in self.names.items() if k in live}

    def finish(self, data: dict) -> dict:
        action, nonce = data.get("action"), data.get("nonce")
        credential, signature = data.get("credential"), data.get("signature")
        if not isinstance(nonce, str) or (not isinstance(credential, dict) and signature is None):
            raise HTTPError(400, "nonce and credential or signature needed")
        name = self.names.pop(nonce, None)
        # The exact signed text, or raises. A device nonce only takes a device signature and
        # a passkey challenge only an assertion: each lives in its own pending list (107)
        if signature is not None:
            text = self.devices.finish(nonce, action, signature)
            channel = f"device {self.devices.fingerprint()}"
        else:
            text = self.pk.finish(nonce, action, credential)
            channel = "phone"
        digest = gate.sha256(text)
        if action in ("continue", "answer"):
            gate.store_continuation(text, self.dirs, self.pk.clock())
            gate.log(self.dirs, "approve-channel", digest, "ok", channel)
            return {"done": "continued", "sha256": digest}
        if action == "stop":
            gate.stop_task(text, self.dirs, self.pk.clock())
            gate.log(self.dirs, "signed", digest, "ok", f"stop, {channel}")  # which key (131)
            return {"done": "stopped", "sha256": digest}
        if action == "override":
            gate.store_override(text, self.dirs, self.pk.clock())
            gate.log(self.dirs, "signed", digest, "ok", f"override, {channel}")
            return {"done": "run now signed", "sha256": digest}
        if action == "halt":
            run = gate.request_halt(text, self.dirs, self.pk.clock(), channel)
            return {"done": "stopping", "sha256": run}
        if action == "discard":
            gate.discard_task(text, self.dirs, self.pk.clock())
            gate.log(self.dirs, "signed", digest, "ok", f"discard, {channel}")
            return {"done": "deleted", "sha256": digest}
        if action == "keep":
            keep.store_keep(text, self.dirs, channel)
            return {"done": "keep signed", "sha256": digest}
        if action == "feedback":
            try:
                req = vault.feedback_request(text, datetime.now())
            except vault.Refused as e:
                raise HTTPError(400, str(e)) from None
            vault.write_request(self.requests, req)
            gate.log(self.dirs, "feedback-signed", digest, "ok", channel)
            return {"done": "sent", "sha256": digest}
        if action == "save":
            try:
                req = vault.save_request(text, datetime.now())
            except vault.Refused as e:
                raise HTTPError(400, str(e)) from None
            vault.write_request(self.requests, req)
            gate.log(self.dirs, "save-signed", digest, "ok", channel)
            return {"done": "saved", "sha256": digest}
        if action == "goal":
            try:
                reqs = vault.goal_requests(text, self.goals())
            except vault.Refused as e:
                raise HTTPError(409, str(e)) from None
            for req in reqs:
                vault.write_request(self.requests, req)
            gate.log(self.dirs, "goal-signed", digest, "ok", f"{len(reqs)} changes, {channel}")
            return {"done": "done" if len(reqs) == 1 else f"{len(reqs)} done", "sha256": digest}
        if action == "inbox":
            # Each request carries the note's hash from the snapshot I signed against: one
            # rewritten since refuses here, a note changed since refuses in julz-vault (117)
            try:
                reqs = vault.inbox_requests(text, self.inbox_notes())
            except vault.Refused as e:
                raise HTTPError(409, str(e)) from None
            for req in reqs:
                vault.write_request(self.requests, req)
            gate.log(self.dirs, "inbox-signed", digest, "ok", f"{len(reqs)} notes, {channel}")
            return {"done": "done" if len(reqs) == 1 else f"{len(reqs)} done", "sha256": digest}
        if action in ("tick", "start"):
            try:
                ticks = vault.ticks_of(text, verb=action)
            except vault.Refused as e:
                raise HTTPError(400, str(e)) from None
            for note, item in ticks:
                vault.write_request(self.requests, {"op": action, "note": note, "item": item})
            gate.log(self.dirs, f"{action}-signed", digest, "ok", f"{len(ticks)} tasks, {channel}")
            word = "ticked" if action == "tick" else "started"
            return {"done": word if len(ticks) == 1 else f"{len(ticks)} {word}", "sha256": digest}
        if action == "approve":
            gate.store_approved(text, self.dirs, gate.load_projects(self.projects_file))
            gate.log(self.dirs, "approve-channel", digest, "ok", channel)
            # The inbox holds the spec without my note
            self.remove_if_same(name, gate.sha256(gate.spec_without_note(text)))
            return {"done": "approved", "sha256": digest}
        self.remove_if_same(name, digest)
        gate.log(self.dirs, "reject", digest, "ok", channel)
        return {"done": "rejected", "sha256": digest}

    def remove_if_same(self, name, digest: str):
        """Remove the inbox file only if it still holds the text I signed. If julz rewrote
        it meanwhile, the new text stays and shows up as a new spec."""
        if not name:
            return
        path = self.spec_path(name)
        try:
            text = gate.decode(gate.read_regular(path, gate.MAX_SPEC_BYTES))
        except gate.SpecError:
            return
        if gate.sha256(text) == digest:
            path.unlink(missing_ok=True)

    # ---------- the device key (threat 108) ----------

    def device_enroll(self, data: dict) -> dict:
        old = self.devices.fingerprint()
        fingerprint = self.devices.enroll(data.get("code"), data.get("public_key"))
        gate.log(self.dirs, "enroll", "", "ok", f"device {fingerprint}" + (f" replaces {old}" if old else ""))
        return {"fingerprint": fingerprint}

    # ---------- enrollment (threat 35) ----------

    def enroll_begin(self, data: dict) -> dict:
        code = data.get("code")
        if not isinstance(code, str) or len(code) > 40:
            raise HTTPError(400, "code needed")
        return {"publicKey": self.pk.enroll_begin(code)["publicKey"]}

    def enroll_finish(self, data: dict) -> dict:
        credential = data.get("credential")
        if not isinstance(credential, dict):
            raise HTTPError(400, "credential needed")
        cred_id = self.pk.enroll_complete(credential)
        gate.log(self.dirs, "enroll", "", "ok", f"passkey {cred_id[:16]}")
        return {"done": "enrolled"}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        timeout = 10  # one request at a time: a client that stalls is dropped

        def version_string(self):
            return "julz"  # no Python version in the Server header

        def do_GET(self):
            self.respond(b"")

        def do_POST(self):
            try:
                length = int(self.headers.get("Content-Length", ""))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                return self.send(*app.json(413, {"error": "request too large"}))
            self.respond(self.rfile.read(length))

        def do_PUT(self):
            self.respond(b"")

        do_DELETE = do_PATCH = do_PUT

        def respond(self, body: bytes):
            self.send(*app.handle(self.command, urlsplit(self.path).path, dict(self.headers),
                                  body))

        def send(self, status, headers, body):
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass  # actions go to runner.log; no request paths or bodies in the journal

    return Handler


def main():
    try:
        origin, port = load_config(CONFIG_FILE)
        devices = dk.DeviceKeys(DEVICE_FILE, ENROLL_FILE)
        if "--device" in sys.argv[1:]:
            # Compare with the fingerprint the app showed after enrolling (108)
            print(devices.fingerprint() or "no device key enrolled")
            return
        if "--revoke-device" in sys.argv[1:]:
            print("device key removed" if dk.revoke(DEVICE_FILE) else "no device key was enrolled")
            return
        if "--enroll-device" in sys.argv[1:]:
            code = wa.new_enroll_code(ENROLL_FILE, time.time())
            print(f"enrollment code (10 minutes, 5 tries): {code}\n"
                  "type it in Julz: Setup, Approve on this phone. It replaces any old device key")
            return
        if "--revoke" in sys.argv[1:]:
            print("passkey removed" if wa.revoke(CRED_FILE) else "no passkey was registered")
            return
        if "--enroll" in sys.argv[1:]:
            if wa.load_credential(CRED_FILE) is not None:
                sys.exit("a passkey is already registered: --revoke it first")
            code = wa.new_enroll_code(ENROLL_FILE, time.time())
            print(f"enrollment code (10 minutes, 5 tries): {code}\nopen {origin} on the phone")
            return
        static = {name: (STATIC_DIR / name).read_bytes() for name, _ in STATIC.values()}
        dirs = gate.Dirs(GATE_DIR, outbox=OUTBOX)
        app = App(wa.Passkeys(origin, CRED_FILE, ENROLL_FILE), INBOX, dirs, PROJECTS_FILE,
                  port, static, devices)
    except gate.GateError as e:
        sys.exit(str(e))
    server = HTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"julz approver on 127.0.0.1:{port} for {origin}")
    server.serve_forever()


if __name__ == "__main__":
    main()
