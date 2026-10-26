#!/usr/bin/env python3
"""Measure whether Julz stays in Russian when I write Russian (BACKLOG 202). Asks as julz-chat
does: user@ (chat.env), the model's own attached notes, julz-chat's tools, history before the
question. Only questions that read: no case asks her to save, edit or delegate.

A reply is Russian when at least half of its letters outside code are Cyrillic, so commands,
paths and terms like SSH do not fail it. Each case is asked twice and passes only when both
replies are Russian (the 4B model is a coin flip). Exits 1 below the pass mark.

Usage: ./eval-language.py [model]   (default julz:latest; pass mark: every case)
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import owui  # noqa: E402

TOOLS = ["julz_notes", "julz_pocket", "julz_delegate"]  # as julz-chat.py sends them
TRIES = 2
FENCE = re.compile(r"```.*?(```|$)", re.S)
INLINE = re.compile(r"`[^`\n]*`")
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
LETTER = re.compile(r"[^\W\d_]")

CASES = [
    {"q": "Какой порт по умолчанию у SSH и как его поменять?"},
    {"q": "Объясни разницу между TCP и UDP простыми словами."},
    # The notes about CPTS are English: does retrieval pull her over
    {"q": "Что такое CPTS и с чего мне начать подготовку?"},
    # Read tools return English text
    {"q": "Какие у меня сейчас задачи?"},
    {"q": "Что я записывала за последнюю неделю?"},
    # Russian full of English terms, the way I really write
    {"q": "Как работает nmap -sV и чем он отличается от -sC?"},
    {"q": "А что ещё стоит сделать после этого?",
     "history": [["user", "Я поставила nftables на ноутбук. Что проверить первым делом?"],
                 ["assistant", "Первым делом проверь, что правила загрузились: `sudo nft list ruleset`. "
                               "Потом убедись, что сервис включён при загрузке."]]},
    # One slip already in the history: does it snowball
    {"q": "Хорошо, а как проверить, что порт закрыт снаружи?",
     "history": [["user", "Как закрыть порт 8080 в nftables?"],
                 ["assistant", "Remove the accept rule for tcp dport 8080 from your input chain, "
                               "then reload with `sudo nft -f /etc/nftables.conf`."]]},
]


def cyrillic_share(text: str) -> float:
    prose = INLINE.sub(" ", FENCE.sub(" ", text))
    letters = LETTER.findall(prose)
    if not letters:
        return 0.0
    return sum(bool(CYRILLIC.match(c)) for c in letters) / len(letters)


def is_russian(text: str) -> bool:
    return cyrillic_share(text) >= 0.5


def run_case(case, ask, tries=TRIES):
    """Ask a case `tries` times; ask(messages) returns the reply text."""
    msgs = [{"role": r, "content": c} for r, c in case.get("history", [])]
    msgs.append({"role": "user", "content": case["q"]})
    shares = [cyrillic_share(ask(msgs)) for _ in range(tries)]
    return all(s >= 0.5 for s in shares), shares


def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "julz:latest"
    key = owui.load_key(owui.CHAT_ENV_FILE)

    def ask(msgs):
        r = owui.api(key, "POST", "/api/chat/completions", data={
            "model": model, "stream": False, "messages": msgs, "tool_ids": TOOLS}, timeout=300)
        return r["choices"][0]["message"]["content"]

    passed = 0
    for case in CASES:
        ok, shares = run_case(case, ask)
        passed += ok
        mark = "PASS" if ok else "FAIL"
        hist = " (history)" if case.get("history") else ""
        print(f"{mark}  {' '.join(f'{s:.2f}' for s in shares)}  {case['q']}{hist}")
    print(f"{passed}/{len(CASES)} stayed Russian")
    sys.exit(0 if passed == len(CASES) else 1)


if __name__ == "__main__":
    main()
