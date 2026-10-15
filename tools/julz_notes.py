"""
title: Julz notes
description: Search, read and create notes in the julz-mem vault. New notes go to Inbox only.
version: 0.1.0
"""
# Paste this file into Open WebUI: Workspace, Tools, +. No third party imports on purpose.
# Security model (SECURITY.md threats 1, 4, 13):
# - every path is resolved and must stay inside its root (CWE-22), symlinks included
# - writes only into Inbox, as new .md files; overwriting needs MY click in the browser,
#   the model cannot confirm for me (LLM06 Excessive Agency)
# - size and rate limits, and every write is appended to the action log
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

MAX_NOTE_BYTES = 100_000
MAX_READ_CHARS = 20_000
MAX_WRITES_PER_MINUTE = 10
MAX_SEARCH_RESULTS = 10
# Letters (any language), digits, space, dash, underscore, dot. No slashes, so no folders.
SAFE_NAME = re.compile(r"^[\w][\w \-.]{0,99}$")


class Tools:
    def __init__(self):
        # Env overrides exist for the tests; in the container the defaults are the mounts
        self.vault = Path(os.environ.get("JULZ_VAULT", "/data/julz-mem")).resolve()
        self.inbox = Path(os.environ.get("JULZ_INBOX", "/data/julz-mem/Inbox")).resolve()
        self.log_file = Path(os.environ.get("JULZ_LOG", "/data/julz-log/actions.log"))
        self._writes = []

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
        if target.suffix != ".md":
            raise ValueError("only .md notes")
        return target

    def _notes(self):
        for p in sorted(self.vault.rglob("*.md")):
            rel = p.relative_to(self.vault)
            if any(part.startswith(".") for part in rel.parts):
                continue
            if p.is_symlink() or not p.resolve().is_relative_to(self.vault):
                continue
            yield p, rel

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

    # ---------- tools the model can call ----------

    async def search_notes(self, query: str) -> str:
        """
        Search my notes by words in the file name or text. Use it to find which note
        talks about a topic before reading it.
        :param query: words to look for, for example "nftables" or "subnet"
        :return: matching note paths with the first matching line
        """
        q = query.strip().lower()
        if not q:
            return "Give me a word to search for."
        hits = []
        for p, rel in self._notes():
            if p.stat().st_size > MAX_NOTE_BYTES:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            if q in str(rel).lower() or q in text.lower():
                line = next((l.strip() for l in text.splitlines() if q in l.lower()), "")
                hits.append(f"- {rel}: {line[:150]}")
            if len(hits) >= MAX_SEARCH_RESULTS:
                break
        return "\n".join(hits) if hits else f"No notes mention '{query}'."

    async def read_note(self, path: str) -> str:
        """
        Read one whole note from my vault. Use the path exactly as search_notes shows it.
        :param path: note path relative to the vault, for example "study/dns.md"
        :return: the note text
        """
        try:
            target = self._inside(self.vault, path)
        except ValueError as e:
            return f"Refused: {e}."
        if not target.is_file():
            return f"No note at {path}. Try search_notes first."
        text = target.read_text(encoding="utf-8", errors="replace")
        if len(text) > MAX_READ_CHARS:
            text = text[:MAX_READ_CHARS] + "\n[truncated]"
        return f"# {path}\n\n{text}"

    async def create_note(self, name: str, content: str, __event_call__=None) -> str:
        """
        Save a new note into my Inbox. If a note with that name exists, I will be asked
        to confirm before it is replaced.
        :param name: short file name without folders, for example "vlan-cheatsheet"
        :param content: the note text in markdown
        :return: what happened
        """
        name = name.strip()
        if name.lower().endswith(".md"):
            name = name[:-3]
        if not SAFE_NAME.match(name) or ".." in name:
            return "Refused: use a plain name with letters, digits, spaces, dashes or underscores."
        data = content.encode("utf-8")
        if len(data) > MAX_NOTE_BYTES:
            return f"Refused: note is over {MAX_NOTE_BYTES // 1000} KB."
        if self._rate_limited():
            return "Refused: too many notes in the last minute."
        try:
            target = self._inside(self.inbox, name + ".md")
        except ValueError as e:
            return f"Refused: {e}."
        rel = target.relative_to(self.vault)

        if target.exists():
            if target.is_symlink() or not target.is_file():
                return "Refused: that name is not a normal note."
            confirmed = False
            if __event_call__ is not None:
                answer = await __event_call__({
                    "type": "confirmation",
                    "data": {"title": "Julz wants to overwrite a note",
                             "message": f"Replace {rel}? The old text will be lost."},
                })
                # Only a real True from the browser counts. An error dict is truthy,
                # so a plain `if answer:` would fail open.
                confirmed = answer is True
            if not confirmed:
                self._log("create_note_refused", note=str(rel), reason="overwrite not confirmed")
                return f"Not saved: {rel} already exists and the overwrite was not confirmed."
            action = "overwrite_note"
        else:
            action = "create_note"

        # O_NOFOLLOW: never write through a symlink swapped in after the checks above
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
        fd = os.open(target, flags, 0o644)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        self._writes.append(time.monotonic())
        self._log(action, note=str(rel), bytes=len(data))
        return f"Saved {rel} ({len(data)} bytes)."
