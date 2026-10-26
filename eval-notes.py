#!/usr/bin/env python3
"""Measure notes mode (BACKLOG 133b, SECURITY 151): with julz-chat's words on, Julz answers from
my notes and says "That is not in your notes." when they do not have it, with no guess from her
own knowledge; "just tell me" lifts it. It goes the phone's way, as eval-learn.py does: julz-chat's
App in this process, a new stored chat per case, deleted after.

Usage: ./eval-notes.py [--off]   (julz:latest, julz-chat's model; pass mark 7 of 8)
--off asks the same without the words, to see that they are what changes her answers.
"""
import importlib.util
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("eval_learn", HERE / "eval-learn.py")
learn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(learn)
chat = learn.chat

NOT_IN = re.compile(r"not in your notes|нет в твоих заметках", re.I)


def from_notes(fact):
    """The fact from a note, and no claim that the notes lack it."""
    return lambda t: bool(re.search(fact, t, re.I)) and not NOT_IN.search(t)


def not_in(fact):
    """She says the notes do not have it, and the fact from her own knowledge is not there."""
    return lambda t: bool(NOT_IN.search(t)) and not re.search(fact, t, re.I)


# Facts from eval/recall.json and recall-claude.json, which name the note each lives in; the
# others are far from anything in the vault
CASES = [
    ("What is my own mnemonic for the OSI layers?", from_notes(r"pizza"), "in notes: OSI mnemonic"),
    ("According to my notes, how many usable hosts does a /26 have?", from_notes(r"\b62\b"), "in notes: /26 hosts"),
    ("What is CPTS?", lambda t: from_notes(r"Penetration Testing Specialist")(t) and "PenTest+" not in t,
     "in notes: CPTS, not PenTest+"),
    ("In the DNS lab guide, which record type maps a name to an IPv6 address?", from_notes(r"AAAA"),
     "in notes: AAAA"),
    ("Who wrote the novel Dune?", not_in(r"Herbert"), "not in notes: Dune"),
    ("What is the capital of Australia?", not_in(r"Canberra"), "not in notes: Australia"),
    ("What is the boiling point of tungsten?", not_in(r"\d[ ,.]?\d{3}\s?°|\d[ ,.]?\d{3}\s?K\b"), "not in notes: tungsten"),
    ("Just tell me: who wrote the novel Dune?", lambda t: bool(re.search(r"Herbert", t)),
     "\"just tell me\" gives the answer"),
]


def main():
    off = "--off" in sys.argv[1:]
    app = chat.App(learn.TOKEN, {learn.HOST}, chat.Upstream(chat.read_key(chat.KEY_FILE)))
    passed = 0
    for i, (q, ok, what) in enumerate(CASES, 1):
        text = learn.ask(app, q, None if off else "notes")
        good = ok(text)
        passed += good
        print(f"{'PASS' if good else 'FAIL'} {i} {what}: {q}")
        if not good:
            print(f"        {len(text)} chars, starts {text[:200]!r}")
    print(f"\n{passed}/{len(CASES)} from my notes only (pass mark 7) with model {chat.MODEL}" + (" and no mode" if off else ""))
    sys.exit(0 if passed >= 7 else 1)


if __name__ == "__main__":
    main()
