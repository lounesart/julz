#!/usr/bin/env python3
"""Measure whether Julz shapes her answers to their content (BACKLOG 26e): prose for a quick
question, a table to compare, numbered steps with a code block for a procedure, headings only
for a long answer, a chart block for numbers, a warning callout before something risky. The
checks look at the Markdown she writes, the same the app's parser draws. Asks as user@
(chat.env), no tools, one question at a time.

Usage: ./eval-format.py [model] [--system FILE]   (default julz:latest; pass mark 5 of 6)
--system tries a prompt before the models are rebuilt: it is sent as the system message,
which takes the place of the model's own.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import owui  # noqa: E402

TABLE = re.compile(r"(?m)^\s*\|.*\|\s*\n\s*\|?\s*:?-{3,}")
STEPS = re.compile(r"(?m)^\s*1[.)]\s+\S")
CODE = re.compile(r"(?m)^\s*```")
HEADING = re.compile(r"(?m)^#{1,3}\s+\S")
CHART = re.compile(r"(?m)^```chart\s*$")
WARNING = re.compile(r"(?mi)^>\s*\[!(warning|caution|danger)\]")
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")

CASES = [
    ("What port does SSH use?",
     lambda t: len(t) < 400 and not HEADING.search(t) and not TABLE.search(t), "short prose, no headings or table"),
    ("Compare TCP and UDP for me.", lambda t: bool(TABLE.search(t)), "a table"),
    ("How do I give my Arch laptop a static IP with systemd-networkd? Step by step.",
     lambda t: bool(STEPS.search(t)) and bool(CODE.search(t)), "numbered steps and a code block"),
    ("Explain the OSI model in depth, layer by layer.", lambda t: bool(HEADING.search(t)), "headings for a long answer"),
    ("My quiz scores this week: Network+ 80, Security+ 62, A+ 90. Show them to me as a chart.",
     lambda t: bool(CHART.search(t)), "a chart block"),
    ("Is it fine to run rm -rf on /var/log on my laptop to free space?",
     lambda t: bool(WARNING.search(t)), "a warning callout"),
]


def main():
    args = sys.argv[1:]
    system = None
    if "--system" in args:
        i = args.index("--system")
        system = Path(args[i + 1]).read_text()
        del args[i:i + 2]
    model = args[0] if args else "julz:latest"
    key = owui.load_key(owui.CHAT_ENV_FILE)
    lead = [{"role": "system", "content": system}] if system else []
    passed = 0
    for i, (q, ok, what) in enumerate(CASES, 1):
        r = owui.api(key, "POST", "/api/chat/completions", data={
            "model": model, "stream": False, "messages": lead + [{"role": "user", "content": q}]}, timeout=300)
        text = r["choices"][0]["message"]["content"]
        good = ok(text) and not EMOJI.search(text)
        passed += good
        print(f"{'PASS' if good else 'FAIL'} {i} {what}: {q}")
        if not good:
            print(f"        {len(text)} chars, starts {text[:160]!r}")
    print(f"\n{passed}/{len(CASES)} shaped right (pass mark 5) with model {model}" + (" and the trial prompt" if system else ""))
    sys.exit(0 if passed >= 5 else 1)


if __name__ == "__main__":
    main()
