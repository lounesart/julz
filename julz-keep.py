#!/usr/bin/env python3
"""Use signed Keeps: copy the checked notes Claude wrote into ~/Documents/julz-mem/Claude/.

I tap Keep on a done card and sign it on the phone. The approver links a marker into
~/.local/share/julz/keep/, and julz-keep.path starts this. julz-keep.timer starts it again
every 10 minutes, for a Keep signed while a run held the gate lock.
Security model: SECURITY.md threats 54 to 63.
- runs in julz-keep.service: no network, no token, no API key, an empty read only home;
  work copies and manifests read only, Claude/ the only writable place in the vault
- every signed file is read once, checked again and hashed; the bytes copied are the bytes
  that matched the manifest I signed (CWE-367)
- built in a hidden folder inside Claude/ and renamed into place, so nothing half done
  ever shows up for julz to read
- julz sees the notes only after I run sync-knowledge.py, in their own collection
Usage: ./julz-keep.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402
import julz_keep as keep  # noqa: E402

HOME = Path.home()
GATE_DIR = HOME / ".local" / "share" / "julz"
WORK_ROOT = GATE_DIR / "work"
CLAUDE_DIR = HOME / "Documents" / "julz-mem" / "Claude"


def main():
    dirs = gate.Dirs(GATE_DIR)
    try:
        results = keep.run_keeps(dirs, WORK_ROOT, CLAUDE_DIR, time.time())
    except gate.GateBusy:
        print("a run holds the gate lock, the timer tries again")
        return
    for root, status in results:
        print(f"keep {root[:8]}: {status}")
    if not results:
        print("no signed Keep")


if __name__ == "__main__":
    main()
