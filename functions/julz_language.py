"""
title: Julz language
description: Code picks the reply language from my last message, so julz does not drift.
version: 0.1.0
"""
# Paste this file into Open WebUI: Admin Panel, Functions, +, then turn it on for the julz
# models. A function runs as the Open WebUI server, so paste only code you have read (A08).
# Why code and not the prompt: the 4B model treats "match the user's language" as a hint and
# drifts to Russian or Polish, pulled by the prompt itself or by Russian notes.
# - only the last user message is read, only its text, and one short line is appended
# - the first line with letters, outside code blocks, decides, so "translate this:" plus
#   pasted text stays English
# - no network, no logging, standard library only
import re

CYRILLIC = re.compile(r"[Ѐ-ӿ]")
LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
POLISH_LETTERS = re.compile(r"[ąćęłńśźżĄĆĘŁŃŚŹŻ]")
# Words that are Polish and not English, for Polish typed without diacritics
POLISH_WORDS = {"co", "nie", "jest", "czy", "jak", "sie", "się", "jestem", "mozesz", "możesz",
                "prosze", "proszę", "dzieki", "dzięki", "napisz", "powiedz", "powiedziec",
                "dlaczego", "gdzie", "kiedy", "ktory", "który", "bardzo", "teraz", "wszystko",
                "dziala", "działa", "mam", "jestes", "jesteś", "mnie", "tez", "też", "zrob"}
WORD = re.compile(r"[^\W\d_]+")


def _first_line_with_letters(text: str) -> str:
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
            continue
        if not in_code and (CYRILLIC.search(line) or LATIN.search(line)):
            return line
    return ""


def detect(text: str) -> str:
    line = _first_line_with_letters(text)
    # Any Cyrillic decides: my Russian is full of Latin tech terms, my English has no Cyrillic
    if CYRILLIC.search(line):
        return "Russian"
    if POLISH_LETTERS.search(line):
        return "Polish"
    words = [w.lower() for w in WORD.findall(line)]
    if sum(w in POLISH_WORDS for w in words) >= 2:
        return "Polish"
    return "English"


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
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = f"{content}\n\n(Reply in {detect(content)}.)"
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" \
                        and isinstance(part.get("text"), str):
                    part["text"] = f"{part['text']}\n\n(Reply in {detect(part['text'])}.)"
                    break
        return body
