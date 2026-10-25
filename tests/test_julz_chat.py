"""Tests for julz-chat.py, the gateway between the phone's native chat and Open WebUI
(SECURITY.md 136, 137). A fake Open WebUI records every call; nothing touches the real one.
Run: python3 -m unittest discover -s tests -v"""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from test_julz_notify import load

chat = load("julz_chat", "julz-chat.py")
ROOT = Path(__file__).resolve().parent.parent
TOKEN = "tk_" + "a" * 29
HOST = "laptop.example.ts.net:8445"
C1 = "079fc63a-254e-4d72-a889-93580cfd574a"
C2 = "cd1bdfc7-d247-4877-9433-73afc0bcd008"
OTHER = "11111111-2222-3333-4444-555555555555"


def msg(id_, role, content, parent=None, done=True, **extra):
    return {"id": id_, "role": role, "content": content, "parentId": parent, "done": done,
            "timestamp": 1792360000, "childrenIds": [], **extra}


class FakeOwui:
    """Open WebUI as julz-chat sees it: a few chats of mine, completions that start a task."""

    def __init__(self):
        self.calls = []
        u1, a1 = "u1000000-0000-0000-0000-000000000000", "a1000000-0000-0000-0000-000000000000"
        self.chats = {
            C1: {"id": C1, "title": "DHCP", "updated_at": 1792360000,
                 "chat": {"history": {"currentId": a1, "messages": {
                     u1: msg(u1, "user", "what is DORA"),
                     a1: msg(a1, "assistant", "Discover, Offer, Request, Ack", u1,
                             output=[{"type": "function_call_output", "output": "SECRET NOTE"}])}}}},
            C2: {"id": C2, "title": "Empty", "updated_at": 1792350000,
                 "chat": {"history": {"currentId": None, "messages": {}}}},
        }
        self.fail = None
        self.toggles = 0

    def __call__(self, method, path, data=None):
        self.calls.append((method, path, data))
        if self.fail:
            raise chat.UpstreamError(self.fail)
        if method == "GET" and path.startswith("/api/v1/chats/?page="):
            return [{"id": c["id"], "title": c["title"], "updated_at": c["updated_at"]}
                    for c in self.chats.values() if not c.get("archived")]
        if method == "GET" and path.startswith("/api/v1/chats/archived?page="):
            return [{"id": c["id"], "title": c["title"], "updated_at": c["updated_at"], "archived": True}
                    for c in self.chats.values() if c.get("archived")]
        if method == "POST" and path.endswith("/archive"):
            c = self.chats[path.split("/")[4]]
            c["archived"] = not c.get("archived", False)  # 0.11.4: a toggle
            self.toggles += 1
            return {"id": c["id"], "archived": c["archived"]}
        if method == "DELETE" and path.startswith("/api/v1/chats/"):
            cid = path.rsplit("/", 1)[1]
            if cid not in self.chats:
                raise chat.UpstreamError(404)
            del self.chats[cid]
            return True
        if method == "GET" and path.startswith("/api/v1/chats/"):
            cid = path.rsplit("/", 1)[1]
            if cid not in self.chats:
                raise chat.UpstreamError(401)
            return json.loads(json.dumps(self.chats[cid]))
        if method == "POST" and path == "/api/chat/completions":
            cid = data.get("chat_id") or "99999999-9999-4999-8999-999999999999"
            um, am = data["user_message"], data["id"]
            c = self.chats.setdefault(cid, {"id": cid, "title": "New Chat", "updated_at": 1,
                                            "chat": {"history": {"currentId": None, "messages": {}}}})
            h = c["chat"]["history"]
            h["messages"].setdefault(um["id"], {**um})
            h["messages"][am] = msg(am, "assistant", "", um["id"], done=False, timestamp=um["timestamp"])
            h["currentId"] = am
            return {"status": True, "task_ids": ["t1"], "chat_id": cid}
        if method == "POST" and path.startswith("/api/tasks/chat/"):
            return {"status": True}
        raise AssertionError(f"unexpected upstream call {method} {path}")

    def finish(self, cid, text="done answer"):
        h = self.chats[cid]["chat"]["history"]
        h["messages"][h["currentId"]].update(content=text, done=True)


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.owui = FakeOwui()
        self.clock = Clock()
        self.app = chat.App(TOKEN, {HOST, "127.0.0.1:8766"}, self.owui, clock=self.clock)

    def req(self, method, target, body=None, token=TOKEN, host=HOST, **headers):
        h = {"Host": host, **headers}
        if token is not None:
            h["Authorization"] = f"Bearer {token}"
        raw = b""
        if body is not None:
            raw = body if isinstance(body, bytes) else json.dumps(body).encode()
            h.setdefault("Content-Type", "application/json")
        status, out_headers, out = self.app.handle(method, target, h, raw)
        return status, json.loads(out), out_headers

    def listed(self):
        self.assertEqual(self.req("GET", "/api/chats")[0], 200)
        self.owui.calls.clear()

    def upstream_paths(self):
        return [(m, p) for m, p, _ in self.owui.calls]


class AuthTest(Base):
    def test_right_token_and_host(self):
        status, data, headers = self.req("GET", "/api/chats")
        self.assertEqual(status, 200)
        self.assertEqual([c["id"] for c in data["chats"]], [C1, C2])
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_missing_or_wrong_token_never_reaches_open_webui(self):
        for token in (None, "", TOKEN + "x", TOKEN[:-1], "tk_" + "b" * 29, TOKEN.upper()):
            self.assertEqual(self.req("GET", "/api/chats", token=token)[0], 401, token)
        for auth in (TOKEN, f"Basic {TOKEN}", f"Digest {TOKEN}", f"Bearer-{TOKEN}", f"bearer{TOKEN}", f"Bearer  {TOKEN}", f"Bearer {TOKEN} "):
            status, _, _ = self.app.handle("GET", "/api/chats", {"Host": HOST, "Authorization": auth}, b"")
            self.assertEqual(status, 401, auth)
        self.assertEqual(self.owui.calls, [])

    def test_wrong_host_is_refused_first(self):
        for host in ("evil.example", "127.0.0.1:3100", "", HOST + ".evil"):
            self.assertEqual(self.req("GET", "/api/chats", host=host)[0], 421, host)
        self.assertEqual(self.owui.calls, [])

    def test_any_origin_is_refused(self):
        # The app sends none; a page in a browser always does
        for origin in ("https://" + HOST, "null", "https://evil.example"):
            self.assertEqual(self.req("GET", "/api/chats", Origin=origin)[0], 403, origin)
        self.assertEqual(self.owui.calls, [])

    def test_a_short_token_is_refused_at_start(self):
        for bad in ("", "short", "tk_" + "a" * 10):
            with self.assertRaises(ValueError):
                chat.App(bad, {HOST}, self.owui)


class RoutesTest(Base):
    def test_only_the_listed_routes(self):
        self.listed()
        for method, target in (("GET", "/api/v1/chats/"), ("POST", "/api/chats/all"),
                               ("DELETE", "/api/chats/all"), ("GET", f"/api/chats/{C1}/share"),
                               ("POST", "/api/chat/completions"), ("GET", "/api/models"),
                               ("GET", "/"), ("PUT", "/api/chats"), ("GET", f"/api/chats/{C1}/x"),
                               ("POST", f"/api/chats/{C1}/delete"), ("GET", "/api/chats/../v1/users")):
            status = self.req(method, target, {} if method != "GET" else None)[0]
            self.assertIn(status, (404, 405), (method, target))
        self.assertEqual(self.owui.calls, [])

    def test_wrong_method_on_a_real_route_is_405(self):
        self.listed()
        self.assertEqual(self.req("DELETE", "/api/chats")[0], 405)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}", {})[0], 405)
        self.assertEqual(self.req("GET", f"/api/chats/{C1}/messages")[0], 405)

    def test_page_numbers(self):
        self.assertEqual(self.req("GET", "/api/chats?page=3")[0], 200)
        self.assertEqual(self.owui.calls[-1][1], "/api/v1/chats/?page=3")
        for page in ("0", "-1", "21", "x", "1&x=2", "", "1e2", "٣"):
            self.assertEqual(self.req("GET", f"/api/chats?page={page}")[0], 400, page)
        self.assertEqual(self.req("GET", "/api/chats?other=1")[0], 400)

    def test_errors_never_carry_details(self):
        self.owui.fail = 500
        status, data, _ = self.req("GET", "/api/chats")
        self.assertEqual((status, data), (502, {"error": "Open WebUI"}))


class UpstreamPathsTest(unittest.TestCase):
    """The client itself refuses any Open WebUI path off its list, whatever calls it."""

    def test_allowed(self):
        for m, p in (("GET", "/api/v1/chats/?page=1"), ("GET", "/api/v1/chats/?page=20"),
                     ("GET", f"/api/v1/chats/{C1}"), ("POST", "/api/chat/completions"),
                     ("POST", f"/api/tasks/chat/{C1}/stop")):
            self.assertTrue(chat.upstream_allowed(m, p), (m, p))
        for m, p in (("GET", "/api/v1/chats/archived?page=1"), ("POST", f"/api/v1/chats/{C1}/archive"),
                     ("DELETE", f"/api/v1/chats/{C1}")):
            self.assertTrue(chat.upstream_allowed(m, p), (m, p))

    def test_refused(self):
        for m, p in (("POST", "/api/v1/chats/archive/all"), ("POST", "/api/v1/chats/unarchive/all"),
                     ("DELETE", "/api/v1/chats/share/all"), ("POST", f"/api/v1/chats/{C1}/clone"),
                     ("POST", f"/api/v1/chats/{C1}/pin"), ("DELETE", f"/api/v1/chats/{C1}/messages/x"),
                     ("GET", "/api/v1/chats/all/archived"), ("GET", "/api/v1/chats/archived?page=21"),
                     ("DELETE", f"/api/v1/chats/{C1}/share"), ("DELETE", "/api/v1/chats/"),
                     ("POST", f"/api/v1/chats/{C1}/share"), ("POST", "/api/v1/chats/import"),
                     ("GET", "/api/v1/chats/all"), ("GET", "/api/v1/chats/all/db"),
                     ("POST", f"/api/v1/chats/{C1}"), ("GET", f"/api/v1/chats/{C1}/tags"),
                     ("GET", "/api/v1/chats/?page=1&x=1"), ("GET", "/api/v1/users/"),
                     ("GET", "/api/chat/completions"), ("POST", "/api/tasks/stop/x"),
                     ("POST", f"/api/tasks/chat/{C1}"), ("GET", f"/api/v1/chats/{C1}/../../users"),
                     ("GET", f"/api/v1/chats/{C1.upper()}"), ("GET", "/api/v1/chats/?page=100")):
            self.assertFalse(chat.upstream_allowed(m, p), (m, p))

    def test_the_client_checks_before_any_socket(self):
        up = chat.Upstream("sk-test", base="http://127.0.0.1:9")  # nothing listens on 9
        with self.assertRaises(chat.UpstreamError) as e:
            up("DELETE", "/api/v1/chats/")
        self.assertEqual(e.exception.status, 0)


class IdsTest(Base):
    def test_a_chat_not_listed_is_not_opened(self):
        self.assertEqual(self.req("GET", f"/api/chats/{C1}")[0], 404)
        self.assertEqual(self.owui.calls, [])
        self.listed()
        self.assertEqual(self.req("GET", f"/api/chats/{C1}")[0], 200)

    def test_wrong_shape_is_refused(self):
        self.listed()
        for cid in (C1.upper(), C1[:-1], C1 + "0", "x" * 36, "local:abc", "..", "%2e%2e", C1.replace("-", "")):
            self.assertEqual(self.req("GET", f"/api/chats/{cid}")[0], 404, cid)
            self.assertEqual(self.req("POST", f"/api/chats/{cid}/messages", {"text": "hi"})[0], 404, cid)
        self.assertEqual(self.owui.calls, [])

    def test_send_and_stop_need_a_listed_chat(self):
        self.assertEqual(self.req("POST", f"/api/chats/{OTHER}/messages", {"text": "hi"})[0], 404)
        self.assertEqual(self.req("POST", f"/api/chats/{OTHER}/stop", {})[0], 404)
        self.assertEqual(self.owui.calls, [])

    def test_a_badly_shaped_id_from_open_webui_is_not_listed(self):
        self.owui.chats["../v1/users"] = {"id": "../v1/users", "title": "x", "updated_at": 1, "chat": {}}
        data = self.req("GET", "/api/chats")[1]
        self.assertEqual([c["id"] for c in data["chats"]], [C1, C2])
        self.assertNotIn("../v1/users", self.app.known)

    def test_a_new_chat_is_known_afterwards(self):
        status, data, _ = self.req("POST", "/api/chats", {"text": "hello"})
        self.assertEqual(status, 200)
        self.assertEqual(self.req("GET", f"/api/chats/{data['chat']}")[0], 200)


class ViewTest(Base):
    def test_a_chat_shows_the_branch_and_no_tool_output(self):
        self.listed()
        status, data, _ = self.req("GET", f"/api/chats/{C1}")
        self.assertEqual(status, 200)
        self.assertEqual(data["title"], "DHCP")
        self.assertFalse(data["busy"])
        self.assertEqual([(m["role"], m["text"]) for m in data["messages"]],
                         [("user", "what is DORA"), ("assistant", "Discover, Offer, Request, Ack")])
        self.assertEqual(set(data), {"id", "title", "busy", "archived", "mode", "messages"})
        for m in data["messages"]:
            self.assertEqual(set(m) - {"error"}, {"id", "role", "text", "done", "time"})
        self.assertNotIn("SECRET NOTE", json.dumps(data))

    def test_only_the_current_branch(self):
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"]["x"] = msg("x", "assistant", "an old regenerated answer", "u1000000-0000-0000-0000-000000000000")
        data = self.req("GET", f"/api/chats/{C1}")[1]
        self.assertNotIn("an old regenerated answer", json.dumps(data))

    def test_roles_other_than_user_and_assistant_are_dropped(self):
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        a1 = h["currentId"]
        h["messages"]["s"] = msg("s", "system", "SYSTEM PROMPT", a1)
        h["currentId"] = "s"
        data = self.req("GET", f"/api/chats/{C1}")[1]
        self.assertNotIn("SYSTEM PROMPT", json.dumps(data))

    def test_a_loop_in_the_tree_ends(self):
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        u1 = "u1000000-0000-0000-0000-000000000000"
        h["messages"][u1]["parentId"] = h["currentId"]
        status, data, _ = self.req("GET", f"/api/chats/{C1}")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["messages"]), 2)

    def test_last_and_error(self):
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"][h["currentId"]]["error"] = {"content": "model crashed"}
        status, data, _ = self.req("GET", f"/api/chats/{C1}/last")
        self.assertEqual(status, 200)
        self.assertEqual(data["text"], "Discover, Offer, Request, Ack")
        self.assertEqual(data["error"], "model crashed")
        self.assertTrue(data["done"])

    def test_a_list_keeps_only_what_the_phone_needs(self):
        self.owui.chats[C1]["secret"] = "x"
        data = self.req("GET", "/api/chats")[1]
        self.assertEqual(set(data["chats"][0]), {"id", "title", "updated"})


class SendTest(Base):
    def completion(self):
        posts = [d for m, p, d in self.owui.calls if p == "/api/chat/completions"]
        self.assertEqual(len(posts), 1)
        return posts[0]

    def test_a_new_chat(self):
        status, data, _ = self.req("POST", "/api/chats", {"text": "hello Julz"})
        self.assertEqual(status, 200)
        body = self.completion()
        self.assertIsNone(body["parent_id"])
        self.assertNotIn("chat_id", body)
        self.assertEqual(body["messages"], [{"role": "user", "content": "hello Julz"}])
        self.assertEqual(body["user_message"]["content"], "hello Julz")
        self.assertEqual(body["user_message"]["role"], "user")
        self.assertEqual(data["chat"], "99999999-9999-4999-8999-999999999999")
        self.assertEqual(data["message"], body["id"])

    def test_a_follow_up_takes_its_history_and_parent_from_the_stored_chat(self):
        self.listed()
        status, _, _ = self.req("POST", f"/api/chats/{C1}/messages", {"text": "and DHCP relay?"})
        self.assertEqual(status, 200)
        body = self.completion()
        a1 = "a1000000-0000-0000-0000-000000000000"
        self.assertEqual(body["chat_id"], C1)
        self.assertEqual(body["parent_id"], a1)
        self.assertEqual(body["user_message"]["parentId"], a1)
        self.assertEqual(body["messages"], [{"role": "user", "content": "what is DORA"},
                                            {"role": "assistant", "content": "Discover, Offer, Request, Ack"},
                                            {"role": "user", "content": "and DHCP relay?"}])

    def test_history_is_trimmed_by_size_newest_kept(self):
        # A chat past julz's num_ctx 8192 lost the start of a quiz and cut her answer (26k): the
        # oldest turns go first, the newest and my new message always stay
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        parent = h["currentId"]
        for i in range(40):
            u, a = f"u{i}", f"a{i}"
            h["messages"][u] = msg(u, "user", f"question {i} " + "x" * 600, parent)
            h["messages"][a] = msg(a, "assistant", f"answer {i} " + "y" * 600, u)
            parent = a
        h["currentId"] = parent
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "and now?"})
        body = self.completion()
        sent = body["messages"]
        self.assertLessEqual(sum(len(m["content"]) for m in sent), chat.MAX_HISTORY_CHARS + len("and now?"))
        self.assertEqual(sent[-1], {"role": "user", "content": "and now?"})
        self.assertTrue(sent[-2]["content"].startswith("answer 39"))
        self.assertTrue(sent[0]["content"].startswith("question"))  # starts on my turn, not mid pair
        self.assertNotIn("what is DORA", [m["content"] for m in sent])

    def test_the_trimmed_history_starts_on_my_message(self):
        # The cut lands on an answer: an answer without its question would mislead her
        msgs = [{"role": "user", "content": "q" * 9000}, {"role": "assistant", "content": "a" * 5000},
                {"role": "user", "content": "u" * 100}]
        out = chat.App.turns(msgs)
        self.assertEqual([m["role"] for m in out], ["user"])
        self.assertEqual(out[0]["content"], "u" * 100)

    def test_one_huge_last_answer_still_leaves_my_message(self):
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"][h["currentId"]]["content"] = "z" * (chat.MAX_HISTORY_CHARS * 2)
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "short?"})
        sent = self.completion()["messages"]
        self.assertEqual(sent[-1], {"role": "user", "content": "short?"})
        self.assertLessEqual(sum(len(m["content"]) for m in sent), chat.MAX_HISTORY_CHARS + len("short?"))

    def test_the_request_is_built_here_whatever_the_phone_sends(self):
        self.listed()
        for extra in ({"model": "julz-pro:latest"}, {"tool_ids": ["evil"]}, {"parent": "x"},
                      {"features": {"web_search": True}}, {"chat_id": OTHER}, {"files": []}):
            self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi", **extra})[0], 400, extra)
        self.assertEqual(self.owui.calls, [])
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi"})
        body = self.completion()
        self.assertEqual(body["model"], "julz:latest")
        self.assertEqual(body["tool_ids"], list(chat.TOOLS))
        self.assertEqual(body["features"], {})
        self.assertNotIn("files", body)
        self.assertNotIn("tool_servers", body)
        self.assertTrue(body["stream"])
        self.assertTrue(body["session_id"])

    @unittest.skipUnless((ROOT / "SECURITY.md").exists(), "the threat model is private, not in a clone")
    def test_tool_list_matches_security_md(self):
        row = next(l for l in (ROOT / "SECURITY.md").read_text().splitlines() if l.startswith("| 137 "))
        listed = re.search(r"v1: ([a-z_, ]+), the three", row).group(1)
        self.assertEqual(tuple(t.strip() for t in listed.split(",")), chat.TOOLS)

    def test_text_checks(self):
        self.listed()
        for text in ("", "   ", "\n", "a\x00b", None, 5, ["hi"], "x" * (chat.MAX_TEXT + 1)):
            self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": text})[0], 400, repr(text)[:20])
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {})[0], 400)
        self.assertEqual(self.owui.calls, [])
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "x" * chat.MAX_TEXT})[0], 200)

    def test_body_checks(self):
        self.listed()
        path = f"/api/chats/{C1}/messages"
        self.assertEqual(self.req("POST", path, b"not json")[0], 400)
        self.assertEqual(self.req("POST", path, b"[1]")[0], 400)
        self.assertEqual(self.req("POST", path, {"text": "hi"}, **{"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.req("POST", path, b"{" + b" " * chat.MAX_BODY + b"}")[0], 413)
        self.assertEqual(self.owui.calls, [])

    def test_one_answer_at_a_time(self):
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "one"})[0], 200)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "two"})[0], 409)
        self.assertEqual(self.req("POST", "/api/chats", {"text": "three"})[0], 409)
        self.owui.finish(C1)
        self.assertEqual(self.req("POST", "/api/chats", {"text": "four"})[0], 200)

    def test_a_stuck_answer_frees_the_slot_after_ten_minutes(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "one"})
        self.clock.t += chat.ANSWER_TIMEOUT - 1
        self.assertEqual(self.req("POST", "/api/chats", {"text": "two"})[0], 409)
        self.clock.t += 2
        self.assertEqual(self.req("POST", "/api/chats", {"text": "two"})[0], 200)

    def test_the_slot_frees_on_time_even_when_the_chat_cannot_be_read(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "one"})
        real = self.owui.__call__

        def reads_fail(method, path, data=None):
            if method == "GET":
                raise chat.UpstreamError(500)
            return real(method, path, data)
        self.app.up = reads_fail
        self.assertEqual(self.req("POST", "/api/chats", {"text": "two"})[0], 409)
        self.clock.t += chat.ANSWER_TIMEOUT
        self.assertEqual(self.req("POST", "/api/chats", {"text": "two"})[0], 200)

    def test_a_chat_still_answering_elsewhere_is_busy(self):
        # Answered from the laptop's web page: its current message is still running
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"][h["currentId"]].update(done=False, timestamp=int(self.clock()) - 60)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi"})[0], 409)
        self.assertTrue(self.req("GET", f"/api/chats/{C1}")[1]["busy"])

    def test_sends_per_hour(self):
        self.listed()
        for i in range(chat.SENDS_PER_HOUR):
            self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": f"m{i}"})[0], 200, i)
            self.owui.finish(C1)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "one more"})[0], 429)
        self.clock.t += 59 * 60
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "still"})[0], 429)
        self.clock.t += 61
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "later"})[0], 200)

    def test_new_chats_per_hour(self):
        for i in range(chat.NEW_PER_HOUR):
            status, data, _ = self.req("POST", "/api/chats", {"text": f"c{i}"})
            self.assertEqual(status, 200, i)
            self.owui.finish(data["chat"])
            self.owui.chats.pop(data["chat"])
        self.assertEqual(self.req("POST", "/api/chats", {"text": "one more"})[0], 429)

    def test_refused_sends_do_not_count(self):
        self.listed()
        for _ in range(chat.SENDS_PER_HOUR + 5):
            self.req("POST", f"/api/chats/{C1}/messages", {"text": ""})
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi"})[0], 200)


    def test_an_answer_in_another_chat_is_refused(self):
        self.listed()
        real = self.owui.__call__

        def swapped(method, path, data=None):
            r = real(method, path, data)
            return {**r, "chat_id": C2} if path == "/api/chat/completions" else r
        self.app.up = swapped
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi"})[0], 502)
        self.assertIsNone(self.app.active)


class StopTest(Base):
    def test_stop_goes_to_that_chat(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "long"})
        self.owui.calls.clear()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/stop", {})[0], 200)
        self.assertEqual([c for c in self.upstream_paths() if c[0] != "GET"], [("POST", f"/api/tasks/chat/{C1}/stop")])

    def test_stopped_before_any_words_is_not_stuck(self):
        # 0.11.4 leaves an answer stopped before its first words at done false (contract, 18 Oct)
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "long"})
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/stop", {})[0], 200)
        view = self.req("GET", f"/api/chats/{C1}")[1]
        self.assertFalse(view["busy"])
        self.assertTrue(view["messages"][-1]["done"])
        self.assertTrue(self.req("GET", f"/api/chats/{C1}/last")[1]["done"])
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "next"})[0], 200)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/stop", {})[0], 200)
        self.assertEqual(self.req("POST", "/api/chats", {"text": "and a new one"})[0], 200)

    def test_an_old_unfinished_answer_does_not_block_its_chat(self):
        # Stopped early from the laptop, or before a restart of julz-chat
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"][h["currentId"]].update(done=False, timestamp=int(self.clock()) - chat.ANSWER_TIMEOUT)
        self.assertFalse(self.req("GET", f"/api/chats/{C1}")[1]["busy"])
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi"})[0], 200)

    def test_stop_takes_no_fields(self):
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/stop", {"all": True})[0], 400)
        self.assertEqual(self.owui.calls, [])


class ArchiveTest(Base):
    def test_archive_twice_stays_archived(self):
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/archive", {})[:2], (200, {"archived": True}))
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/archive", {})[:2], (200, {"archived": True}))
        self.assertEqual(self.owui.toggles, 1)  # the toggle only on a change
        self.assertNotIn(C1, [c["id"] for c in self.req("GET", "/api/chats")[1]["chats"]])

    def test_archived_list_and_unarchive(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/archive", {})
        self.app.known.clear()  # a restart: archived chats become known from their own list
        status, data, _ = self.req("GET", "/api/chats/archived")
        self.assertEqual(status, 200)
        self.assertEqual([c["id"] for c in data["chats"]], [C1])
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/unarchive", {})[:2], (200, {"archived": False}))
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/unarchive", {})[:2], (200, {"archived": False}))
        self.assertEqual(self.owui.toggles, 2)
        self.assertIn(C1, [c["id"] for c in self.req("GET", "/api/chats")[1]["chats"]])

    def test_a_view_says_whether_the_chat_is_archived(self):
        self.listed()
        self.assertFalse(self.req("GET", f"/api/chats/{C1}")[1]["archived"])
        self.req("POST", f"/api/chats/{C1}/archive", {})
        self.assertTrue(self.req("GET", f"/api/chats/{C1}")[1]["archived"])

    def test_no_archive_while_it_answers(self):
        # 0.11.4 stops a chat's running tasks when it is archived: a swipe would cut the answer
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "long"})
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/archive", {})[0], 409)
        self.assertEqual(self.owui.toggles, 0)
        self.owui.finish(C1)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/archive", {})[0], 200)

    def test_archived_pages(self):
        self.assertEqual(self.req("GET", "/api/chats/archived?page=2")[0], 200)
        self.assertEqual(self.owui.calls[-1][1], "/api/v1/chats/archived?page=2")
        self.assertEqual(self.req("GET", "/api/chats/archived?page=21")[0], 400)

    def test_archive_takes_no_fields_and_a_listed_chat(self):
        self.assertEqual(self.req("POST", f"/api/chats/{OTHER}/archive", {})[0], 404)
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/archive", {"all": True})[0], 400)
        self.assertEqual(self.owui.toggles, 0)

    def test_a_wrong_toggle_result_is_an_error(self):
        self.listed()
        real = self.owui.__call__

        def stuck(method, path, data=None):
            r = real(method, path, data)
            return {**r, "archived": False} if path.endswith("/archive") else r
        self.app.up = stuck
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/archive", {})[:2], (502, {"error": "Open WebUI"}))

    def test_archived_takes_get_only(self):
        for method in ("POST", "DELETE", "PUT"):
            self.assertEqual(self.req(method, "/api/chats/archived", {} if method == "POST" else None)[0], 405, method)
        self.assertEqual(self.owui.calls, [])

    def test_archives_per_hour(self):
        self.listed()
        for i in range(chat.ARCHIVES_PER_HOUR):
            self.assertEqual(self.req("POST", f"/api/chats/{C1}/{'archive' if i % 2 == 0 else 'unarchive'}", {})[0], 200, i)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/archive", {})[0], 429)
        self.clock.t += 3601
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/archive", {})[0], 200)


class DeleteTest(Base):
    def test_delete_one(self):
        self.listed()
        self.assertEqual(self.req("DELETE", f"/api/chats/{C1}")[:2], (200, {"deleted": True}))
        self.assertNotIn(C1, self.owui.chats)
        self.assertIn(C2, self.owui.chats)
        self.assertEqual(self.req("GET", f"/api/chats/{C1}")[0], 404)  # forgotten here too
        self.assertNotIn(C1, self.app.known)

    def test_a_refused_delete_keeps_the_chat_known(self):
        self.listed()
        real = self.owui.__call__
        self.app.up = lambda method, path, data=None: False if method == "DELETE" else real(method, path, data)
        self.assertEqual(self.req("DELETE", f"/api/chats/{C1}")[0], 502)
        self.assertIn(C1, self.app.known)

    def test_only_a_listed_chat(self):
        self.assertEqual(self.req("DELETE", f"/api/chats/{C1}")[0], 404)
        self.assertEqual(self.req("DELETE", "/api/chats")[0], 405)
        self.assertEqual(self.req("DELETE", "/api/chats/all")[0], 404)
        self.assertEqual(len(self.owui.chats), 2)

    def test_deletes_per_hour(self):
        for i in range(chat.DELETES_PER_HOUR):
            cid = f"{i:08d}-0000-4000-8000-000000000000"
            self.owui.chats[cid] = {"id": cid, "title": "x", "updated_at": 1, "chat": {"history": {"currentId": None, "messages": {}}}}
        self.owui.chats[OTHER] = {"id": OTHER, "title": "x", "updated_at": 1, "chat": {"history": {"currentId": None, "messages": {}}}}
        self.listed()
        for i in range(chat.DELETES_PER_HOUR):
            self.assertEqual(self.req("DELETE", f"/api/chats/{i:08d}-0000-4000-8000-000000000000")[0], 200, i)
        self.assertEqual(self.req("DELETE", f"/api/chats/{OTHER}")[0], 429)
        self.assertIn(OTHER, self.owui.chats)


class RetryEditTest(Base):
    U1, A1 = "u1000000-0000-0000-0000-000000000000", "a1000000-0000-0000-0000-000000000000"

    def completion(self):
        posts = [d for m, p, d in self.owui.calls if p == "/api/chat/completions"]
        self.assertEqual(len(posts), 1)
        return posts[0]

    def test_retry_answers_my_last_message_again(self):
        self.listed()
        status, data, _ = self.req("POST", f"/api/chats/{C1}/retry", {})
        self.assertEqual(status, 200)
        body = self.completion()
        self.assertEqual(body["chat_id"], C1)
        self.assertEqual(body["parent_id"], self.U1)
        self.assertEqual(body["user_message"]["id"], self.U1)
        self.assertEqual(body["user_message"]["content"], "what is DORA")
        self.assertEqual(body["messages"], [{"role": "user", "content": "what is DORA"}])
        self.assertEqual(body["model"], "julz:latest")
        self.assertEqual(body["tool_ids"], list(chat.TOOLS))
        self.assertNotEqual(data["message"], self.A1)
        h = self.owui.chats[C1]["chat"]["history"]
        self.assertIn(self.A1, h["messages"])  # the old answer stays in Open WebUI

    def test_edit_sends_my_new_words_beside_the_old(self):
        self.listed()
        status, _, _ = self.req("POST", f"/api/chats/{C1}/edit", {"text": "what is DORA in DHCP"})
        self.assertEqual(status, 200)
        body = self.completion()
        self.assertEqual(body["chat_id"], C1)
        self.assertIsNone(body["parent_id"])
        self.assertIsNone(body["user_message"]["parentId"])
        self.assertNotEqual(body["user_message"]["id"], self.U1)
        self.assertEqual(body["messages"], [{"role": "user", "content": "what is DORA in DHCP"}])

    def test_edit_in_a_longer_chat_keeps_the_earlier_turns(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "and relay?"})
        self.owui.finish(C1, "a relay forwards")
        self.owui.calls.clear()
        self.req("POST", f"/api/chats/{C1}/edit", {"text": "and DHCP snooping?"})
        body = self.completion()
        self.assertEqual(body["parent_id"], self.A1)
        self.assertEqual(body["messages"], [{"role": "user", "content": "what is DORA"},
                                            {"role": "assistant", "content": "Discover, Offer, Request, Ack"},
                                            {"role": "user", "content": "and DHCP snooping?"}])

    def test_retry_and_edit_wait_for_a_running_answer(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "x"})
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {})[0], 409)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 409)

    def test_retry_needs_an_answer_and_edit_a_message_of_mine(self):
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C2}/retry", {})[0], 409)
        self.assertEqual(self.req("POST", f"/api/chats/{C2}/edit", {"text": "y"})[0], 409)

    def test_retry_needs_my_message_then_an_answer(self):
        # An answer that never came: the branch ends with my message
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"]["u2"] = msg("u2", "user", "and relay?", h["currentId"])
        h["currentId"] = "u2"
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {})[0], 409)

    def test_edit_only_my_message_at_the_end(self):
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"]["a2"] = msg("a2", "assistant", "more", h["currentId"])
        h["currentId"] = "a2"
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 409)

    def test_fields(self):
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {"model": "julz-pro:latest"})[0], 400)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y", "parent": "x"})[0], 400)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": ""})[0], 400)
        self.assertEqual(self.owui.calls, [])

    def test_they_count_as_sends(self):
        self.listed()
        for i in range(chat.SENDS_PER_HOUR):
            self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {})[0], 200, i)
            self.owui.finish(C1)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {})[0], 429)


class ModeTest(Base):
    """Learning mode (135, SECURITY 151): the phone names a mode, julz-chat owns the words."""

    def completion(self):
        posts = [d for m, p, d in self.owui.calls if p == "/api/chat/completions"]
        self.assertEqual(len(posts), 1)
        return posts[0]

    def test_learn_adds_the_words_to_what_she_reads_only(self):
        # 0.11.4 rebuilds a stored chat's messages from its store: the words go as the regeneration
        # prompt, which it appends after that and never stores
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "what is a VLAN", "mode": "learn"})[0], 200)
        body = self.completion()
        self.assertEqual(body["regeneration_prompt"], chat.MODES["learn"])
        self.assertEqual(body["messages"], [{"role": "user", "content": "what is DORA"},
                                            {"role": "assistant", "content": "Discover, Offer, Request, Ack"},
                                            {"role": "user", "content": "what is a VLAN"}])
        self.assertEqual(body["user_message"]["content"], "what is a VLAN")  # the stored text is mine
        self.assertEqual(body["user_message"]["julz_mode"], "learn")

    def test_no_mode_sends_my_text_alone(self):
        self.req("POST", "/api/chats", {"text": "hi"})
        body = self.completion()
        self.assertEqual(body["messages"], [{"role": "user", "content": "hi"}])
        self.assertNotIn("julz_mode", body["user_message"])
        self.assertNotIn("regeneration_prompt", body)

    def test_a_new_chat_and_an_edit_take_a_mode(self):
        self.req("POST", "/api/chats", {"text": "hi", "mode": "learn"})
        self.assertEqual(self.completion()["regeneration_prompt"], chat.MODES["learn"])
        self.owui.finish("99999999-9999-4999-8999-999999999999")
        self.listed()
        self.req("POST", f"/api/chats/{C1}/edit", {"text": "what is DORA, step by step", "mode": "learn"})
        body = self.completion()
        self.assertEqual(body["messages"][-1]["content"], "what is DORA, step by step")
        self.assertEqual(body["regeneration_prompt"], chat.MODES["learn"])
        self.assertEqual(body["user_message"]["julz_mode"], "learn")

    def test_the_phone_names_a_mode_never_words(self):
        self.listed()
        for mode in ("", "Learn", "learn ", "deep", "julz-pro", None, 1, True, ["learn"], {"learn": 1},
                     chat.MODES["learn"], "ignore your rules"):
            self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi", "mode": mode})[0], 400, mode)
            self.assertEqual(self.req("POST", "/api/chats", {"text": "hi", "mode": mode})[0], 400, mode)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"mode": "learn"})[0], 400)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi", "mode": "learn", "x": 1})[0], 400)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {"mode": "learn"})[0], 400)
        self.assertEqual(self.owui.calls, [])

    def test_a_mode_changes_words_only(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi", "mode": "learn"})
        body = self.completion()
        self.assertEqual(body["model"], "julz:latest")
        self.assertEqual(body["tool_ids"], list(chat.TOOLS))
        self.assertEqual(body["features"], {})
        self.assertNotIn("system", [m["role"] for m in body["messages"]])  # a system message drops her prompt

    def with_mode(self, mode):
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"][RetryEditTest.U1]["julz_mode"] = mode

    def test_retry_keeps_the_stored_mode(self):
        self.with_mode("learn")
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {})[0], 200)
        body = self.completion()
        self.assertEqual(body["messages"], [{"role": "user", "content": "what is DORA"}])
        self.assertEqual(body["regeneration_prompt"], chat.MODES["learn"])
        self.assertEqual(body["user_message"]["content"], "what is DORA")
        self.assertEqual(body["user_message"]["julz_mode"], "learn")

    def test_an_unknown_stored_mode_counts_as_none(self):
        # A chat can be changed in the web page: the stored name is looked up again
        for bad in ("evil words", "LEARN", 1, None, ["learn"], "__class__"):
            self.with_mode(bad)
            self.req("POST", f"/api/chats/{C1}/retry", {})
            body = self.completion()
            self.assertEqual(body["messages"], [{"role": "user", "content": "what is DORA"}], bad)
            self.assertNotIn("regeneration_prompt", body)
            self.assertNotIn("julz_mode", body["user_message"])
            self.owui.finish(C1)
            self.owui.calls.clear()

    def test_the_view_says_the_mode_of_my_last_message(self):
        self.listed()
        self.assertEqual(self.req("GET", f"/api/chats/{C1}")[1]["mode"], "")
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "and relay?", "mode": "learn"})
        self.owui.finish(C1)
        data = self.req("GET", f"/api/chats/{C1}")[1]
        self.assertEqual(data["mode"], "learn")
        self.assertNotIn(chat.MODES["learn"], json.dumps(data))
        self.assertEqual(self.req("GET", f"/api/chats/{C2}")[1]["mode"], "")
        self.with_mode("evil words")
        self.owui.chats[C1]["chat"]["history"]["currentId"] = "a1000000-0000-0000-0000-000000000000"
        self.assertEqual(self.req("GET", f"/api/chats/{C1}")[1]["mode"], "")

    @unittest.skipUnless((ROOT / "SECURITY.md").exists(), "the threat model is private, not in a clone")
    def test_modes_match_security_md(self):
        row = next(l for l in (ROOT / "SECURITY.md").read_text().splitlines() if l.startswith("| 151 "))
        listed = re.search(r"MODES \(v1: ([a-z, ]+)\)", row).group(1)
        self.assertEqual(tuple(m.strip() for m in listed.split(",")), tuple(chat.MODES))


class FilesTest(unittest.TestCase):
    def test_token_and_key_files_must_be_private(self):
        with tempfile.TemporaryDirectory() as d:
            tok, key = Path(d) / "phone-token", Path(d) / "chat.env"
            tok.write_text(TOKEN + "\n")
            key.write_text("OPENWEBUI_API_KEY=sk-abc\n")
            for f in (tok, key):
                os.chmod(f, 0o600)
            self.assertEqual(chat.read_token(tok), TOKEN)
            self.assertEqual(chat.read_key(key), "sk-abc")
            for f, reader in ((tok, chat.read_token), (key, chat.read_key)):
                os.chmod(f, 0o640)
                with self.assertRaises(chat.gate.GateError):
                    reader(f)
                os.chmod(f, 0o600)
            key.write_text("OTHER=1\n")
            with self.assertRaises(chat.gate.GateError):
                chat.read_key(key)


class UnitTest(unittest.TestCase):
    def test_sandboxed_like_the_approver(self):
        unit = (ROOT / "systemd" / "julz-chat.service").read_text()
        for line in ("TemporaryFileSystem=%h:ro", "NoNewPrivileges=yes", "ProtectSystem=strict",
                     "PrivateTmp=yes", "UMask=0077", "%h/.local/lib/julz/current/julz-chat.py"):
            self.assertIn(line, unit)
        self.assertNotRegex(unit, r"(?m)^BindPaths=")  # nothing writable
        binds = " ".join(re.findall(r"(?m)^BindReadOnlyPaths=(.*)$", unit))
        self.assertEqual(sorted(binds.split()), sorted(["%h/.local/lib/julz", "%h/.config/julz/chat.json",
                         "%h/.config/julz/chat.env", "%h/.config/julz/ntfy/phone-token"]))

    def test_deploy_restarts_it(self):
        deploy = load("deploy", "deploy.py")
        self.assertIn("julz-chat.service", deploy.LONG_RUNNING)


if __name__ == "__main__":
    unittest.main()
