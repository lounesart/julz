#!/usr/bin/env python3
"""Ask again the bad answers I kept (BACKLOG 155): eval/answers.json, filled by eval-promote.py.
An item passes when every `expect` is in her answer and no `avoid` is, case does not matter.
It goes the phone's way, as eval-learn.py does: julz-chat's App in this process, a new stored
chat per item in its mode, deleted after.

Usage: ./eval-answers.py   (julz:latest, julz-chat's model; every item must pass)
"""
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("eval_learn", HERE / "eval-learn.py")
learn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(learn)
chat = learn.chat

ANSWERS = HERE / "eval" / "answers.json"


def passes(item: dict, text: str) -> bool:
    low = text.lower()
    return bool(text) and all(w.lower() in low for w in item["expect"]) \
        and not any(w.lower() in low for w in item["avoid"])


def main():
    items = json.loads(ANSWERS.read_text(encoding="utf-8"))
    app = chat.App(learn.TOKEN, {learn.HOST}, chat.Upstream(chat.read_key(chat.KEY_FILE)))
    passed = 0
    for i, item in enumerate(items, 1):
        text = learn.ask(app, item["q"], item["mode"] if item["mode"] != "none" else None)
        good = passes(item, text)
        passed += good
        print(f"{'PASS' if good else 'FAIL'} {i} {item['case']}: {item['q'][:80]}")
        if not good:
            print(f"        {len(text)} chars, starts {text[:200]!r}")
    print(f"\n{passed}/{len(items)} kept answers right with model {chat.MODEL}")
    sys.exit(0 if passed == len(items) else 1)


if __name__ == "__main__":
    main()
