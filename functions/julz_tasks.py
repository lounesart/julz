"""
title: Julz tasks
description: Code spots an open task in my message ("also I walked 10k") and tells julz, so she ticks it without a set phrase.
version: 0.1.0
"""
# Paste this file into Open WebUI: Admin Panel, Functions, +, then turn it on for the julz
# models. A function runs as the Open WebUI server, so paste only code you have read (A08).
# Why code and not the prompt: the 4B model calls tick_task when I use the words of its
# prompt, but misses "also I walked 10k" in a chatty message (found 2026-10-16).
# SECURITY.md threat 82:
# - it never ticks anything: it adds one short line naming at most 3 matching open tasks, and
#   julz decides, because "I need to walk 10k" must not tick
# - it reads open tasks in Inbox/ and daily/ (not daily/done/) from the read only vault mount,
#   skips hidden files, links and big files, never writes, no network, no logging
# - task text in the line is cut short and a task with hidden characters is left out
import os
import re
import unicodedata
from pathlib import Path

OPEN_TASK = re.compile(r"^\s*[-*] \[ \] (.+?)\s*$", re.M)
WORD = re.compile(r"\w+")
STOP = {"i", "a", "an", "the", "my", "me", "also", "and", "or", "to", "of", "in", "on", "at",
        "for", "it", "is", "was", "did", "do", "done", "just", "today", "yesterday", "so",
        "then", "too", "with", "from", "that", "this", "got", "have", "had", "finally"}
ROOTS = ("Inbox", "daily")
MAX_NOTE_BYTES = 100_000
MAX_SHOWN = 3
MAX_ITEM = 80
HIDDEN = ("Cc", "Cf", "Co", "Cs", "Cn")


def words(text: str) -> list[str]:
    return [w for w in WORD.findall(text.lower()) if len(w) >= 2 and w not in STOP]


def same(task_word: str, user_word: str) -> bool:
    """walk and walked, book and booked: the same first four letters, or the same word."""
    if task_word == user_word:
        return True
    return len(task_word) >= 4 and len(user_word) >= 4 and task_word[:4] == user_word[:4]


def score(task: str, said: list[str]) -> float:
    tw = words(task)
    if not tw:
        return 0.0
    hit = sum(any(same(t, u) for u in said) for t in tw)
    return hit / len(tw) if hit else 0.0


def open_tasks(vault: Path) -> list[tuple[str, str]]:
    found = []
    for root in ROOTS:
        base = vault / root
        if not base.is_dir() or base.is_symlink():
            continue
        for p in sorted(base.rglob("*.md")):
            rel = p.relative_to(vault)
            if rel.parts[:2] == ("daily", "done") or any(x.startswith(".") for x in rel.parts) \
                    or p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_NOTE_BYTES:
                continue
            for item in OPEN_TASK.findall(p.read_text(encoding="utf-8", errors="replace")):
                if not any(unicodedata.category(c) in HIDDEN for c in item):
                    found.append((str(rel), item))
    return found


def hint(text: str, vault: Path) -> str:
    said = words(text)
    if not said:
        return ""
    ranked = sorted(((score(item, said), rel, item) for rel, item in open_tasks(vault)),
                    key=lambda x: -x[0])
    best = [(rel, item) for s, rel, item in ranked if s >= 0.5][:MAX_SHOWN]
    if not best:
        return ""
    named = "; ".join(f'"{item[:MAX_ITEM].replace(chr(34), "")}" in {rel}' for rel, item in best)
    return (f"\n\n(Tasks filter: open tasks that may match: {named}. If the user says they "
            "did one, call tick_task with its words. Otherwise ignore this line.)")


class Filter:
    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list):
            return body
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                break
        else:
            return body
        vault = Path(os.environ.get("JULZ_VAULT", "/data/julz-mem")).resolve()
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = content + hint(content, vault)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" \
                        and isinstance(part.get("text"), str):
                    part["text"] += hint(part["text"], vault)
                    break
        return body
