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
lang = load("julz_language", "functions/julz_language.py")
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
        self.on_get = None  # what Open WebUI does to a chat between two reads

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
            if self.on_get:
                self.on_get(self.chats[cid]["chat"]["history"])
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
        self.sleeps = []
        self.app = chat.App(TOKEN, {HOST, "127.0.0.1:8766"}, self.owui, clock=self.clock, sleep=self.sleep)

    def sleep(self, s):
        self.sleeps.append(s)
        self.clock.t += s

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
        self.assertEqual(set(data), {"id", "title", "busy", "archived", "mode", "web", "messages"})
        for m in data["messages"]:
            self.assertEqual(set(m) - {"error", "end"}, {"id", "role", "text", "done", "time"})
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


class EndTest(Base):
    """Why an answer ended (26k): 0.11.4 drops Ollama's done_reason and keeps its counters, so
    a full window means cut. Measured 25 Oct: done_reason length came with prompt_eval_count
    plus eval_count equal to num_ctx, cached prefix or not."""

    def end(self, model="julz:latest", usage=None, **extra):
        self.setUp()  # a fresh chat each call: nothing left from the case before
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        a = h["messages"][h["currentId"]]
        a.update(model=model, **extra)
        if usage is not None:
            a["usage"] = usage
        status, data, _ = self.req("GET", f"/api/chats/{C1}/last")
        self.assertEqual(status, 200)  # unknown means left out, never a failed request
        return data.get("end")

    def test_window_reached_is_length(self):
        self.assertEqual(self.end(usage={"prompt_eval_count": 15000, "eval_count": 1384}), "length")
        self.assertEqual(self.end(usage={"prompt_eval_count": 16000, "eval_count": 900}), "length")

    def test_under_the_window_is_stop(self):
        self.assertEqual(self.end(usage={"prompt_eval_count": 15000, "eval_count": 1383}), "stop")
        self.assertEqual(self.end(usage={"prompt_eval_count": 2166, "eval_count": 0}), "stop")

    def test_unknown_is_left_out(self):
        for usage in (None, "x", {}, {"prompt_eval_count": 16384}, {"eval_count": 16384},
                      {"prompt_eval_count": "15000", "eval_count": 1384},
                      {"prompt_eval_count": True, "eval_count": 16384},
                      {"prompt_eval_count": 17000, "eval_count": -1},
                      {"prompt_eval_count": 15000.0, "eval_count": 1384}):
            self.assertIsNone(self.end(usage=usage), usage)
        full = {"prompt_eval_count": 15000, "eval_count": 1384}
        self.assertIsNone(self.end(model="julz-sec:latest", usage=full))
        self.assertIsNone(self.end(model=None, usage=full))
        self.assertIsNone(self.end(usage=full, error={"content": "model crashed"}))
        self.assertIsNone(self.end(usage=full, done=False, timestamp=int(self.clock())))  # running

    def test_the_window_is_the_modelfile(self):
        for line in (ROOT / "modelfiles" / "julz.Modelfile").read_text().splitlines():
            if line.startswith("PARAMETER num_ctx"):
                self.assertEqual(chat.WINDOWS[chat.MODEL], int(line.split()[2]))

    def test_the_task_model_is_julz_without_her_prompt(self):
        # 168: Open WebUI's queries and titles are written by julz-task; her prompt about me
        # must not reach a search engine, and the same base and window let Ollama share one copy
        def params(name):
            text = (ROOT / "modelfiles" / f"{name}.Modelfile").read_text()
            return text, [l for l in text.splitlines() if l.startswith(("FROM ", "PARAMETER num_ctx"))]
        task, julz = params("julz-task"), params("julz")
        self.assertEqual(task[1], julz[1])
        self.assertNotIn("SYSTEM", task[0])
        self.assertNotIn("Arch", task[0])


def kb(name, *files, kind="collection", doc="chunk words"):
    """One stored source as Open WebUI 0.11.4 keeps it (probed 26 Oct, 133c)."""
    return {"source": {"id": "e9f0198c-adbe-401a-a132-23d9c4763623", "name": name, "type": kind},
            "document": [doc] * len(files), "metadata": [{"source": f, "name": f, "file_id": "x"} for f in files]}


class SourcesTest(Base):
    """133c, threat 165: the notes an answer's retrieval found, as vault paths, names only."""

    def sources(self, sources, role="assistant"):
        self.setUp()
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        a = h["messages"][h["currentId"]]
        a["sources"] = sources
        a["role"] = role
        status, data, _ = self.req("GET", f"/api/chats/{C1}/last")
        self.assertEqual(status, 200)  # odd sources are dropped, never a failed request
        return data.get("sources")

    def test_real_shape(self):
        got = self.sources([
            kb("julz-mem", "study__cert-map.md", "study__interview__htb-and-certs.md", "study__cert-map.md"),
            {"source": {"name": "julz_notes/search_notes"}, "document": ["whole note"],
             "metadata": [{"source": "julz_notes/search_notes", "parameters": {}}], "tool_result": True},
            kb("julz-claude", "Claude__cpts__00-cpts-overview.md", "Claude__julz__11-glossary.md")])
        self.assertEqual(got, ["study/cert-map.md", "study/interview/htb-and-certs.md",
                               "Claude/cpts/00-cpts-overview.md", "Claude/julz/11-glossary.md"])

    def test_names_only(self):
        self.setUp()
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"][h["currentId"]]["sources"] = [kb("julz-mem", "study__a.md", doc="SECRET CHUNK")]
        for target in (f"/api/chats/{C1}/last", f"/api/chats/{C1}"):
            raw = self.app.handle("GET", target, {"Host": HOST, "Authorization": f"Bearer {TOKEN}"}, b"")[2]
            self.assertNotIn(b"SECRET", raw)
            self.assertIn(b"study/a.md", raw)

    def test_each_collection_its_own_roots(self):
        self.assertEqual(self.sources([kb("julz-mem", "daily__2026-10-26.md", "Claude__x.md", "Outbox__r.md",
                                          "Inbox__claude__s.md", "feedback__f.md", "top.md")]), ["daily/2026-10-26.md"])
        self.assertIsNone(self.sources([kb("julz-claude", "study__x.md", "daily__y.md", "x.md")]))
        self.assertIsNone(self.sources([kb("other", "study__x.md")]))
        self.assertIsNone(self.sources([kb("julz-mem", "study__x.md", kind="file")]))

    def test_odd_names_dropped(self):
        bad = ["study__..__x.md", "study__a..md", "study__x.txt", "study__x.md\n", "study__x", "study__.x.md",
               "study__a____x.md", "study__a__b__c__d.md", "study__" + "x" * 200 + ".md", "study__x\u200b.md",
               "study__x/y.md", "study__x\\y.md", "study__x\ty.md", "study__x\ny.md", "study.md",
               "study__" + "__".join(["y" * 95] * 3) + ".md", "", 5, None, ["study__x.md"]]
        self.assertIsNone(self.sources([kb("julz-mem", *bad)]))
        self.assertEqual(self.sources([kb("julz-mem", "study__a__b__c.md", "study__тест заметка.md")]),
                         ["study/a/b/c.md", "study/тест заметка.md"])

    def test_odd_shapes_dropped(self):
        for odd in (None, "x", {}, [None], ["x"], [{"source": "x"}], [{"source": {"type": "collection"}}],
                    [{"source": {"type": "collection", "name": "julz-mem"}, "metadata": "x"}],
                    [{"source": {"type": "collection", "name": "julz-mem"}, "metadata": [None, "x", {"name": 3}]}]):
            self.assertIsNone(self.sources(odd), odd)

    def test_at_most_six_and_not_on_mine(self):
        many = [f"study__n{i}.md" for i in range(9)]
        self.assertEqual(self.sources([kb("julz-mem", *many)]), [f"study/n{i}.md" for i in range(6)])
        self.assertIsNone(self.sources([kb("julz-mem", "study__a.md")], role="user"))


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

    def test_retry_waits_for_a_running_answer(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "x"})
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {})[0], 409)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "y"})[0], 409)

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


class EditWhileAnsweringTest(Base):
    """203: an edit while she answers stops that answer, waits for its last write, then sends."""
    U1, A1 = RetryEditTest.U1, RetryEditTest.A1

    def running(self, text="x"):
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": text})[0], 200)
        h = self.owui.chats[C1]["chat"]["history"]
        self.old = h["currentId"]
        self.owui.calls.clear()
        return h

    def writes(self):
        return [(m, p) for m, p in self.upstream_paths() if m != "GET"]

    def test_edit_stops_then_sends_one_new_answer(self):
        h = self.running()
        h["messages"][self.old]["content"] = "half an ans"
        status, data, _ = self.req("POST", f"/api/chats/{C1}/edit", {"text": "and DHCP relay?"})
        self.assertEqual(status, 200)
        self.assertEqual(self.writes(), [("POST", f"/api/tasks/chat/{C1}/stop"), ("POST", "/api/chat/completions")])
        body = [d for m, p, d in self.owui.calls if p == "/api/chat/completions"][0]
        self.assertEqual(body["parent_id"], self.A1)
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "and DHCP relay?"})
        self.assertEqual(h["currentId"], data["message"])
        self.assertIn(self.old, h["messages"])  # the stopped answer stays in Open WebUI
        self.assertTrue(self.req("GET", f"/api/chats/{C1}")[1]["busy"])
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 200)

    def test_it_waits_until_open_webui_marks_it_done(self):
        h = self.running()
        reads = []

        def grow(hist):  # the task writes two more words after the stop, then done
            reads.append(1)
            m = hist["messages"][self.old]
            if self.owui.calls[-1][1] == "/api/chat/completions":
                return
            if any(p.endswith("/stop") for _, p, _ in self.owui.calls):
                m["content"] += " w"
                if len(reads) >= 5:
                    m["done"] = True
        self.owui.on_get = grow
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 200)
        paths = self.upstream_paths()
        done_at = max(i for i, (m, p) in enumerate(paths) if m == "GET")
        self.assertEqual(paths[done_at + 1], ("POST", "/api/chat/completions"))
        self.assertTrue(h["messages"][self.old]["done"])
        self.assertTrue(self.sleeps)

    def test_stopped_before_any_words_it_goes_on_once_nothing_changes(self):
        self.running()  # stays done false with no words, as 0.11.4 leaves it (18 Oct)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 200)
        self.assertGreaterEqual(sum(self.sleeps), 1)
        self.assertLessEqual(sum(self.sleeps), chat.STOP_WAIT)

    def test_an_answer_that_keeps_growing_is_left_alone(self):
        self.running()
        self.owui.on_get = lambda hist: hist["messages"][self.old].update(
            content=hist["messages"][self.old]["content"] + " w")
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 409)
        self.assertNotIn(("POST", "/api/chat/completions"), self.upstream_paths())
        self.assertLessEqual(sum(self.sleeps), chat.STOP_WAIT)

    def test_a_bad_edit_does_not_stop_the_answer(self):
        self.running()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": ""})[0], 400)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y", "parent": "x"})[0], 400)
        self.app.sends.extend([self.clock()] * chat.SENDS_PER_HOUR)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 429)
        self.assertEqual(self.writes(), [])
        self.assertTrue(self.req("GET", f"/api/chats/{C1}")[1]["busy"])

    def test_an_answer_in_another_chat_is_not_stopped(self):
        self.listed()
        self.req("POST", f"/api/chats/{C2}/messages", {"text": "x"})
        self.owui.calls.clear()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 409)
        self.assertEqual(self.writes(), [])

    def test_only_an_answer_to_my_last_message(self):
        # Running at the end of the branch, but my message is not right before it
        h = self.running()
        mine = h["messages"][self.old]["parentId"]
        h["messages"]["a9"] = msg("a9", "assistant", "", self.old, done=False,
                                  timestamp=int(self.clock()))
        h["messages"][self.old]["done"] = True
        h["currentId"] = "a9"
        self.assertNotEqual(mine, None)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/edit", {"text": "y"})[0], 409)
        self.assertEqual(self.writes(), [])


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

    def test_notes_mode_goes_the_same_way(self):
        # 133b: the second mode, only my notes and "not in your notes"
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "what is CPTS", "mode": "notes"})[0], 200)
        body = self.completion()
        self.assertEqual(body["regeneration_prompt"], chat.MODES["notes"])
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "what is CPTS"})
        self.assertEqual(body["user_message"]["julz_mode"], "notes")
        self.assertEqual(body["tool_ids"], list(chat.TOOLS))
        self.owui.finish(C1)
        self.assertEqual(self.req("GET", f"/api/chats/{C1}")[1]["mode"], "notes")

    def test_each_mode_names_itself_for_the_language_filter(self):
        # julz_language finds a mode's turn by "(Name mode, " and takes the language from mine (202)
        for name, words in chat.MODES.items():
            self.assertTrue(lang.is_mode_turn(words), name)
            self.assertNotIn("\n", words, name)

    def test_notes_mode_says_not_in_your_notes(self):
        self.assertIn("That is not in your notes.", chat.MODES["notes"])
        self.assertNotEqual(chat.MODES["notes"], chat.MODES["learn"])

    @unittest.skipUnless((ROOT / "SECURITY.md").exists(), "the threat model is private, not in a clone")
    def test_modes_match_security_md(self):
        row = next(l for l in (ROOT / "SECURITY.md").read_text().splitlines() if l.startswith("| 151 "))
        listed = re.search(r"MODES \(v1: ([a-z, ]+)\)", row).group(1)
        self.assertEqual(tuple(m.strip() for m in listed.split(",")), tuple(chat.MODES))


def web(*pages, queries=("dhcp relay", "dhcp option 82")):
    """One stored web search source as 0.11.4 keeps it (probed 27 Oct, middleware.py files)."""
    urls = [p[0] for p in pages]
    return {"source": {"name": ", ".join(map(str, queries)), "type": "web_search", "urls": urls, "queries": list(queries),
                       "collection_name": "web-search-x"},
            "document": ["page words"] * len(pages),
            "metadata": [{"source": u, "title": t, "description": "d", "language": "en"} for u, t in pages]}


R1 = ("https://en.wikipedia.org/wiki/DHCP_relay", "DHCP relay - Wikipedia")
R2 = ("https://www.rfc-editor.org/rfc/rfc3046", "RFC 3046")


class WebTest(Base):
    """26d, SECURITY 168: a web turn has no tools, a web chat never gets them back, the query
    template sees my message and these words only, links not among the results go plain."""

    def completion(self):
        posts = [d for m, p, d in self.owui.calls if p == "/api/chat/completions"]
        self.assertEqual(len(posts), 1)
        return posts[0]

    def tainted(self, sources=None, **mine):
        """C1 with a web turn stored on its answer (or a mark on my message)."""
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        if sources is not None:
            h["messages"][RetryEditTest.A1]["sources"] = sources
        h["messages"][RetryEditTest.U1].update(mine)
        return h

    def test_a_web_turn_searches_with_no_tools_and_our_words_last(self):
        self.listed()
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "and relay?", "web": True})[0], 200)
        body = self.completion()
        self.assertEqual(body["features"], {"web_search": True})
        self.assertEqual(body["tool_ids"], [])
        # END:2 is mine and these; they quote my message before it, so a follow-up has its topic
        self.assertEqual(body["regeneration_prompt"], chat.web_words("what is DORA"))
        self.assertEqual(body["messages"][-1], {"role": "user", "content": "and relay?"})
        self.assertIs(body["user_message"]["julz_web"], True)
        self.assertNotIn("julz_mode", body["user_message"])

    def test_web_off_or_left_out_is_a_normal_turn(self):
        for extra in ({}, {"web": False}):
            self.setUp()
            self.listed()
            self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi", **extra})
            body = self.completion()
            self.assertEqual(body["features"], {})
            self.assertEqual(body["tool_ids"], list(chat.TOOLS))
            self.assertNotIn("regeneration_prompt", body)
            self.assertNotIn("julz_web", body["user_message"])

    def test_learn_and_web_send_both_words_web_last(self):
        self.req("POST", "/api/chats", {"text": "teach me relay", "mode": "learn", "web": True})
        body = self.completion()
        self.assertEqual(body["regeneration_prompt"], chat.MODES["learn"] + " " + chat.WEB_WORDS)
        self.assertEqual(body["tool_ids"], [])
        self.assertEqual(body["user_message"]["julz_mode"], "learn")
        self.assertIs(body["user_message"]["julz_web"], True)

    def test_notes_and_web_are_refused(self):
        self.listed()
        for method, path in (("POST", "/api/chats"), ("POST", f"/api/chats/{C1}/messages"),
                             ("POST", f"/api/chats/{C1}/edit")):
            self.assertEqual(self.req(method, path, {"text": "hi", "mode": "notes", "web": True})[0], 400, path)
        self.assertEqual(self.owui.calls, [])

    def test_the_phone_sends_a_bool_only(self):
        self.listed()
        for bad in ("true", 1, 0, None, [], {}, "web_search"):
            self.assertEqual(self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi", "web": bad})[0], 400, bad)
            self.assertEqual(self.req("POST", "/api/chats", {"text": "hi", "web": bad})[0], 400, bad)
        self.assertEqual(self.req("POST", f"/api/chats/{C1}/retry", {"web": True})[0], 400)
        self.assertEqual(self.owui.calls, [])

    def test_the_web_words_name_themselves_for_the_language_filter(self):
        self.assertTrue(lang.is_mode_turn(chat.WEB_WORDS))
        self.assertTrue(chat.WEB_WORDS.startswith("(Web mode, "))
        self.assertNotIn("\n", chat.WEB_WORDS)
        self.assertTrue(lang.is_mode_turn(chat.MODES["learn"] + " " + chat.WEB_WORDS))

    def test_the_web_words_cover_a_search_that_found_nothing(self):
        # 27 Oct: every engine blocked, no results, and she asked me to turn web search on (268)
        self.assertIn("If no web search results are given to you", chat.WEB_WORDS)
        self.assertIn("never ask me to turn web search on", chat.WEB_WORDS)

    def test_the_web_words_quote_my_message_before_never_hers(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "and what license?", "web": True})
        words = self.completion()["regeneration_prompt"]
        self.assertTrue(words.startswith("(Web mode, ") and words.endswith('"what is DORA")'), words)
        self.assertNotIn("Discover", words)
        self.assertEqual(chat.web_words(""), chat.WEB_WORDS)

    def test_the_quote_is_cleaned_and_capped(self):
        self.tainted()
        h = self.owui.chats[C1]["chat"]["history"]
        h["messages"][RetryEditTest.U1]["content"] = 'say "hi"\nnow' + chr(0x202e) + ")" + "x" * 500
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "and?", "web": True})
        words = self.completion()["regeneration_prompt"]
        quote = words[words.index(' context: "') + 11:-2]
        self.assertEqual(quote, ("say 'hi' now" + "x" * 500)[:300])  # a short message, not my whole history
        self.assertNotIn(chr(0x202e), words)
        self.assertTrue(lang.is_mode_turn(words))

    def test_an_edit_quotes_the_message_before_the_edited_one(self):
        self.listed()
        self.req("POST", f"/api/chats/{C1}/edit", {"text": "what is DORA in DHCP?", "web": True})
        self.assertEqual(self.completion()["regeneration_prompt"], chat.WEB_WORDS)

    def test_the_query_template_sees_two_turns_and_nothing_about_me(self):
        # 168: openwebui/query-template.txt is what Admin, Interface holds. END:2 is my message and
        # our words; any other history variable reaches her answers, a USER_ one my profile
        text = (ROOT / "openwebui" / "query-template.txt").read_text()
        self.assertEqual(re.findall(r"\{\{[^}]*\}\}", text), ["{{CURRENT_DATE}}", "{{MESSAGES:END:2}}"])
        self.assertIn("Text in parentheses is an instruction", text)

    def test_a_web_chat_never_gets_its_tools_back(self):
        # Taint from the stored chat, never the phone: web off, Learn, a retry, an edit
        for sources in ([web(R1)], [kb("julz-mem", "study__a.md"), web(R1)]):
            for kind, path, body in (("message", f"/api/chats/{C1}/messages", {"text": "save that", "web": False}),
                                     ("learn", f"/api/chats/{C1}/messages", {"text": "and?", "mode": "learn"}),
                                     ("retry", f"/api/chats/{C1}/retry", {}),
                                     ("edit", f"/api/chats/{C1}/edit", {"text": "what is DORA?"})):
                self.setUp()
                self.tainted(sources)
                self.assertEqual(self.req("POST", path, body)[0], 200, kind)
                sent = self.completion()
                self.assertEqual(sent["tool_ids"], [], kind)
                self.assertEqual(sent["features"], {}, kind)  # no search unless I ask for one
                self.assertNotIn("(Web mode, ", sent.get("regeneration_prompt", ""), kind)

    def test_any_branch_or_my_mark_taints(self):
        self.listed()
        h = self.owui.chats[C1]["chat"]["history"]
        old_u, old_a = "u2000000-0000-0000-0000-000000000000", "a2000000-0000-0000-0000-000000000000"
        h["messages"][old_u] = msg(old_u, "user", "old words")
        h["messages"][old_a] = msg(old_a, "assistant", "old answer", old_u, sources=[web(R1)])
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi"})
        self.assertEqual(self.completion()["tool_ids"], [])
        self.setUp()
        self.tainted(julz_web=True)
        self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi"})
        self.assertEqual(self.completion()["tool_ids"], [])

    def test_notes_alone_do_not_taint(self):
        for sources in ([kb("julz-mem", "study__a.md")], [{"source": {"type": "web"}}], None, "x", [None]):
            self.setUp()
            self.tainted(sources if sources is not None else [])
            self.req("POST", f"/api/chats/{C1}/messages", {"text": "hi"})
            self.assertEqual(self.completion()["tool_ids"], list(chat.TOOLS), sources)

    def test_retry_searches_again_only_when_my_message_was_a_web_turn(self):
        self.tainted([web(R1)], julz_web=True)
        self.req("POST", f"/api/chats/{C1}/retry", {})
        body = self.completion()
        self.assertEqual(body["features"], {"web_search": True})
        self.assertEqual(body["regeneration_prompt"], chat.WEB_WORDS)
        self.assertIs(body["user_message"]["julz_web"], True)
        for mark in ("true", 1, None, [True]):
            self.setUp()
            self.tainted(julz_web=mark)
            self.req("POST", f"/api/chats/{C1}/retry", {})
            self.assertEqual(self.completion()["features"], {}, mark)

    def test_the_view_marks_a_web_chat(self):
        self.listed()
        self.assertIs(self.req("GET", f"/api/chats/{C1}")[1]["web"], False)
        self.tainted([web(R1)])
        self.assertIs(self.req("GET", f"/api/chats/{C1}")[1]["web"], True)

    def answer(self, text, sources=None, mine="what is DORA"):
        self.setUp()
        h = self.tainted(sources)
        h["messages"][RetryEditTest.A1]["content"] = text
        h["messages"][RetryEditTest.U1]["content"] = mine
        return self.req("GET", f"/api/chats/{C1}/last")[1]

    def test_links_not_among_the_results_go_plain(self):
        cases = [
            (f"See [relay]({R1[0]}).", f"See [relay]({R1[0]})."),
            (f"See {R1[0]}.", f"See {R1[0]}."),
            ("[x](https://evil.example/?q=DORA)", "[x](hxxps://evil.example/?q=DORA)"),
            ("go to https://evil.example/c?d=secret now", "go to hxxps://evil.example/c?d=secret now"),
            (f"{R1[0]}?q=secret", f"hxxps://{R1[0][8:]}?q=secret"),
            (f"x{R1[0]}/../../evil", f"xhxxps://{R1[0][8:]}/../../evil"),
            ("![p](https://evil.example/p.png)", "![p](hxxps://evil.example/p.png)"),
            ("http://plain.example stays", "http://plain.example stays"),
        ]
        for text, want in cases:
            self.assertEqual(self.answer(text, [web(R1)])["text"], want, text)

    def test_my_own_links_stay(self):
        got = self.answer("Your link https://mine.example/a and https://evil.example/b",
                          [web(R1)], mine="check https://mine.example/a please")
        self.assertEqual(got["text"], "Your link https://mine.example/a and hxxps://evil.example/b")

    def test_a_chat_with_no_web_turn_keeps_its_links(self):
        self.assertEqual(self.answer("See https://evil.example/x")["text"], "See https://evil.example/x")

    def test_every_answer_of_a_web_chat_is_filtered(self):
        # A page's words can live on in her later answers, so the whole chat, the view too
        self.listed()
        h = self.tainted([web(R1)])
        u, a = "u3000000-0000-0000-0000-000000000000", "a3000000-0000-0000-0000-000000000000"
        h["messages"][u] = msg(u, "user", "more", RetryEditTest.A1)
        h["messages"][a] = msg(a, "assistant", f"later https://evil.example/x and {R1[0]}", u)
        h["currentId"] = a
        texts = [m["text"] for m in self.req("GET", f"/api/chats/{C1}")[1]["messages"]]
        self.assertEqual(texts[-1], f"later hxxps://evil.example/x and {R1[0]}")

    def test_the_answer_shows_what_was_searched_and_found(self):
        got = self.answer("ok", [kb("julz-mem", "study__a.md"), web(R1, R2)])
        self.assertEqual(got["searched"], ["dhcp relay", "dhcp option 82"])
        self.assertEqual(got["links"], [
            {"url": R1[0], "host": "en.wikipedia.org", "title": R1[1]},
            {"url": R2[0], "host": "www.rfc-editor.org", "title": R2[1]}])
        self.assertEqual(got["sources"], ["study/a.md"])
        self.assertNotIn("page words", json.dumps(got))

    def test_odd_links_are_dropped_and_titles_cleaned(self):
        got = self.answer("ok", [web(R1, ("http://plain.example/", "t"), ("javascript:alert(1)", "t"),
                                     ("https://user:pw@evil.example/", "t"), ("https://nodot/", "t"),
                                     ("https://evil.example/a b", "t"), ("https://x.example/" + "a" * 2000, "t"),
                                     ("https://xn--80ak6aa92e.com/", "punycode"), ("https://аррӏе.com/", "t"),
                                     ("https://ok.example/", "bad\u202etitle\u200b\n" + "x" * 300), (5, "t"),
                                     (R1[0], "again"))])
        self.assertEqual([l["url"] for l in got["links"]],
                         [R1[0], "https://xn--80ak6aa92e.com/", "https://ok.example/"])
        self.assertEqual(got["links"][1]["host"], "xn--80ak6aa92e.com")  # never the look-alike letters
        self.assertEqual(got["links"][2]["title"], "badtitle " + "x" * (chat.MAX_TITLE - 9))

    def test_at_most_ten_links_and_five_queries(self):
        pages = [(f"https://s{i}.example/", f"t{i}") for i in range(14)]
        got = self.answer("ok", [web(*pages, queries=[f"q{i}" for i in range(8)] + ["", 5, "x" * 300])])
        self.assertEqual(len(got["links"]), 10)
        self.assertEqual(got["searched"], [f"q{i}" for i in range(5)])

    def test_queries_are_cleaned_and_long_ones_dropped(self):
        got = self.answer("ok", [web(R1, queries=["dhcp\u202e relay\u200b\n", "x" * (chat.MAX_QUERY + 1), "dhcp relay", "rfc"])])
        self.assertEqual(got["searched"], ["dhcp relay", "rfc"])

    def test_a_changed_chat_keeps_notes_alone_on_retry(self):
        # Notes and web stored together can only come from the web page: Notes wins, no search
        self.tainted(julz_mode="notes", julz_web=True)
        self.req("POST", f"/api/chats/{C1}/retry", {})
        body = self.completion()
        self.assertEqual(body["features"], {})
        self.assertEqual(body["regeneration_prompt"], chat.MODES["notes"])
        self.assertNotIn("julz_web", body["user_message"])

    def test_odd_web_shapes_are_dropped(self):
        for odd in ([{"source": {"type": "web_search", "queries": "q"}, "metadata": "x"}],
                    [{"source": {"type": "web_search"}, "metadata": [None, 5, {"source": None}]}]):
            got = self.answer("see https://evil.example/", odd)
            self.assertNotIn("links", got)
            self.assertNotIn("searched", got)
            self.assertEqual(got["text"], "see hxxps://evil.example/")  # still a web chat

    def test_no_links_on_my_messages(self):
        self.tainted([web(R1)])
        mine = self.req("GET", f"/api/chats/{C1}")[1]["messages"][0]
        self.assertEqual(mine["role"], "user")
        self.assertNotIn("links", mine)


class WarmTest(Base):
    """260, threat 167: Chat opened loads julz and bge-m3 through two fixed Ollama calls."""

    def setUp(self):
        super().setUp()
        self.ollama_calls, self.jobs = [], []
        self.ollama_fail = None
        self.app = chat.App(TOKEN, {HOST, "127.0.0.1:8766"}, self.owui, clock=self.clock, sleep=self.sleep,
                            ollama=self.ollama, spawn=self.jobs.append)

    def ollama(self, path, data):
        self.ollama_calls.append((path, data))
        if self.ollama_fail:
            raise self.ollama_fail

    def warm(self, body=None, **kw):
        return self.req("POST", "/api/warm", {} if body is None else body, **kw)

    def run_jobs(self):
        while self.jobs:
            self.jobs.pop(0)()

    def test_loads_both_models_with_the_fixed_calls(self):
        status, data, _ = self.warm()
        self.assertEqual((status, data), (200, {"warm": True}))
        self.assertEqual(self.ollama_calls, [])  # in a thread, not in the request
        self.run_jobs()
        self.assertEqual(self.ollama_calls, [  # julz first, so she never pushes bge-m3 out
            ("/api/generate", {"model": "julz:latest", "prompt": "hi", "stream": False,
                               "options": {"num_predict": 1}}),
            ("/api/embed", {"model": "bge-m3:latest", "input": "hi"})])
        self.assertEqual(self.owui.calls, [])

    def test_the_calls_are_the_chat_model_and_carry_no_keep_alive(self):
        self.assertEqual(chat.WARM_CALLS[0][1]["model"], chat.MODEL)
        for _, data in chat.WARM_CALLS:
            self.assertNotIn("keep_alive", data)

    def test_token_and_host_first(self):
        self.assertEqual(self.warm(token=None)[0], 401)
        self.assertEqual(self.warm(token=TOKEN + "x")[0], 401)
        self.assertEqual(self.warm(host="evil.example")[0], 421)
        self.assertEqual(self.warm(Origin="https://evil.example")[0], 403)
        self.assertEqual(self.jobs, [])

    def test_post_with_an_empty_body_only(self):
        for body in ({"text": "rm -rf"}, {"model": "julz-pro"}, {"prompt": "x"}, [], b"not json"):
            self.assertEqual(self.warm(body)[0], 400, body)
        status = self.req("POST", "/api/warm", b"{}", **{"Content-Type": "text/plain"})[0]
        self.assertEqual(status, 415)
        self.assertEqual(self.req("GET", "/api/warm")[0], 405)
        self.assertEqual(self.req("POST", "/api/warm?model=julz-pro", {})[0], 404)
        self.assertEqual(self.req("DELETE", "/api/warm")[0], 405)
        self.assertEqual(self.jobs, [])

    def test_one_a_minute(self):
        self.assertTrue(self.warm()[1]["warm"])
        self.run_jobs()
        self.clock.t += 59
        self.assertEqual(self.warm()[1], {"warm": False})
        self.assertEqual(self.jobs, [])
        self.clock.t += 1
        self.assertTrue(self.warm()[1]["warm"])

    def test_none_while_one_runs(self):
        self.assertTrue(self.warm()[1]["warm"])
        self.clock.t += 300  # the load still running, a slow laptop
        self.assertEqual(self.warm()[1], {"warm": False})
        self.run_jobs()
        self.assertTrue(self.warm()[1]["warm"])

    def test_none_while_she_answers(self):
        self.app.active = (C1, "a1", self.clock.t)
        self.assertEqual(self.warm()[1], {"warm": False})
        self.assertEqual(self.jobs, [])

    def test_a_failed_load_frees_the_next(self):
        self.ollama_fail = chat.UpstreamError(502)
        self.warm()
        self.run_jobs()  # never raises out of the thread
        self.assertEqual(len(self.ollama_calls), 1)  # stops at the first failure
        self.ollama_fail = None
        self.clock.t += 60
        self.assertTrue(self.warm()[1]["warm"])


class OllamaClientTest(unittest.TestCase):
    """The client refuses anything but the two warm calls, whatever calls it (threat 167)."""

    def test_refused_before_any_socket(self):
        up = chat.Ollama(base="http://127.0.0.1:9")  # nothing listens on 9
        gen = {"model": "julz:latest", "prompt": "hi", "stream": False, "options": {"num_predict": 1}}
        for path, data in (("/api/pull", {"model": "x"}), ("/api/delete", {"model": "julz:latest"}),
                           ("/api/create", {"model": "julz:latest"}), ("/api/copy", {}),
                           ("/api/chat", gen), ("/api/generate", {**gen, "prompt": "rm -rf"}),
                           ("/api/generate", {**gen, "model": "julz-pro:latest"}),
                           ("/api/generate", {**gen, "keep_alive": -1}),
                           ("/api/generate", {**gen, "options": {"num_predict": 9999}}),
                           ("/api/embed", {"model": "bge-m3:latest", "input": "secret"}),
                           ("/api/generate/", gen), ("/api/generate", None)):
            with self.assertRaises(chat.UpstreamError) as e:
                up(path, data)
            self.assertEqual(e.exception.status, 0, (path, data))

    def test_a_listed_call_reaches_the_socket(self):
        up = chat.Ollama(base="http://127.0.0.1:9")
        with self.assertRaises(chat.UpstreamError) as e:
            up(*chat.WARM_CALLS[0])
        self.assertEqual(e.exception.status, 502)  # it tried, nothing listened


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
