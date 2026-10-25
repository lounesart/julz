"""
title: Julz history
description: Code keeps a long chat inside the model's window, with room left for the answer.
version: 0.1.0
"""
# Paste this file into Open WebUI: Admin Panel, Functions, +, then turn it on for the julz
# models. A function runs as the Open WebUI server, so paste only code you have read (A08).
# Why (BACKLOG 26k, measured 25 Oct): 0.11.4 sends the whole stored chat, and Ollama drops the
# oldest messages until the prompt fits num_ctx 8192, leaving the answer whatever is over, and
# halves raw a request whose one message is too big (the tool picking call: tool specs, then
# the last 4 messages as one). Inlets run after the store rebuild and before tool picking, so
# both calls get what is kept here.
# - system messages are never touched, a chat under the budget passes unchanged
# - my current turn (all after her last answer: my message, learn mode's words) is kept; when
#   it alone is over the budget, its oldest part keeps its end
# - then my first message, when it fits (a quiz and its key live there), only if it is mine
# - then older messages, newest first, whole or not at all, starting on one of mine
# - anything unexpected: the body goes on unchanged, as before this filter
# - no network, no logging, standard library only
import json

# Characters, not tokens: 2.75 characters a token measured on my docs, Russian runs denser.
# 8000 keeps tool picking (about 3800 tokens of specs) under 8192 and leaves the answer about
# 1500 tokens beside her prompt (about 2400) and retrieved notes.
HISTORY_CHARS = 8_000


def size(m: dict) -> int:
    content = m.get("content")
    if isinstance(content, str):
        n = len(content)
    elif isinstance(content, list):
        n = sum(len(p["text"]) for p in content
                if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str))
    elif content is None:
        n = 0
    else:
        raise TypeError("unexpected content")
    output = m.get("output")
    return max(n, len(json.dumps(output))) if output else n


def cut(m: dict, room: int) -> dict:
    """Its end, room characters; a message with images or parts is kept as it is."""
    if not isinstance(m.get("content"), str):
        return m
    return {**m, "content": m["content"][-room:] if room > 0 else ""}


def trim(messages: list[dict], room: int) -> list[dict]:
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if sum(size(m) for m in rest) <= room:
        return messages
    answers = [i for i, m in enumerate(rest) if m.get("role") == "assistant"]
    start = answers[-1] + 1 if answers and answers[-1] + 1 < len(rest) else len(rest) - 1
    turn, older = [], rest[:start]
    for m in reversed(rest[start:]):
        n = size(m)
        if n > room:
            turn.append(cut(m, room))
            room = 0
            break
        turn.append(m)
        room -= n
    turn.reverse()
    pinned = []
    if older and older[0].get("role") == "user" and size(older[0]) <= room:
        pinned = [older[0]]
        room -= size(older[0])
    window = []
    for m in reversed(older[len(pinned):]):
        n = size(m)
        if n > room:
            break
        window.append(m)
        room -= n
    window.reverse()
    while window and window[0].get("role") != "user":
        window.pop(0)
    return system + pinned + window + turn


class Filter:
    def inlet(self, body: dict, __user__: dict | None = None) -> dict:
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list) or not all(isinstance(m, dict) for m in messages):
            return body
        try:
            kept = trim(messages, HISTORY_CHARS)
        except (TypeError, ValueError, KeyError, AttributeError):
            return body
        if kept is not messages:
            body["messages"] = kept
        return body
