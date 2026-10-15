#!/usr/bin/env python3
"""Recall eval: ask the questions in eval/recall.json with the julz-mem knowledge base attached.

A question passes when every expected keyword appears in the answer (case insensitive).
Exits 1 below the pass mark, so it can gate changes to the model, prompt or embeddings.
Usage: ./eval-recall.py [model]   (default: julz:latest)
"""
import json
import sys
from pathlib import Path

from owui import KB_NAME, api, find_kb, load_key

PASS_MARK = 8
EVAL_FILE = Path(__file__).parent / "eval" / "recall.json"


def source_names(resp):
    names = set()
    for src in resp.get("sources") or []:
        for meta in src.get("metadata") or []:
            if meta.get("name") or meta.get("source"):
                names.add(meta.get("name") or meta.get("source"))
    return names


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "julz:latest"
    key = load_key()
    kb = find_kb(key)
    if kb is None:
        sys.exit(f"knowledge base {KB_NAME} not found, run ./sync-knowledge.py first")

    cases = json.loads(EVAL_FILE.read_text())
    passed = 0
    for i, case in enumerate(cases, 1):
        resp = api(key, "POST", "/api/chat/completions", {
            "model": model,
            "messages": [{"role": "user", "content": case["q"]}],
            "files": [{"type": "collection", "id": kb["id"]}],
            "stream": False,
        }, timeout=300)
        answer = resp["choices"][0]["message"]["content"]
        missing = [k for k in case["expect"] if k.lower() not in answer.lower()]
        cited = any(case["source"] in n for n in source_names(resp))
        ok = not missing
        passed += ok
        print(f"{'PASS' if ok else 'FAIL'} {i:2} cited={'yes' if cited else 'no '} {case['q']}")
        if missing:
            print(f"        missing {missing}; answer: {answer[:200]!r}")

    print(f"\n{passed}/{len(cases)} passed (pass mark {PASS_MARK}) with model {model}")
    sys.exit(0 if passed >= PASS_MARK else 1)


if __name__ == "__main__":
    main()
