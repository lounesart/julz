"""Attack tests for julz-approve-web.py: the phone approver page, SECURITY.md threats 31 to 37.
App.handle is driven like a browser would, with the software authenticator from
test_julz_webauthn.py standing in for the phone. Every request and reply goes through JSON.
Run: python3 -m unittest discover -s tests -v"""
import hashlib
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
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
        self.devices = web.dk.DeviceKeys(base / "device.json", base / "enroll.json", clock=self.clock)
        self.app = web.App(self.pk, self.inbox, self.dirs, self.projects_file, PORT, STATIC,
                           self.devices)
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

    def act(self, action, name, sha=None, key=None, note=None, **sign):
        """Tap a button: begin, touch the sensor, finish. Returns the finish reply."""
        if sha is None:
            sha = next(s["sha256"] for s in self.state()["specs"] if s["name"] == name)
        begin = {"action": action, "name": name, "sha256": sha}
        if note is not None:
            begin["note"] = note
        status, _, data = self.post("/api/begin", begin)
        if status != 200:
            return status, data
        cred = (key or self.key).sign(data, **sign)
        status, _, data = self.post("/api/finish", {"action": action, "nonce": data["nonce"],
                                                    "credential": cred})
        return status, data

    def approved(self):
        return sorted(p.name for p in self.dirs.approved.iterdir() if gate.APPROVED_NAME.match(p.name)) \
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

    def test_the_page_loads_nothing_from_outside(self):
        # E1 restyle: our look with system fonts, no font, image or script from anywhere else
        self.assertNotIn("font-src", web.CSP)
        self.assertNotIn("img-src 'self'", web.CSP)
        for name, data in STATIC.items():
            text = data.decode()
            with self.subTest(name=name):
                for bad in ("http://", "https://", "//fonts", "@import", "url(", "@font-face",
                            "innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
                    self.assertNotIn(bad, text)

    def test_state_names_the_page_files(self):
        # An open page compares this with the value it started with and reloads on a change,
        # so a stale script with old buttons does not stay in use after a restart
        page = self.state()["page"]
        self.assertRegex(page, r"^[0-9a-f]{12}$")
        same = web.App(self.pk, self.inbox, self.dirs, self.projects_file, PORT, STATIC)
        self.assertEqual(same.page, page)
        for name in STATIC:
            with self.subTest(name=name):
                changed = {**STATIC, name: STATIC[name] + b"\n"}
                other = web.App(self.pk, self.inbox, self.dirs, self.projects_file, PORT,
                                changed)
                self.assertNotEqual(other.page, page)

    def test_page_reloads_when_stale(self):
        js = STATIC["approve.js"].decode()
        self.assertIn("else if (s.page !== page) { location.reload(); return; }", js)
        self.assertIn('id="page"', STATIC["index.html"].decode())

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
        self.write_spec("bidi.md", GOOD.replace("README", "\u202eEMDAER", 1))
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


class DeviceBase(Base):
    """An enrolled device key, played by `cryptography` (107)."""

    def setUp(self):
        super().setUp()
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        import base64
        self.ec, self.hashes, self.b64 = ec, hashes, base64
        self.phone = ec.generate_private_key(ec.SECP256R1())
        der = self.phone.public_key().public_bytes(serialization.Encoding.DER,
                                                   serialization.PublicFormat.SubjectPublicKeyInfo)
        code = wa.new_enroll_code(self.pk.enroll_file, self.clock())
        status, _, data = self.post("/api/device/enroll", {"code": code,
                                                           "public_key": base64.b64encode(der).decode()})
        self.assertEqual(status, 200, data)
        self.fingerprint = data["fingerprint"]
        self.spec = self.write_spec("readme.md", GOOD)

    def sign(self, begun, key=None):
        data = web.dk.payload(begun["action"], begun["text"], begun["nonce"])
        sig = (key or self.phone).sign(data, self.ec.ECDSA(self.hashes.SHA256()))
        return self.b64.b64encode(sig).decode()


class DeviceWebTest(DeviceBase):
    """Threats 107 to 111 over HTTP: the app approves with its device key, through the same
    paths as a passkey, never around them."""

    def device_act(self, action, name, note=None, key=None, finish_as=None):
        sha = next(s["sha256"] for s in self.state()["specs"] if s["name"] == name)
        body = {"action": action, "name": name, "sha256": sha, "via": "device"}
        if note is not None:
            body["note"] = note
        status, _, begun = self.post("/api/begin", body)
        if status != 200:
            return status, begun, None
        status, _, data = self.post("/api/finish", {"action": finish_as or action, "nonce": begun["nonce"],
                                                    "signature": self.sign(begun, key)})
        return status, data, begun

    def test_state_shows_the_device_fingerprint(self):
        self.assertEqual(self.state()["device"], self.fingerprint)
        self.assertRegex(self.fingerprint, r"^[0-9a-f]{4}(-[0-9a-f]{4}){3}$")

    def test_approve_with_a_note_from_the_app(self):
        status, data, begun = self.device_act("approve", "readme.md", note="use port 8080")
        self.assertEqual(status, 200, data)
        text = GOOD + "note: use port 8080\n"
        self.assertEqual(begun["text"], text)  # the app shows exactly what it signs (109)
        self.assertEqual(self.approved(), [f"{gate.sha256(text)}.md"])
        self.assertFalse(self.spec.exists())
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        # who signed it (110): the approval's own entry, not the enrollment line
        self.assertIn(("approve-channel", gate.sha256(text), f"device {self.fingerprint}"),
                      [(e["action"], e["sha256"], e.get("reason")) for e in log])

    def test_deny_from_the_app(self):
        status, data, _ = self.device_act("reject", "readme.md")
        self.assertEqual(status, 200, data)
        self.assertEqual(self.approved(), [])
        self.assertFalse(self.spec.exists())
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn(("reject", gate.sha256(GOOD), f"device {self.fingerprint}"),
                      [(e["action"], e["sha256"], e.get("reason")) for e in log])

    def test_another_key_or_action_refused(self):
        status, _, _ = self.device_act("approve", "readme.md", key=self.ec.generate_private_key(self.ec.SECP256R1()))
        self.assertEqual(status, 403)
        status, _, _ = self.device_act("reject", "readme.md", finish_as="approve")
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])
        self.assertTrue(self.spec.exists())

    def test_device_and_passkey_nonces_do_not_cross(self):
        self.enroll()  # a passkey too
        sha = gate.sha256(GOOD)
        # a passkey challenge finished with a device signature
        _, _, begun = self.post("/api/begin", {"action": "approve", "name": "readme.md", "sha256": sha})
        fake = {"nonce": begun["nonce"], "action": "approve", "text": GOOD}
        status, _, _ = self.post("/api/finish", {"action": "approve", "nonce": begun["nonce"],
                                                 "signature": self.sign(fake)})
        self.assertEqual(status, 403)
        # a device nonce finished with a passkey assertion
        _, _, begun = self.post("/api/begin", {"action": "approve", "name": "readme.md", "sha256": sha,
                                               "via": "device"})
        status, _, _ = self.post("/api/finish", {"action": "approve", "nonce": begun["nonce"],
                                                 "credential": {"id": "x"}})
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])

    def test_no_device_key_no_device_begin(self):
        web.dk.revoke(self.devices.device_file)
        status, _, _ = self.post("/api/begin", {"action": "approve", "name": "readme.md",
                                                "sha256": gate.sha256(GOOD), "via": "device"})
        self.assertEqual(status, 403)
        self.assertIsNone(self.state()["device"])

    def test_post_rules_unchanged_for_the_app(self):
        # The app sends the approver's own Origin; anything else is refused as before (111)
        status, _, _ = self.post("/api/device/enroll", {"code": "x", "public_key": "x"},
                                 Origin="https://evil.example")
        self.assertEqual(status, 403)
        status, _, _ = self.post("/api/device/enroll", {"code": "x", "public_key": "x"}, Origin=None)
        self.assertEqual(status, 403)
        status, _, _ = self.post("/api/begin", {"action": "approve", "via": "device"},
                                 Content_Type="text/plain")
        self.assertEqual(status, 415)

    def test_enrolling_needs_a_fresh_code(self):
        status, _, _ = self.post("/api/device/enroll", {"code": "0000000000", "public_key": "x"})
        self.assertEqual(status, 403)
        self.assertEqual(self.state()["device"], self.fingerprint)  # the old key stays


class TickWebTest(DeviceBase):
    """Threat 113: ticking todos from the app. The app proves which snapshot it saw and picks
    (list, task) pairs; the server builds the text, one fingerprint signs them all."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.app.todos_file = base / "vault" / "todos.json"
        self.app.requests = base / "julz-mem" / "Inbox" / ".requests"
        self.app.requests.mkdir(parents=True)
        lists = [{"name": "shop", "note": "daily/shop.md", "done": 1, "total": 4,
                  "open": ["milk", "bread"], "doing": ["tea"], "done_items": ["eggs"]},
                 {"name": "physio", "note": "Inbox/physio.md", "done": 0, "total": 1,
                  "open": ["book physio"], "doing": [], "done_items": []}]
        self.snap = {"date": "2026-10-17", "id": web.vault.snapshot_id(lists), "lists": lists}
        self.app.todos_file.parent.mkdir()
        self.app.todos_file.write_text(json.dumps(self.snap))

    def tick(self, picks, sha=None, finish_as=None, key=None, action="tick"):
        body = {"action": action, "sha256": sha or self.snap["id"], "pick": picks, "via": "device"}
        status, _, begun = self.post("/api/begin", body)
        if status != 200:
            return status, begun, None
        status, _, data = self.post("/api/finish", {"action": finish_as or action, "nonce": begun["nonce"],
                                                    "signature": self.sign(begun, key)})
        return status, data, begun

    def written(self):
        return sorted((json.loads(p.read_text()) for p in self.app.requests.iterdir()),
                      key=lambda r: r["item"])

    def test_one_fingerprint_ticks_the_picked_tasks(self):
        status, data, begun = self.tick([{"list": "physio", "item": "book physio"},
                                         {"list": "shop", "item": "bread"}])
        self.assertEqual(status, 200, data)
        self.assertEqual(begun["text"], f"tick: {self.snap['id']}\n"
                                        "daily/shop.md: bread\nInbox/physio.md: book physio\n")
        self.assertEqual(self.written(), [{"op": "tick", "note": "Inbox/physio.md", "item": "book physio"},
                                          {"op": "tick", "note": "daily/shop.md", "item": "bread"}])
        for p in self.app.requests.iterdir():
            self.assertRegex(p.name, web.vault.REQUEST_NAME.pattern)
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn(("tick-signed", gate.sha256(begun["text"]), f"2 tasks, device {self.fingerprint}"),
                      [(e["action"], e["sha256"], e.get("reason")) for e in log])

    def test_one_fingerprint_starts_the_picked_tasks(self):
        # 127: start is built as tick, with its own head
        status, data, begun = self.tick([{"list": "shop", "item": "milk"}], action="start")
        self.assertEqual(status, 200, data)
        self.assertEqual(begun["text"], f"start: {self.snap['id']}\ndaily/shop.md: milk\n")
        self.assertEqual(self.written(), [{"op": "start", "note": "daily/shop.md", "item": "milk"}])
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn("start-signed", [e["action"] for e in log])

    def test_a_task_in_progress_ticks_but_does_not_start_again(self):
        status, _, _ = self.tick([{"list": "shop", "item": "tea"}], action="start")
        self.assertEqual(status, 400)
        status, data, _ = self.tick([{"list": "shop", "item": "tea"}])
        self.assertEqual(status, 200, data)
        self.assertEqual(self.written(), [{"op": "tick", "note": "daily/shop.md", "item": "tea"}])

    def test_a_start_is_never_finished_as_a_tick(self):
        status, _, _ = self.tick([{"list": "shop", "item": "milk"}], action="start", finish_as="tick")
        self.assertNotEqual(status, 200)
        status, _, _ = self.tick([{"list": "shop", "item": "milk"}], finish_as="start")
        self.assertNotEqual(status, 200)
        self.assertEqual(self.written(), [])

    def test_another_snapshot_is_refused(self):
        status, _, _ = self.tick([{"list": "shop", "item": "milk"}], sha="d" * 64)
        self.assertEqual(status, 409)
        # a task gone since the phone's snapshot: still "reload", not a bad pick
        status, _, _ = self.tick([{"list": "shop", "item": "cheese"}], sha="d" * 64)
        self.assertEqual(status, 409)
        self.assertEqual(self.written(), [])

    def test_a_snapshot_without_a_real_id_ticks_nothing(self):
        self.app.todos_file.write_text(json.dumps({**self.snap, "id": "x"}))
        status, _, _ = self.tick([{"list": "shop", "item": "milk"}], sha="x")
        self.assertEqual(status, 404)
        self.assertEqual(self.written(), [])

    def test_only_open_tasks_of_the_snapshot(self):
        for name, picks in {"free text": [{"list": "shop", "item": "rm -rf"}],
                            "done task": [{"list": "shop", "item": "eggs"}],
                            "a path": [{"list": "daily/shop.md", "item": "milk"}],
                            "extra key": [{"list": "shop", "item": "milk", "note": "study/x.md"}],
                            "repeat": [{"list": "shop", "item": "milk"}] * 2,
                            "not a list": {"list": "shop", "item": "milk"}}.items():
            with self.subTest(name=name):
                status, _, _ = self.tick(picks)
                self.assertEqual(status, 400, name)
        self.assertEqual(self.written(), [])

    def test_no_or_broken_snapshot_ticks_nothing(self):
        for raw in (None, "{", json.dumps({"id": "x", "lists": []}),
                    json.dumps({**self.snap, "lists": [{"name": "shop"}]}),
                    json.dumps({**self.snap, "lists": [{**self.snap["lists"][0], "doing": "tea"}]}),
                    json.dumps({**self.snap, "lists": [{**self.snap["lists"][0], "doing": [5]}]})):
            with self.subTest(raw=str(raw)[:20]):
                if raw is None:
                    self.app.todos_file.unlink(missing_ok=True)
                else:
                    self.app.todos_file.write_text(raw)
                status, _, _ = self.tick([{"list": "shop", "item": "milk"}])
                self.assertIn(status, (404, 409))
        self.assertEqual(self.written(), [])

    # ----- the Done tab (threat 114) -----

    def write_week(self, data):
        p = self.app.todos_file.parent / "done-week.json"
        p.write_text(data if isinstance(data, str) else json.dumps(data))

    def test_done_week_served_as_written(self):
        week = {"date": "2026-10-17", "days": [{"date": "2026-10-17", "items": [{"list": "shop", "item": "eggs"}]}]}
        self.write_week(week)
        status, _, data = self.request("GET", "/api/done")
        self.assertEqual(status, 200)
        self.assertEqual(data, {"days": week["days"]})

    def test_done_week_off_shape_is_an_empty_week(self):
        good_day = {"date": "2026-10-17", "items": [{"list": "shop", "item": "eggs"}]}
        for name, data in {"missing": None, "not json": "{",
                           "link": {"date": "x", "days": [{**good_day, "items": [{"list": "shop", "item": "see https://evil.example"}]}]},
                           "hidden": {"date": "x", "days": [{**good_day, "items": [{"list": "shop", "item": "a\u202eb"}]}]},
                           "long": {"date": "x", "days": [{**good_day, "items": [{"list": "shop", "item": "y" * 81}]}]},
                           "extra key": {"date": "x", "days": [{**good_day, "x": 1}]},
                           "bad date": {"date": "x", "days": [{**good_day, "date": "17 Oct"}]},
                           "too many": {"date": "x", "days": [{**good_day, "items": good_day["items"] * 61}]},
                           "eight days": {"date": "x", "days": [good_day] * 8}}.items():
            with self.subTest(name=name):
                p = self.app.todos_file.parent / "done-week.json"
                p.unlink(missing_ok=True)
                if data is not None:
                    self.write_week(data)
                status, _, got = self.request("GET", "/api/done")
                self.assertEqual((status, got), (200, {"days": []}), name)

    def test_done_week_is_read_only(self):
        status, _, _ = self.post("/api/done", {})
        self.assertEqual(status, 405)

    def test_the_unit_binds_only_what_ticks_need(self):
        unit = (ROOT / "systemd" / "julz-approver.service").read_text().splitlines()
        rw = {p for l in unit if l.startswith("BindPaths=") for p in l.split("=", 1)[1].split()}
        ro = {p for l in unit if l.startswith("BindReadOnlyPaths=") for p in l.split("=", 1)[1].split()}
        self.assertIn("%h/.local/share/julz/vault", ro)
        self.assertNotIn("%h/.local/share/julz/vault", rw)
        self.assertIn("%h/Documents/julz-mem/Inbox/.requests", rw)
        # Nothing else of the vault is writable: the Claude specs folder, the requests and the
        # cards Julz asks for (threat 156) only
        self.assertEqual({p for p in rw if p.startswith("%h/Documents/julz-mem")},
                         {"%h/Documents/julz-mem/Inbox/claude", "%h/Documents/julz-mem/Inbox/.requests",
                          "%h/Documents/julz-mem/Inbox/.proposals"})

    def test_a_tick_signature_is_no_approval_and_back(self):
        status, _, _ = self.tick([{"list": "shop", "item": "milk"}], finish_as="approve")
        self.assertEqual(status, 403)
        status, _, _ = self.tick([{"list": "shop", "item": "milk"}],
                                 key=self.ec.generate_private_key(self.ec.SECP256R1()))
        self.assertEqual(status, 403)
        self.assertEqual(self.written(), [])
        self.assertEqual(self.approved(), [])


class InboxWebTest(DeviceBase):
    """Threats 116 and 117: the Inbox on the phone, read and acted on through the approver."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.app.todos_file = base / "vault" / "todos.json"
        self.app.requests = base / "julz-mem" / "Inbox" / ".requests"
        self.app.requests.mkdir(parents=True)
        self.app.todos_file.parent.mkdir()
        notes = [{"name": "draft", "note": "Inbox/draft.md", "sha256": "a" * 64, "size": 30,
                  "modified": "2026-10-17", "preview": "# Draft\nA thought.\n"},
                 {"name": "shop", "note": "Inbox/shop.md", "sha256": "b" * 64, "size": 10,
                  "modified": "2026-10-16", "preview": "- [ ] milk\n"}]
        folders = ["daily", "study", "study/network-plus"]
        self.snap = {"id": web.vault.inbox_id(notes, folders), "notes": notes, "folders": folders}
        self.write(self.snap)

    def write(self, data):
        (self.app.todos_file.parent / "inbox.json").write_text(
            data if isinstance(data, str) else json.dumps(data))

    def act(self, picks, sha=None, finish_as=None):
        status, _, begun = self.post("/api/begin", {"action": "inbox", "sha256": sha or self.snap["id"],
                                                    "pick": picks, "via": "device"})
        if status != 200:
            return status, begun, None
        status, _, data = self.post("/api/finish", {"action": finish_as or "inbox", "nonce": begun["nonce"],
                                                    "signature": self.sign(begun)})
        return status, data, begun

    def written(self):
        return sorted((json.loads(p.read_text()) for p in self.app.requests.iterdir()), key=lambda r: r["note"])

    def test_the_inbox_is_served(self):
        status, _, data = self.request("GET", "/api/inbox")
        self.assertEqual(status, 200)
        self.assertEqual(data, self.snap)

    def test_an_off_shape_inbox_is_empty(self):
        empty = {"id": "", "notes": [], "folders": []}
        note = self.snap["notes"][0]
        for name, data in {"not json": "{", "extra key": {**self.snap, "x": 1},
                           "bad sha": {**self.snap, "notes": [{**note, "sha256": "x"}]},
                           "path outside": {**self.snap, "notes": [{**note, "note": "study/x.md"}]},
                           "long preview": {**self.snap, "notes": [{**note, "preview": "y" * 2001}]},
                           "hidden in preview": {**self.snap, "notes": [{**note, "preview": "a\u202eb"}]},
                           "bad folder": {**self.snap, "folders": ["../x"]},
                           "too many": {**self.snap, "notes": [note] * 21}}.items():
            with self.subTest(name=name):
                self.write(data)
                status, _, got = self.request("GET", "/api/inbox")
                self.assertEqual((status, got), (200, empty), name)

    def test_one_fingerprint_moves_and_deletes(self):
        status, data, begun = self.act([{"note": "Inbox/shop.md", "do": "move", "to": "daily"},
                                        {"note": "Inbox/draft.md", "do": "delete"}])
        self.assertEqual(status, 200, data)
        self.assertEqual(begun["text"], f"inbox: {self.snap['id']}\ndelete: Inbox/draft.md\n"
                                        "move: Inbox/shop.md -> daily/shop.md\n")
        self.assertEqual(self.written(), [
            {"op": "delete", "note": "Inbox/draft.md", "sha256": "a" * 64},
            {"op": "move", "note": "Inbox/shop.md", "to": "daily/shop.md", "sha256": "b" * 64}])

    def test_unlisted_folder_or_note_is_refused(self):
        for picks in ([{"note": "Inbox/draft.md", "do": "move", "to": "Claude"}],
                      [{"note": "Inbox/other.md", "do": "delete"}]):
            with self.subTest(picks=picks):
                status, _, _ = self.act(picks)
                self.assertEqual(status, 400)
        self.assertEqual(self.written(), [])

    def test_another_snapshot_at_begin_or_finish_is_refused(self):
        status, _, _ = self.act([{"note": "Inbox/draft.md", "do": "delete"}], sha="d" * 64)
        self.assertEqual(status, 409)
        # the vault rewrote the snapshot between begin and finish
        _, _, begun = self.post("/api/begin", {"action": "inbox", "sha256": self.snap["id"], "via": "device",
                                               "pick": [{"note": "Inbox/draft.md", "do": "delete"}]})
        notes = [{**self.snap["notes"][0], "sha256": "c" * 64}] + self.snap["notes"][1:]
        self.write({**self.snap, "notes": notes, "id": web.vault.inbox_id(notes, self.snap["folders"])})
        status, _, _ = self.post("/api/finish", {"action": "inbox", "nonce": begun["nonce"],
                                                 "signature": self.sign(begun)})
        self.assertEqual(status, 409)
        self.assertEqual(self.written(), [])

    def test_no_snapshot_no_begin(self):
        (self.app.todos_file.parent / "inbox.json").unlink()
        status, _, _ = self.post("/api/begin", {"action": "inbox", "sha256": "", "via": "device",
                                                "pick": [{"note": "Inbox/draft.md", "do": "delete"}]})
        self.assertEqual(status, 404)

    def test_a_note_gone_since_the_phone_saw_it_says_reload(self):
        status, _, _ = self.act([{"note": "Inbox/gone.md", "do": "delete"}], sha="d" * 64)
        self.assertEqual(status, 409)

    def test_an_inbox_signature_is_nothing_else(self):
        status, _, _ = self.act([{"note": "Inbox/draft.md", "do": "delete"}], finish_as="tick")
        self.assertEqual(status, 403)
        self.assertEqual(self.written(), [])

    # ----- the notes browser (threat 118) -----

    def write_notes(self, data):
        (self.app.todos_file.parent / "notes.json").write_text(data if isinstance(data, str) else json.dumps(data))

    DNS = {"name": "dns", "note": "study/network-plus/dns.md", "modified": "2026-10-16", "size": 20, "text": "# DNS\n",
           "tags": ["net"]}

    def test_notes_are_served_without_their_text(self):
        # 206: the list stays small; one note's text comes by id when it is opened
        self.write_notes({"folders": [{"folder": "study/network-plus", "notes": [self.DNS]}]})
        status, _, data = self.request("GET", "/api/notes")
        listed = {k: v for k, v in self.DNS.items() if k != "text"}
        listed["id"] = hashlib.sha256(b"study/network-plus/dns.md").hexdigest()
        listed["tags"] = [0]
        self.assertEqual((status, data), (200, {"folders": [{"folder": "study/network-plus", "notes": [listed]}],
                                               "tags": ["net"]}))

    def test_tags_come_as_one_table_and_indexes(self):
        # 212, threat 149: a sorted table, each note points into it
        a = {**self.DNS, "tags": ["sec", "net"]}
        b = {**self.DNS, "name": "osi", "note": "daily/osi.md", "tags": []}
        c = {**self.DNS, "name": "ip", "note": "daily/ip.md", "tags": ["сеть", "net"]}
        self.write_notes({"folders": [{"folder": "daily", "notes": [b, c]},
                                      {"folder": "study/network-plus", "notes": [a]}]})
        _, _, data = self.request("GET", "/api/notes")
        self.assertEqual(data["tags"], ["net", "sec", "сеть"])
        self.assertEqual([n["tags"] for f in data["folders"] for n in f["notes"]], [[], [2, 0], [1, 0]])

    # ----- one note by id (threat 148) -----

    def note_id(self, path):
        return hashlib.sha256(path.encode()).hexdigest()

    def test_a_listed_id_gives_its_text(self):
        self.write_notes({"folders": [{"folder": "study/network-plus", "notes": [self.DNS]}]})
        status, _, data = self.request("GET", "/api/notes/" + self.note_id(self.DNS["note"]))
        self.assertEqual((status, data), (200, {"note": "study/network-plus/dns.md", "text": "# DNS\n"}))

    def test_anything_but_a_listed_id_is_not_found_and_opens_no_file(self):
        self.write_notes({"folders": [{"folder": "study/network-plus", "notes": [self.DNS]}]})
        good = self.note_id(self.DNS["note"])
        # A real spec on disk: julz-vault leaves it out of notes.json, so no id reaches it
        (self.inbox / "s.md").write_text("spec\n")
        read = []
        real = web.gate.read_regular
        def spy(path, *a, **k):
            read.append(Path(path).name)
            return real(path, *a, **k)
        web.gate.read_regular = spy
        self.addCleanup(setattr, web.gate, "read_regular", real)
        near = good[:63] + ("1" if good[63] == "0" else "0")
        for name, tail in {"unknown": "0" * 64, "one digit off": near, "short": good[:63], "long": good + "0",
                           "upper case": good.upper(), "a path": "study/network-plus/dns.md",
                           "dot dot": "../../.ssh/id_ed25519", "encoded slash": "study%2Fdns.md",
                           "a query": good + "?x=1", "a trailing slash": good + "/",
                           "a spec": self.note_id("Inbox/claude/s.md"), "empty": ""}.items():
            with self.subTest(name=name):
                status, _, data = self.request("GET", "/api/notes/" + tail)
                self.assertEqual(status, 404, name)
                self.assertNotIn("text", data)
        self.assertTrue(set(read) <= {"notes.json"}, read)

    def test_a_planted_snapshot_gives_no_note(self):
        bad = {**self.DNS, "text": "a\u202eb"}
        self.write_notes({"folders": [{"folder": "study/network-plus", "notes": [bad]}]})
        status, _, _ = self.request("GET", "/api/notes/" + self.note_id(self.DNS["note"]))
        self.assertEqual(status, 404)

    def test_one_note_is_read_only(self):
        self.write_notes({"folders": [{"folder": "study/network-plus", "notes": [self.DNS]}]})
        status, _, _ = self.post("/api/notes/" + self.note_id(self.DNS["note"]), {})
        self.assertEqual(status, 405)

    def test_300_full_notes_list_under_the_phone_limit(self):
        # The reason for 206: every Cyrillic letter escapes to 6 bytes, 300 x 4000 never fit
        # 212: plus the most tags there may be, 200 different of 40 Cyrillic letters, 10 a note
        table = [f"т{i:03d}" + "я" * 36 for i in range(200)]
        notes = [{**self.DNS, "name": f"n{i}", "note": f"study/n{i}.md", "text": "я" * 4000,
                  "tags": [table[(i * 10 + j) % 200] for j in range(10)]} for i in range(300)]
        self.write_notes({"folders": [{"folder": "study", "notes": notes}]})
        status, hdrs, raw = self.app.handle("GET", "/api/notes", {"Host": f"{HOST}:8443"}, b"")
        self.assertEqual(status, 200)
        self.assertLess(len(raw), 256_000)
        self.assertEqual(len(json.loads(raw)["folders"][0]["notes"]), 300)
        status, _, raw = self.app.handle("GET", "/api/notes/" + self.note_id("study/n7.md"), {"Host": f"{HOST}:8443"}, b"")
        self.assertEqual((status, json.loads(raw)["text"]), (200, "я" * 4000))
        self.assertLess(len(raw), 256_000)

    def test_off_shape_notes_are_empty(self):
        note = {"name": "dns", "note": "study/dns.md", "modified": "2026-10-16", "size": 20, "text": "# DNS\n", "tags": []}
        many = [{**note, "note": f"study/m{i}.md", "tags": [f"t{i}x{j}" for j in range(10)]} for i in range(21)]
        for name, data in {"missing": None, "not json": "{",
                           "a template": {"folders": [{"folder": "Templates", "notes": [{**note, "note": "Templates/t.md"}]}]},
                           "spec folder": {"folders": [{"folder": "Inbox/claude", "notes": [{**note, "note": "Inbox/claude/s.md"}]}]},
                           "outside its folder": {"folders": [{"folder": "study", "notes": [{**note, "note": "daily/x.md"}]}]},
                           "dot dot": {"folders": [{"folder": "study/..", "notes": []}]},
                           "hidden": {"folders": [{"folder": "study", "notes": [{**note, "text": "a\u202eb"}]}]},
                           "long": {"folders": [{"folder": "study", "notes": [{**note, "text": "y" * 4001}]}]},
                           "extra key": {"folders": [{"folder": "study", "notes": [{**note, "x": 1}]}]},
                           "too many": {"folders": [{"folder": "study", "notes": [note] * 301}]},
                           **{f"tag {k}": {"folders": [{"folder": "study", "notes": [{**note, "tags": t}]}]} for k, t in {
                               "missing": None, "not a list": "net", "not a string": [1], "space": ["a b"],
                               "upper case": ["Net"], "number first": ["2026"], "dot": ["a.b"], "colon": ["x:y"],
                               "hidden": ["a\u202eb"], "joiner": ["a\u200db"], "too long": ["l" * 41], "empty": [""],
                               "duplicate": ["a", "a"], "eleven": [f"t{i}" for i in range(11)]}.items()},
                           "tags missing": {"folders": [{"folder": "study", "notes": [
                               {k: v for k, v in note.items() if k != "tags"}]}]},
                           "201 different": {"folders": [{"folder": "study", "notes": many}]}}.items():
            with self.subTest(name=name):
                p = self.app.todos_file.parent / "notes.json"
                p.unlink(missing_ok=True)
                if data is not None:
                    self.write_notes(data)
                status, _, got = self.request("GET", "/api/notes")
                self.assertEqual((status, got), (200, {"folders": [], "tags": []}), name)

    def test_notes_are_read_only(self):
        status, _, _ = self.post("/api/notes", {})
        self.assertEqual(status, 405)

    def test_inbox_is_read_only_over_get(self):
        status, _, _ = self.post("/api/inbox", {})
        self.assertEqual(status, 405)


class FeedbackWebTest(DeviceBase):
    """Threat 120: feedback written in the app, signed, and the list of it."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.app.todos_file = base / "vault" / "todos.json"
        self.app.requests = base / "julz-mem" / "Inbox" / ".requests"
        self.app.requests.mkdir(parents=True)
        self.app.todos_file.parent.mkdir()

    def send(self, kind, text, sha=None, finish_as=None):
        body = {"action": "feedback", "kind": kind, "text": text, "via": "device",
                "sha256": sha or gate.sha256(text)}
        status, _, begun = self.post("/api/begin", body)
        if status != 200:
            return status, begun, None
        status, _, data = self.post("/api/finish", {"action": finish_as or "feedback", "nonce": begun["nonce"],
                                                    "signature": self.sign(begun)})
        return status, data, begun

    def written(self):
        return [json.loads(p.read_text()) for p in self.app.requests.iterdir()]

    def test_one_fingerprint_writes_one_note(self):
        status, data, begun = self.send("bug", "Logs title wraps.")
        self.assertEqual(status, 200, data)
        self.assertEqual(begun["text"], "feedback: bug\nLogs title wraps.\n")
        req, = self.written()
        self.assertEqual(req["op"], "create")
        self.assertRegex(req["note"], r"^feedback/\d{4}-\d{2}-\d{2} logs-title-wraps \d{6}\.md$")
        self.assertIn("kind: bug\nstate: new\nfrom: phone\n", req["text"])
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn("feedback-signed", [e["action"] for e in log])

    def test_refused_at_begin(self):
        for kind, text in (("rant", "x"), ("idea", ""), ("idea", "see https://evil.example"),
                           ("idea", "y" * 2001), ("bug", "a\u202eb")):
            with self.subTest(kind=kind, text=text[:20]):
                status, _, _ = self.send(kind, text)
                self.assertEqual(status, 400)
        self.assertEqual(self.written(), [])

    def test_another_text_than_the_hash_is_refused(self):
        status, _, _ = self.send("idea", "Tabs for Messages.", sha=gate.sha256("something else"))
        self.assertEqual(status, 409)
        self.assertEqual(self.written(), [])

    def test_a_feedback_signature_is_nothing_else(self):
        status, _, _ = self.send("idea", "Tabs for Messages.", finish_as="approve")
        self.assertEqual(status, 403)
        self.assertEqual(self.written(), [])

    def write_list(self, data):
        (self.app.todos_file.parent / "feedback.json").write_text(data if isinstance(data, str) else json.dumps(data))

    def test_the_list_is_served(self):
        items = [{"name": "2026-10-17 tabs", "done": False, "created": "2026-10-17", "kind": "idea",
                  "state": "planned", "where": "BACKLOG 41", "text": "Tabs for messages."},
                 {"name": "2026-10-15 old", "done": True, "created": "2026-10-15", "kind": "",
                  "state": "done", "where": "", "text": "Fixed thing."}]
        self.write_list({"items": items})
        status, _, data = self.request("GET", "/api/feedback")
        self.assertEqual((status, data), (200, {"items": items}))

    def test_an_off_shape_list_is_empty(self):
        ok = {"name": "2026-10-17 tabs", "done": False, "created": "2026-10-17", "kind": "idea",
              "state": "new", "where": "", "text": "x"}
        for name, data in {"missing": None, "not json": "{", "extra key": {"items": [{**ok, "x": 1}]},
                           "hidden": {"items": [{**ok, "text": "a\u202eb"}]},
                           "long": {"items": [{**ok, "text": "y" * 601}]},
                           "bad kind": {"items": [{**ok, "kind": "rant"}]},
                           "bad name": {"items": [{**ok, "name": "../x"}]},
                           "too many": {"items": [ok] * 71}}.items():
            with self.subTest(name=name):
                p = self.app.todos_file.parent / "feedback.json"
                p.unlink(missing_ok=True)
                if data is not None:
                    self.write_list(data)
                status, _, got = self.request("GET", "/api/feedback")
                self.assertEqual((status, got), (200, {"items": []}), name)


class SaveWebTest(DeviceBase):
    """Threat 139: a chat answer saved into Inbox, signed with the device key."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.app.requests = base / "julz-mem" / "Inbox" / ".requests"
        self.app.requests.mkdir(parents=True)

    def send(self, text, sha=None, finish_as=None):
        body = {"action": "save", "text": text, "via": "device", "sha256": sha or gate.sha256(text)}
        status, _, begun = self.post("/api/begin", body)
        if status != 200:
            return status, begun, None
        status, _, data = self.post("/api/finish", {"action": finish_as or "save", "nonce": begun["nonce"],
                                                    "signature": self.sign(begun)})
        return status, data, begun

    def written(self):
        return [json.loads(p.read_text()) for p in self.app.requests.iterdir()]

    def test_one_fingerprint_saves_one_note_in_inbox(self):
        status, data, begun = self.send("DORA is Discover, Offer, Request, Ack.")
        self.assertEqual(status, 200, data)
        self.assertEqual(begun["text"], "save: chat answer\nDORA is Discover, Offer, Request, Ack.\n")
        req, = self.written()
        self.assertEqual(req["op"], "create")
        self.assertRegex(req["note"], r"^Inbox/\d{4}-\d{2}-\d{2} dora-is-discover-offer-request \d{6}\.md$")
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn("save-signed", [e["action"] for e in log])

    def test_refused_at_begin(self):
        for text in ("", "a\u202eb", None, 5):
            with self.subTest(text=str(text)[:20]):
                status, _, _ = self.send(text, sha="0" * 64)
                self.assertEqual(status, 400)
        self.assertEqual(self.written(), [])

    def test_another_text_than_the_hash_is_refused(self):
        status, _, _ = self.send("An answer.", sha=gate.sha256("something else"))
        self.assertEqual(status, 409)
        self.assertEqual(self.written(), [])

    def test_a_save_signature_is_nothing_else(self):
        for other in ("approve", "feedback"):
            status, _, _ = self.send("An answer.", finish_as=other)
            self.assertEqual(status, 403, other)
        self.assertEqual(self.written(), [])


class CaseWebTest(DeviceBase):
    """Threat 153: a bad answer kept as an eval case in feedback/eval/, signed with the device key."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.app.requests = base / "julz-mem" / "Inbox" / ".requests"
        self.app.requests.mkdir(parents=True)

    def send(self, question, answer, mode="none", sha=None, finish_as=None):
        if sha is None:
            sha = gate.sha256(question + "\x00" + answer)
        body = {"action": "case", "question": question, "answer": answer, "mode": mode,
                "via": "device", "sha256": sha}
        status, _, begun = self.post("/api/begin", body)
        if status != 200:
            return status, begun, None
        status, _, data = self.post("/api/finish", {"action": finish_as or "case", "nonce": begun["nonce"],
                                                    "signature": self.sign(begun)})
        return status, data, begun

    def written(self):
        return [json.loads(p.read_text()) for p in self.app.requests.iterdir()]

    def test_one_fingerprint_keeps_one_case(self):
        status, data, begun = self.send("Which nft command lists rules?", "sudo iptables -L", "learn")
        self.assertEqual(status, 200, data)
        self.assertEqual(begun["text"], "case: bad answer\nmode: learn\nquestion: 30\n"
                                        "Which nft command lists rules?\nanswer:\nsudo iptables -L\n")
        req, = self.written()
        self.assertEqual(req["op"], "create")
        self.assertRegex(req["note"], r"^feedback/eval/\d{4}-\d{2}-\d{2} which-nft-command-lists-rules \d{6}\.md$")
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn("case-signed", [e["action"] for e in log])

    def test_refused_at_begin(self):
        for q, a, mode in (("", "a", "none"), ("q", "", "none"), ("a\u202eb", "a", "none"),
                           (None, "a", "none"), ("q", 5, "none"), ("q", "a", "solve"), ("q", "a", None)):
            with self.subTest(q=str(q)[:20], a=str(a)[:20], mode=mode):
                status, _, _ = self.send(q, a, mode, sha="0" * 64)
                self.assertEqual(status, 400)
        self.assertEqual(self.written(), [])

    def test_another_text_than_the_hash_is_refused(self):
        for sha in (gate.sha256("q\x00something else"), gate.sha256("qa"), gate.sha256("a\x00q")):
            status, _, _ = self.send("q", "a", sha=sha)
            self.assertEqual(status, 409)
        self.assertEqual(self.written(), [])

    def test_a_case_signature_is_nothing_else(self):
        for other in ("approve", "feedback", "save"):
            status, _, _ = self.send("q", "a", finish_as=other)
            self.assertEqual(status, 403, other)
        self.assertEqual(self.written(), [])


class ProposalWebTest(DeviceBase):
    """Threat 156: a change Julz asks for in the native chat, a card I sign (208)."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.app.requests = base / "julz-mem" / "Inbox" / ".requests"
        self.app.proposals_dir = base / "julz-mem" / "Inbox" / ".proposals"
        self.app.requests.mkdir(parents=True)
        self.app.proposals_dir.mkdir()
        self.clock.now = 1_760_000_000.0
        self.n = 0

    def propose(self, age=0, **req):
        self.n += 1
        name = f"{int(self.clock.now) - age}-{self.n:08x}.json"
        (self.app.proposals_dir / name).write_text(json.dumps(req))
        return name

    def listed(self):
        status, _, data = self.request("GET", "/api/proposals")
        self.assertEqual(status, 200, data)
        return data["proposals"]

    def send(self, action, pid, sha=None, finish_as=None, before_finish=None):
        if sha is None:
            sha = next(p["sha256"] for p in self.listed() if p["id"] == pid)
        status, _, begun = self.post("/api/begin", {"action": action, "id": pid, "via": "device", "sha256": sha})
        if status != 200:
            return status, begun, None
        if before_finish:
            before_finish()
        status, _, data = self.post("/api/finish", {"action": finish_as or action, "nonce": begun["nonce"],
                                                    "signature": self.sign(begun)})
        return status, data, begun

    def written(self):
        return [json.loads(p.read_text()) for p in self.app.requests.iterdir()]

    def test_listed_with_the_card_text(self):
        pid = self.propose(op="append", note="daily/week.md", text="- [ ] bread")
        item, = self.listed()
        self.assertEqual(item, {"id": pid, "text": "Julz asks to add to daily/week.md:\n\n- [ ] bread\n",
                                "sha256": gate.sha256(item["text"])})

    def test_one_fingerprint_one_request(self):
        req = {"op": "move", "note": "Inbox/physio.md", "to": "daily/physio.md", "sha256": "b" * 64}
        pid = self.propose(**req)
        status, data, begun = self.send("change", pid)
        self.assertEqual(status, 200, data)
        self.assertEqual(begun["text"], "Julz asks to move Inbox/physio.md to daily/physio.md\n")
        self.assertEqual(self.written(), [req])
        self.assertFalse((self.app.proposals_dir / pid).exists())
        self.assertEqual(self.listed(), [])
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn("change-signed", [e["action"] for e in log])
        # The same card again: it is gone, so nothing more is written
        status, _, _ = self.send("change", pid, sha=gate.sha256(begun["text"]))
        self.assertEqual(status, 404)
        self.assertEqual(len(self.written()), 1)

    def test_drop_writes_nothing(self):
        pid = self.propose(op="delete", note="Inbox/physio.md", sha256="c" * 64)
        status, data, _ = self.send("drop", pid)
        self.assertEqual(status, 200, data)
        self.assertEqual(self.written(), [])
        self.assertFalse((self.app.proposals_dir / pid).exists())
        log = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertIn("change-dropped", [e["action"] for e in log])

    def test_changed_between_begin_and_finish(self):
        pid = self.propose(op="append", note="daily/week.md", text="- [ ] bread")
        path = self.app.proposals_dir / pid

        def swap():
            path.write_text(json.dumps({"op": "append", "note": "daily/week.md", "text": "- [ ] other"}))

        for action in ("change", "drop"):
            path.write_text(json.dumps({"op": "append", "note": "daily/week.md", "text": "- [ ] bread"}))
            status, _, _ = self.send(action, pid, before_finish=swap)
            self.assertEqual(status, 409, action)
            self.assertEqual(self.written(), [])
        # Gone between begin and finish: nothing written either
        path.write_text(json.dumps({"op": "append", "note": "daily/week.md", "text": "- [ ] bread"}))
        status, _, _ = self.send("change", pid, before_finish=path.unlink)
        self.assertEqual(status, 409)
        self.assertEqual(self.written(), [])

    def test_another_text_than_the_hash_is_refused(self):
        pid = self.propose(op="append", note="daily/week.md", text="- [ ] bread")
        status, _, _ = self.send("change", pid, sha=gate.sha256("Julz asks to add to daily/week.md:\n\n- [ ] cake\n"))
        self.assertEqual(status, 409)
        self.assertEqual(self.written(), [])

    def test_a_change_signature_is_nothing_else(self):
        pid = self.propose(op="append", note="daily/week.md", text="x")
        for other in ("drop", "approve", "save", "case"):
            status, _, _ = self.send("change", pid, finish_as=other)
            self.assertEqual(status, 403, other)
        status, _, _ = self.send("drop", pid, finish_as="change")
        self.assertEqual(status, 403)
        self.assertEqual(self.written(), [])
        self.assertTrue((self.app.proposals_dir / pid).exists())

    def test_bad_ones_not_listed(self):
        self.propose(op="tick", note="daily/week.md", item="bread")
        self.propose(op="append", note="Inbox/claude/spec.md", text="x")
        self.propose(op="append", note="daily/week.md", text="a\u202eb")
        self.propose(op="append", note="daily/week.md", text="x", extra=1)
        self.propose(age=86_401, op="append", note="daily/week.md", text="old")
        self.propose(age=-600, op="append", note="daily/week.md", text="future")
        (self.app.proposals_dir / "notaname.json").write_text(json.dumps({"op": "append", "note": "daily/w.md", "text": "x"}))
        (self.app.proposals_dir / f"{int(self.clock.now)}-0000ffff.json").symlink_to(self.app.requests)
        target = Path(self.tmp.name) / "planted.json"
        target.write_text(json.dumps({"op": "append", "note": "daily/w.md", "text": "x"}))
        (self.app.proposals_dir / f"{int(self.clock.now)}-0000fffe.json").symlink_to(target)
        (self.app.proposals_dir / f"{int(self.clock.now)}-0000fffd.json").write_bytes(b"x" * 20_000)
        self.assertEqual(self.listed(), [])
        status, _, _ = self.send("change", f"{int(self.clock.now)}-0000fffe.json", sha="0" * 64)
        self.assertEqual(status, 404)

    def test_at_most_ten_oldest_first(self):
        ids = [self.propose(age=100 - i, op="append", note="daily/week.md", text=f"line {i}") for i in range(12)]
        self.assertEqual([p["id"] for p in self.listed()], ids[:10])
        # One not shown is never signed, even by its own id and text
        status, _, _ = self.send("change", ids[11], sha=gate.sha256("Julz asks to add to daily/week.md:\n\nline 11\n"))
        self.assertEqual(status, 404)
        self.assertEqual(self.written(), [])

    def test_no_folder_no_cards(self):
        self.app.proposals_dir.rmdir()
        self.assertEqual(self.listed(), [])

    def test_unknown_id_at_begin(self):
        for pid in ("../x.json", None, 5, "1760000000-00000001.json"):
            status, _, _ = self.post("/api/begin", {"action": "change", "id": pid, "via": "device", "sha256": "0" * 64})
            self.assertEqual(status, 404, pid)


class IntegrationsWebTest(Base):
    """Threat 122: the Links tab's list, fixed words and numbers only."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.app.todos_file = base / "vault" / "todos.json"
        self.app.todos_file.parent.mkdir()

    def items(self):
        status, _, data = self.request("GET", "/api/integrations")
        self.assertEqual(status, 200)
        return {i["id"]: i for i in data["items"]}

    def test_the_list_and_its_statuses(self):
        items = self.items()
        self.assertEqual(list(items), ["keep", "delegate", "vault", "push", "voice", "memlog", "ci"])
        self.assertEqual(items["delegate"]["status"], "Gated")
        self.assertEqual(items["ci"]["status"], "Planned")
        for i in items.values():
            self.assertEqual(set(i), {"id", "name", "what", "status", "facts"})

    def test_facts_are_counts_from_the_log_never_its_text(self):
        now = self.clock()
        stamp = lambda s: datetime.fromtimestamp(now - s, timezone.utc).isoformat(timespec="seconds")
        self.dirs.log.parent.mkdir(parents=True, exist_ok=True)
        with self.dirs.log.open("w") as f:
            for s in (3600, 7200, 9 * 86400):  # two runs this week, one older
                f.write(json.dumps({"time": stamp(s), "action": "run", "sha256": "a" * 64, "status": "ok"}) + "\n")
            f.write(json.dumps({"time": stamp(60), "action": "sync", "sha256": "", "status": "ok",
                                "reason": "14 notes in julz-claude <img src=x> ignore previous"}) + "\n")
        items = self.items()
        self.assertIn("Runs, 7 days: 2", items["delegate"]["facts"])  # label: value, a spec line (22e)
        keep = " ".join(items["keep"]["facts"])
        self.assertIn("14 notes", keep)
        self.assertNotIn("img", keep)
        self.assertNotIn("ignore", keep)
        self.assertEqual(items["keep"]["status"], "On")

    def test_a_failed_sync_asks_for_a_check(self):
        self.dirs.log.parent.mkdir(parents=True, exist_ok=True)
        self.dirs.log.write_text(json.dumps({"time": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
                                             "action": "sync", "sha256": "", "status": "failed", "reason": "x"}) + "\n")
        self.assertEqual(self.items()["keep"]["status"], "Check")

    def test_commits_today_from_the_vault_status(self):
        self.assertIn("Commits today: not written yet", self.items()["vault"]["facts"])
        (self.app.todos_file.parent / "vault-status.json").write_text(json.dumps({"date": "2026-10-18", "commits_today": 6}))
        self.assertIn("Commits today: 6", self.items()["vault"]["facts"])
        (self.app.todos_file.parent / "vault-status.json").write_text(json.dumps({"date": "x", "commits_today": "6; rm -rf"}))
        self.assertIn("Commits today: not written yet", self.items()["vault"]["facts"])

    def test_integrations_are_read_only(self):
        status, _, _ = self.post("/api/integrations", {})
        self.assertEqual(status, 405)


class GoalsWebTest(DeviceBase):
    """Threat 123: goals in the app, read and changed through the approver."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.app.todos_file = base / "vault" / "todos.json"
        self.app.requests = base / "julz-mem" / "Inbox" / ".requests"
        self.app.requests.mkdir(parents=True)
        self.app.todos_file.parent.mkdir()
        periods = [{"key": "2026-10-18", "label": "Today", "note": "goals/2026-10-18.md", "goals": []},
                   {"key": "2026-W42", "label": "This week", "note": "goals/2026-W42.md", "goals": [
                       {"text": "Study 10 h (3/10)", "done": False, "progress": [3, 10], "goal": None, "linked": None,
                        "parent": None, "rollup": None, "parts": 0, "due": None,
                        "est": None, "spent": None, "hours": None},
                       {"text": "Exam #goal/exam", "done": False, "progress": None, "goal": "exam", "linked": [1, 2],
                        "parent": "cpts", "rollup": 50, "parts": 2, "due": None,
                        "est": 360, "spent": 90, "hours": [135, 420]}]}]
        tree = {"exam": "cpts", "cpts": None}
        milestones = [{"goal": "cpts", "text": "Pass CPTS #goal/cpts [due:: 2027-03-01]", "due": "2027-03-01", "rollup": 50}]
        import hashlib
        self.snap = {"id": hashlib.sha256(json.dumps([periods, tree, milestones], sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
                     "periods": periods, "tree": tree, "milestones": milestones}
        (self.app.todos_file.parent / "goals.json").write_text(json.dumps(self.snap))

    def act(self, picks, sha=None):
        status, _, begun = self.post("/api/begin", {"action": "goal", "sha256": sha or self.snap["id"], "pick": picks, "via": "device"})
        if status != 200:
            return status, begun, None
        status, _, data = self.post("/api/finish", {"action": "goal", "nonce": begun["nonce"], "signature": self.sign(begun)})
        return status, data, begun

    def written(self):
        return sorted((json.loads(p.read_text()) for p in self.app.requests.iterdir()), key=lambda r: r["op"])

    def test_a_real_snapshot_is_served_whole(self):
        # The approver must accept what julz-vault really writes (found 18 Oct: a new key emptied it)
        import importlib.util, tempfile, subprocess
        from datetime import date
        spec = importlib.util.spec_from_file_location("v", ROOT / "julz_vault.py"); v = importlib.util.module_from_spec(spec); spec.loader.exec_module(v)
        vault = Path(tempfile.mkdtemp())
        (vault / "goals").mkdir()
        (vault / "goals" / "2026.md").write_text("- [ ] Pass CPTS #goal/cpts [due:: 2027-03-01]\n- [ ] Net+ (1/2) #goal/net [in:: cpts]\n")
        (self.app.todos_file.parent / "goals.json").write_text(json.dumps(v.goals_snapshot(vault, date(2026, 10, 18))))
        status, _, data = self.request("GET", "/api/goals")
        self.assertEqual(status, 200)
        year = next(p for p in data["periods"] if p["key"] == "2026")
        self.assertEqual([g["rollup"] for g in year["goals"]], [50, None])
        self.assertEqual([(m["goal"], m["due"], m["rollup"]) for m in data["milestones"]], [("cpts", "2027-03-01", 50)])

    def test_goals_are_served(self):
        status, _, data = self.request("GET", "/api/goals")
        self.assertEqual((status, data), (200, self.snap))

    def test_one_fingerprint_adds_and_counts(self):
        status, data, begun = self.act([{"do": "add", "period": "2026-10-18", "text": "Walk 10k"},
                                        {"do": "bump", "period": "2026-W42", "item": "Study 10 h (3/10)"}])
        self.assertEqual(status, 200, data)
        self.assertIn("add: 2026-10-18 Walk 10k #goal/walk-10k\n", begun["text"])
        self.assertEqual(self.written(), [{"op": "goal", "note": "goals/2026-10-18.md", "item": "Walk 10k #goal/walk-10k"},
                                          {"op": "progress", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)"}])

    def test_target_and_link_through_the_approver(self):
        lists = [{"name": "study", "note": "daily/study.md", "done": 0, "total": 1, "open": ["DNS lab"], "done_items": []}]
        self.app.todos_file.write_text(json.dumps({"date": "2026-10-18", "id": web.vault.snapshot_id(lists), "lists": lists}))
        status, data, begun = self.act([
            {"do": "target", "period": "2026-W42", "item": "Exam #goal/exam", "target": "5"},
            {"do": "link", "period": "2026-W42", "item": "Exam #goal/exam", "list": "study", "todo": "DNS lab"}])
        self.assertEqual(status, 200, data)
        self.assertIn("link: 2026-W42 exam daily/study.md: DNS lab\n", begun["text"])
        self.assertEqual(self.written(), [{"op": "link", "note": "daily/study.md", "item": "DNS lab", "goal": "exam"},
                                          {"op": "target", "note": "goals/2026-W42.md", "item": "Exam #goal/exam", "target": 5}])

    def test_unlink_through_the_approver(self):
        lists = [{"name": "physio", "note": "daily/physio.md", "done": 0, "total": 1,
                  "open": ["Review session notes #goal/exam"], "doing": [], "done_items": []}]
        self.app.todos_file.write_text(json.dumps({"date": "2026-10-18", "id": web.vault.snapshot_id(lists), "lists": lists}))
        status, data, begun = self.act([{"do": "unlink", "period": "2026-W42", "item": "Exam #goal/exam",
                                         "list": "physio", "todo": "Review session notes #goal/exam"}])
        self.assertEqual(status, 200, data)
        self.assertIn("unlink: 2026-W42 exam daily/physio.md: Review session notes #goal/exam\n", begun["text"])
        self.assertEqual(self.written(), [{"op": "unlink", "note": "daily/physio.md", "item": "Review session notes #goal/exam", "goal": "exam"}])

    def test_estimate_and_log_through_the_approver(self):
        status, data, begun = self.act([{"do": "est", "period": "2026-W42", "item": "Study 10 h (3/10)", "hours": "10"},
                                        {"do": "log", "period": "2026-W42", "item": "Study 10 h (3/10)", "hours": "1.5"}])
        self.assertEqual(status, 200, data)
        self.assertIn("log: 2026-W42 1.5h Study 10 h (3/10)\n", begun["text"])
        self.assertEqual(self.written(), [{"op": "est", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10)", "minutes": 600},
                                          {"op": "log", "note": "goals/2026-W42.md", "item": "Study 10 h (3/10) [est:: 10h]", "minutes": 90}])
        status, _, _ = self.act([{"do": "log", "period": "2026-W42", "item": "Study 10 h (3/10)", "hours": "25"}])
        self.assertEqual(status, 400)

    def test_a_due_date_through_the_approver(self):
        from datetime import date, timedelta
        day = (date.today() + timedelta(days=12)).isoformat()
        status, data, begun = self.act([{"do": "due", "period": "2026-W42", "item": "Exam #goal/exam", "due": day}])
        self.assertEqual(status, 200, data)
        self.assertIn(f"due: 2026-W42 {day} Exam #goal/exam\n", begun["text"])
        self.assertEqual(self.written(), [{"op": "due", "note": "goals/2026-W42.md", "item": "Exam #goal/exam", "due": day}])
        status, _, _ = self.act([{"do": "due", "period": "2026-W42", "item": "Exam #goal/exam", "due": "2026-02-30"}])
        self.assertEqual(status, 400)

    def test_refused_and_stale(self):
        status, _, _ = self.act([{"do": "add", "period": "2026-10-18", "text": "see https://evil.example"}])
        self.assertEqual(status, 400)
        status, _, _ = self.act([{"do": "bump", "period": "2026-W42", "item": "Study 10 h (3/10)"}], sha="d" * 64)
        self.assertEqual(status, 409)
        self.assertEqual(self.written(), [])

    def test_an_off_shape_snapshot_is_empty(self):
        week = self.snap["periods"][1]
        for name, periods in {"missing keys": [{"key": "../x"}],
                              "bad key": [{**week, "key": "../x", "note": "goals/../x.md"}],
                              "hidden text": [{**week, "goals": [{**week["goals"][0], "text": "a\u202eb"}]}],
                              "rollup over 100": [{**week, "goals": [{**week["goals"][0], "rollup": 101}]}],
                              "bad parent": [{**week, "goals": [{**week["goals"][0], "parent": "../x"}]}],
                              "due with text": [{**week, "goals": [{**week["goals"][0], "due": "2026-10-30 x"}]}],
                              "due not a day": [{**week, "goals": [{**week["goals"][0], "due": "2026-02-30"}]}],
                              "est as text": [{**week, "goals": [{**week["goals"][0], "est": "6h"}]}],
                              "negative spent": [{**week, "goals": [{**week["goals"][0], "spent": -15}]}],
                              "huge hours": [{**week, "goals": [{**week["goals"][0], "hours": [0, 10 ** 9]}]}],
                              "hours not a pair": [{**week, "goals": [{**week["goals"][0], "hours": [1]}]}],
                              "hours a bool": [{**week, "goals": [{**week["goals"][0], "hours": [True, 1]}]}]}.items():
            with self.subTest(name=name):
                (self.app.todos_file.parent / "goals.json").write_text(json.dumps({**self.snap, "periods": periods}))
                status, _, data = self.request("GET", "/api/goals")
                self.assertEqual((status, data), (200, {"id": "", "periods": [], "tree": {}, "milestones": []}), name)
        m = self.snap["milestones"][0]
        for name, ms in {"missing keys": [{"goal": "cpts"}], "hidden text": [{**m, "text": "a\u202eb"}],
                         "a link": [{**m, "text": "see https://evil.example"}], "bad due": [{**m, "due": "soon"}],
                         "bad id": [{**m, "goal": "../x"}], "rollup over 100": [{**m, "rollup": 101}],
                         "too many": [m] * 21, "not a list": {"a": m}}.items():
            with self.subTest(name=name):
                (self.app.todos_file.parent / "goals.json").write_text(json.dumps({**self.snap, "milestones": ms}))
                status, _, data = self.request("GET", "/api/goals")
                self.assertEqual((status, data), (200, {"id": "", "periods": [], "tree": {}, "milestones": []}), name)


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

    def test_approve_with_a_note_signs_spec_and_note(self):
        # Threat 93: the server adds my note to the text I sign, and the inbox copy goes
        status, data = self.act("approve", "readme.md", note="use port 8080")
        self.assertEqual(status, 200, data)
        text = GOOD + "note: use port 8080\n"
        self.assertEqual(self.approved(), [f"{gate.sha256(text)}.md"])
        self.assertEqual((self.dirs.approved / f"{gate.sha256(text)}.md").read_text(), text)
        self.assertFalse(self.spec.exists())

    def test_a_bad_note_is_refused_before_signing(self):
        for bad in ("a\nproject: other", "see https://evil.example", "x" * 281, "ghp_abcdefghijklmnop", 5):
            with self.subTest(bad=bad):
                status, data = self.act("approve", "readme.md", note=bad)
                self.assertEqual(status, 400, data)
        self.assertEqual(self.approved(), [])
        self.assertTrue(self.spec.exists())

    def test_reject_ignores_a_note(self):
        status, data = self.act("reject", "readme.md", note="whatever")
        self.assertEqual(status, 200, data)
        self.assertEqual(self.approved(), [])

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

    def test_only_known_actions(self):
        for action in ("run", "enroll", "approve-all", None):
            with self.subTest(action=action):
                status, _, _ = self.post("/api/begin", {"action": action, "name": "readme.md",
                                                        "sha256": gate.sha256(GOOD)})
                self.assertEqual(status, 400)

    def test_continue_needs_a_waiting_task(self):
        # A spec name is not a task: continue and stop only work on open needs
        for action in ("continue", "stop"):
            status, _, _ = self.post("/api/begin", {"action": action, "name": "readme.md",
                                                    "root": "readme.md",
                                                    "sha256": gate.sha256(GOOD)})
            self.assertEqual(status, 404)

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


class NeedWebTest(Base):
    """Threats 37 and 40 on the page: an open need is answered by a signed continue or stop."""

    def setUp(self):
        super().setUp()
        self.enroll()
        self.root = gate.sha256(GOOD)
        self.need = {"need": "install python-requests", "why": "import fails"}
        self.task = {"root": self.root, "project": "julz-sandbox",
                     "goal": "add a usage line to the README", "step": 2,
                     "status": "waiting", "need": self.need["need"], "why": self.need["why"],
                     "need_hash": gate.need_hash(self.need), "opened": self.clock(),
                     "last_run": self.root}
        gate.save_task(self.dirs, self.task)

    def answer(self, action, sha=None, key=None):
        if sha is None:
            sha = self.state()["needs"][0]["sha256"]
        status, _, data = self.post("/api/begin", {"action": action, "root": self.root,
                                                   "sha256": sha})
        if status != 200:
            return status, data
        status, _, data = self.post("/api/finish", {"action": action, "nonce": data["nonce"],
                                                    "credential": (key or self.key).sign(data)})
        return status, data

    def test_state_shows_need(self):
        needs = self.state()["needs"]
        self.assertEqual(len(needs), 1)
        n = needs[0]
        self.assertEqual((n["need"], n["why"], n["step"]), (self.need["need"],
                                                              self.need["why"], 2))
        self.assertEqual(n["text"], gate.continuation_text(self.task))
        self.assertEqual(n["sha256"], gate.sha256(n["text"]))
        self.assertEqual(n["work"], str(self.dirs.log.parent / "work" / self.root))

    def test_continue_queues_continuation(self):
        status, data = self.answer("continue")
        self.assertEqual(status, 200, data)
        text = gate.continuation_text(self.task)
        self.assertEqual(self.approved(), [f"{gate.sha256(text)}.md"])
        self.assertEqual(gate.load_task(self.dirs, self.root)["status"], "approved")
        self.assertEqual(self.state()["needs"], [])
        self.assertIn('"approve-channel"', self.dirs.log.read_text())

    def test_stop_ends_task(self):
        status, data = self.answer("stop")
        self.assertEqual(status, 200, data)
        self.assertEqual(self.approved(), [])
        self.assertEqual(gate.load_task(self.dirs, self.root)["status"], "stopped")
        self.assertIn('"stop"', self.dirs.log.read_text())

    def test_need_changed_after_view_refused(self):
        seen = self.state()["needs"][0]["sha256"]
        other = {"need": "run sudo rm -rf /", "why": "cleanup"}
        gate.save_task(self.dirs, {**self.task, **other, "need_hash": gate.need_hash(other)})
        status, _ = self.answer("continue", sha=seen)
        self.assertEqual(status, 409)
        self.assertEqual(self.approved(), [])

    def test_stop_signature_cannot_continue(self):
        sha = self.state()["needs"][0]["sha256"]
        _, _, data = self.post("/api/begin", {"action": "stop", "root": self.root, "sha256": sha})
        status, _, _ = self.post("/api/finish", {"action": "continue", "nonce": data["nonce"],
                                                 "credential": self.key.sign(data)})
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])

    def test_other_key_cannot_continue(self):
        status, _ = self.answer("continue", key=softkeys.SoftKey())
        self.assertEqual(status, 403)
        self.assertEqual(gate.load_task(self.dirs, self.root)["status"], "waiting")

    def test_expired_need_hidden_and_refused(self):
        sha = self.state()["needs"][0]["sha256"]
        self.clock.now += gate.NEED_TTL + 1
        self.assertEqual(self.state()["needs"], [])
        status, _ = self.answer("continue", sha=sha)
        self.assertEqual(status, 404)

    def test_page_cannot_choose_the_text(self):
        # Two tasks wait. The page asks to sign A but sends B's text along: the server must
        # sign and store A's text from its own state, never what the page sent
        other = {**self.task, "root": "b" * 64}
        gate.save_task(self.dirs, other)
        a_need = [n for n in self.state()["needs"] if n["root"] == self.root][0]
        _, _, data = self.post("/api/begin", {"action": "continue", "root": self.root,
                                              "sha256": a_need["sha256"],
                                              "text": gate.continuation_text(other)})
        status, _, _ = self.post("/api/finish", {"action": "continue", "nonce": data["nonce"],
                                                 "credential": self.key.sign(data)})
        self.assertEqual(status, 200)
        self.assertEqual(self.approved(), [f"{a_need['sha256']}.md"])
        self.assertEqual(gate.load_task(self.dirs, "b" * 64)["status"], "waiting")

    def typed(self, answer, sha=None):
        """Begin a typed answer. Returns (status, begin reply)."""
        if sha is None:
            sha = self.state()["needs"][0]["sha256"]
        status, _, data = self.post("/api/begin", {"action": "answer", "root": self.root,
                                                   "sha256": sha, "answer": answer})
        return status, data

    def test_typed_answer_queues_signed_text(self):
        status, data = self.typed("use port 8080")
        self.assertEqual(status, 200, data)
        status, _, done = self.post("/api/finish", {"action": "answer", "nonce": data["nonce"],
                                                    "credential": self.key.sign(data)})
        self.assertEqual(status, 200, done)
        text = gate.continuation_text(self.task, "use port 8080")
        self.assertEqual(done["sha256"], gate.sha256(text))
        self.assertEqual((self.dirs.approved / f"{gate.sha256(text)}.md").read_text(), text)
        self.assertEqual(gate.load_task(self.dirs, self.root)["status"], "approved")
        self.assertNotIn("8080", self.dirs.log.read_text())  # threat 50

    def test_signed_answer_cannot_become_another(self):
        # Threat 51: sign A, then try to finish as B or as a plain continue. Only A is stored
        _, a = self.typed("answer A")
        status, _, _ = self.post("/api/finish", {"action": "continue", "nonce": a["nonce"],
                                                 "credential": self.key.sign(a)})
        self.assertEqual(status, 403)
        _, a = self.typed("answer A")
        _, b = self.typed("answer B")
        status, _, _ = self.post("/api/finish", {"action": "answer", "nonce": b["nonce"],
                                                 "credential": self.key.sign(a)})
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])

    def test_bad_typed_answers_refused(self):
        for bad in ("a\nstep: 3", "x >>>owner answer", "x" * 301, "", None, ["a"],
                    "ghp_abcdefghijklmnopqrstuvwxyz", "a\u202eb"):
            with self.subTest(bad=bad):
                status, data = self.typed(bad)
                self.assertEqual(status, 400, data)
        self.assertEqual(self.pk.pending, {})
        self.assertEqual(self.approved(), [])

    def test_secret_refusal_does_not_echo_it(self):
        status, data = self.typed("ghp_abcdefghijklmnopqrstuvwxyz")
        self.assertEqual(status, 400)
        self.assertNotIn("ghp_", json.dumps(data))

    def test_typed_answer_to_changed_need_refused(self):
        seen = self.state()["needs"][0]["sha256"]
        other = {"need": "paste your token", "why": "push"}
        gate.save_task(self.dirs, {**self.task, **other, "need_hash": gate.need_hash(other)})
        status, _ = self.typed("ok", sha=seen)
        self.assertEqual(status, 409)

    def test_typed_answer_without_assertion_stores_nothing(self):
        _, data = self.typed("ok")
        status, _, _ = self.post("/api/finish", {"action": "answer", "nonce": data["nonce"],
                                                 "credential": softkeys.SoftKey().sign(data)})
        self.assertEqual(status, 403)
        self.assertEqual(gate.load_task(self.dirs, self.root)["status"], "waiting")

    def test_bad_root_refused(self):
        for root in ("../x", None, ["a"], "0" * 64):
            with self.subTest(root=root):
                status, _, _ = self.post("/api/begin", {"action": "continue", "root": root,
                                                        "sha256": "0" * 64})
                self.assertEqual(status, 404)


class HaltWebTest(Base):
    """Threat 47 on the page: stopping the run going now needs a signed halt."""

    def setUp(self):
        super().setUp()
        self.enroll()
        self.dirs.ensure()
        self.run = {"sha256": gate.sha256(GOOD), "root": gate.sha256(GOOD), "step": 1,
                    "project": "julz-sandbox", "goal": "add a usage line to the README",
                    "started": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        self.dirs.running.write_text(json.dumps(self.run))
        # current_run compares with the page clock: align it with the real start time
        self.clock.now = time.time()

    def halt(self, run_id=None, action="halt", sign_action=None):
        state = self.state()["running"]
        _, _, data = self.post("/api/begin", {"action": sign_action or action,
                                              "run": run_id or state["sha256"],
                                              "sha256": state["text_sha256"]})
        if "nonce" not in data:
            return 404, data
        status, _, reply = self.post("/api/finish", {"action": action, "nonce": data["nonce"],
                                                     "credential": self.key.sign(data)})
        return status, reply

    def test_state_shows_running(self):
        r = self.state()["running"]
        self.assertEqual((r["sha256"], r["goal"]), (self.run["sha256"], self.run["goal"]))
        self.assertEqual(r["text"], gate.halt_text(self.run))

    def test_signed_halt_writes_stop(self):
        status, reply = self.halt()
        self.assertEqual(status, 200, reply)
        self.assertTrue(gate.stop_requested(self.dirs, self.run["sha256"]))
        self.assertIn('"halt"', self.dirs.log.read_text())

    def test_halt_logs_phone_for_a_passkey(self):
        self.halt()
        e = [json.loads(l) for l in self.dirs.log.read_text().splitlines()][-1]
        self.assertEqual((e["action"], e["reason"]), ("halt", "phone"))

    def test_page_cannot_pick_another_run(self):
        status, _ = self.halt(run_id="c" * 64)
        self.assertEqual(status, 404)
        self.assertFalse(any(self.dirs.control.glob("stop-*")))

    def test_other_action_signature_cannot_halt(self):
        status, _ = self.halt(sign_action="reject", action="halt")
        self.assertEqual(status, 404)  # reject needs a spec name, there is none
        state = self.state()["running"]
        _, _, data = self.post("/api/begin", {"action": "halt", "run": state["sha256"],
                                              "sha256": state["text_sha256"]})
        status, _, _ = self.post("/api/finish", {"action": "stop", "nonce": data["nonce"],
                                                 "credential": self.key.sign(data)})
        self.assertEqual(status, 403)
        self.assertFalse(any(self.dirs.control.glob("stop-*")))

    def test_other_key_cannot_halt(self):
        state = self.state()["running"]
        _, _, data = self.post("/api/begin", {"action": "halt", "run": state["sha256"],
                                              "sha256": state["text_sha256"]})
        status, _, _ = self.post("/api/finish", {"action": "halt", "nonce": data["nonce"],
                                                 "credential": softkeys.SoftKey().sign(data)})
        self.assertEqual(status, 403)
        self.assertFalse(any(self.dirs.control.glob("stop-*")))

    def test_nothing_running_nothing_to_halt(self):
        self.dirs.running.unlink()
        self.assertIsNone(self.state()["running"])
        status, _, _ = self.post("/api/begin", {"action": "halt", "run": self.run["sha256"],
                                                "sha256": "0" * 64})
        self.assertEqual(status, 404)

    def test_run_finished_between_view_and_tap(self):
        state = self.state()["running"]
        _, _, data = self.post("/api/begin", {"action": "halt", "run": state["sha256"],
                                              "sha256": state["text_sha256"]})
        self.dirs.running.unlink()  # the run ended while I touched the sensor
        status, _, _ = self.post("/api/finish", {"action": "halt", "nonce": data["nonce"],
                                                 "credential": self.key.sign(data)})
        self.assertEqual(status, 409)
        self.assertFalse(any(self.dirs.control.glob("stop-*")))


class StoppedWebTest(Base):
    """Continue and Delete for a run I stopped, and the recent runs list."""

    def setUp(self):
        super().setUp()
        self.enroll()
        self.root = gate.sha256(GOOD)
        self.task = {"root": self.root, "project": "julz-sandbox",
                     "goal": "add a usage line to the README", "step": 2,
                     "status": "waiting", "need": gate.STOPPED_NEED["need"],
                     "why": gate.STOPPED_NEED["why"],
                     "need_hash": gate.need_hash(gate.STOPPED_NEED), "opened": self.clock(),
                     "last_run": self.root, "stopped": True}
        gate.save_task(self.dirs, self.task)

    def sign(self, begin_action, finish_action):
        sha = self.state()["needs"][0]["sha256"]
        _, _, data = self.post("/api/begin", {"action": begin_action, "root": self.root,
                                              "sha256": sha})
        status, _, reply = self.post("/api/finish", {"action": finish_action,
                                                     "nonce": data["nonce"],
                                                     "credential": self.key.sign(data)})
        return status, reply

    def test_stopped_card_is_marked(self):
        self.assertTrue(self.state()["needs"][0]["stopped"])

    def test_delete_discards_task(self):
        status, reply = self.sign("discard", "discard")
        self.assertEqual(status, 200, reply)
        self.assertEqual(gate.load_task(self.dirs, self.root)["status"], "discarded")
        self.assertEqual(self.state()["needs"], [])
        self.assertEqual(self.approved(), [])

    def test_delete_logs_signed_channel(self):
        self.sign("discard", "discard")
        e = [json.loads(l) for l in self.dirs.log.read_text().splitlines()][-1]
        self.assertEqual((e["action"], e["reason"]), ("signed", "discard, phone"))

    def test_continue_queues_resume(self):
        status, reply = self.sign("continue", "continue")
        self.assertEqual(status, 200, reply)
        self.assertEqual(gate.load_task(self.dirs, self.root)["status"], "approved")
        self.assertEqual(len(self.approved()), 1)

    def test_continue_signature_cannot_delete(self):
        status, _ = self.sign("continue", "discard")
        self.assertEqual(status, 403)
        self.assertEqual(gate.load_task(self.dirs, self.root)["status"], "waiting")

    def test_delete_signature_cannot_continue(self):
        status, _ = self.sign("discard", "continue")
        self.assertEqual(status, 403)
        self.assertEqual(self.approved(), [])

    def write_log(self, *entries):
        with open(self.dirs.log, "a") as f:
            for e in entries:
                f.write(json.dumps(e) + "\n")

    def test_recent_runs_newest_first_with_goal(self):
        cont = f"continue: {self.root}\nstep: 2\nneed_hash: {'0' * 64}\nanswer: done\n"
        self.dirs.ensure()  # save_task makes only tasks/ now
        (self.dirs.done / f"{self.root}.md").write_text(GOOD)
        (self.dirs.done / f"{gate.sha256(cont)}.md").write_text(cont)
        self.write_log({"time": "2026-10-16T02:00:00+00:00", "action": "run",
                        "sha256": self.root, "status": "stopped"},
                       {"time": "2026-10-16T02:05:00+00:00", "action": "start",
                        "sha256": gate.sha256(cont), "status": "ok"},
                       {"time": "2026-10-16T02:06:00+00:00", "action": "run",
                        "sha256": gate.sha256(cont), "status": "ok"})
        recent = self.state()["recent"]
        self.assertEqual([(r["status"], r["goal"]) for r in recent],
                         [("ok", "add a usage line to the README"),
                          ("stopped", "add a usage line to the README")])
        self.assertEqual(recent[0]["time"], "2026-10-16 02:06:00")

    def test_recent_capped_and_garbage_skipped(self):
        with open(self.dirs.log, "a") as f:
            f.write("not json\n")
        for i in range(web.MAX_RECENT + 3):
            self.write_log({"time": f"2026-10-16T02:{i:02d}:00+00:00", "action": "run",
                            "sha256": f"{i:064x}", "status": "ok"})
        self.write_log({"action": "run", "sha256": "../../etc", "status": "ok"})
        recent = self.state()["recent"]
        self.assertEqual(len(recent), web.MAX_RECENT)
        self.assertTrue(all(gate.HEX64.match(r["sha256"]) for r in recent))

    def test_huge_log_read_from_the_end_only(self):
        with open(self.dirs.log, "a") as f:
            f.write(("x" * 1000 + "\n") * 200)  # 200 KB of noise before the real line
        self.write_log({"time": "2026-10-16T03:00:00+00:00", "action": "run",
                        "sha256": "e" * 64, "status": "failed"})
        read = []
        real_open = open

        class Counting:
            def __init__(self, f):
                self.f = f

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.f.close()

            def seek(self, *a):
                return self.f.seek(*a)

            def read(self, *a):
                data = self.f.read(*a)
                read.append(len(data))
                return data

        web.open = lambda path, mode="r", *a, **k: Counting(real_open(path, mode, *a, **k))
        try:
            self.assertEqual(self.state()["recent"][0]["status"], "failed")
        finally:
            del web.open
        self.assertLessEqual(sum(read), web.LOG_TAIL)


class QueuedWebTest(Base):
    """An approval waiting for the runner or the cap (threat 28) is shown, so a tap never
    seems lost. Found on 2026-10-16 when the page went blank after two approvals."""

    def at(self, age):
        """A runner.log time `age` seconds before the test clock."""
        return datetime.fromtimestamp(self.clock() - age, timezone.utc).isoformat(
            timespec="seconds")

    def log_runs(self, *ages, continuation=False):
        self.dirs.log.parent.mkdir(parents=True, exist_ok=True)
        with open(self.dirs.log, "a") as f:
            for age in ages:
                e = {"time": self.at(age), "action": "run", "sha256": "0" * 64, "status": "ok"}
                if continuation:
                    e["continuation"] = True
                f.write(json.dumps(e) + "\n")

    def full(self):
        """Soft cap full, an approved first run waiting. Returns its hash."""
        self.log_runs(*[60] * gate.MAX_RUNS)
        gate.store_approved(GOOD, self.dirs, {"julz-sandbox"})
        return gate.sha256(GOOD)

    def run_now(self, item, sha=None, key=None, finish_as="override"):
        if sha is None:
            sha = [q for q in self.state()["queued"] if q["sha256"] == item][0]["override"]["sha256"]
        status, _, data = self.post("/api/begin", {"action": "override", "item": item,
                                                   "sha256": sha})
        if status != 200:
            return status, data
        status, _, data = self.post("/api/finish", {"action": finish_as, "nonce": data["nonce"],
                                                    "credential": (key or self.key).sign(data)})
        return status, data

    def test_a_noted_approval_is_shown_too(self):
        # Threat 93: a note must not hide the approval from the page
        text = gate.approved_text(GOOD, "use port 8080")
        gate.store_approved(text, self.dirs, {"julz-sandbox"})
        q = self.state()["queued"]
        self.assertEqual([x["sha256"] for x in q], [gate.sha256(text)])

    def test_override_offered_only_when_soft_cap_full(self):
        gate.store_approved(GOOD, self.dirs, {"julz-sandbox"})
        self.assertIsNone(self.state()["queued"][0]["override"])
        self.log_runs(*[60] * gate.MAX_RUNS)
        q = self.state()["queued"][0]
        self.assertEqual(q["override"]["text"],
                         f"override: {q['sha256']}\nused: {gate.MAX_RUNS} of {gate.MAX_RUNS}\n")

    def test_cap_survives_a_rotation(self):
        # Threat 53: right after a rotation the runs sit in the archive, not in runner.log
        digest = self.full()
        name = gate.rotate(self.dirs, self.clock(), max_bytes=1)
        arch = self.dirs.logdir / name
        os.utime(arch, (self.clock() - 60, self.clock() - 60))
        q = self.state()["queued"][0]
        self.assertEqual(q["sha256"], digest)
        self.assertEqual(q["override"]["text"],
                         f"override: {digest}\nused: {gate.MAX_RUNS} of {gate.MAX_RUNS}\n")

    def test_no_override_at_ceiling_or_for_continuation(self):
        digest = self.full()
        self.log_runs(*[60] * (gate.HARD_MAX - gate.MAX_RUNS), continuation=True)
        self.assertIsNone(self.state()["queued"][0]["override"])
        self.assertEqual(self.state()["cap"]["hard_slot"], self.at(60 - gate.RUN_WINDOW))
        cont = f"continue: {digest}\nstep: 2\nneed_hash: {'0' * 64}\nanswer: done\n"
        (self.dirs.approved / f"{gate.sha256(cont)}.md").write_text(cont)
        kinds = {q["kind"]: q["override"] for q in self.state()["queued"]}
        self.assertEqual(kinds, {"spec": None, "continue": None})

    def test_continuation_gets_no_run_now(self):
        # Soft cap full, ceiling not: only the first run is offered Run now
        digest = self.full()
        cont = f"continue: {digest}\nstep: 2\nneed_hash: {'0' * 64}\nanswer: done\n"
        (self.dirs.approved / f"{gate.sha256(cont)}.md").write_text(cont)
        offered = {q["kind"]: q["override"] is not None for q in self.state()["queued"]}
        self.assertEqual(offered, {"spec": True, "continue": False})

    def test_signed_run_now_writes_marker(self):
        self.enroll()
        digest = self.full()
        status, data = self.run_now(digest)
        self.assertEqual(status, 200, data)
        self.assertTrue((self.dirs.approved / f"override-{digest}").exists())
        q = self.state()["queued"][0]
        self.assertEqual((q["overridden"], q["override"]), (True, None))
        self.assertIn('"override"', self.dirs.log.read_text())

    def test_other_signatures_cannot_override(self):
        self.enroll()
        digest = self.full()
        self.assertEqual(self.run_now(digest, finish_as="approve")[0], 403)
        self.assertEqual(self.run_now(digest, key=softkeys.SoftKey())[0], 403)
        self.assertFalse((self.dirs.approved / f"override-{digest}").exists())

    def test_run_now_for_unknown_or_changed_item(self):
        self.enroll()
        digest = self.full()
        seen = self.state()["queued"][0]["override"]["sha256"]
        self.assertEqual(self.run_now("0" * 64, sha=seen)[0], 404)
        self.log_runs(60)  # one more run since the page showed the count
        self.assertEqual(self.run_now(digest, sha=seen)[0], 409)
        self.assertFalse((self.dirs.approved / f"override-{digest}").exists())

    def test_nothing_queued(self):
        s = self.state()
        self.assertEqual(s["queued"], [])
        self.assertEqual(s["cap"], {"used": 0, "max": gate.MAX_RUNS, "all": 0,
                                    "hard": gate.HARD_MAX, "next_slot": None,
                                    "hard_slot": None})

    def test_approved_spec_and_continuation_shown_oldest_first(self):
        gate.store_approved(GOOD, self.dirs, {"julz-sandbox"})
        root = gate.sha256(GOOD)
        os.utime(self.dirs.approved / f"{root}.md", (100, 100))
        self.dirs.ensure()  # publish makes only what it writes now
        (self.dirs.done / f"{root}.md").write_text(GOOD)
        cont = f"continue: {root}\nstep: 3\nneed_hash: {'0' * 64}\nanswer: teal\n"
        (self.dirs.approved / f"{gate.sha256(cont)}.md").write_text(cont)
        q = self.state()["queued"]
        self.assertEqual([(x["sha256"], x["goal"], x["step"]) for x in q],
                         [(root, "add a usage line to the README", 1),
                          (gate.sha256(cont), "add a usage line to the README", 3)])
        self.assertNotIn("teal", json.dumps(q))  # the answer stays off the page list

    def test_at_most_three_and_garbage_skipped(self):
        self.dirs.ensure()
        for i in range(5):
            text = GOOD.replace("README", f"README {i}")
            (self.dirs.approved / f"{gate.sha256(text)}.md").write_text(text)
        (self.dirs.approved / "notes.md").write_text(GOOD)
        self.assertEqual(len(self.state()["queued"]), web.MAX_SHOWN)

    def test_cap_full_names_next_slot(self):
        # 10 runs, the oldest 100 minutes ago: the next slot is when it is 2 hours old
        self.log_runs(100 * 60, *[60] * (gate.MAX_RUNS - 1))
        cap = self.state()["cap"]
        self.assertEqual((cap["used"], cap["max"]), (gate.MAX_RUNS, gate.MAX_RUNS))
        self.assertEqual(cap["next_slot"], self.at(100 * 60 - gate.RUN_WINDOW))

    def test_cap_not_full_has_no_slot(self):
        self.log_runs(gate.RUN_WINDOW + 60, *[60] * (gate.MAX_RUNS - 1))
        self.assertEqual(self.state()["cap"]["next_slot"], None)
        self.assertEqual(self.state()["cap"]["used"], gate.MAX_RUNS - 1)


class DeviceKeepWebTest(DeviceBase):
    """131: a Keep signed with the device key logs the device, not "phone"."""

    def setUp(self):
        super().setUp()
        self.root = gate.sha256(GOOD)
        work = Path(self.tmp.name) / "work" / self.root
        work.mkdir(parents=True)
        (work / "guide.md").write_text("# Guide\n")
        project = Path(self.tmp.name) / "project"
        project.mkdir()
        gate.save_task(self.dirs, {"root": self.root, "project": "julz-sandbox",
                                   "goal": "write a guide", "step": 1, "status": "done"})
        self.dirs.ensure()
        web.keep.write_manifest(self.dirs.manifests,
                                web.keep.build_manifest(project, work, self.root))

    def test_device_keep_logs_the_device(self):
        sha = self.state()["keeps"][0]["sha256"]
        status, _, begun = self.post("/api/begin", {"action": "keep", "root": self.root, "sha256": sha,
                                                    "topic": "network-plus", "pick": ["guide.md"],
                                                    "via": "device"})
        self.assertEqual(status, 200, begun)
        status, _, data = self.post("/api/finish", {"action": "keep", "nonce": begun["nonce"],
                                                    "signature": self.sign(begun)})
        self.assertEqual(status, 200, data)
        e = [json.loads(l) for l in self.dirs.log.read_text().splitlines()][-1]
        self.assertEqual((e["action"], e["reason"]), ("keep-signed", f"device {self.fingerprint}"))


class KeepWebTest(Base):
    """Threats 55, 57, 60 on the page: a Keep card, signed with only the topic from the page."""

    def setUp(self):
        super().setUp()
        self.enroll()
        self.root = gate.sha256(GOOD)
        work = Path(self.tmp.name) / "work" / self.root
        work.mkdir(parents=True)
        (work / "guide.md").write_text("# Guide\n")
        (work / "more.md").write_text("# More\n")
        (work / "bad.md").write_text("![x](https://evil.net/?q=1)\n")
        project = Path(self.tmp.name) / "project"
        project.mkdir()
        gate.save_task(self.dirs, {"root": self.root, "project": "julz-sandbox",
                                   "goal": "write a guide", "step": 1, "status": "done"})
        self.dirs.ensure()
        web.keep.write_manifest(self.dirs.manifests,
                                web.keep.build_manifest(project, work, self.root))

    def card(self):
        return self.state()["keeps"][0]

    ALL = ["guide.md", "more.md"]

    def keep_act(self, topic="network-plus", sha=None, finish="keep", begin="keep", pick=None,
                 **extra):
        if sha is None:
            sha = self.card()["sha256"]
        status, _, data = self.post("/api/begin", {"action": begin, "root": self.root,
                                                   "sha256": sha, "topic": topic,
                                                   "pick": self.ALL if pick is None else pick,
                                                   **extra})
        if status != 200:
            return status, data
        status, _, reply = self.post("/api/finish", {"action": finish, "nonce": data["nonce"],
                                                     "credential": self.key.sign(data)})
        return status, reply

    def marker(self):
        return self.dirs.keep / self.root

    def test_card_shows_kept_and_rejected_files(self):
        c = self.card()
        self.assertEqual(c["root"], self.root)
        self.assertEqual(c["files"], [{"path": "guide.md", "size": 8}, {"path": "more.md", "size": 7}])
        self.assertEqual(c["rejected"], [{"path": "bad.md", "reason": "markdown image"}])

    def test_keep_writes_the_server_built_text(self):
        sha = self.card()["sha256"]
        status, reply = self.keep_act(text="keep: evil\n")  # extra page fields are ignored
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.marker().read_text(),
                         web.keep.keep_text(self.root, "network-plus", sha, self.ALL))
        self.assertEqual(self.state()["keeps"], [])  # pending: no second card

    def test_state_lists_used_topics(self):
        self.assertEqual(self.state()["topics"], [])
        gate.save_task(self.dirs, {"root": "b" * 64, "status": "done", "kept": 1.0,
                                   "topic": "network-plus"})
        self.assertEqual(self.state()["topics"], ["network-plus"])

    def test_pick_signed_in_manifest_order(self):
        sha = self.card()["sha256"]
        status, reply = self.keep_act(pick=["more.md"])
        self.assertEqual(status, 200, reply)
        self.assertEqual(self.marker().read_text(),
                         web.keep.keep_text(self.root, "network-plus", sha, ["more.md"]))

    def test_page_order_does_not_matter(self):
        sha = self.card()["sha256"]
        self.assertEqual(self.keep_act(pick=["more.md", "guide.md"])[0], 200)
        self.assertIn("pick: guide.md more.md\n", self.marker().read_text())

    def test_bad_picks_refused_before_signing(self):
        for pick in ([], ["bad.md"], ["../x.md"], ["guide.md", "guide.md"], "guide.md",
                     [5], [["guide.md"]], ["guide.md more.md"]):  # a list in a list: no 500
            with self.subTest(pick=pick):
                status, _ = self.keep_act(pick=pick)
                self.assertEqual(status, 400)
        self.assertFalse(self.marker().exists())

    def test_bad_topics_refused_before_signing(self):
        for topic in ("../x", "net\nfiles: 9", "A", "", None, 5, "a" * 41):
            with self.subTest(topic=topic):
                status, _ = self.keep_act(topic=topic)
                self.assertEqual(status, 400)
        self.assertFalse(self.marker().exists())

    def test_changed_manifest_refused(self):
        status, _ = self.keep_act(sha="0" * 64)
        self.assertEqual(status, 409)
        self.assertFalse(self.marker().exists())

    def test_unknown_task_refused(self):
        status, _, _ = self.post("/api/begin", {"action": "keep", "root": "b" * 64,
                                                "sha256": self.card()["sha256"],
                                                "topic": "x"})
        self.assertEqual(status, 404)

    def test_other_action_signature_refused(self):
        status, _ = self.keep_act(finish="approve")
        self.assertEqual(status, 403)
        self.assertFalse(self.marker().exists())

    def test_keep_twice_refused(self):
        self.assertEqual(self.keep_act()[0], 200)
        status, _ = self.keep_act(sha=gate.sha256("x"))
        self.assertEqual(status, 404)

    def test_no_assertion_no_marker(self):
        _, _, data = self.post("/api/begin", {"action": "keep", "root": self.root,
                                              "sha256": self.card()["sha256"], "topic": "x",
                                              "pick": self.ALL})
        status, _, _ = self.post("/api/finish", {"action": "keep", "nonce": data["nonce"],
                                                 "credential": {"id": "x"}})
        self.assertEqual(status, 403)
        self.assertFalse(self.marker().exists())


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
