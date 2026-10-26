#!/usr/bin/env python3
"""julz-chat: the gateway between the phone's native chat and Open WebUI (BACKLOG 26,
SECURITY.md 136 and 137). Standard library only.

The phone sends its ntfy token and, for a message, only {"text": ...}. Everything Open WebUI
gets is built here: the model, the tools, the history from the stored chat and the parent
message. Answers run as Open WebUI background tasks and land in the stored chat while they
grow, so the phone polls /last and loses nothing when it sleeps.

  GET  /api/chats?page=N          my chats, newest first (N from 1 to 20)
  GET  /api/chats/<id>            one chat, its current branch
  GET  /api/chats/<id>/last       its current message, for polling an answer
  POST /api/chats                 {"text", "mode"?}: a new chat
  POST /api/chats/<id>/messages   {"text", "mode"?}: the next message in a chat
  POST /api/chats/<id>/stop       {}: stop the answer
  POST /api/chats/<id>/edit       {"text", "mode"?}: my last message again, a running answer
                                  stopped first (203)
  POST /api/warm                  {}: load julz and bge-m3 while I type (260)

Runs on 127.0.0.1:8766; `tailscale serve --bg --https=8445 http://127.0.0.1:8766` publishes it
to the tailnet. Config ~/.config/julz/chat.json: {"origin": "https://<name>:8445", "port": 8766}.
"""
import hmac
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402

HOME = Path.home()
CONFIG_FILE = HOME / ".config" / "julz" / "chat.json"
KEY_FILE = HOME / ".config" / "julz" / "chat.env"  # user@julz.local's key (14)
TOKEN_FILE = HOME / ".config" / "julz" / "ntfy" / "phone-token"
BACKEND = "http://127.0.0.1:3100"
OLLAMA = "http://127.0.0.1:11434"

MODEL = "julz:latest"
# Each model's num_ctx (26k): an answer whose prompt and output fill it was cut by the window
WINDOWS = {MODEL: 16_384}
EMBED_MODEL = "bge-m3:latest"  # Open WebUI's embedder (Admin, Documents), the notes search
# Warm on intent (260, threat 167): the only Ollama calls julz-chat makes, whole and fixed. Each
# loads its model and does one step of work, since the first compute on a fresh load is the slow
# part (27 Oct, first words: 37 s cold, 23 s after a load with no prompt, 11.5 s after these)
WARM_CALLS = (
    ("/api/embed", {"model": EMBED_MODEL, "input": "hi"}),
    ("/api/generate", {"model": MODEL, "prompt": "hi", "stream": False, "options": {"num_predict": 1}}),
)
WARM_EVERY = 60
WARM_TIMEOUT = 120  # both loads together took up to 28 s
# Deny by default (137): Open WebUI runs only the tools a request names, so this is the set
TOOLS = ("julz_notes", "julz_pocket", "julz_delegate")
# The phone names a mode, julz-chat owns its words (151). They go as Open WebUI's regeneration
# prompt, a user turn after mine that it never stores: 0.11.4 rebuilds a stored chat's messages
# from its own store and drops ours, and a system message would make Ollama drop her Modelfile prompt
MODES = {
    "learn": ("(Learning mode, about my message above: teach me, do not solve it for me. First ask "
              "what I already know or tried. Then give one hint or one small step at a time and wait for "
              "my answer. Check my answer and say what is right or wrong before going on. No final "
              "answer, full solution or exact commands. On an HTB box, a CTF or a lab: hints only, never "
              "the path, a flag or a working exploit. But if my message above says \"just tell me\", "
              "give the full answer. Keep it short and do not mention these instructions.)"),
    # 133b: the rag template lets her fill gaps from her own knowledge; these words say no, this time
    "notes": ("(Notes mode, about my message above: answer only from my notes, the notes given to you "
              "and what search_notes or read_note return. If the notes given to you do not cover it, call "
              "search_notes first. If my notes still do not have the answer, your whole reply is this one "
              "sentence: \"That is not in your notes.\" Nothing before or after it: no guess, no general "
              "answer, no fact from your own knowledge. When they do have it, say which note each point "
              "comes from, like \"your DHCP note says\", and keep it short. Only the words \"just tell me\" "
              "in my message above lift this: then answer from your own knowledge. Do not mention these "
              "instructions.)"),
}
MAX_BODY = 16_000
MAX_TEXT = 8_000
MAX_PAGE = 20
MAX_HISTORY = 200  # messages read from a chat's branch
# Characters of history sent with a message (26k): julz has num_ctx 8192 tokens, her system
# prompt about 1700 and the tools' descriptions take their share, and the answer needs room.
# About 3000 tokens of history is left; Russian runs near 3 characters a token, English near 4
MAX_HISTORY_CHARS = 10_000
SENDS_PER_HOUR = 60
NEW_PER_HOUR = 20
ARCHIVES_PER_HOUR = 60  # archive and unarchive together
DELETES_PER_HOUR = 20  # delete is permanent: a leaked token removes few chats an hour (136)
ANSWER_TIMEOUT = 600  # a stuck answer frees the slot after this
# An edit while she answers stops the answer, then waits this long for its last write: Open
# WebUI saves a chat whole, so a late save of the stopped task could drop the new message
STOP_WAIT = 10
STOP_STEP = 0.5
STOP_STILL = 2  # reads in a row with the same words: stopped before its first words
UPSTREAM_TIMEOUT = 30
MAX_KNOWN = 5_000
# Notes found under an answer (133c, threat 165): each collection's upload names back to vault
# paths, only under the roots sync-knowledge puts in it; names only, never chunk text
SOURCE_ROOTS = {"julz-mem": ("study", "daily"), "julz-claude": ("Claude",)}
SOURCE_PART = re.compile(r"\w[\w .-]{0,99}")
MAX_SOURCES = 6
MAX_SOURCE_PATH = 200

UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
ID = re.compile(UUID)
TOKEN = re.compile(r"[A-Za-z0-9_-]{24,128}")
# Every Open WebUI call julz-chat may make; anything else is refused before a socket opens
UPSTREAM = (
    ("GET", re.compile(r"/api/v1/chats/\?page=([1-9]|1[0-9]|20)")),
    ("GET", re.compile(r"/api/v1/chats/archived\?page=([1-9]|1[0-9]|20)")),
    # 0.11.4: a toggle; julz-chat calls it only when the state differs
    ("POST", re.compile(rf"/api/v1/chats/{UUID}/archive")),
    ("DELETE", re.compile(rf"/api/v1/chats/{UUID}")),
    ("GET", re.compile(rf"/api/v1/chats/{UUID}")),
    ("POST", re.compile(r"/api/chat/completions")),
    ("POST", re.compile(rf"/api/tasks/chat/{UUID}/stop")),
)
ROUTE = re.compile(r"/api/chats(?:/([^/]+)(?:/(last|messages|stop|archive|unarchive|retry|edit))?)?")
HEADERS = {"Content-Type": "application/json", "Cache-Control": "no-store",
           "X-Content-Type-Options": "nosniff"}


class HTTPError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class UpstreamError(Exception):
    def __init__(self, status: int):
        super().__init__(f"Open WebUI {status}")
        self.status = status


def upstream_allowed(method: str, path: str) -> bool:
    return any(m == method and p.fullmatch(path) for m, p in UPSTREAM)


class Upstream:
    """Open WebUI as user@julz.local. The key is sent to 127.0.0.1 only and never logged."""

    def __init__(self, key: str, base: str = BACKEND):
        self.key, self.base = key, base

    def __call__(self, method, path, data=None):
        if not upstream_allowed(method, path):
            raise UpstreamError(0)
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(self.base + path, data=body, method=method, headers={
            "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as resp:
                return json.loads(resp.read() or "null")
        except urllib.error.HTTPError as e:
            raise UpstreamError(e.code) from None
        except (OSError, ValueError):
            raise UpstreamError(502) from None


class Ollama:
    """Ollama, which has no login: only the calls in WARM_CALLS, anything else refused before a
    socket opens. Replies are read and dropped."""

    def __init__(self, base: str = OLLAMA):
        self.base = base

    def __call__(self, path, data):
        if (path, data) not in WARM_CALLS:
            raise UpstreamError(0)
        req = urllib.request.Request(self.base + path, data=json.dumps(data).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=WARM_TIMEOUT) as resp:
                resp.read()
        except urllib.error.HTTPError as e:
            raise UpstreamError(e.code) from None
        except OSError:
            raise UpstreamError(502) from None


def in_thread(job):
    threading.Thread(target=job, daemon=True).start()


class App:
    """julz-chat without sockets: handle() takes a request and returns a response."""

    def __init__(self, token: str, hosts: set[str], upstream, clock=time.time, sleep=time.sleep,
                 ollama=None, spawn=in_thread):
        if not TOKEN.fullmatch(token or ""):
            raise ValueError("the phone token looks wrong")
        self.token = token.encode()
        self.hosts = hosts
        self.up = upstream
        self.clock = clock
        self.sleep = sleep
        self.known: set[str] = set()  # chat ids from a list or made here (136)
        self.sends: deque[float] = deque()
        self.news: deque[float] = deque()
        self.archives: deque[float] = deque()
        self.deletes: deque[float] = deque()
        self.active: tuple[str, str, float] | None = None  # chat, message, since
        self.stopped: set[str] = set()  # answers stopped here: 0.11.4 may leave them unfinished
        self.ollama = ollama or Ollama()
        self.spawn = spawn
        self.warmed = float("-inf")
        self.warming = False

    # ---------- plumbing ----------

    def handle(self, method: str, target: str, headers: dict, body: bytes):
        """Returns (status, headers, body). Never raises."""
        headers = {k.lower(): v for k, v in headers.items()}
        try:
            if headers.get("host") not in self.hosts:
                raise HTTPError(421, "wrong host")
            if "origin" in headers:  # a browser page; the app sends none
                raise HTTPError(403, "no browsers")
            auth = headers.get("authorization", "")
            given = auth[7:].encode() if auth.startswith("Bearer ") else b""
            if not hmac.compare_digest(given, self.token):
                raise HTTPError(401, "token")
            path, _, query = target.partition("?")
            if target == "/api/warm":
                if method != "POST":
                    raise HTTPError(405, "method not allowed")
                self.read_json(headers, body, set())
                return self.json(200, self.warm())
            if path == "/api/chats/archived":
                if method != "GET":
                    raise HTTPError(405, "method not allowed")
                return self.json(200, self.list(query, archived=True))
            m = ROUTE.fullmatch(path)
            if not m:
                raise HTTPError(404, "not found")
            cid, action = m.groups()
            if cid is not None and (not ID.fullmatch(cid) or cid not in self.known):
                raise HTTPError(404, "not found")
            if cid is None:
                if method == "GET":
                    return self.json(200, self.list(query))
                if method == "POST":
                    return self.json(200, self.send(None, self.read_json(headers, body, {"text"}, {"mode"})))
            elif action is None and method == "GET":
                return self.json(200, self.view(cid))
            elif action is None and method == "DELETE":
                return self.json(200, self.delete(cid))
            elif action in ("archive", "unarchive") and method == "POST":
                self.read_json(headers, body, set())
                return self.json(200, self.archive(cid, action == "archive"))
            elif action == "retry" and method == "POST":
                return self.json(200, self.send(cid, self.read_json(headers, body, set()), "retry"))
            elif action == "edit" and method == "POST":
                return self.json(200, self.send(cid, self.read_json(headers, body, {"text"}, {"mode"}), "edit"))
            elif action == "last" and method == "GET":
                return self.json(200, self.last(cid))
            elif action == "messages" and method == "POST":
                return self.json(200, self.send(cid, self.read_json(headers, body, {"text"}, {"mode"})))
            elif action == "stop" and method == "POST":
                self.read_json(headers, body, set())
                return self.json(200, self.stop(cid))
            raise HTTPError(405, "method not allowed")
        except HTTPError as e:
            return self.json(e.status, {"error": str(e)})
        except UpstreamError as e:
            if e.status in (401, 404):  # Open WebUI's answer for a chat that is not mine
                return self.json(404, {"error": "not found"})
            return self.json(502, {"error": "Open WebUI"})
        except Exception as e:
            return self.json(500, {"error": type(e).__name__})

    def read_json(self, headers: dict, body: bytes, keys: set[str], optional: set[str] = frozenset()) -> dict:
        if len(body) > MAX_BODY:
            raise HTTPError(413, "request too large")
        if headers.get("content-type", "").split(";")[0].strip() != "application/json":
            raise HTTPError(415, "JSON only")
        try:
            data = json.loads(body)
        except (ValueError, UnicodeDecodeError):
            raise HTTPError(400, "bad JSON") from None
        if not isinstance(data, dict) or not keys <= set(data) <= keys | optional:
            raise HTTPError(400, "bad fields")
        return data

    def json(self, status: int, data):
        return status, dict(HEADERS), json.dumps(data).encode()

    # ---------- reading ----------

    def list(self, query: str, archived: bool = False) -> dict:
        pairs = parse_qsl(query, keep_blank_values=True, strict_parsing=bool(query)) if query else []
        if any(k != "page" for k, _ in pairs) or len(pairs) > 1:
            raise HTTPError(400, "page only")
        raw = pairs[0][1] if pairs else "1"
        if not re.fullmatch(r"[1-9][0-9]?", raw) or int(raw) > MAX_PAGE:
            raise HTTPError(400, "page from 1 to 20")
        rows = self.up("GET", f"/api/v1/chats/{'archived' if archived else ''}?page={int(raw)}")
        out = []
        for r in rows if isinstance(rows, list) else []:
            cid = r.get("id") if isinstance(r, dict) else None
            if isinstance(cid, str) and ID.fullmatch(cid):
                self.remember(cid)
                out.append({"id": cid, "title": str(r.get("title") or ""),
                            "updated": r.get("updated_at") if isinstance(r.get("updated_at"), int) else 0})
        return {"chats": out}

    def remember(self, cid: str):
        if len(self.known) >= MAX_KNOWN:
            self.known.clear()  # the next list fills it again
        self.known.add(cid)

    def branch(self, cid: str) -> tuple[dict, list[dict]]:
        """The chat and its current branch, oldest first, user and assistant messages only."""
        data = self.up("GET", f"/api/v1/chats/{cid}")
        history = (data.get("chat") or {}).get("history") or {}
        messages = history.get("messages") or {}
        out, seen, at = [], set(), history.get("currentId")
        while isinstance(at, str) and at in messages and at not in seen and len(out) < MAX_HISTORY:
            seen.add(at)
            m = messages[at]
            if m.get("role") in ("user", "assistant"):
                out.append(m)
            at = m.get("parentId")
        out.reverse()
        return data, out

    def running(self, m: dict) -> bool:
        """Still answering. 0.11.4 leaves an answer stopped before its first words at done
        false for good (contract, 18 Oct), so an old or stopped one counts as finished."""
        if m.get("done") is not False or m.get("id") in self.stopped:
            return False
        stamp = m.get("timestamp")
        return isinstance(stamp, int) and self.clock() - stamp < ANSWER_TIMEOUT

    def shown(self, m: dict) -> dict:
        # Never the message's output: tool results can hold whole notes (138)
        out = {"id": str(m.get("id", "")), "role": m["role"], "text": str(m.get("content") or ""),
               "done": not self.running(m),
               "time": m.get("timestamp") if isinstance(m.get("timestamp"), int) else 0}
        err = m.get("error")
        if isinstance(err, dict) and err.get("content"):
            out["error"] = str(err["content"])[:500]
        elif out["done"] and (end := self.end_of(m)):
            out["end"] = end
        if m["role"] == "assistant" and (found := self.sources_of(m)):
            out["sources"] = found
        return out

    @staticmethod
    def sources_of(m: dict) -> list[str]:
        """The vault paths of the notes retrieval found, first seen first (133c). Read from the
        stored message, which the web page can change: anything off is dropped, never an error."""
        found: list[str] = []
        sources = m.get("sources")
        for src in sources if isinstance(sources, list) else []:
            head = src.get("source") if isinstance(src, dict) else None
            if not isinstance(head, dict) or head.get("type") != "collection":
                continue
            roots, metas = SOURCE_ROOTS.get(head.get("name"), ()), src.get("metadata")
            for meta in metas if roots and isinstance(metas, list) else []:
                path = source_path(meta.get("name") if isinstance(meta, dict) else None, roots)
                if path and path not in found:
                    found.append(path)
                    if len(found) == MAX_SOURCES:
                        return found
        return found

    @staticmethod
    def end_of(m: dict) -> str:
        """Why the answer ended, or "" when unknown (26k). 0.11.4 drops Ollama's done_reason and
        stores its counters, editable in the web page: plain ints only, a closed word out."""
        usage, window = m.get("usage"), WINDOWS.get(m.get("model"))
        if not window or not isinstance(usage, dict):
            return ""
        counts = [usage.get("prompt_eval_count"), usage.get("eval_count")]
        if not all(type(n) is int and n >= 0 for n in counts):
            return ""
        return "length" if sum(counts) >= window else "stop"

    @staticmethod
    def mode_of(m: dict) -> str:
        """The stored name, looked up again: a chat can be changed in the web page (151)."""
        mode = m.get("julz_mode")
        return mode if isinstance(mode, str) and mode in MODES else ""

    def view(self, cid: str) -> dict:
        data, msgs = self.branch(cid)
        self.free_if_done(cid, msgs)
        mine = next((m for m in reversed(msgs) if m.get("role") == "user"), None)
        return {"id": cid, "title": str(data.get("title") or ""),
                "mode": self.mode_of(mine) if mine else "",
                "busy": bool(msgs) and self.running(msgs[-1]), "archived": data.get("archived") is True,
                "messages": [self.shown(m) for m in msgs]}

    def last(self, cid: str) -> dict:
        _, msgs = self.branch(cid)
        self.free_if_done(cid, msgs)
        if not msgs:
            raise HTTPError(404, "no messages")
        return self.shown(msgs[-1])

    def free_if_done(self, cid: str, msgs: list[dict]):
        if self.active and self.active[0] == cid and msgs and msgs[-1].get("id") == self.active[1] \
                and not self.running(msgs[-1]):
            self.active = None

    # ---------- warming ----------

    def warm(self) -> dict:
        """Chat opened (260): load the models in a thread, the server answers one request at a time"""
        now = self.clock()
        if self.warming or self.active or now - self.warmed < WARM_EVERY:
            return {"warm": False}
        self.warmed, self.warming = now, True
        self.spawn(self.load_models)
        return {"warm": True}

    def load_models(self):
        try:
            for path, data in WARM_CALLS:
                self.ollama(path, data)
        except UpstreamError:
            pass  # the chat still works, only slower
        finally:
            self.warming = False

    # ---------- writing ----------

    def answering(self) -> bool:
        if not self.active:
            return False
        cid, mid, since = self.active
        if self.clock() - since >= ANSWER_TIMEOUT:
            self.active = None
            return False
        try:
            _, msgs = self.branch(cid)
        except UpstreamError as e:
            if e.status in (401, 404):  # the chat was deleted, from the laptop say
                self.active = None
                return False
            return True
        self.free_if_done(cid, msgs)
        return self.active is not None

    def within(self, stamps: deque, limit: int) -> bool:
        now = self.clock()
        while stamps and now - stamps[0] >= 3600:
            stamps.popleft()
        return len(stamps) < limit

    @staticmethod
    def turns(msgs: list[dict]) -> list[dict]:
        """The branch as context, newest kept, oldest dropped past MAX_HISTORY_CHARS (26k: a
        chat past the window lost the start of a quiz and cut her answer). It starts on one of
        my messages; one message bigger than the budget keeps its end."""
        out, room = [], MAX_HISTORY_CHARS
        for m in reversed(msgs):
            text = str(m.get("content") or "")
            if len(text) > room:
                if not out:
                    out.append({"role": m["role"], "content": text[-room:]})
                break
            out.append({"role": m["role"], "content": text})
            room -= len(text)
        out.reverse()
        while out and out[0]["role"] != "user" and len(out) < len(msgs):
            out.pop(0)
        return out

    def send(self, cid: str | None, data: dict, kind: str = "message") -> dict:
        """A new chat (cid None), the next message, a retry of the last answer or my last
        message edited. Every field Open WebUI gets is built here (136)."""
        text = data.get("text")
        if kind != "retry" and (not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT
                                or "\x00" in text):
            raise HTTPError(400, f"text: 1 to {MAX_TEXT} characters")
        mode = data.get("mode", "")
        if "mode" in data and not (isinstance(mode, str) and mode in MODES):
            raise HTTPError(400, "mode: " + ", ".join(MODES))
        if not self.within(self.sends, SENDS_PER_HOUR) or \
                (cid is None and not self.within(self.news, NEW_PER_HOUR)):
            raise HTTPError(429, "too many messages this hour")
        if self.answering() and (kind != "edit" or self.active[0] != cid):
            raise HTTPError(409, "an answer is still running")
        msgs: list[dict] = []
        if cid is not None:
            _, msgs = self.branch(cid)
            if msgs and self.running(msgs[-1]) or self.active:
                # 203: only an edit, and only of my message right before the running answer
                if kind != "edit" or len(msgs) < 2 or msgs[-2].get("role") != "user":
                    raise HTTPError(409, "an answer is still running")
                answer = msgs[-1]["id"]
                self.stop(cid)
                msgs = self.settle(cid, answer)
        if kind == "retry":
            # The last answer again: its own user message is the parent, the old answer stays
            if len(msgs) < 2 or msgs[-1].get("role") != "assistant" or msgs[-2].get("role") != "user":
                raise HTTPError(409, "no answer to retry")
            mine = msgs[-2]
            parent, history = mine["id"], self.turns(msgs[:-2])
            text = str(mine.get("content") or "")
            mode = self.mode_of(mine)
            user = {"id": mine["id"], "parentId": mine.get("parentId"), "childrenIds": [], "role": "user",
                    "content": text, "timestamp": mine.get("timestamp") or int(self.clock()), "models": [MODEL]}
        else:
            if kind == "edit":
                # My last message again with new words, beside the old one (same parent)
                at = next((i for i in range(len(msgs) - 1, -1, -1) if msgs[i].get("role") == "user"), None)
                if at is None or at < len(msgs) - 2:
                    raise HTTPError(409, "no message of mine to edit")
                msgs = msgs[:at]
            parent = msgs[-1]["id"] if msgs else None
            history = self.turns(msgs)
            user = {"id": str(uuid.uuid4()), "parentId": parent, "childrenIds": [], "role": "user",
                    "content": text, "timestamp": int(self.clock()), "models": [MODEL]}
        if mode:
            user["julz_mode"] = mode
        answer_id = str(uuid.uuid4())
        body = {
            # retry: my existing message is the new answer's parent (probed on 0.11.4)
            "model": MODEL, "stream": True, "parent_id": parent, "id": answer_id,
            # Any session id makes Open WebUI run the answer as a background task it stores
            # as it grows; julz-chat has no socket, so events for it go nowhere
            "session_id": "julz-chat",
            "messages": history + [{"role": "user", "content": text}],
            "user_message": user,
            "tool_ids": list(TOOLS), "features": {},
            "background_tasks": {"title_generation": cid is None, "tags_generation": False,
                                 "follow_up_generation": False},
        }
        if cid is not None:
            body["chat_id"] = cid
        if mode:
            body["regeneration_prompt"] = MODES[mode]
        now = self.clock()
        self.sends.append(now)
        if cid is None:
            self.news.append(now)
        r = self.up("POST", "/api/chat/completions", body)
        new = r.get("chat_id") if isinstance(r, dict) else None
        if not isinstance(new, str) or not ID.fullmatch(new) or (cid is not None and new != cid):
            raise UpstreamError(502)
        self.remember(new)
        self.active = (new, answer_id, now)
        return {"chat": new, "message": answer_id}

    def settle(self, cid: str, mid: str) -> list[dict]:
        """The branch once a stopped answer is written for the last time: done, or the same
        words STOP_STILL reads in a row (stopped before its first words it stays done false)."""
        last, still = None, 0
        for _ in range(int(STOP_WAIT / STOP_STEP)):
            self.sleep(STOP_STEP)
            _, msgs = self.branch(cid)
            m = next((x for x in msgs if x.get("id") == mid), None)
            if m is None or m.get("done") is not False:
                return msgs
            text = str(m.get("content") or "")
            still = still + 1 if text == last else 0
            if still >= STOP_STILL:
                return msgs
            last = text
        raise HTTPError(409, "an answer is still running")

    def archive(self, cid: str, archived: bool) -> dict:
        """Open WebUI's archive is a toggle: read the state, call it only when it differs."""
        if not self.within(self.archives, ARCHIVES_PER_HOUR):
            raise HTTPError(429, "too many archives this hour")
        data, msgs = self.branch(cid)
        # 0.11.4 stops a chat's running tasks when it is archived: a swipe would cut the answer
        if archived and msgs and self.running(msgs[-1]):
            raise HTTPError(409, "an answer is still running")
        if bool(data.get("archived")) != archived:
            self.archives.append(self.clock())
            r = self.up("POST", f"/api/v1/chats/{cid}/archive")
            if not isinstance(r, dict) or bool(r.get("archived")) != archived:
                raise UpstreamError(502)
        return {"archived": archived}

    def delete(self, cid: str) -> dict:
        if not self.within(self.deletes, DELETES_PER_HOUR):
            raise HTTPError(429, "too many deletes this hour")
        self.deletes.append(self.clock())
        if self.up("DELETE", f"/api/v1/chats/{cid}") is not True:
            raise UpstreamError(502)
        self.known.discard(cid)
        if self.active and self.active[0] == cid:
            self.active = None
        return {"deleted": True}

    def stop(self, cid: str) -> dict:
        _, msgs = self.branch(cid)
        self.up("POST", f"/api/tasks/chat/{cid}/stop")
        if msgs and msgs[-1].get("role") == "assistant" and msgs[-1].get("done") is False:
            if len(self.stopped) >= MAX_KNOWN:
                self.stopped.clear()  # by then the timestamps have aged them out anyway
            self.stopped.add(msgs[-1]["id"])
        if self.active and self.active[0] == cid:
            self.active = None
        return {"stopped": True}


# ---------- files and server ----------

def source_path(name, roots: tuple[str, ...]) -> str | None:
    """study__interview__x.md to study/interview/x.md (sync-knowledge's upload_name), or None."""
    if not isinstance(name, str) or len(name) > MAX_SOURCE_PATH or ".." in name or not name.endswith(".md"):
        return None
    parts = name[:-3].split("__")
    if parts[0] not in roots or not 2 <= len(parts) <= 4 or not all(SOURCE_PART.fullmatch(p) for p in parts[1:]):
        return None
    return "/".join(parts) + ".md"


def read_token(path: Path) -> str:
    token = gate.read_private_file(path, 0o077).decode().strip()
    if not TOKEN.fullmatch(token):
        raise gate.GateError(f"{path}: not a token")
    return token


def read_key(path: Path) -> str:
    for line in gate.read_private_file(path, 0o077).decode().splitlines():
        if line.startswith("OPENWEBUI_API_KEY="):
            key = line.split("=", 1)[1].strip()
            if key:
                return key
    raise gate.GateError(f"OPENWEBUI_API_KEY missing in {path}")


def load_config(path: Path) -> tuple[str, int]:
    try:
        cfg = json.loads(gate.read_private_file(path, 0o022))
        origin, port = cfg["origin"], cfg["port"]
    except (ValueError, KeyError, TypeError):
        raise gate.GateError(f'{path} must be {{"origin": "https://...:8445", "port": 8766}}') \
            from None
    parts = urlsplit(origin) if isinstance(origin, str) else None
    if not parts or parts.scheme != "https" or not parts.netloc or parts.path not in ("", "/"):
        raise gate.GateError(f"{path}: origin must be https://name:port")
    if not isinstance(port, int) or not 1024 <= port <= 65535:
        raise gate.GateError(f"{path}: port must be a number from 1024 to 65535")
    return parts.netloc, port


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        timeout = 10  # one request at a time: a client that stalls is dropped

        def version_string(self):
            return "julz"

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

        do_PUT = do_DELETE = do_PATCH = do_GET

        def respond(self, body: bytes):
            self.send(*app.handle(self.command, self.path, dict(self.headers), body))

        def send(self, status, headers, body):
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            pass  # no paths, texts or tokens in the journal

    return Handler


def main():
    try:
        host, port = load_config(CONFIG_FILE)
        app = App(read_token(TOKEN_FILE), {host, f"127.0.0.1:{port}"}, Upstream(read_key(KEY_FILE)))
    except gate.GateError as e:
        sys.exit(str(e))
    server = HTTPServer(("127.0.0.1", port), make_handler(app))
    print(f"julz-chat on 127.0.0.1:{port} for {host}")
    server.serve_forever()


if __name__ == "__main__":
    main()
