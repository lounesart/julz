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
Usage:
  ./julz-approve-web.py --enroll   print a one time code, then open the page on the phone
  ./julz-approve-web.py --revoke   forget the registered passkey (lost phone, threat 42)
  ./julz-approve-web.py            serve
Config: ~/.config/julz/approver.json  {"origin": "https://<laptop>.<tailnet>.ts.net:8443",
                                       "port": 8765}   (mode 600)
"""
import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402
import julz_webauthn as wa  # noqa: E402

HOME = Path.home()
INBOX = HOME / "Documents" / "julz-mem" / "Inbox" / "claude"
OUTBOX = HOME / "Documents" / "julz-mem" / "Outbox"
GATE_DIR = HOME / ".local" / "share" / "julz"
PROJECTS_FILE = HOME / ".config" / "julz" / "projects.json"
CONFIG_FILE = HOME / ".config" / "julz" / "approver.json"
# Own folder: saving the sign counter needs a writable directory, and ~/.config/julz holds
# the Claude token and API keys (threat 41)
CRED_FILE = HOME / ".config" / "julz" / "approver" / "passkey.json"
ENROLL_FILE = GATE_DIR / "webauthn" / "enroll.json"
STATIC_DIR = Path(__file__).resolve().parent / "approver"

MAX_BODY = 16_000
MAX_SHOWN = 3
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
                 port: int, static: dict[str, bytes]):
        self.pk = passkeys
        self.inbox = Path(inbox)
        self.dirs = dirs
        self.projects_file = projects_file
        self.static = static
        # Through tailscale serve the browser sends the public name; on the laptop itself,
        # 127.0.0.1. Anything else is DNS rebinding or a confused client (threat 36)
        self.hosts = {urlsplit(passkeys.origin).netloc, f"127.0.0.1:{port}"}
        self.names: dict[str, str] = {}  # nonce -> inbox file name, or task root for a need

    # ---------- plumbing ----------

    def handle(self, method: str, path: str, headers: dict, body: bytes):
        """Returns (status, headers, body). Never raises."""
        headers = {k.lower(): v for k, v in headers.items()}
        try:
            if headers.get("host") not in self.hosts:
                raise HTTPError(421, "wrong host")
            gets = {"/api/state": self.state}
            posts = {"/api/begin": self.begin, "/api/finish": self.finish,
                     "/api/enroll/begin": self.enroll_begin,
                     "/api/enroll/finish": self.enroll_finish}
            if method == "GET" and path in STATIC:
                name, ctype = STATIC[path]
                return self.reply(200, self.static[name], ctype)
            if method == "GET" and path in gets:
                return self.json(200, gets[path]())
            if method == "POST" and path in posts:
                return self.json(200, posts[path](self.read_json(headers, body)))
            if path in STATIC or path in gets or path in posts:
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
        return [{**{k: n[k] for k in keys}, "work": str(work / n["root"])}
                for n in gate.open_needs(self.dirs, self.pk.clock())[:MAX_SHOWN]]

    def state(self) -> dict:
        shown, refused, waiting = self.specs()
        return {"enrolled": wa.load_credential(self.pk.cred_file) is not None,
                "specs": shown, "refused": refused, "waiting": waiting,
                "needs": self.needs(), "running": self.running()}

    def running(self) -> dict | None:
        """The run going now, with the text to sign to stop it (threat 47)."""
        run = gate.current_run(self.dirs, self.pk.clock())
        if run is None:
            return None
        text = gate.halt_text(run)
        return {"sha256": run["sha256"], "project": run.get("project", ""),
                "goal": run.get("goal", ""), "step": run.get("step", 1),
                "started": run["started"], "text": text, "text_sha256": gate.sha256(text)}

    # ---------- signed actions ----------

    def begin(self, data: dict) -> dict:
        action, seen = data.get("action"), data.get("sha256")
        if action in ("approve", "reject"):
            name = data.get("name")
            shown, _, _ = self.specs()
            match = [s for s in shown if s["name"] == self.spec_path(name).name]
            key = name
        elif action in ("continue", "stop"):
            # The text to sign is built from host task state, never sent by the page
            key = data.get("root")
            match = [n for n in self.needs() if n["root"] == key]
        elif action == "halt":
            # Only the run going now, with the text built from running.json
            run = self.running()
            key = data.get("run")
            match = [{"text": run["text"], "sha256": run["text_sha256"]}] \
                if run and run["sha256"] == key else []
        else:
            raise HTTPError(400, "action must be approve, reject, continue, stop or halt")
        if not match:
            raise HTTPError(404, "not in the list: reload")
        if match[0]["sha256"] != seen:
            # Changed after the page showed it. Never sign text I did not see
            raise HTTPError(409, "changed since you saw it: reload")
        nonce, options = self.pk.begin(action, match[0]["text"])
        self.names = {k: v for k, v in self.names.items() if k in self.pk.pending}
        self.names[nonce] = key
        return {"nonce": nonce, "publicKey": options["publicKey"]}

    def finish(self, data: dict) -> dict:
        action, nonce = data.get("action"), data.get("nonce")
        credential = data.get("credential")
        if not isinstance(nonce, str) or not isinstance(credential, dict):
            raise HTTPError(400, "nonce and credential needed")
        name = self.names.pop(nonce, None)
        text = self.pk.finish(nonce, action, credential)  # the exact signed text, or raises
        digest = gate.sha256(text)
        if action == "continue":
            gate.store_continuation(text, self.dirs, self.pk.clock())
            gate.log(self.dirs, "approve-channel", digest, "ok", "phone")
            return {"done": "continued", "sha256": digest}
        if action == "stop":
            gate.stop_task(text, self.dirs, self.pk.clock())
            return {"done": "stopped", "sha256": digest}
        if action == "halt":
            run = gate.request_halt(text, self.dirs, self.pk.clock())
            return {"done": "stopping", "sha256": run}
        if action == "approve":
            gate.store_approved(text, self.dirs, gate.load_projects(self.projects_file))
            gate.log(self.dirs, "approve-channel", digest, "ok", "phone")
            self.remove_if_same(name, digest)
            return {"done": "approved", "sha256": digest}
        self.remove_if_same(name, digest)
        gate.log(self.dirs, "reject", digest, "ok", "phone")
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
                  port, static)
    except gate.GateError as e:
        sys.exit(str(e))
    server = HTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"julz approver on 127.0.0.1:{port} for {origin}")
    server.serve_forever()


if __name__ == "__main__":
    main()
