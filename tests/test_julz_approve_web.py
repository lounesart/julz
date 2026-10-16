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
