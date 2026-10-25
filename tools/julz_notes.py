"""
title: Julz notes
description: Search, list, read (from plain words) and create notes in the julz-mem vault, show folders and recent notes, pick notes due for review, and add to, edit, move or delete my notes after I confirm.
version: 0.9.0
"""
# Paste this file into Open WebUI: Workspace, Tools, +. No third party imports on purpose,
# except fastapi for the checklist embed, imported only inside Open WebUI, where it is.
# Security model (SECURITY.md threats 1, 4, 13, 65 to 76):
# - every path is resolved and must stay inside its root (CWE-22), symlinks included
# - writes itself only into Inbox, as new .md files; overwriting needs MY click in the browser,
#   the model cannot confirm for me (LLM06 Excessive Agency)
# - Inbox/, study/ and daily/ stay read only here except Inbox itself. Adding, editing one
#   passage, moving, deleting or creating outside Inbox needs MY click, then only drops a
#   request into Inbox/.requests/ with the hash of what I saw; julz-vault on the host checks
#   it again, applies it and commits (threats 65 to 76). Claude/ and Outbox/ never change
# - size and rate limits, and every write is appended to the action log
import hashlib
import html
import json
import os
import re
import secrets
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

MAX_NOTE_BYTES = 100_000
MAX_READ_CHARS = 20_000
MAX_WRITES_PER_MINUTE = 10
MAX_SEARCH_RESULTS = 10
# Letters (any language), digits, space, dash, underscore, dot. No slashes, so no folders.
SAFE_NAME = re.compile(r"^[\w][\w \-.]{0,99}$")
# Words that say how to find a note, not which one: "read my dhcp note" means "dhcp"
STOP_WORDS = {"a", "an", "the", "my", "me", "of", "in", "on", "about", "for", "please",
              "note", "notes", "file", "guide", "read", "show", "open", "md", "txt"}
MAX_CHOICES = 5
MAX_LIST = 60
MAX_DUE = 5
MAX_APPEND_CHARS = 4000
MAX_SHOWN_CHARS = 2000
NO_DIALOG = (" Nothing was changed: this chat has no confirm button, so this works only on the "
             "Open WebUI web page for now. Tell the user plainly that nothing was changed; do "
             "not say it is saved, drafted or waiting.")
# Where no dialog shows, a change goes to Approve on the phone as a card I sign (208, threat
# 156). The caps are the approver's and julz_vault's (a test keeps them equal)
MAX_PROPOSALS = 10
MAX_CARD = 4000
CARD_ROOM = 300  # the card's own words and paths around the text
PROPOSAL_TTL = 86_400
NO_CARD = {"too long for a card": "the change is too long to sign on the phone",
           "too many cards waiting": "too many changes already wait on the phone"}
PROPOSAL_NAME = re.compile(r"(\d{10})-[0-9a-f]{8}\.json")
ON_THE_PHONE = (" yet: this chat has no confirm button, so the change went to Approve on the "
                "user's phone as a card. Nothing changes until they sign it there. Tell the "
                "user exactly that; do not say it is done.")
FRONT_MATTER_MAX = 2000
# Days between reviews by the note's status; a note never reviewed is due at once
REVIEW_DAYS = {"learning": 3, "review": 7, "solid": 30}
DEFAULT_REVIEW_DAYS = 7
MINE = "study"
# Top folders julz may change, each change after my click (SECURITY.md 71 to 76). Claude/,
# Outbox/ and Templates/ stay read only. Subfolders only in study/ and daily/: Inbox/claude/
# is where delegation specs wait for my phone
EDITABLE = ("Inbox", "study", "daily")
SUBFOLDERS_IN = ("study", "daily")
FOLDER = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
KINDS = ("todo", "thought", "concept", "lab")
# Words a task may add to mine without making it up (threat 140)
FILLERS = {"a", "an", "to", "of", "at", "in", "on", "my", "the", "and", "for", "with", "from", "into",
           "your", "our", "then"}
# A new Inbox note is the one write with no click, so my last message must ask for it (threat 161)
SAVE_WORD = re.compile(
    r"\b(?:save[sd]?|saving|(?:make|take|create|new)\s+(?:a\s+)?(?:new\s+)?note|"
    r"note\s+(?:this|that|it|down)|jot|write\s+(?:it\s+|this\s+|that\s+)?down|"
    r"remember\s+(?:this|that)|keep\s+(?:this|that)|record|store|to-?dos?)\b|"
    r"\b(?:сохран|запиш|записа|запомни|zapisz|zapisa|zanotuj|zachowaj|zapamiętaj)\w*|"
    r"\b(?:сделай|создай|нов\w*)\s+(?:\w+\s+)?заметк\w*|"
    r"\b(?:zrób|utwórz|now\w*)\s+(?:\w+\s+)?notatk\w*", re.I)
# An addition to a note: a card or click follows, so the words are wider, a miss costs a message
ADD_WORD = re.compile(
    r"\b(?:add|adds|added|adding|append|put|insert|attach)\b|"
    r"\b(?:добав|допиш|дописа|внеси|внести|вставь|dodaj|dopisz|dopisa|wstaw|wpisz)\w*", re.I)
# Open and done checkboxes. A tick by julz adds "(done <date>)", so done_tasks can tell when
OPEN_TASK = re.compile(r"^\s*[-*] \[ \] (.+?)\s*$", re.M)
DONE_TASK = re.compile(r"^\s*[-*] \[[xX]\] (.+?) \(done (\d{4}-\d{2}-\d{2})\)\s*$", re.M)
TASK_ROOTS = ("Inbox", "daily")
MAX_ITEM = 200
# "2", "2, 4", "2 and 4": numbers from show_todos
NUMBERS = re.compile(r"\s*\d+(?:\s*(?:,|and|&|\s)\s*\d+)*\s*")
# My own message that solves feedback: "solved 1, 3", nothing else on its first line
SOLVED = re.compile(r"\s*solved\s+(" + NUMBERS.pattern + ")", re.I)
FEEDBACK_SHOWN = 120
# Bad answers kept as eval cases (threat 153): her own wrong words, never read back to her
KEPT_CASES = ("feedback", "eval")
MAX_RECENT = 20
ROLES = {"Inbox": "julz drafts, not reviewed", "study": "your study notes",
         "daily": "your real life notes", "Claude": "kept from Claude, read only",
         "Outbox": "Claude run reports, read only", "Templates": "Obsidian forms, read only",
         "feedback": "your feedback about julz, read by Claude Code"}
# Plain text only in my notes: Obsidian would render a link or image (a zero click fetch)
NOT_PLAIN = re.compile(r"!\[|\]\(|<[A-Za-z!?/]|://|(?i:\bwww\.)")
HIDDEN = ("Cc", "Cf", "Co", "Cs", "Cn")



def checklist_html(tasks: list, verb: str = "done") -> str:
    """The open tasks as a checklist for an Open WebUI Rich UI embed. Ticked boxes and Mark
    done send "done 1, 3" into the chat (feedback: "solved 1, 3"), the same message I could type: Open WebUI asks me
    before it sends, julz ticks with tick_task. Task text is escaped (XSS, A03), the script
    only knows numbers, nothing is fetched from outside."""
    rows, current = [], None
    for n, (rel, item) in enumerate(tasks, 1):
        if rel != current:
            rows.append(f"<h3>{html.escape(str(rel))}</h3>")
            current = rel
        rows.append(f'<label><input type="checkbox" value="{n}"> {n}. {html.escape(item)}</label>')
    return """<!doctype html><meta charset="utf-8">
<style>
:root { color-scheme: light dark; font: 15px/1.4 system-ui, sans-serif; }
body { margin: 0; padding: 8px 4px; }
h3 { margin: 10px 0 4px; font-size: 13px; opacity: .7; font-weight: 600; }
label { display: block; padding: 6px 2px; }
input { width: 18px; height: 18px; vertical-align: -3px; margin-right: 6px; }
button { margin-top: 10px; padding: 8px 16px; font: inherit; border-radius: 8px; border: 1px solid; }
</style>
""" + "\n".join(rows) + """
<button id="done">Mark """ + verb + """</button>
<script>
function height() {
  parent.postMessage({type: "iframe:height", height: document.documentElement.scrollHeight}, "*");
}
document.getElementById("done").onclick = function () {
  var n = Array.from(document.querySelectorAll("input:checked")).map(function (b) { return b.value; });
  if (!n.length) return;
  parent.postMessage({type: "input:prompt:submit", text: '""" + verb + """ ' + n.join(", ")}, "*");
  this.disabled = true;
  this.textContent = "Sent: """ + verb + """ " + n.join(", ");
};
window.onload = height;
window.onresize = height;
</script>"""


def done_html(done: list) -> str:
    """What I got done as an Open WebUI embed, newest first, the date on every task: the 4B
    model dropped the dates when it retold the list. Text escaped (A03), the script only
    sizes the frame, nothing is sent or fetched."""
    rows = [f'<li><span class="d">{d.strftime("%a %d %b")}</span> {html.escape(item)} '
            f'<span class="w">{html.escape(str(rel))}</span></li>' for d, item, rel in done]
    return """<!doctype html><meta charset="utf-8">
<style>
:root { color-scheme: light dark; font: 15px/1.4 system-ui, sans-serif; }
body { margin: 0; padding: 8px 4px; }
ul { list-style: none; margin: 0; padding: 0; }
li { padding: 5px 2px; }
.d { display: inline-block; min-width: 7.5em; font-weight: 600; font-variant-numeric: tabular-nums; }
.w { font-size: 12px; opacity: .6; }
</style>
<ul>
""" + "\n".join(rows) + """
</ul>
<script>
function height() {
  parent.postMessage({type: "iframe:height", height: document.documentElement.scrollHeight}, "*");
}
window.onload = height;
window.onresize = height;
</script>"""


def _embed(page: str):
    """An Open WebUI Rich UI embed of page, or None outside Open WebUI."""
    try:
        from fastapi.responses import HTMLResponse
    except ImportError:
        return None
    return HTMLResponse(content=page, headers={"Content-Disposition": "inline"})


CALLOUT =re.compile(r"^\[!(\w+)\][+-]?\s*(.*)$")
CALLOUT_TYPES = {"note", "tip", "hint", "info", "todo", "warning", "caution", "danger", "bug",
                 "summary", "abstract", "question", "example", "quote", "success", "failure",
                 "important"}
LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+(.*)$")
TABLE_RULE = re.compile(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?")


def _clean(text: str) -> str:
    return "".join(c for c in text if c == "\t" or unicodedata.category(c) not in HIDDEN)


def _inline(text: str) -> str:
    """Bold, italic, code, highlight, wikilinks; links as plain text, images never loaded.
    Each piece is HTML escaped first, so only these tags can come out (XSS, A03)."""
    out = []
    for part in re.split(r"(`[^`\n]+`)", _clean(text)):
        if len(part) > 1 and part[0] == part[-1] == "`":
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        t = html.escape(part)
        t = re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda m: f'<span class="img">[image: {m[1]}]</span>', t)
        t = re.sub(r"\[([^\]\[]+)\]\(([^)\s]+)\)", lambda m: f'{m[1]} <span class="url">({m[2]})</span>', t)
        t = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r'<span class="wl">\2</span>', t)
        t = re.sub(r"\[\[([^\]]+)\]\]", lambda m: f'<span class="wl">{m[1].rsplit("/", 1)[-1]}</span>', t)
        t = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", t)
        t = re.sub(r"==(.+?)==", r"<mark>\1</mark>", t)
        t = re.sub(r"(?<![*\w])\*(?!\s)(.+?)(?<!\s)\*(?![*\w])", r"<em>\1</em>", t)
        t = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<em>\1</em>", t)
        out.append(t)
    return "".join(out)


def _blocks(body: str) -> list:
    lines, out, para, i = body.split("\n"), [], [], 0

    def flush():
        if para:
            out.append("<p>" + "<br>".join(_inline(l) for l in para) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        s = line.strip()
        if s.startswith("```"):
            flush()
            code, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append("<pre><code>" + html.escape(_clean("\n".join(code))) + "</code></pre>")
            i += 1
            continue
        if not s:
            flush()
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", s)
        if m:
            flush()
            out.append(f"<h{len(m[1])}>{_inline(m[2])}</h{len(m[1])}>")
            i += 1
            continue
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", s):
            flush()
            out.append("<hr>")
            i += 1
            continue
        if s.startswith(">"):
            flush()
            quote = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            cm = CALLOUT.match(quote[0].strip())
            if cm:
                kind = cm[1].lower() if cm[1].lower() in CALLOUT_TYPES else "note"
                inner = "<br>".join(_inline(l) for l in quote[1:] if l.strip())
                out.append(f'<div class="callout {kind}"><div class="ct">'
                           f'{_inline(cm[2]) or kind.capitalize()}</div>'
                           + (f"<div>{inner}</div>" if inner else "") + "</div>")
            else:
                out.append("<blockquote>" + "<br>".join(_inline(l) for l in quote) + "</blockquote>")
            continue
        if s.startswith("|") and i + 1 < len(lines) and TABLE_RULE.fullmatch(lines[i + 1].strip()):
            flush()

            def cells(l):
                return [c.strip() for c in l.strip().strip("|").split("|")]
            head, rows, i = cells(line), [], i + 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(cells(lines[i]))
                i += 1
            out.append("<table><tr>" + "".join(f"<th>{_inline(c)}</th>" for c in head) + "</tr>"
                       + "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>"
                                 for r in rows) + "</table>")
            continue
        lm = LIST_ITEM.match(line)
        if lm:
            flush()
            ordered, items = lm[2][0].isdigit(), []
            while i < len(lines):
                lm = LIST_ITEM.match(lines[i])
                if not lm or lm[2][0].isdigit() != ordered:
                    break
                tm = re.match(r"^\[([ xX])\]\s+(.*)$", lm[3])
                if tm:
                    done = tm[1] != " "
                    items.append(f'<li class="task{" done" if done else ""}"><span class="box">'
                                 f'{"&#9745;" if done else "&#9744;"}</span> {_inline(tm[2])}</li>')
                else:
                    items.append(f"<li>{_inline(lm[3])}</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        para.append(line)
        i += 1
    flush()
    return out


def note_html(rel: str, who: str, text: str) -> str:
    """A note as Obsidian's reading view shows it, for an Open WebUI Rich UI embed:
    properties with tag pills, headings, callouts, tables, task boxes, wikilinks. Escaped
    first; links are text, images never load, nothing is fetched (SECURITY.md 84)."""
    meta, body = Tools._front(text)
    props = []
    for key, value in meta.items():
        if key == "tags":
            pills = "".join(f'<span class="tag">#{html.escape(_clean(t))}</span>'
                            for t in Tools._tags(meta))
            props.append(f"<tr><td>tags</td><td>{pills}</td></tr>")
        else:
            props.append(f"<tr><td>{html.escape(_clean(key))}</td>"
                         f"<td>{html.escape(_clean(value))}</td></tr>")
    head = f'<div class="path">{html.escape(_clean(rel))} &middot; {html.escape(who)}</div>'
    panel = f'<table class="props">{"".join(props)}</table>' if props else ""
    return """<!doctype html><meta charset="utf-8">
<style>
:root { color-scheme: light dark; --fg: #222; --muted: #777; --line: #ddd; --code: #f3f3f3;
  --accent: #7c3aed; font: 15px/1.6 system-ui, sans-serif; }
@media (prefers-color-scheme: dark) { :root { --fg: #ddd; --muted: #999; --line: #3a3a3a;
  --code: #262626; --accent: #a78bfa; } }
body { margin: 0; padding: 8px 6px; color: var(--fg); }
.path { color: var(--muted); font-size: 12px; margin-bottom: 6px; }
table { border-collapse: collapse; margin: 8px 0; }
td, th { border: 1px solid var(--line); padding: 4px 10px; text-align: left; }
th { background: var(--code); }
.props { font-size: 13px; } .props td:first-child { color: var(--muted); }
.tag { display: inline-block; padding: 0 8px; margin: 1px 3px 1px 0; border-radius: 10px;
  background: color-mix(in srgb, var(--accent) 18%, transparent); color: var(--accent); }
h1, h2, h3, h4 { margin: 14px 0 6px; line-height: 1.25; } h1 { font-size: 1.6em; }
h2 { font-size: 1.3em; border-bottom: 1px solid var(--line); padding-bottom: 3px; }
code { background: var(--code); padding: 1px 5px; border-radius: 4px; font-size: .9em; }
pre { background: var(--code); padding: 10px; border-radius: 6px; overflow-x: auto; }
pre code { padding: 0; background: none; }
blockquote { margin: 8px 0; padding: 2px 12px; border-left: 3px solid var(--line); color: var(--muted); }
mark { background: #fde68a; color: #222; padding: 0 2px; }
.wl { color: var(--accent); }
.url, .img { color: var(--muted); font-size: .9em; }
ul, ol { padding-left: 22px; } li.task { list-style: none; margin-left: -20px; }
li.done { color: var(--muted); text-decoration: line-through; }
.box { display: inline-block; width: 18px; }
hr { border: 0; border-top: 1px solid var(--line); margin: 14px 0; }
.callout { margin: 10px 0; padding: 8px 12px; border-radius: 6px; border-left: 4px solid #3b82f6;
  background: color-mix(in srgb, #3b82f6 10%, transparent); }
.callout .ct { font-weight: 600; margin-bottom: 2px; }
.tip, .hint, .success { border-color: #10b981; background: color-mix(in srgb, #10b981 10%, transparent); }
.warning, .caution, .todo { border-color: #f59e0b; background: color-mix(in srgb, #f59e0b 10%, transparent); }
.danger, .bug, .failure { border-color: #ef4444; background: color-mix(in srgb, #ef4444 10%, transparent); }
.summary, .abstract, .example, .important { border-color: #8b5cf6; background: color-mix(in srgb, #8b5cf6 10%, transparent); }
.question, .quote { border-color: #6b7280; background: color-mix(in srgb, #6b7280 10%, transparent); }
</style>
""" + head + panel + "\n".join(_blocks(body)) + """
<script>
function height() {
  parent.postMessage({type: "iframe:height", height: document.documentElement.scrollHeight}, "*");
}
window.onload = height;
window.onresize = height;
</script>"""

class Tools:
    def __init__(self):
        # Env overrides exist for the tests; in the container the defaults are the mounts
        self.vault = Path(os.environ.get("JULZ_VAULT", "/data/julz-mem")).resolve()
        self.inbox = Path(os.environ.get("JULZ_INBOX", "/data/julz-mem/Inbox")).resolve()
        self.log_file = Path(os.environ.get("JULZ_LOG", "/data/julz-log/actions.log"))
        self._writes = []
        self._last_card = 0  # microsecond stamp of the last card's name (208)
        self._today = date.today

    # ---------- helpers ----------

    def _inside(self, root: Path, rel: str) -> Path:
        """Resolve rel under root and refuse anything that escapes it."""
        if not rel or rel.startswith(("/", "~")) or "\x00" in rel:
            raise ValueError("path must be relative to the vault")
        target = (root / rel).resolve()
        if not target.is_relative_to(root):
            raise ValueError("path is outside the vault")
        if any(part.startswith(".") for part in target.relative_to(root).parts):
            raise ValueError("hidden files and folders are off limits")
        if target.relative_to(root).parts[:2] == KEPT_CASES:
            raise ValueError("kept bad answers are off limits")
        if target.suffix != ".md":
            raise ValueError("only .md notes")
        return target

    def _notes(self):
        for p in sorted(self.vault.rglob("*.md")):
            rel = p.relative_to(self.vault)
            if any(part.startswith(".") for part in rel.parts) or rel.parts[:2] == KEPT_CASES:
                continue
            if p.is_symlink() or not p.resolve().is_relative_to(self.vault):
                continue
            yield p, rel

    @staticmethod
    def _words(text: str) -> list[str]:
        return [w for w in re.findall(r"\w+", text.lower()) if w not in STOP_WORDS]

    @staticmethod
    def _front(text: str) -> tuple[dict, str]:
        """Front matter (key: value lines between --- at the top) and the body after it.
        Tags may be [a, b] or one "- a" per line."""
        if not text.startswith("---\n"):
            return {}, text
        end = text.find("\n---", 3)
        if end == -1 or end > FRONT_MATTER_MAX:
            return {}, text
        meta, key = {}, None
        for line in text[4:end].splitlines():
            if line.lstrip().startswith("- ") and key:
                meta[key] = (meta[key] + ", " + line.strip()[2:]).strip(", ")
                continue
            key, sep, value = line.partition(":")
            key = key.strip().lower() if sep else None
            if key:
                meta[key] = value.strip()
        return meta, text[end + 4:]

    @staticmethod
    def _tags(meta: dict) -> list[str]:
        return [t.strip().lower() for t in meta.get("tags", "").strip("[]").split(",") if t.strip()]

    @classmethod
    def _first_line(cls, text: str) -> str:
        _, body = cls._front(text)
        return next((l.strip() for l in body.splitlines() if l.strip()), "")

    @staticmethod
    def _who(rel: Path) -> str:
        return {"Claude": "Claude wrote, I kept it", "Outbox": "a Claude report",
                "Inbox": "julz wrote, not reviewed",
                "Templates": "an Obsidian template",
                "feedback": "your feedback"}.get(rel.parts[0], "your note")

    def _find(self, query: str, roots: tuple = ()):
        """Notes ranked by how many of the words are in their path or title. An exact name
        only breaks a tie, so "dhcp lab" beats a note called dhcp.md; then notes (mine and
        kept ones) beat run reports and julz's unreviewed drafts. Returns the best ones:
        one means a clear winner, more means a real tie. roots limits it to those top folders."""
        words = self._words(query)
        if not words:
            return [], words
        joined = {" ".join(words), "-".join(words), "_".join(words), "".join(words)}
        scored = []
        for p, rel in self._notes():
            if roots and rel.parts[0] not in roots:
                continue
            if p.stat().st_size > MAX_NOTE_BYTES:
                continue
            title = self._first_line(p.read_text(encoding="utf-8", errors="replace"))
            hay = f"{rel} {title}".lower()
            hits = sum(w in hay for w in words)
            if hits:
                note = rel.parts[0] not in ("Outbox", "Inbox")
                scored.append(((hits, rel.stem.lower() in joined, note), rel, title))
        if not scored:
            return [], words
        best = max(s[0] for s in scored)
        return [(rel, title) for score, rel, title in scored if score == best], words

    def _log(self, action: str, **fields):
        entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "action": action, **fields}
        # Content is never logged, only names and sizes (threat 7)
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rate_limited(self) -> bool:
        now = time.monotonic()
        self._writes = [t for t in self._writes if now - t < 60]
        return len(self._writes) >= MAX_WRITES_PER_MINUTE

    def _resolve(self, note: str, roots: tuple = EDITABLE):
        """One existing note in one of roots, from a path or plain words, that a request may
        change. Returns (rel, None) or (None, the answer to give)."""
        note = note.strip()
        where = ", ".join(r + "/" for r in roots)
        if "/" in note or note.startswith((".", "~")):
            try:
                target = self._inside(self.vault, note)
            except ValueError as e:
                return None, f"Refused: {e}."
            rel = target.relative_to(self.vault)
            if rel.parts[0] not in roots:
                return None, f"Refused: julz can only change notes in {where}"
            if not target.is_file():
                return None, f"No note at {note}."
        else:
            found, _ = self._find(note, roots=roots)
            if not found:
                return None, f"No note matches '{note}' in {where}"
            if len(found) > 1:
                choices = "; ".join(str(rel) for rel, _ in found[:MAX_CHOICES])
                return None, (f"Several notes fit '{note}': {choices}. Ask the user which one, "
                              "then call again with its path.")
            rel = found[0][0]
        meta, _ = self._front((self.vault / rel).read_text(encoding="utf-8", errors="replace"))
        if meta.get("kind") == "moc":
            return None, (f"Refused: {rel} is an index julz-vault rebuilds from the folder. "
                          "Change the notes it lists instead.")
        return rel, None

    def _mine(self, note: str):
        return self._resolve(note, (MINE,))

    @staticmethod
    def _plain_error(text: str) -> str | None:
        if NOT_PLAIN.search(text) or any(
                ch not in "\n\t" and unicodedata.category(ch) in HIDDEN for ch in text):
            return ("Refused: links, images, HTML, web addresses and hidden characters cannot "
                    "go into notes. Write it as plain text.")
        return None

    @staticmethod
    def _folder(folder: str):
        """A folder julz may write into: a root of EDITABLE, one safe level below study/ or
        daily/. Returns (parts, None) or (None, the answer)."""
        parts = folder.strip().strip("/").split("/")
        roots = {r.lower(): r for r in EDITABLE}
        if not parts or parts[0].lower() not in roots or len(parts) > 2:
            return None, (f"Refused: notes go into Inbox, study, study/<folder>, daily or "
                          f"daily/<folder>, not '{folder}'.")
        parts[0] = roots[parts[0].lower()]
        if len(parts) == 2 and (parts[0] not in SUBFOLDERS_IN or not FOLDER.fullmatch(parts[1])):
            return None, ("Refused: a folder name is lowercase letters, digits and dashes, "
                          "directly in study/ or daily/.")
        return parts, None

    async def _confirm(self, __event_call__, title: str, message: str):
        """True on my click, False on Cancel, None when no dialog can show: the native chat
        has no browser and 0.11.4 answers with an error dict (208). None is falsy, so a caller
        asking only "yes?" still fails closed."""
        if __event_call__ is None:
            return None
        reply = await __event_call__({"type": "confirmation",
                                      "data": {"title": title, "message": message}})
        if reply is True:  # an error dict is truthy, so only True counts
            return True
        return False if reply is False else None

    @staticmethod
    def _why(ok) -> str:
        return "no dialog" if ok is None else "not confirmed"

    @staticmethod
    def _not_done(ok, answer: str) -> str:
        # "not confirmed" alone made her say a draft was waiting for my click (208)
        return answer + NO_DIALOG if ok is None else answer

    @staticmethod
    def _todo_items(body: str) -> list:
        items = [re.sub(r"^\s*(?:[-*+]\s*)?(?:\[[ xX]?\]\s*)?", "", l).strip()
                 for l in body.splitlines()]
        # A heading the model wrote above the tasks is not a task (126b); #tag stays.
        # Neither is a bare label like "Breakfast:", the phone check's six empty tasks (208)
        return [i for i in items if i and not re.match(r"#{1,6}(?:\s|$)", i)
                and not re.fullmatch(r"[^:]{1,40}\s*:", i)]

    def _shown(self, content: str, whole: bool = False) -> str:
        """The saved text as the user reads it. A reply leaves out the front matter, or she
        lists the tags and the date (209); the confirm dialog shows all of it (CWE-451)."""
        text = content if whole else self._front(content)[1].lstrip("\n")
        return text[:MAX_SHOWN_CHARS] + ("\n[...]" if len(text) > MAX_SHOWN_CHARS else "")

    def _build(self, kind: str, name: str, content: str, parts: list) -> str:
        """The note for a kind, built here so the small model only gives the words."""
        tags = [kind] + ([parts[1]] if len(parts) == 2 and parts[0] == MINE else [])
        front = ["---", "tags:", *[f"  - {t}" for t in tags],
                 f"created: {self._today().isoformat()}"]
        if kind in ("concept", "lab"):
            front.append("status: learning")
        front += ["---", ""]
        title = "# " + name[:1].upper() + name[1:]
        body = content.strip()
        if kind == "todo":
            sections = [title, "", "\n".join(f"- [ ] {i}" for i in self._todo_items(body))]
        elif kind == "concept":
            sections = [title, "", "## What it is", "", body, "", "## Example", "",
                        "## Why it matters", ""]
        elif kind == "lab":
            sections = [title, "", "## Goal", "", body, "", "## Steps", "", "## Result", ""]
        else:
            sections = [title, "", body]
        return "\n".join(front + sections).rstrip("\n") + "\n"

    def _request(self, payload: dict) -> None:
        """Drop a request for julz-vault. Written under a hidden name and renamed, so the
        host never reads half of one (CWE-362)."""
        folder = self.inbox / ".requests"
        folder.mkdir(mode=0o700, exist_ok=True)
        name = f"{int(time.time())}-{secrets.token_hex(4)}.json"
        tmp = folder / f".tmp-{name}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.rename(tmp, folder / name)

    def _ask_phone(self, action: str, payload: dict, what: str) -> str:
        """No dialog in this chat: drop the request as a proposal the approver shows as a card
        (208, threat 156). Never a request: only my signature on the phone makes one."""
        size = sum(len(payload.get(k, "")) for k in ("text", "old", "new")) + len(payload["note"])
        why = "too long for a card" if size > MAX_CARD - CARD_ROOM else None
        folder = self.inbox / ".proposals"
        if why is None:
            folder.mkdir(mode=0o700, exist_ok=True)
            waiting = 0
            for e in os.scandir(folder):
                m = PROPOSAL_NAME.fullmatch(e.name)
                if not m or not e.is_file(follow_symlinks=False):
                    continue
                if time.time() - int(m.group(1)) > PROPOSAL_TTL:
                    os.unlink(e.path)  # the approver no longer shows it either
                else:
                    waiting += 1
            if waiting >= MAX_PROPOSALS:
                why = "too many cards waiting"
        if why:
            self._log(f"{action}_refused", note=payload["note"], reason=why)
            return f"Not {what}: {NO_CARD[why]}." + NO_DIALOG
        # Named as julz_vault.write_request names them, so the approver lists them in the order
        # she asked; written under a hidden name and renamed (CWE-362)
        stamp = max(time.time_ns() // 1000, self._last_card + 1)
        self._last_card = stamp
        name = f"{stamp // 1_000_000}-{stamp % 16 ** 8:08x}.json"
        tmp = folder / f".tmp-{name}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.rename(tmp, folder / name)
        self._writes.append(time.monotonic())
        self._log(f"{action}_proposed", note=payload["note"])
        return f"Not {what}" + ON_THE_PHONE

    # ---------- tools the model can call ----------

    async def search_notes(self, query: str) -> str:
        """
        Search my notes by words in the file name or text, any order, any case. Use it to
        find which notes talk about a topic. It shows one line per note, never the whole
        note: to show a note, call read_note.
        :param query: words to look for, for example "nftables" or "dhcp lease"
        :return: matching note paths with the first matching line
        """
        words = self._words(query)
        if not words:
            return "Give me a word to search for."
        hits = []
        for p, rel in self._notes():
            if p.stat().st_size > MAX_NOTE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            hay = f"{rel}\n{text}".lower()
            if all(w in hay for w in words):
                body = self._front(text)[1]  # a tags: line is no answer to show
                line = next((l.strip() for l in body.splitlines() if words[0] in l.lower()), "")
                if not line:
                    # Only the name matched. A blank here read as "the note is empty" to
                    # julz (found 2026-10-16), so show its first line instead
                    line = f"(name matches) {self._first_line(text) or '(empty note)'}"
                hits.append(f"- {rel} ({self._who(rel)}): {line[:150]}")
            if len(hits) >= MAX_SEARCH_RESULTS:
                break
        return "\n".join(hits) if hits else f"No notes mention '{query}'."

    async def read_note(self, path: str) -> str:
        """
        Show one whole note. Call it whenever the user wants to see, open or read a note,
        and pass their own words, for example "dhcp", "dhcp lab" or "my subnetting note".
        Never ask the user for the exact file name. A path from search_notes works too.
        :param path: the user's words for the note, or a path like "study/dns.md"
        :return: the note text, or a short list to choose from when several fit
        """
        if "/" not in path and not path.strip().startswith((".", "~")):
            # Loose words (asked for 2026-10-16): find the note, never ask for its name
            found, words = self._find(path)
            if not found:
                return f"No note matches '{path}'. Try search_notes with other words."
            if len(found) > 1:
                choices = "; ".join(f"{rel} ({self._who(rel)}, {title[:60]})"
                                    for rel, title in found[:MAX_CHOICES])
                return (f"Several notes fit '{path}': {choices}. Pick the one the user means "
                        "from what they asked, or ask them, then call read_note with its path.")
            rel = found[0][0]
            target = self._inside(self.vault, str(rel))
            return self._show(rel, target, f"# {rel} ({self._who(rel)}), opened for '{path}'")
        try:
            target = self._inside(self.vault, path)
        except ValueError as e:
            return f"Refused: {e}."
        if not target.is_file():
            return f"No note at {path}. Try search_notes first."
        rel = target.relative_to(self.vault)
        return self._show(rel, target, f"# {path}")

    def _show(self, rel: Path, target: Path, header: str):
        """The note as text for julz, and inside Open WebUI rendered for me as well."""
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n[truncated]"
        context = f"{header}\n\n{text}"
        try:
            from fastapi.responses import HTMLResponse
        except ImportError:
            return context
        embed = HTMLResponse(content=note_html(str(rel), self._who(rel), text),
                             headers={"Content-Disposition": "inline"})
        # Said from julz's side as a done fact: "the user sees it" made the 4B model believe
        # someone else opened it, and it told me it cannot open notes (found 2026-10-16)
        return embed, (f"You already opened {rel} with read_note and it is now on the user's "
                       "screen, rendered. Reply in one or two sentences: what it covers, or the "
                       "answer to their question. Never say you cannot open notes, never tell "
                       "the user to run a command, do not repeat the note.\n\n" + context)

    async def list_notes(self, topic: str = "") -> str:
        """
        List my notes with who wrote each one, its title and how well I know it. Use it when
        the user asks what notes they have, or what they have on a topic.
        :param topic: optional words like "network-plus" or "dhcp"; empty lists everything
        :return: one line per note
        """
        words = self._words(topic)
        lines = []
        for p, rel in self._notes():
            if p.stat().st_size > MAX_NOTE_BYTES:
                continue
            meta, body = self._front(p.read_text(encoding="utf-8", errors="replace"))
            if words:
                hay = " ".join([str(rel).lower(), *self._tags(meta)])
                if not all(w in hay for w in words):
                    continue
            if len(lines) >= MAX_LIST:
                lines.append("[more notes not shown, ask with a topic]")
                break
            status = meta.get("status", "")
            who = self._who(rel) + (f", {status}" if status else "")
            title = next((l.strip() for l in body.splitlines() if l.strip()), "")
            lines.append(f"- {rel} ({who}): {title[:80]}")
        if not lines:
            return f"No notes about '{topic}'." if words else "No notes yet."
        return "\n".join(lines)

    async def due_notes(self) -> str:
        """
        Pick my own notes that are due for review, most overdue first. Use it when the user
        wants to refresh their memory, revise or be quizzed and does not name a topic.
        :return: the notes to quiz on, and what to do next
        """
        today = self._today()
        due = []
        for p, rel in self._notes():
            if rel.parts[0] != MINE or p.stat().st_size > MAX_NOTE_BYTES:
                continue
            meta, body = self._front(p.read_text(encoding="utf-8", errors="replace"))
            if meta.get("kind") == "moc":
                continue  # an index, nothing to learn in it
            every = REVIEW_DAYS.get(meta.get("status", "").lower(), DEFAULT_REVIEW_DAYS)
            try:
                last = date.fromisoformat(meta.get("reviewed", ""))
                overdue = (today - last).days - every
                when = f"last reviewed {last.isoformat()}"
            except ValueError:
                overdue, when = 10**6, "never reviewed"
            if overdue >= 0:
                title = next((l.strip() for l in body.splitlines() if l.strip()), "")
                due.append((overdue, str(rel), f"- {rel} ({when}): {title[:80]}"))
        if not due:
            return "Nothing is due for review today."
        due.sort(key=lambda d: (-d[0], d[1]))
        lines = [d[2] for d in due[:MAX_DUE]]
        return ("Due for review:\n" + "\n".join(lines) + "\nRead one with read_note, quiz the "
                "user one question at a time without showing the note, and when they know it, "
                "call mark_reviewed with its path.")

    async def show_folders(self) -> str:
        """
        Show the folders of my notes, how many notes each holds and what each is for. Use it
        when the user asks where things are, what folders they have or how notes are organized.
        :return: a folder tree with note counts
        """
        def count(d: Path) -> str:
            n = sum(1 for p, rel in self._notes() if p.is_relative_to(d))
            return f"{n} note" if n == 1 else f"{n} notes"

        def subdirs(d: Path):
            return sorted((e for e in os.scandir(d) if e.is_dir(follow_symlinks=False)
                           and not e.name.startswith(".")), key=lambda e: e.name)

        lines = []
        for top in subdirs(self.vault):
            role = ROLES.get(top.name, "")
            lines.append(f"{top.name}/ ({count(Path(top.path))})" + (f": {role}" if role else ""))
            for sub in subdirs(top.path):
                lines.append(f"  {sub.name}/ ({count(Path(sub.path))})")
        return "\n".join(lines) if lines else "The vault has no folders yet."

    async def recent_notes(self, days: int = 7) -> str:
        """
        Notes created or changed lately, newest first, with where they are. Use it when the
        user asks what was saved, created or changed recently, or where a new note went.
        :param days: how many days back, 7 if not given
        :return: one line per note with date and folder
        """
        try:
            days = max(1, min(int(days), 365))
        except (TypeError, ValueError):
            days = 7
        cutoff = time.time() - days * 86400
        items = sorted(((p.stat().st_mtime, rel) for p, rel in self._notes()
                        if p.stat().st_mtime >= cutoff), reverse=True)
        if not items:
            return f"Nothing changed in the last {days} days."
        lines = []
        for m, rel in items[:MAX_RECENT]:
            meta, _ = self._front((self.vault / rel).read_text(encoding="utf-8", errors="replace"))
            who = "index made by julz-vault" if meta.get("kind") == "moc" else self._who(rel)
            lines.append(f"- {datetime.fromtimestamp(m).strftime('%Y-%m-%d %H:%M')} {rel} ({who})")
        return "\n".join(lines)

    def _open_tasks(self) -> list:
        """Every open task on every list, in path then line order: the numbers show_todos
        prints and tick_task takes."""
        tasks = []
        for p, rel in self._notes():
            if rel.parts[0] not in TASK_ROOTS or rel.parts[:2] == ("daily", "done") \
                    or p.stat().st_size > MAX_NOTE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            tasks += [(rel, i) for i in OPEN_TASK.findall(text)]
        return tasks

    async def show_todos(self) -> str:
        """
        Show every open task as a checklist the user can tick, numbered, grouped by list. Use it
        for "what's on my list", "show my todos". Ticked boxes come back as "done 1, 3".
        :return: the numbered open tasks
        """
        tasks = self._open_tasks()[:MAX_LIST]
        if not tasks:
            return "No open tasks."
        lines, current = [], None
        for n, (rel, item) in enumerate(tasks, 1):
            if rel != current:
                lines.append(f"{rel}:")
                current = rel
            lines.append(f"  {n}. {item}")
        text = "\n".join(lines)
        # inside Open WebUI: a checklist I can tick. Anywhere else: the numbered text
        embed = _embed(checklist_html(tasks))
        if embed is None:
            return (text + "\nShow this list as it is. The user answers with numbers, "
                    "like 'done 2 and 4': then call tick_task with those numbers.")
        return embed, ("You already showed the user their open tasks as a checklist they can "
                       "tick. Say in one sentence how many are open. When a message like 'done "
                       "1, 3' comes, call tick_task with those numbers. Never say you cannot show "
                       "tasks, do not repeat the list.\n" + text)

    async def _tick_numbers(self, task: str) -> str:
        tasks = self._open_tasks()
        numbers = [int(n) for n in re.findall(r"\d+", task)]
        missing = [n for n in numbers if not 1 <= n <= len(tasks)]
        if missing:
            return (f"No task {', '.join(map(str, missing))}: the list has {len(tasks)}. "
                    "Nothing ticked. Show the list again with show_todos.")
        ticked = []
        for n in dict.fromkeys(numbers):
            rel, item = tasks[n - 1]
            if len(item) > MAX_ITEM or self._plain_error(item):
                return f"Refused: task {n} is too long or not plain text. Tick it in Obsidian."
            if self._rate_limited():
                return "Refused: too many changes in the last minute."
            self._request({"op": "tick", "note": str(rel), "item": item})
            self._writes.append(time.monotonic())
            self._log("tick_task", note=str(rel))
            ticked.append(f"{item} ({rel})")
        return "Ticked: " + "; ".join(ticked) + "."

    async def tick_task(self, task: str, note: str = "") -> str:
        """
        Tick one open task (a "- [ ]" line) as done. Call it whenever the user says they did
        something ("I bought milk", "booked the physio"), even if you do not know which list it
        is on: leave note empty and it searches every open task.
        :param task: a few words of the task, like "milk", or numbers from show_todos, like "2, 4"
        :param note: the todo note if known, like "daily/physio.md"; empty searches all lists
        :return: what happened
        """
        bare = re.sub(r"^\s*(?:done|tick|ticked|check|checked)\b\s*:?", "", task, flags=re.I)
        if not note.strip() and NUMBERS.fullmatch(bare):
            return await self._tick_numbers(bare)
        words = self._words(task)
        if not words:
            return "Refused: say which task, in a few words."
        if note.strip():
            rel, answer = self._resolve(note, TASK_ROOTS)
            if answer:
                return answer
            places = [rel]
        else:
            places = [rel for p, rel in self._notes() if rel.parts[0] in TASK_ROOTS
                      and rel.parts[:2] != ("daily", "done") and p.stat().st_size <= MAX_NOTE_BYTES]
        hits = []
        for rel in places:
            text = (self.vault / rel).read_text(encoding="utf-8", errors="replace")
            hits += [(rel, i) for i in OPEN_TASK.findall(text)
                     if all(w in i.lower() for w in words)]
        if not hits:
            where = f"in {places[0]}" if note.strip() else "on any list"
            return (f"No open task mentions '{task}' {where}. Ask if they want it added as a "
                    "new todo, already ticked.")
        if len(hits) > 1:
            return (f"Several open tasks fit '{task}': "
                    + "; ".join(f"{i} ({rel})" for rel, i in hits[:MAX_CHOICES]) + ". Ask which one.")
        rel, item = hits[0]
        if len(item) > MAX_ITEM or self._plain_error(item):
            return "Refused: that task line is too long or not plain text. Tick it in Obsidian."
        if self._rate_limited():
            return "Refused: too many changes in the last minute."
        self._request({"op": "tick", "note": str(rel), "item": item})
        self._writes.append(time.monotonic())
        self._log("tick_task", note=str(rel))
        return f"Ticked '{item}' in {rel}. When every task is ticked, the note moves to daily/done."

    async def done_tasks(self, days: int = 7) -> str:
        """
        What the user got done lately: ticked tasks and finished todo notes, newest first. Use it
        for "what did I do this week", "what did I finish this month".
        :param days: how many days back, 7 for a week, 30 for a month
        :return: one line per finished task with its date
        """
        try:
            days = max(1, min(int(days), 366))
        except (TypeError, ValueError):
            days = 7
        since = self._today() - timedelta(days=days - 1)
        done = []
        for p, rel in self._notes():
            if rel.parts[0] not in TASK_ROOTS or p.stat().st_size > MAX_NOTE_BYTES:
                continue
            meta, body = self._front(p.read_text(encoding="utf-8", errors="replace"))
            for item, when in DONE_TASK.findall(body):
                try:
                    d = date.fromisoformat(when)
                except ValueError:
                    continue
                if d >= since:
                    done.append((d, item, rel))
            try:
                d = date.fromisoformat(meta.get("completed", ""))
            except ValueError:
                d = None
            if d and d >= since:
                title = next((l.strip("# ").strip() for l in body.splitlines() if l.strip()), "")
                done.append((d, f"finished the list: {title}", rel))
        if not done:
            return f"Nothing done in the last {days} days."
        done.sort(key=lambda x: x[0], reverse=True)
        done = done[:MAX_LIST]
        text = "\n".join(f"- {d.isoformat()} {item} ({rel})" for d, item, rel in done)
        embed = _embed(done_html(done))
        if embed is None:
            return text + "\nShow every line as it is, each task with its date."
        return embed, (f"You already showed the user what they got done in the last {days} "
                       "days, each task with its date. Say in one or two sentences how much "
                       "they did and praise one thing, do not repeat the list.\n" + text)

    async def save_feedback(self, text: str, __event_call__=None) -> str:
        """
        Save the user's feedback about you, the assistant (what you do badly, what to change),
        for Claude Code to read at the start of the next session. The user confirms it first.
        Use it when the user complains about how you behave in general, even without the word
        feedback: "you always forget my notes", "stop adding emoji from now on". Not for a
        change to the answer you just gave (shorter, another format, a better example): just
        give that answer, with no tool.
        :param text: the feedback in the user's own words
        :return: what happened
        """
        if not text.strip():
            return "Refused: there is no feedback to save."
        if len(text) > MAX_APPEND_CHARS:
            return f"Refused: at most {MAX_APPEND_CHARS} characters."
        error = self._plain_error(text)
        if error:
            return error
        today = self._today().isoformat()
        slug = "-".join(re.findall(r"[a-z0-9]+", text.lower())[:5])[:40] or "note"
        rel = f"feedback/{today} {slug}.md"
        n = 2
        while os.path.lexists(self.vault / rel):
            rel = f"feedback/{today} {slug}-{n}.md"
            n += 1
        if self._rate_limited():
            return "Refused: too many changes in the last minute."
        ok = await self._confirm(__event_call__, "Julz wants to save feedback for Claude Code",
                                 f"Save this for Claude Code to read next session?\n\n{text}")
        content = (f"---\ntags:\n  - feedback\ncreated: {today}\n---\n\n# Feedback {today}\n\n"
                   f"{text.strip()}\n")
        if ok is None:
            return self._ask_phone("save_feedback", {"op": "create", "note": rel, "text": content}, "saved")
        if not ok:
            self._log("save_feedback_refused", reason=self._why(ok))
            return self._not_done(ok, "Not saved: the feedback was not confirmed.")
        self._request({"op": "create", "note": rel, "text": content})
        self._writes.append(time.monotonic())
        self._log("save_feedback", note=rel)
        return f"Saved {rel}. Claude Code reads it at the start of the next session."

    def _open_feedback(self) -> list:
        """Open feedback notes, oldest first, as (path, first line of text): the numbers
        show_feedback prints and resolve_feedback takes. feedback/done/ is left out."""
        base = self.vault / "feedback"
        if not base.is_dir() or base.is_symlink():
            return []
        found = []
        for p in sorted(base.glob("*.md")):
            if p.name.startswith(".") or p.is_symlink() or not p.is_file() \
                    or p.stat().st_size > MAX_NOTE_BYTES:
                continue
            _, body = self._front(p.read_text(encoding="utf-8", errors="replace"))
            line = next((l.strip() for l in body.splitlines()
                         if l.strip() and not l.lstrip().startswith("#")), p.stem)
            found.append((p.relative_to(self.vault), line[:FEEDBACK_SHOWN]))
        return found

    async def show_feedback(self) -> str:
        """
        Show the user's open feedback about julz as a numbered checklist they can tick as
        solved. Use it for "show my feedback", "what did I complain about".
        :return: the numbered open feedback
        """
        notes = self._open_feedback()[:MAX_LIST]
        if not notes:
            return "No open feedback."
        text = "\n".join(f"{n}. {line} ({rel.stem[:10]})" for n, (rel, line) in enumerate(notes, 1))
        embed = _embed(checklist_html([(rel.stem[:10], line) for rel, line in notes], "solved"))
        if embed is None:
            return (text + "\nShow this list as it is. The user answers like 'solved 2': then "
                    "call resolve_feedback with those numbers.")
        return embed, ("You already showed the user their open feedback as a checklist. Say in "
                       "one sentence how many are open. When a message like 'solved 1, 3' "
                       "comes, call resolve_feedback with those numbers. Do not repeat the "
                       "list.\n" + text)

    @staticmethod
    def _my_last_message(messages) -> str:
        """The user's own last message: tool results and notes never sit there (threat 85)."""
        for m in reversed(messages or []):
            if isinstance(m, dict) and m.get("role") == "user":
                content = m.get("content")
                if isinstance(content, list):
                    content = " ".join(c.get("text", "") for c in content
                                       if isinstance(c, dict) and c.get("type") == "text")
                return content if isinstance(content, str) else ""
        return ""

    @classmethod
    def _my_last_words(cls, messages) -> str:
        """The first line of my last message, the only place a solve may come from."""
        return cls._my_last_message(messages).split("\n", 1)[0]

    @classmethod
    def _made_up(cls, tasks: list, messages) -> list:
        """Tasks with a word that is not in my last message, or with no word at all (threat
        140). A word matches mine exactly, or by its first four letters ("packing" for
        "pack"); a short one only exactly, so "rm -rf" is never mine by accident."""
        mine = set(re.findall(r"[^\W\d_]+", cls._my_last_message(messages).lower()))
        stems = {w[:4] for w in mine if len(w) >= 4}

        def said(w):
            return w in FILLERS or w in mine or (len(w) >= 4 and w[:4] in stems)
        made_up = []
        for t in tasks:
            words = re.findall(r"[^\W\d_]+", t.lower())
            if not words or not all(said(w) for w in words):
                made_up.append(t)
        return made_up

    async def resolve_feedback(self, numbers: str, __messages__=None) -> str:
        """
        Mark feedback notes as solved, so they leave the list. Call it only right after the
        user's message "solved 1, 3", with those numbers.
        :param numbers: the numbers from show_feedback, like "1, 3"
        :return: what happened
        """
        said = SOLVED.fullmatch(self._my_last_words(__messages__))
        wanted = [int(n) for n in re.findall(r"\d+", str(numbers))]
        if not said or not wanted or set(wanted) != {int(n) for n in re.findall(r"\d+", said[1])}:
            self._log("resolve_feedback_refused", reason="not the user's own words")
            return ("Refused: feedback is solved only when the user's own last message is "
                    "'solved' and the numbers, like 'solved 1, 3'. Ask them to tick it in the list.")
        notes = self._open_feedback()
        missing = [n for n in wanted if not 1 <= n <= len(notes)]
        if missing:
            return (f"No feedback {', '.join(map(str, missing))}: the list has {len(notes)}. "
                    "Nothing solved. Show the list again with show_feedback.")
        solved = []
        for n in dict.fromkeys(wanted):
            if self._rate_limited():
                return "Refused: too many changes in the last minute."
            rel, line = notes[n - 1]
            self._request({"op": "resolve", "note": str(rel)})
            self._writes.append(time.monotonic())
            self._log("resolve_feedback", note=str(rel))
            solved.append(line)
        return "Solved and moved to feedback/done: " + "; ".join(solved) + "."

    async def mark_reviewed(self, note: str) -> str:
        """
        Record that the user just reviewed one of their own notes, so it comes back later.
        Call it after a quiz on that note went well.
        :param note: the note's path, like "study/network-plus/dhcp.md", or the user's words
        :return: what happened
        """
        rel, answer = self._mine(note)
        if answer:
            return answer
        if self._rate_limited():
            return "Refused: too many changes in the last minute."
        self._request({"op": "reviewed", "note": str(rel)})
        self._writes.append(time.monotonic())
        self._log("mark_reviewed", note=str(rel))
        return f"Marked {rel} as reviewed today."

    async def append_note(self, note: str, text: str, __event_call__=None,
                          __messages__=None) -> str:
        """
        Add text to the end of one of the user's notes, after they confirm it. Use it when
        the user asks to add, append or save something into an existing note. It never
        changes or removes what is already there. Plain text only, no links or HTML.
        :param note: the note's path, like "daily/week.md", or the user's words for it
        :param text: the text to add, readable markdown (lists, a table, a "> [!tip]" callout),
            no HTML or links
        :return: what happened
        """
        if not text.strip():
            return "Refused: there is nothing to add."
        if len(text) > MAX_APPEND_CHARS:
            return f"Refused: at most {MAX_APPEND_CHARS} characters at a time."
        error = self._plain_error(text)
        if error:
            return error
        rel, answer = self._resolve(note)
        if answer:
            return answer
        # Her study answers went into daily/ as cards I never asked for (158)
        mine = self._my_last_message(__messages__)
        if not (ADD_WORD.search(mine) or SAVE_WORD.search(mine)):
            self._log("append_note_refused", note=str(rel), reason="no add word")
            return ("Refused: text is added to a note only when the user asks for it in their "
                    "last message (add, append, save). Nothing was added. If it may help, ask "
                    "them whether to add it.")
        if self._rate_limited():
            return "Refused: too many changes in the last minute."
        ok = await self._confirm(__event_call__, "Julz wants to add to your note",
                                 f"Add this to the end of {rel}?\n\n{text}")
        if ok is None:
            return self._ask_phone("append_note", {"op": "append", "note": str(rel), "text": text}, "added")
        if not ok:
            self._log("append_note_refused", note=str(rel), reason=self._why(ok))
            return self._not_done(ok, f"Not added: the addition to {rel} was not confirmed.")
        self._request({"op": "append", "note": str(rel), "text": text})
        self._writes.append(time.monotonic())
        self._log("append_note", note=str(rel), chars=len(text))
        return (f"Added to the end of {rel} under a dated heading, in a few seconds. "
                "Nothing else in the note changed.")

    async def edit_note(self, note: str, old_text: str, new_text: str, __event_call__=None) -> str:
        """
        Change one passage of a note: replace old_text with new_text, or remove it when
        new_text is empty. old_text must be copied exactly from the note (read it first) and
        appear only once. The user sees before and after and confirms. Use it to fix, shorten,
        cut or reword part of a note; never pass the whole note.
        :param note: the note's path, like "study/network-plus/dhcp.md", or the user's words
        :param old_text: the exact passage now in the note
        :param new_text: what replaces it; empty removes the passage
        :return: what happened
        """
        if not old_text:
            return "Refused: give the exact passage to change, copied from the note."
        if len(old_text) > MAX_APPEND_CHARS or len(new_text) > MAX_APPEND_CHARS:
            return f"Refused: at most {MAX_APPEND_CHARS} characters on each side."
        error = new_text and self._plain_error(new_text)
        if error:
            return error
        rel, answer = self._resolve(note)
        if answer:
            return answer
        raw = (self.vault / rel).read_bytes()
        found = raw.decode("utf-8", errors="replace").count(old_text)
        if found == 0:
            return (f"Refused: that passage is not in {rel}. Read the note and copy the exact "
                    "words.")
        if found > 1:
            return f"Refused: that passage is in {rel} {found} times. Include more words around it."
        if self._rate_limited():
            return "Refused: too many changes in the last minute."
        ok = await self._confirm(__event_call__, "Julz wants to change your note",
                                 f"Change {rel}?\n\nBefore:\n{old_text}\n\n"
                                 f"After:\n{new_text or '(removed)'}")
        req = {"op": "replace", "note": str(rel), "old": old_text, "new": new_text,
               "sha256": hashlib.sha256(raw).hexdigest()}
        if ok is None:
            return self._ask_phone("edit_note", req, "changed")
        if not ok:
            self._log("edit_note_refused", note=str(rel), reason=self._why(ok))
            return self._not_done(ok, f"Not changed: the change to {rel} was not confirmed.")
        self._request(req)
        self._writes.append(time.monotonic())
        self._log("edit_note", note=str(rel), removed=len(old_text), added=len(new_text))
        return f"Changed {rel} in a few seconds. Only that passage changed."

    async def move_note(self, note: str, to: str, __event_call__=None) -> str:
        """
        Move or rename a note, after the user confirms. Use it to file an Inbox note away
        ("move physio to daily"), sort notes into folders or rename one. A move never replaces
        another note.
        :param note: the note's path or the user's words for it
        :param to: a folder like "daily" or "study/linux", or a new path like "study/linux/nft.md"
        :return: what happened
        """
        rel, answer = self._resolve(note)
        if answer:
            return answer
        to = to.strip().strip("/")
        folder, _, name = to.rpartition("/") if to.endswith(".md") else (to, "", rel.name)
        parts, answer = self._folder(folder)
        if answer:
            return answer
        stem = name[:-3] if name.endswith(".md") else ""
        if not stem or not SAFE_NAME.match(stem) or ".." in stem:
            return "Refused: a note name is letters, digits, spaces, dashes or underscores."
        dest = "/".join([*parts, stem + ".md"])
        if dest == str(rel) or os.path.lexists(self.vault / dest):
            return f"Refused: {dest} already exists. A move never replaces a note."
        if self._rate_limited():
            return "Refused: too many changes in the last minute."
        ok = await self._confirm(__event_call__, "Julz wants to move a note",
                                 f"Move {rel} to {dest}?")
        raw = (self.vault / rel).read_bytes()
        req = {"op": "move", "note": str(rel), "to": dest, "sha256": hashlib.sha256(raw).hexdigest()}
        if ok is None:
            return self._ask_phone("move_note", req, "moved")
        if not ok:
            self._log("move_note_refused", note=str(rel), reason=self._why(ok))
            return self._not_done(ok, f"Not moved: moving {rel} was not confirmed.")
        self._request(req)
        self._writes.append(time.monotonic())
        self._log("move_note", note=str(rel), to=dest)
        return f"Moved {rel} to {dest}, in a few seconds."

    async def delete_note(self, note: str, __event_call__=None) -> str:
        """
        Delete a note, after the user confirms. Git keeps a copy, so it can be restored on the
        laptop. Use it only when the user asks to delete or remove a note.
        :param note: the note's path or the user's words for it
        :return: what happened
        """
        rel, answer = self._resolve(note)
        if answer:
            return answer
        if self._rate_limited():
            return "Refused: too many changes in the last minute."
        ok = await self._confirm(__event_call__, "Julz wants to delete a note",
                                 f"Delete {rel}? git keeps a copy, so it can be restored.")
        raw = (self.vault / rel).read_bytes()
        req = {"op": "delete", "note": str(rel), "sha256": hashlib.sha256(raw).hexdigest()}
        if ok is None:
            return self._ask_phone("delete_note", req, "deleted")
        if not ok:
            self._log("delete_note_refused", note=str(rel), reason=self._why(ok))
            return self._not_done(ok, f"Not deleted: deleting {rel} was not confirmed.")
        self._request(req)
        self._writes.append(time.monotonic())
        self._log("delete_note", note=str(rel))
        return f"Deleted {rel}, in a few seconds. It can be restored from git on the laptop."

    async def create_note(self, name: str, content: str, kind: str = "", folder: str = "Inbox",
                          __event_call__=None, __messages__=None) -> str:
        """
        Save a new note, only when the user asks to save, note or write something down ("make
        a note", "save this", "запиши"). Never to keep your own answer or an explanation you
        gave. By default it goes into the Inbox. Save what the user said in their own words;
        do not invent lines. Pick a kind and the code adds the right headings:
        "todo" (each line becomes a checkbox), "thought", "concept" (a study topic), "lab".
        Outside the Inbox the user confirms first.
        :param name: short file name without folders, for example "physio review"
        :param content: the user's own words, in readable markdown: ## headings for parts, a
            table for comparisons, - lists, a "> [!tip] Key point" callout. No HTML or links.
            For "todo", only the tasks the user named, one a line; if they named none, ask
            them which tasks first and do not call this
        :param kind: "todo", "thought", "concept", "lab", or empty for plain text
        :param folder: "Inbox" (default), "daily", "study" or "study/<cert>" like "study/linux"
        :return: what happened, with the saved text
        """
        name = name.strip()
        if name.lower().endswith(".md"):
            name = name[:-3]
        if not SAFE_NAME.match(name) or ".." in name:
            # Logged too: with no entry it looked as if she never called it (208, phone 24 Oct)
            self._log("create_note_refused", note=name[:80], reason="bad name")
            return ("Refused: use a plain name with letters, digits, spaces, dashes or underscores, "
                    "no folders (pick the place with folder). Nothing was saved.")
        kind = kind.strip().lower()
        if kind and kind not in KINDS:
            return f"Refused: kind is one of {', '.join(KINDS)}, or empty."
        if kind == "todo" and not self._todo_items(content):
            return ("Refused: a to-do list needs tasks, and none were given. Nothing was saved. "
                    "Ask the user which tasks go on it; do not make any up.")
        if kind == "todo":
            # Words alone did not stop her inventing tasks (208); a page could plant one too
            made_up = self._made_up(self._todo_items(content), __messages__)
            if made_up or not self._my_last_message(__messages__):
                self._log("create_note_refused", note=name, reason="tasks not in my message")
                return ("Refused: a to-do list holds only tasks the user named in their last "
                        "message, in their words. Nothing was saved. Not named by them: "
                        + ("; ".join(made_up) or "any, no message of theirs was found") + ". Save only their tasks, or ask them which "
                        "tasks go on it.")
        parts, answer = self._folder(folder or "Inbox")
        if answer:
            return answer
        if kind:
            content = self._build(kind, name, content, parts)
        data = content.encode("utf-8")
        if len(data) > MAX_NOTE_BYTES:
            return f"Refused: note is over {MAX_NOTE_BYTES // 1000} KB."
        if self._rate_limited():
            return "Refused: too many notes in the last minute."
        if parts != ["Inbox"]:
            # A card I never asked for is noise I learn to sign unread (158, threat 161)
            if not SAVE_WORD.search(self._my_last_message(__messages__)):
                self._log("create_note_refused", note="/".join(parts + [name]), reason="no save word")
                return self._not_asked()
            return await self._create_elsewhere(name, content, parts, self._shown(content, whole=True),
                                                __event_call__)
        try:
            target = self._inside(self.inbox, name + ".md")
        except ValueError as e:
            return f"Refused: {e}."
        rel = target.relative_to(self.vault)

        if target.exists():
            if target.is_symlink() or not target.is_file():
                return "Refused: that name is not a normal note."
            ok = await self._confirm(__event_call__, "Julz wants to overwrite a note",
                                     f"Replace {rel}? The old text will be lost.")
            if not ok:
                self._log("create_note_refused", note=str(rel), reason=self._why(ok))
                return self._not_done(ok, f"Not saved: {rel} already exists and the overwrite "
                                          f"was not confirmed.")
            action = "overwrite_note"
        else:
            # Docstrings alone did not stop her saving her own answers (158)
            if not SAVE_WORD.search(self._my_last_message(__messages__)):
                self._log("create_note_refused", note=str(rel), reason="no save word")
                return self._not_asked()
            action = "create_note"

        # O_NOFOLLOW: never write through a symlink swapped in after the checks above
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        fd = os.open(target, flags, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        self._writes.append(time.monotonic())
        self._log(action, note=str(rel), bytes=len(data))
        # "Saved" alone read as a note already there: she called her own new one a draft (208)
        made = "over the old note" if action == "overwrite_note" else (
            "as a new note, made just now; nothing was there before")
        # The user cannot open Inbox from the chat, so the answer carries the exact text
        return (f"Saved {rel} {made} ({len(data)} bytes). Show the user this saved text as it "
                f"is, and say it is in {rel}:\n\n{self._shown(content)}")

    @staticmethod
    def _not_asked() -> str:
        return ("Refused: a new note is saved only when the user asks for it in their last "
                "message (save, note this, write down). Nothing was saved. Do not save your "
                "own answers; if the user wants this kept, they can say save.")

    async def _create_elsewhere(self, name, content, parts, shown, __event_call__) -> str:
        """A new note in study/ or daily/: the host writes it, after my click (threat 74)."""
        error = self._plain_error(content)
        if error:
            return error
        rel = "/".join([*parts, name + ".md"])
        if os.path.lexists(self.vault / rel):
            return f"Refused: {rel} already exists. Use append_note or edit_note to change it."
        ok = await self._confirm(__event_call__, "Julz wants to create a note",
                                 f"Create {rel}?\n\n{shown}")
        if ok is None:
            return self._ask_phone("create_note", {"op": "create", "note": rel, "text": content}, "saved")
        if not ok:
            self._log("create_note_refused", note=rel, reason="not confirmed")
            return f"Not saved: creating {rel} was not confirmed."
        self._request({"op": "create", "note": rel, "text": content})
        self._writes.append(time.monotonic())
        self._log("create_note", note=rel, bytes=len(content.encode("utf-8")))
        return (f"Saved {rel} as a new note, in a few seconds; nothing was there before. Show "
                f"the user this saved text as it is, and say it is in {rel}:\n\n"
                f"{self._shown(content)}")
