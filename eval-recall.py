#!/usr/bin/env python3
"""Recall eval: ask the questions in eval/recall.json with the julz-mem knowledge base attached.

A question passes when every expected keyword appears in the answer (case insensitive).
Exits 1 below the pass mark, so it can gate changes to the model, prompt or embeddings.
A case with "tries" is asked that many times and passes only when every try has the
keywords and cites the source: the model rewrites the question before retrieval, so one try
of a cross language case is a coin flip (129). A case with "forbid" fails a try whose answer
holds any of those words, in every mode: a wrong fact beside the right note (118).

--claude asks eval/recall-claude.json with only julz-claude attached (notes Claude wrote and
I kept, PLAN-keep.md). There the hard pass is retrieval: the answer must draw on the right
Claude__ file, every case. Keywords and how often julz says "Claude wrote" are measured and
printed, not gated: the 4B model drops rules, and code cannot make it say the words
(SECURITY.md threat 61).
--chat attaches no collection, as julz-chat sends my messages: then only what the model itself
has attached in Open WebUI (or her tools) can bring the note (118).
Usage: ./eval-recall.py [model] [--claude] [--chat]   (default model: julz:latest)
"""
import json
import sys
from pathlib import Path

from owui import CHAT_ENV_FILE, CLAUDE_KB_NAME, KB_NAME, api, find_kb, load_key

PASS_MARK = 8
EVAL_FILE = Path(__file__).parent / "eval" / "recall.json"
CLAUDE_EVAL_FILE = Path(__file__).parent / "eval" / "recall-claude.json"


def source_names(resp):
    names = set()
    for src in resp.get("sources") or []:
        for meta in src.get("metadata") or []:
            if meta.get("name") or meta.get("source"):
                names.add(meta.get("name") or meta.get("source"))
    return names


def fact_in_chunk(resp, case) -> bool:
    """133: a chunk of the expected note holds every expect word. Cited only says the file came
    back; on 25 Oct it did with the wrong part of it, and she guessed the CPTS name."""
    for src in resp.get("sources") or []:
        for doc, meta in zip(src.get("document") or [], src.get("metadata") or []):
            name = meta.get("name") or meta.get("source") or ""
            if case["source"] in name and all(k.lower() in doc.lower() for k in case["expect"]):
                return True
    return False


def says_claude_wrote(answer: str) -> bool:
    return "claude wrote" in answer.lower()


def ask(key, model, kb, q):
    body = {"model": model, "messages": [{"role": "user", "content": q}], "stream": False}
    if kb is not None:  # None is --chat: what the model has attached, as julz-chat sends it
        body["files"] = [{"type": "collection", "id": kb["id"]}]
    resp = api(key, "POST", "/api/chat/completions", body, timeout=300)
    return resp["choices"][0]["message"]["content"], resp


def run_case(case, ask, claude=False):
    """Ask a case its number of tries and judge it. ask(q) returns (answer, response)."""
    tries = case.get("tries", 1)
    good = cited_count = found = 0
    shown = None  # the first failing try, else the last one, is what gets printed
    for _ in range(tries):
        answer, resp = ask(case["q"])
        missing = [k for k in case["expect"] if k.lower() not in answer.lower()]
        # A wrong fact fails in every mode, --claude too (118: CPTS called PenTest+)
        said = [k for k in case.get("forbid", []) if k.lower() in answer.lower()]
        cited = any(case["source"] in n for n in source_names(resp))
        cited_count += cited
        found += fact_in_chunk(resp, case)  # measured, not gated
        if claude or tries > 1:
            ok = cited and (claude or not missing)
        else:
            ok = not missing
        ok = ok and not said
        good += ok
        if shown is None or (shown[0] and not ok):
            shown = (ok, missing, said, answer)
    _, missing, said, answer = shown
    return {"ok": good == tries, "good": good, "tries": tries, "cited": cited_count == tries, "found": found,
            "missing": missing, "said": said, "answer": answer,
            "credited": says_claude_wrote(answer)}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    claude = "--claude" in sys.argv[1:]
    model = args[0] if args else "julz:latest"
    name = CLAUDE_KB_NAME if claude else KB_NAME
    # As user@: julz-sync has no model, and the phone group reads both collections (SECURITY.md 14)
    key = load_key(CHAT_ENV_FILE)
    kb = find_kb(key, name)
    if kb is None:
        sys.exit(f"knowledge base {name} not found, run ./sync-knowledge.py first")
    if "--chat" in sys.argv[1:]:
        kb = None

    cases = json.loads((CLAUDE_EVAL_FILE if claude else EVAL_FILE).read_text())
    passed = keywords = credited = found = 0
    for i, case in enumerate(cases, 1):
        r = run_case(case, lambda q: ask(key, model, kb, q), claude)
        missing, cited, answer = r["missing"], r["cited"], r["answer"]
        keywords += not missing
        credited += r["credited"]
        found += r["found"] == r["tries"]
        passed += r["ok"]
        extra = f" says-claude={'yes' if r['credited'] else 'no '}" if claude else ""
        rate = f" {r['good']}/{r['tries']}" if r["tries"] > 1 else ""
        fact = (f" fact={r['found']}/{r['tries']}" if r["tries"] > 1
                else f" fact={'yes' if r['found'] else 'no '}")
        print(f"{'PASS' if r['ok'] else 'FAIL'} {i:2}{rate} cited={'yes' if cited else 'no '}{fact}"
              f"{extra} {case['q']}")
        if not r["ok"] or missing:
            print(f"        missing {missing}; said {r['said']}; answer: {answer[:200]!r}")

    n = len(cases)
    if claude:
        print(f"\nretrieval {passed}/{n} (hard pass: all), fact in a chunk {found}/{n}, "
              f"keywords {keywords}/{n}, "
              f"\"Claude wrote\" {credited}/{n} (measured) with model {model}")
        sys.exit(0 if passed == n else 1)
    print(f"\n{passed}/{n} passed (pass mark {PASS_MARK}), fact in a chunk {found}/{n} with model {model}")
    sys.exit(0 if passed >= PASS_MARK else 1)


if __name__ == "__main__":
    main()
