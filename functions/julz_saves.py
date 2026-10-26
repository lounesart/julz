"""
title: Julz honest saves
description: When Julz says she saved, added or moved something and no note tool did it this turn, a warning line goes above her answer.
version: 0.2.0
"""
# Paste this file into Open WebUI: Admin Panel, Functions, +, then turn it on for the julz
# models. A function runs as the Open WebUI server, so paste only code you have read (A08).
# Why code and not the prompt: a prompt line saying "never say saved without a tool result"
# was measured and changed nothing; she claimed daily notes no tool wrote (BACKLOG 208).
# SECURITY.md threat 141:
# - only a tool result Open WebUI itself marks (tool_result, named julz_notes/<write tool>)
#   that starts with that tool's success words counts; a note read aloud cannot fake one
# - it never removes or rewrites her words: one warning line above them, once
# - it reads only what Open WebUI hands the outlet: no files, no network, no logging
# Shown in saved chats only: 0.11.4 does not hand an outlet edit back to a plain API call.
import re

# What each write tool of julz_notes answers when it changed something (tools/julz_notes.py)
WRITES = {
    "create_note": ("Saved ",),
    "save_feedback": ("Saved ",),
    "append_note": ("Added to the end ",),
    "edit_note": ("Changed ",),
    "move_note": ("Moved ",),
    "delete_note": ("Deleted ",),
    "tick_task": ("Ticked ", "Ticked:"),
    "mark_reviewed": ("Marked ",),
    "resolve_feedback": ("Solved and moved ",),
}
# What a write tool answers after "Not <done>" when the change went to the phone as a card
# (ON_THE_PHONE, 208): nothing happened yet, but the warning says so instead of "no change" (241)
CARD = " yet: this chat has no confirm button, so the change went to Approve on the "
TOOL = "julz_notes/"
CLAIM = re.compile(r"\b(?:I(?:'ve| have)?|is|are|was|were|has been|have been)\s+(?:now\s+|just\s+|already\s+)?"
                   r"(?:saved|created|added|made|changed|moved|deleted|ticked|marked|updated|wrote|written|"
                   r"appended|stored)\b", re.I)
# "Nothing was saved" is honest: a denial earlier in the same clause cancels the claim
DENIAL = re.compile(r"\b(?:nothing|not|never|no)\b|n't", re.I)
WARNING = ("> [!warning] Nothing was saved in this answer: no note tool reported a change, so "
           "what Julz says below did not happen. Check your notes or ask her again.")
CARD_WARNING = ("> [!warning] Not saved yet: the change waits on Approve on your phone. Nothing "
                "changes until you sign it there with your fingerprint.")


def claims_a_change(text: str) -> bool:
    for m in CLAIM.finditer(text):
        clause = re.split(r"[.!?\n,;:]", text[:m.start()])[-1]
        if not DENIAL.search(clause):
            return True
    return False


def write_results(metadata):
    """Each (write tool, text) this turn that Open WebUI marks as a julz_notes tool result."""
    sources = metadata.get("sources") if isinstance(metadata, dict) else None
    if not isinstance(sources, list):
        return
    for src in sources:
        if not isinstance(src, dict) or src.get("tool_result") is not True:
            continue
        name = src.get("source", {}).get("name") if isinstance(src.get("source"), dict) else None
        if not isinstance(name, str) or not name.startswith(TOOL) or name[len(TOOL):] not in WRITES:
            continue
        docs = src.get("document")
        for d in docs if isinstance(docs, list) else ():
            if isinstance(d, str):
                yield name[len(TOOL):], d


def saved_this_turn(metadata) -> bool:
    return any(d.startswith(WRITES[name]) for name, d in write_results(metadata))


def card_this_turn(metadata) -> bool:
    return any(d.startswith("Not ") and CARD in d for _, d in write_results(metadata))


class Filter:
    def outlet(self, body: dict, __metadata__: dict | None = None) -> dict:
        messages = body.get("messages") if isinstance(body, dict) else None
        if not isinstance(messages, list) or not messages:
            return body
        last = messages[-1]
        if not isinstance(last, dict) or last.get("role") != "assistant":
            return body
        text = last.get("content")
        if not isinstance(text, str) or text.startswith((WARNING, CARD_WARNING)):
            return body
        if claims_a_change(text) and not saved_this_turn(__metadata__):
            line = CARD_WARNING if card_this_turn(__metadata__) else WARNING
            last["content"] = line + "\n\n" + text
        return body
