#!/usr/bin/env python3
"""Push the julz-mem vault into the Open WebUI knowledge bases.

Two collections, never mixed (SECURITY.md threat 58):
- "julz-mem": my own notes, everything in the vault except Inbox/, Outbox/, Claude/, Templates/, feedback/
- "julz-claude": notes Claude wrote and I kept from the phone, from Claude/ only. Their names
  start with Claude__, so a citation shows who wrote them even when julz gets the wording wrong
Diff sync, make before break (BACKLOG 129, SECURITY.md 143): notes are matched by name and the
SHA-256 of their bytes; new and changed ones are added first, stale copies removed only after
every add worked. The old full resync removed first and left her 4 of 32 notes on 20 Oct.
Chunk headers (BACKLOG 133, SECURITY.md 163): the uploaded copy gets a line under each heading
naming its note and part, since Open WebUI splits at headings and a chunk lost both. The vault
file is never changed; the hash covers what is uploaded, so a change here re-uploads each note once.
Usage: ./sync-knowledge.py            both collections (by hand)
       ./sync-knowledge.py --claude   julz-claude only (julz-keep-sync.service, after a Keep)
"""
import hashlib
import re
import sys
import unicodedata
from pathlib import Path

from owui import CLAUDE_KB_NAME, KB_NAME, api, find_kb, kb_files, load_key, upload_file

VAULT = (Path.home() / "Documents" / "julz-mem").resolve()
HEADER_MAX = 200  # a long heading would be repeated into every chunk under it (163)
HEADING = re.compile(r"^(#{1,3})[ \t]+(.*)$")


def _notes(root: Path, suffixes: tuple[str, ...]):
    for p in sorted(root.rglob("*")):
        if p.suffix not in suffixes:
            continue
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue  # .obsidian, .trash, a .tmp- folder of a Keep still being built
        # A symlink in the vault could pull files like ~/.ssh/config into the index (CWE-22)
        if p.is_symlink() or not p.is_file() or not p.resolve().is_relative_to(root):
            print(f"skip (outside vault): {rel}")
            continue
        yield p, rel


def vault_notes(root=VAULT):
    for p, rel in _notes(root, (".md",)):
        # Inbox is where Julz writes, maybe after reading a hostile web page. Syncing it would
        # turn one injection into permanent memory (LLM04). I review and move notes by hand.
        # Outbox holds Claude Code reports, shaped by specs julz wrote: same rule.
        # Claude/ holds kept notes: they go to julz-claude, never into my own collection (58)
        # Templates/ holds empty Obsidian forms, feedback/ is about julz: neither is knowledge
        if rel.parts[0] in ("Inbox", "Outbox", "Claude", "Templates", "feedback"):
            continue
        yield p, rel


def claude_notes(root=VAULT / "Claude"):
    """Kept notes. julz-keep checked every one of them before it copied them (threats 54-56)."""
    if root.is_symlink() or not root.is_dir():
        return
    yield from _notes(root.resolve(), (".md", ".txt"))


def _clean(text: str) -> str:
    # Hidden characters in a heading would ride into every chunk under it (163, CWE-1007)
    text = re.sub(r"\s+", " ", text)
    text = "".join(c for c in text if unicodedata.category(c) not in ("Cc", "Cf"))
    return re.sub(r"\s+#+$", "", re.sub(r" +", " ", text).strip()).strip()


def with_headers(text: str, folder: Path) -> str:
    """The note as uploaded: under each #, ## and ### heading a line "In folder > title > part"."""
    lines = text.split("\n")
    out, path, fence, start = [], [], None, 0
    if lines and lines[0].strip() == "---":  # front matter is not the note's text
        end = next((i for i, line in enumerate(lines[1:], 1) if line.strip() in ("---", "...")), None)
        if end is not None:
            out, start = lines[:end + 1], end + 1
    root = [] if str(folder) == "." else [str(folder)]
    for line in lines[start:]:
        out.append(line)
        mark = line.lstrip()[:3]
        if fence:
            fence = None if mark == fence else fence
            continue
        if mark in ("```", "~~~"):
            fence = mark
            continue
        m = HEADING.match(line)
        title = _clean(m.group(2)) if m else ""
        if not title:
            continue
        level = len(m.group(1))
        path = path[:level - 1] + [title]
        out.append(("In " + " > ".join(root + path))[:HEADER_MAX])
    return "\n".join(out)


def upload_name(rel: Path, claude: bool) -> str:
    # Keep the folder in the name so the source of a recalled fact is clear
    name = str(rel).replace("/", "__")
    return f"Claude__{name}" if claude else name


def sync(key, name: str, description: str, notes, claude: bool) -> int:
    kb = find_kb(key, name)
    if kb is None:
        kb = api(key, "POST", "/api/v1/knowledge/create",
                 {"name": name, "description": description})
        print(f"created knowledge base {name}")
    kb_id = kb["id"]

    want = []
    for path, rel in notes:
        data = with_headers(path.read_text(errors="replace"), rel.parent).encode()
        want.append((data, rel, upload_name(rel, claude), hashlib.sha256(data).hexdigest()))
    old = kb_files(key, kb_id)  # the whole listing, or it exits before any change
    if not want and old:
        # An unreadable vault looks like "every note deleted": never empty her memory on it
        sys.exit(f"{name}: the vault reads empty, refusing to remove {len(old)} files")

    have = {}  # (name, hash) -> one live file id; any other copy is stale
    for f in old:
        have.setdefault((f["filename"], (f.get("meta") or {}).get("file_hash")), f["id"])
    keep = set()
    for data, rel, uname, digest in want:
        if (uname, digest) in have:
            keep.add(have[(uname, digest)])
            continue
        uploaded = upload_file(key, data, uname)
        api(key, "POST", f"/api/v1/knowledge/{kb_id}/file/add", {"file_id": uploaded["id"]})
        print(f"added {rel}")

    # Only now, with every add done: a run that died above left her old memory whole
    stale = [f for f in old if f["id"] not in keep]
    for f in stale:
        api(key, "POST", f"/api/v1/knowledge/{kb_id}/file/remove", {"file_id": f["id"]})
    count = len(want)
    print(f"kept {len(keep)}, added {count - len(keep)}, removed {len(stale)} in {name}")
    print(f"done: {count} notes in {name} ({kb_id})")
    return count


def main():
    key = load_key()
    if "--claude" not in sys.argv[1:]:
        sync(key, KB_NAME, "Notes vault ~/Documents/julz-mem", vault_notes(), claude=False)
    sync(key, CLAUDE_KB_NAME, "Notes Claude wrote, kept from the phone", claude_notes(),
         claude=True)


if __name__ == "__main__":
    main()
