"""Attack tests for julz-approve-web.py: the phone approver page, SECURITY.md threats 31 to 37.
App.handle is driven like a browser would, with the software authenticator from
test_julz_webauthn.py standing in for the phone. Every request and reply goes through JSON.
Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


web = load("julz_approve_web", "julz-approve-web.py")
softkeys = load("test_julz_webauthn_keys", "tests/test_julz_webauthn.py")
# The web script imported its own julz_gate and julz_webauthn: use those classes (HANDOFF)
gate, wa = web.gate, web.wa

HOST = softkeys.HOST
ORIGIN = softkeys.ORIGIN
PORT = 8765
GOOD = ("goal: add a usage line to the README\n"
        "project: julz-sandbox\n"
        "done_when: README has a Usage section\n")
XSS = GOOD.replace("add a usage line", "<img src=x onerror=alert(1)>")
STATIC = {name: (ROOT / "approver" / name).read_bytes()
          for name in ("index.html", "approve.js", "approve.css")}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.inbox = base / "Inbox" / "claude"
        self.inbox.mkdir(parents=True)
        self.dirs = gate.Dirs(base / "gate", outbox=base / "Outbox")
        self.projects_file = base / "projects.json"
        self.projects_file.write_text(json.dumps({"julz-sandbox": "/srv/julz/julz-sandbox"}))
        self.projects_file.chmod(0o600)
        self.clock = softkeys.Clock()
        self.pk = wa.Passkeys(ORIGIN, base / "passkey.json", base / "enroll.json",
                              clock=self.clock)
        self.app = web.App(self.pk, self.inbox, self.dirs, self.projects_file, PORT, STATIC)
        self.key = softkeys.SoftKey()

    def tearDown(self):
        self.tmp.cleanup()

    # a browser on the phone, through tailscale serve
    def request(self, method, path, body=None, **headers):
        h = {"Host": f"{HOST}:8443"}
        if body is not None:
            h.update({"Origin": ORIGIN, "Content-Type": "application/json"})
            body = json.dumps(body).encode()
        h.update({k.replace("_", "-"): v for k, v in headers.items() if v is not None})
        for k in [k for k, v in headers.items() if v is None]:
            h.pop(k.replace("_", "-"), None)
        status, hdrs, raw = self.app.handle(method, path, h, body or b"")
        data = json.loads(raw) if hdrs["Content-Type"] == "application/json" else raw
        return status, hdrs, data

    def post(self, path, body, **headers):
        return self.request("POST", path, body, **headers)

    def write_spec(self, name, text, age=0):
        path = self.inbox / name
        path.write_text(text)
        if age:
            os.utime(path, (1_000_000 - age, 1_000_000 - age))
        return path

    def enroll(self):
        code = wa.new_enroll_code(self.pk.enroll_file, self.clock())
        status, _, data = self.post("/api/enroll/begin", {"code": code})
        self.assertEqual(status, 200, data)
        cred = self.key.register(data)
        status, _, data = self.post("/api/enroll/finish", {"credential": cred})
        self.assertEqual(status, 200, data)

    def state(self):
        status, _, data = self.request("GET", "/api/state")
        self.assertEqual(status, 200, data)
        return data

    def act(self, action, name, sha=None, key=None, **sign):
        """Tap a button: begin, touch the sensor, finish. Returns the finish reply."""
        if sha is None:
            sha = next(s["sha256"] for s in self.state()["specs"] if s["name"] == name)
        status, _, data = self.post("/api/begin", {"action": action, "name": name, "sha256": sha})
        if status != 200:
            return status, data
        cred = (key or self.key).sign(data, **sign)
        status, _, data = self.post("/api/finish", {"action": action, "nonce": data["nonce"],
                                                    "credential": cred})
        return status, data

    def approved(self):
        return sorted(p.name for p in self.dirs.approved.iterdir()) \
            if self.dirs.approved.exists() else []


class HeadersTest(Base):
    """Threat 34: the page cannot run injected script; threat 36: wrong hosts are refused."""

    def test_csp_on_every_response(self):
        for method, path in (("GET", "/"), ("GET", "/approve.js"), ("GET", "/api/state"),
                             ("GET", "/nope"), ("PUT", "/")):
            with self.subTest(path=path):
                _, hdrs, _ = self.request(method, path)
                self.assertEqual(hdrs["Content-Security-Policy"], web.CSP)
                self.assertEqual(hdrs["X-Content-Type-Options"], "nosniff")
                self.assertEqual(hdrs["X-Frame-Options"], "DENY")

    def test_csp_allows_no_inline_or_third_party(self):
        self.assertIn("default-src 'none'", web.CSP)
        self.assertIn("script-src 'self';", web.CSP)
        self.assertIn("frame-ancestors 'none'", web.CSP)
        self.assertNotIn("unsafe", web.CSP)
        self.assertNotIn("http", web.CSP)

    def test_page_has_no_inline_script_or_style(self):
        html = STATIC["index.html"].decode()
        self.assertEqual(re.findall(r"<script(?![^>]*\bsrc=)", html), [])
        self.assertNotIn("style=", html)
        self.assertNotIn("<style", html)
        self.assertNotRegex(html, r"\son[a-z]+=")

    def test_js_never_parses_html(self):
        js = STATIC["approve.js"].decode()
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                     "eval(", "Function(", "setTimeout(\"", "DOMParser"):
            self.assertNotIn(sink, js)
        self.assertIn("textContent", js)

    def test_wrong_host_refused(self):
        for host in ("evil.example", f"{HOST}", f"{HOST}:443", "127.0.0.1:8443",
                     f"localhost:{PORT}", None):
            with self.subTest(host=host):
                status, _, _ = self.request("GET", "/api/state", Host=host)
                self.assertEqual(status, 421)

    def test_local_host_allowed(self):
        status, _, _ = self.request("GET", "/", Host=f"127.0.0.1:{PORT}")
        self.assertEqual(status, 200)

    def test_methods_and_paths(self):
        self.assertEqual(self.request("GET", "/nope")[0], 404)
        self.assertEqual(self.request("PUT", "/api/state")[0], 405)
        self.assertEqual(self.request("GET", "/api/begin")[0], 405)
        self.assertEqual(self.request("GET", "/approve.css")[0], 200)
        self.assertEqual(self.request("GET", "/../julz_gate.py")[0], 404)


class PostRulesTest(Base):
    """Threat 36: POSTs only from the approver's own origin, small JSON only."""

    def test_wrong_origin_refused(self):
        # A request that would succeed with the right origin, so only the origin check
        # can be what refuses it (an earlier version passed for the wrong reason)
        self.enroll()
        (self.inbox / "readme.md").write_text(GOOD)
        body = {"action": "approve", "name": "readme.md", "sha256": gate.sha256(GOOD)}
        for origin in ("https://evil.example", f"https://{HOST}", "null", None):
            with self.subTest(origin=origin):
                status, _, _ = self.post("/api/begin", body, Origin=origin)
                self.assertEqual(status, 403)
        self.assertEqual(self.post("/api/begin", body)[0], 200)

    def test_not_json_refused(self):
        status, _, _ = self.post("/api/enroll/begin", {"code": "x"},
                                 Content_Type="text/plain")
        self.assertEqual(status, 415)

    def test_big_body_refused(self):
        status, _, _ = self.post("/api/enroll/begin", {"code": "x" * web.MAX_BODY})
        self.assertEqual(status, 413)

    def test_bad_json_refused(self):
        status, _, _ = self.app.handle("POST", "/api/begin",
                                       {"Host": f"{HOST}:8443", "Origin": ORIGIN,
                                        "Content-Type": "application/json"}, b"{nope")
        self.assertEqual(status, 400)
        status, _, _ = self.post("/api/begin", ["a", "list"])
        self.assertEqual(status, 400)


class QueueTest(Base):
    """Threat 37: few specs at a time, refused ones visible, text passed as data."""

    def setUp(self):
        super().setUp()
        self.enroll()

    def test_state_lists_specs_oldest_first(self):
        self.write_spec("b-new.md", GOOD.replace("README\n", "docs\n", 1), age=10)
        self.write_spec("a-old.md", GOOD, age=100)
        s = self.state()
        self.assertTrue(s["enrolled"])
        self.assertEqual([x["name"] for x in s["specs"]], ["a-old.md", "b-new.md"])
        self.assertEqual(s["specs"][0]["text"], GOOD)
        self.assertEqual(s["specs"][0]["sha256"], gate.sha256(GOOD))

    def test_at_most_three_shown(self):
        for i in range(5):
            self.write_spec(f"s{i}.md", GOOD.replace("README\n", f"README {i}\n", 1),
                            age=100 - i)
        s = self.state()
        self.assertEqual([x["name"] for x in s["specs"]], ["s0.md", "s1.md", "s2.md"])
        self.assertEqual(s["waiting"], 2)

    def test_hostile_spec_refused_not_shown(self):
        self.write_spec("bidi.md", GOOD.replace("README", "‮EMDAER", 1))
        s = self.state()
        self.assertEqual(s["specs"], [])
        self.assertEqual(len(s["refused"]), 1)

    def test_markup_is_plain_json_text(self):
        self.write_spec("xss.md", XSS)
        status, hdrs, _ = self.request("GET", "/api/state")
        self.assertEqual(hdrs["Content-Type"], "application/json")
        self.assertEqual(self.state()["specs"][0]["text"], XSS)  # the page sets textContent

    def test_symlinked_spec_refused(self):
        target = Path(self.tmp.name) / "outside.md"
        target.write_text(GOOD)
        (self.inbox / "link.md").symlink_to(target)
        self.assertEqual(self.state()["specs"], [])


class ApproveTest(Base):
    """Threats 31 and 32 over HTTP: only my passkey approves, exactly the text I saw."""

    def setUp(self):
        super().setUp()
        self.enroll()
        self.spec = self.write_spec("readme.md", GOOD)

    def test_approve_stores_exact_text(self):
        status, data = self.act("approve", "readme.md")
        self.assertEqual(status, 200, data)
        digest = gate.sha256(GOOD)
        self.assertEqual(self.approved(), [f"{digest}.md"])
        self.assertEqual((self.dirs.approved / f"{digest}.md").read_text(), GOOD)
        self.assertFalse(self.spec.exists())
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn(("approve", digest), [(e["action"], e["sha256"]) for e in log])
        self.assertIn(("approve-channel", "phone"), [(e["action"], e.get("reason")) for e in log])

    def test_reject_stores_nothing(self):
        status, data = self.act("reject", "readme.md")
        self.assertEqual(status, 200, data)
        self.assertEqual(self.approved(), [])
        self.assertFalse(self.spec.exists())
        self.assertIn('"reject"', self.dirs.log.read_text())

    def test_no_assertion_no_approval(self):
        sha = gate.sha256(GOOD)
        _, _, data = self.post("/api/begin", {"action": "approve", "name": "readme.md",
                                              "sha256": sha})
        status, _, _ = self.post("/api/finish", {"action": "approve", "nonce": data["nonce"],
                                                 "credential": {}})
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])
        self.assertTrue(self.spec.exists())

    def test_other_key_refused(self):
        status, _ = self.act("approve", "readme.md", key=softkeys.SoftKey())
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])

    def test_webui_origin_assertion_refused(self):
        status, _ = self.act("approve", "readme.md", origin=softkeys.WEBUI_ORIGIN)
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])

    def test_no_fingerprint_refused(self):
        status, _ = self.act("approve", "readme.md", uv=False)
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])

    def test_reject_assertion_cannot_approve(self):
        _, _, data = self.post("/api/begin", {"action": "reject", "name": "readme.md",
                                              "sha256": gate.sha256(GOOD)})
        cred = self.key.sign(data)
        status, _, _ = self.post("/api/finish", {"action": "approve", "nonce": data["nonce"],
                                                 "credential": cred})
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])

    def test_spec_changed_after_view_refused(self):
        seen = self.state()["specs"][0]["sha256"]
        self.spec.write_text(GOOD.replace("add a usage line", "delete the README"))
        status, data = self.act("approve", "readme.md", sha=seen)
        self.assertEqual(status, 409, data)
        self.assertEqual(self.approved(), [])

    def test_spec_changed_after_begin_stores_signed_text(self):
        sha = gate.sha256(GOOD)
        _, _, data = self.post("/api/begin", {"action": "approve", "name": "readme.md",
                                              "sha256": sha})
        evil = GOOD.replace("add a usage line", "delete the README")
        self.spec.write_text(evil)  # julz swaps it while I touch the sensor
        status, _, reply = self.post("/api/finish", {"action": "approve", "nonce": data["nonce"],
                                                     "credential": self.key.sign(data)})
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.approved(), [f"{sha}.md"])
        self.assertEqual((self.dirs.approved / f"{sha}.md").read_text(), GOOD)
        self.assertEqual(self.spec.read_text(), evil)  # left for me to see, not deleted

    def test_traversal_name_refused(self):
        outside = Path(self.tmp.name) / "Inbox" / "x.md"
        outside.write_text(GOOD)
        for name in ("../x.md", "..%2fx.md", "/etc/passwd", "readme", "", None, ["readme.md"]):
            with self.subTest(name=name):
                status, _, _ = self.post("/api/begin", {"action": "approve", "name": name,
                                                        "sha256": gate.sha256(GOOD)})
                self.assertEqual(status, 400)

    def test_only_approve_and_reject(self):
        for action in ("stop", "continue", "run", None):
            with self.subTest(action=action):
                status, _, _ = self.post("/api/begin", {"action": action, "name": "readme.md",
                                                        "sha256": gate.sha256(GOOD)})
                self.assertEqual(status, 400)

    def test_hidden_spec_cannot_be_signed(self):
        # Fourth spec is not on the page, so it cannot be approved by guessing its name
        for i in range(3):
            self.write_spec(f"a{i}.md", GOOD.replace("README\n", f"README {i}\n", 1),
                            age=500 - i)
        hidden = GOOD.replace("README\n", "README hidden\n", 1)
        self.write_spec("zz-hidden.md", hidden)
        status, _ = self.act("approve", "zz-hidden.md", sha=gate.sha256(hidden))
        self.assertEqual(status, 404)

    def test_already_ran_refused(self):
        self.dirs.ensure()
        (self.dirs.done / f"{gate.sha256(GOOD)}.md").write_text(GOOD)
        status, _ = self.act("approve", "readme.md")
        self.assertEqual(status, 409)
        self.assertEqual(self.approved(), [])

    def test_replay_refused(self):
        sha = gate.sha256(GOOD)
        _, _, data = self.post("/api/begin", {"action": "approve", "name": "readme.md",
                                              "sha256": sha})
        body = {"action": "approve", "nonce": data["nonce"], "credential": self.key.sign(data)}
        self.assertEqual(self.post("/api/finish", body)[0], 200)
        (self.dirs.approved / f"{sha}.md").unlink()
        self.assertEqual(self.post("/api/finish", body)[0], 403)
        self.assertEqual(self.approved(), [])

    def test_not_enrolled_cannot_begin(self):
        wa.revoke(self.pk.cred_file)
        status, _, _ = self.post("/api/begin", {"action": "approve", "name": "readme.md",
                                                "sha256": gate.sha256(GOOD)})
        self.assertEqual(status, 403)


class EnrollWebTest(Base):
    """Threat 35 over HTTP."""

    def test_enroll_flow(self):
        self.assertFalse(self.state()["enrolled"])
        self.enroll()
        self.assertTrue(self.state()["enrolled"])
        self.assertIn('"enroll"', self.dirs.log.read_text())

    def test_wrong_code_refused(self):
        wa.new_enroll_code(self.pk.enroll_file, self.clock())
        status, _, _ = self.post("/api/enroll/begin", {"code": "0000000000"})
        self.assertEqual(status, 403)

    def test_second_enroll_refused(self):
        self.enroll()
        code = wa.new_enroll_code(self.pk.enroll_file, self.clock())
        status, _, _ = self.post("/api/enroll/begin", {"code": code})
        self.assertEqual(status, 403)


class SocketTest(Base):
    """The real HTTP layer: headers reach handle(), oversized bodies are never read."""

    def test_real_server(self):
        import http.client
        import threading
        from http.server import HTTPServer
        server = HTTPServer(("127.0.0.1", 0), web.make_handler(self.app))
        port = server.server_address[1]
        self.app.hosts.add(f"127.0.0.1:{port}")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/?x=1")
            r = conn.getresponse()
            self.assertEqual(r.status, 200)
            self.assertEqual(r.getheader("Content-Security-Policy"), web.CSP)
            self.assertEqual(r.getheader("Server"), "julz")
            r.read()
            conn.request("POST", "/api/begin", body=b"",
                         headers={"Content-Length": str(web.MAX_BODY + 1)})
            r = conn.getresponse()
            self.assertEqual(r.status, 413)
            r.read()
            conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("GET", "/", headers={"Host": "evil.example"})
            self.assertEqual(conn.getresponse().status, 421)
            conn.close()
        finally:
            server.shutdown()
            server.server_close()


class ConfigTest(Base):
    def test_config_checked(self):
        cfg = Path(self.tmp.name) / "approver.json"
        cfg.write_text(json.dumps({"origin": ORIGIN, "port": PORT}))
        cfg.chmod(0o600)
        self.assertEqual(web.load_config(cfg), (ORIGIN, PORT))
        for bad in ({"origin": f"https://{HOST}", "port": PORT},
                    {"origin": ORIGIN, "port": 80}, {"origin": ORIGIN, "port": "8765"},
                    {"origin": ORIGIN}):
            with self.subTest(bad=bad):
                cfg.write_text(json.dumps(bad))
                with self.assertRaises(gate.GateError):
                    web.load_config(cfg)
        cfg.write_text(json.dumps({"origin": ORIGIN, "port": PORT}))
        cfg.chmod(0o644)
        with self.assertRaises(gate.GateError):
            web.load_config(cfg)


if __name__ == "__main__":
    unittest.main()
