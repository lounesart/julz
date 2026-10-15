#!/usr/bin/env python3
"""Push the julz-mem vault into the Open WebUI knowledge base "julz-mem".

Full resync: removes every file from the knowledge base, then uploads every note again.
Fine for a small vault. Switch to the /sync/diff endpoint if it gets slow.
Usage: ./sync-knowledge.py
"""
from pathlib import Path

from owui import KB_NAME, api, find_kb, load_key, upload_file

VAULT = (Path.home() / "Documents" / "julz-mem").resolve()


def vault_notes(root=VAULT):
    for p in sorted(root.rglob("*.md")):
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue  # .obsidian, .trash and other hidden folders
        # Inbox is where Julz writes, maybe after reading a hostile web page. Syncing it would
        # turn one injection into permanent memory (LLM04). I review and move notes by hand.
        # Outbox holds Claude Code reports, shaped by specs julz wrote: same rule.
        if rel.parts[0] in ("Inbox", "Outbox"):
            continue
        # A symlink in the vault could pull files like ~/.ssh/config into the index (CWE-22)
        if p.is_symlink() or not p.resolve().is_relative_to(root):
            print(f"skip (outside vault): {rel}")
            continue
        yield p, rel


def main():
    key = load_key()
    kb = find_kb(key)
    if kb is None:
        kb = api(key, "POST", "/api/v1/knowledge/create",
                 {"name": KB_NAME, "description": "Notes vault ~/Documents/julz-mem"})
        print(f"created knowledge base {KB_NAME}")
    kb_id = kb["id"]

    old = api(key, "GET", f"/api/v1/knowledge/{kb_id}/files?limit=1000")["items"]
    for f in old:
        api(key, "POST", f"/api/v1/knowledge/{kb_id}/file/remove", {"file_id": f["id"]})
    print(f"removed {len(old)} old files")

    count = 0
    for path, rel in vault_notes():
        # Keep the folder in the name so the source of a recalled fact is clear
        name = str(rel).replace("/", "__")
        uploaded = upload_file(key, path, name)
        api(key, "POST", f"/api/v1/knowledge/{kb_id}/file/add", {"file_id": uploaded["id"]})
        print(f"added {rel}")
        count += 1
    print(f"done: {count} notes in {KB_NAME} ({kb_id})")


if __name__ == "__main__":
    main()
