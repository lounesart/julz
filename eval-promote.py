#!/usr/bin/env python3
"""Turn a bad answer I kept from the phone (feedback/eval/, BACKLOG 155, SECURITY.md 153) into
an item of eval/answers.json, which eval-answers.py asks again. Run by me at the desk, on a
case I have read: it copies my question and the mode, and the checks are words I type here.
Her answer is never copied, since a web page may have shaped it.

Usage: ./eval-promote.py                                   the cases, newest first
       ./eval-promote.py NAME --expect WORDS [--avoid WORDS] [--mode none|learn]
--expect and --avoid can repeat; an item passes when every expect is in her answer and no
avoid is (case does not matter). --mode is needed when the phone did not know it.
"""
import argparse
import json
import os
import stat
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_keep as keep  # noqa: E402
import julz_vault as vault  # noqa: E402

CASES = Path.home() / "Documents" / "julz-mem" / "feedback" / "eval"
ANSWERS = Path(__file__).resolve().parent / "eval" / "answers.json"
MODES = ("none", "learn")
MAX_WORDS = 60
MAX_ITEMS = 500


class Refused(Exception):
    """A case or a check that fails; the message says which."""


def read_case(folder: Path, name) -> dict:
    """My question and the mode from one case note, exactly as julz-vault wrote them."""
    if not isinstance(name, str) or name.startswith(".") or not vault.NAME.fullmatch(name):
        raise Refused("not a case name")
    path = folder / f"{name}.md"
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise Refused("no such case") from None
    if not stat.S_ISREG(st.st_mode):
        raise Refused("not a regular file")
    meta, body = vault.front(vault.read_note(path).decode("utf-8", errors="replace"))
    n = meta.get("question_chars", "")
    if "eval-case" not in vault.tags(meta) or meta.get("mode") not in vault.CASE_MODES \
            or not vault.CASE_LEN.fullmatch(n):
        raise Refused("not a case note")
    head = "\n## Question\n\n"
    start = body.find(head)
    if start == -1:
        raise Refused("not a case note")
    start += len(head)
    q = body[start:start + int(n)]
    if not body[start + int(n):].startswith("\n\n## Answer\n\n"):
        raise Refused("not a case note")
    try:
        q = vault.checked_text(q, vault.MAX_CASE_Q + 2 + len(vault.CASE_CUT))
    except vault.Refused as e:
        raise Refused(str(e)) from None
    return {"q": q, "mode": meta["mode"]}


def check_words(words) -> list[str]:
    for w in words:
        if not isinstance(w, str) or not w.strip() or w != w.strip() or len(w) > MAX_WORDS \
                or "\n" in w or keep.check_text(w):
            raise Refused(f"bad check words: {str(w)[:20]!r}")
    return list(words)


def load(answers: Path) -> list:
    return json.loads(answers.read_text(encoding="utf-8")) if answers.exists() else []


def promote(folder: Path, answers: Path, name, expect, avoid, mode) -> dict:
    case = read_case(folder, name)
    mode = mode or case["mode"]
    if mode not in MODES:
        raise Refused("the mode is none or learn: give --mode when the phone did not know it")
    expect, avoid = check_words(expect), check_words(avoid)
    if not expect and not avoid:
        raise Refused("give at least one --expect or --avoid")
    items = load(answers)
    if any(i.get("case") == name for i in items):
        raise Refused("already promoted")
    if len(items) >= MAX_ITEMS:
        raise Refused("answers.json is full")
    item = {"q": case["q"], "mode": mode, "expect": expect, "avoid": avoid, "case": name}
    tmp = answers.with_name(f".{answers.name}.tmp")
    tmp.write_text(json.dumps(items + [item], ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, answers)
    return item


def list_cases(folder: Path, answers: Path) -> list[tuple[str, bool, str]]:
    done = {i.get("case") for i in load(answers)}
    rows = []
    for p in sorted(folder.glob("*.md"), reverse=True) if folder.is_dir() else []:
        try:
            q = read_case(folder, p.stem)["q"].splitlines()[0][:80]
        except (Refused, OSError):
            q = "(does not parse)"
        rows.append((p.stem, p.stem in done, q))
    return rows


def main():
    ap = argparse.ArgumentParser(description="A kept bad answer into eval/answers.json")
    ap.add_argument("name", nargs="?")
    ap.add_argument("--expect", action="append", default=[])
    ap.add_argument("--avoid", action="append", default=[])
    ap.add_argument("--mode")
    args = ap.parse_args()
    try:
        if args.name is None:
            for name, done, q in list_cases(CASES, ANSWERS):
                print(f"{'promoted' if done else 'new     '}  {name}  {q}")
            return
        item = promote(CASES, ANSWERS, args.name, args.expect, args.avoid, args.mode)
    except Refused as e:
        sys.exit(f"refused: {e}")
    print(f"added to {ANSWERS.name}: {json.dumps(item, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
