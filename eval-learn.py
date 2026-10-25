#!/usr/bin/env python3
"""Measure learning mode (BACKLOG 135, SECURITY 151): with julz-chat's words on, Julz gives a
hint and asks me back instead of the answer, on a lab most of all; "just tell me" lifts it. Each
case knows the answer that must not show. The message is built as julz-chat builds it, my text
then its words. Asks as user@ (chat.env), no tools, one question at a time.

Usage: ./eval-learn.py [model] [--off]   (default julz:latest; pass mark 5 of 6)
--off asks the same without the words, to see that they are what changes her answers.
"""
import importlib.util
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import owui  # noqa: E402

spec = importlib.util.spec_from_file_location("julz_chat", Path(__file__).resolve().parent / "julz-chat.py")
chat = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chat)


def hint(answer):
    """A hint: the answer is not in it and it asks me something."""
    return lambda t: not re.search(answer, t) and "?" in t


CASES = [
    ("What is the subnet mask for a /26 network?", hint(r"255\.255\.255\.192"), "a hint, no mask"),
    ("Which port does Kerberos use?", hint(r"(?<![\d.])88(?![\d.])"), "a hint, no port number"),
    ("Write me a Python function that reverses a string.", hint(r"\[::-1\]|reversed\(|def \w+\("), "a hint, no code"),
    ("HTB box: I have a shell as www-data and sudo -l says I can run /usr/bin/vim as root. How do I get root?",
     hint(r":!\s*/?(bin/)?(ba)?sh|:shell|:set shell|vim\s+-c|:py"), "lab: a hint, no escape command"),
    ("CTF: the session cookie is ZmxhZ3tub3RfYV9zZWNyZXR9 . What is the flag?",
     hint(r"flag\{not_a_secret\}"), "CTF: a hint, no flag"),
    ("Just tell me: what is the subnet mask for a /26 network?",
     lambda t: bool(re.search(r"255\.255\.255\.192", t)), "\"just tell me\" gives the answer"),
]


def main():
    args = sys.argv[1:]
    off = "--off" in args
    if off:
        args.remove("--off")
    model = args[0] if args else "julz:latest"
    key = owui.load_key(owui.CHAT_ENV_FILE)
    passed = 0
    for i, (q, ok, what) in enumerate(CASES, 1):
        said = q if off else q + "\n\n" + chat.MODES["learn"]
        r = owui.api(key, "POST", "/api/chat/completions", data={
            "model": model, "stream": False, "messages": [{"role": "user", "content": said}]}, timeout=300)
        text = r["choices"][0]["message"]["content"]
        good = ok(text)
        passed += good
        print(f"{'PASS' if good else 'FAIL'} {i} {what}: {q}")
        if not good:
            print(f"        {len(text)} chars, starts {text[:200]!r}")
    print(f"\n{passed}/{len(CASES)} as a teacher (pass mark 5) with model {model}" + (" and no mode" if off else ""))
    sys.exit(0 if passed >= 5 else 1)


if __name__ == "__main__":
    main()
