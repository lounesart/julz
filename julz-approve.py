#!/usr/bin/env python3
"""Approve Claude Code specs that julz wrote, one at a time, by hand.

Reads ~/Documents/julz-mem/Inbox/claude/*.md, shows each spec exactly as Claude will get it,
asks y/N. A yes stores the text under its sha256 in ~/.local/share/julz/approved/ (never
mounted into a container) and removes the inbox copy. A spec that fails the checks in
julz_gate.py is shown as refused and never asked about. SECURITY.md threats 21 to 23.
Usage: ./julz-approve.py   (needs a terminal: approval must come from a person)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402

HOME = Path.home()
INBOX = HOME / "Documents" / "julz-mem" / "Inbox" / "claude"
OUTBOX = HOME / "Documents" / "julz-mem" / "Outbox"
GATE_DIR = HOME / ".local" / "share" / "julz"
PROJECTS_FILE = HOME / ".config" / "julz" / "projects.json"


def require_tty(stream):
    # Without this, a script (or julz) could pipe "y" in, and the gate would need no person
    if not stream.isatty():
        sys.exit("julz-approve needs a terminal: approval must come from a person")


def review(inbox: Path, dirs: gate.Dirs, projects, ask, out) -> list[str]:
    """Show each inbox spec and ask about it. Returns the hashes I approved."""
    approved = []
    for path in sorted(inbox.iterdir()):
        if path.suffix != ".md":
            continue
        try:
            text, spec = gate.load_spec(path, projects)
        except gate.SpecError as e:
            # repr: a file name or snippet with escape codes must not reach my terminal raw
            out(f"refused  {path.name!r}: {e}")
            continue
        digest = gate.sha256(text)
        out(f"\n--- {path.name}  project {spec['project']}  sha256 {digest}")
        out(text.rstrip("\n"))
        out("---")
        if ask("Approve? [y/N] ").strip().lower() not in ("y", "yes"):
            out("skipped")
            continue
        try:
            gate.store_approved(text, dirs, projects)
        except gate.SpecError as e:
            out(f"not stored: {e}")
            continue
        # Stored the text I saw, not the file: if julz rewrote it meanwhile, that is ignored
        path.unlink()
        approved.append(digest)
        out(f"approved {digest}")
    return approved


def main():
    require_tty(sys.stdin)
    try:
        projects = gate.load_projects(PROJECTS_FILE)
    except gate.GateError as e:
        sys.exit(str(e))
    if not INBOX.is_dir():
        sys.exit(f"{INBOX} does not exist")
    approved = review(INBOX, gate.Dirs(GATE_DIR, outbox=OUTBOX), projects, input, print)
    print(f"\n{len(approved)} approved")


if __name__ == "__main__":
    main()
