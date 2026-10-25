#!/usr/bin/env python3
"""Give kept notes to julz: keep the julz-claude collection in Open WebUI the same as Claude/.

julz-keep stamps ~/.local/share/julz/sync/pending when it kept something, and
julz-keep-sync.path starts this. julz-keep-sync.timer starts it again every 10 minutes: that
retries a sync that failed (Open WebUI not running) and catches a kept note I deleted by hand,
which no Keep stamps (BACKLOG 13). It hashes Claude/ first; with no stamp, the same fingerprint
as the last good sync and a check under a day old it exits at once and never reads the key.
Security model: SECURITY.md threats 58, 64 and 154.
- runs in julz-keep-sync.service: the Open WebUI key and Claude/ read only, nothing in the
  vault writable. julz-keep writes the vault and has no key; this has the key and writes
  nothing there
- touches only julz-claude, never my own julz-mem collection (that one is julz-mem-sync's)
- a failure is pushed once, not every 10 minutes
Usage: ./julz-keep-sync.py
"""
import hashlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import julz_gate as gate  # noqa: E402

GATE_DIR = Path.home() / ".local" / "share" / "julz"
# The unit's StateDirectory. Never sync/: julz-keep-sync.path watches that folder
STATE = Path.home() / ".local" / "state" / "julz-keepsync"
DAY = 86400

spec = importlib.util.spec_from_file_location("sync_knowledge", HERE / "sync-knowledge.py")
sk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sk)


def fingerprint(notes) -> str:
    """One hash for the names and bytes of every kept note that would be synced. No key needed."""
    h = hashlib.sha256()
    for path, rel in sorted(notes, key=lambda n: str(n[1])):
        name = sk.upload_name(rel, claude=True)
        h.update(f"{name}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def _last(synced: Path) -> dict:
    try:
        data = json.loads(synced.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run_sync(dirs: gate.Dirs, state: Path, fp: str, do_sync, now: float) -> str:
    """One try. do_sync() returns the note count or raises. Returns what happened."""
    pending = dirs.sync / "pending"
    synced, failed = state / "synced", state / "failed"
    try:
        stamp = pending.lstat()
    except FileNotFoundError:
        stamp = None
    if stamp is not None and (not pending.is_file() or pending.is_symlink()):
        pending.unlink()
        return "odd stamp removed"
    last = _last(synced)
    if stamp is None and last.get("fingerprint") == fp and 0 <= now - last.get("checked", 0) < DAY:
        return "nothing to sync"
    try:
        count = do_sync()
    except (Exception, SystemExit) as e:  # owui.api exits on an HTTP error
        reason = f"{type(e).__name__}: {str(e)[:120]}"
        if not failed.exists():  # push once; the stamp stays for the timer
            failed.write_text(reason + "\n")
            gate.log(dirs, "sync", "", "failed", reason)
        return f"failed, will retry: {reason}"
    tmp = synced.with_name(".synced.tmp")
    tmp.write_text(json.dumps({"fingerprint": fp, "checked": now}) + "\n")
    os.replace(tmp, synced)
    # A Keep that landed during the sync re-stamped it: leave it, the next run picks it up
    try:
        if stamp is not None and pending.lstat().st_mtime_ns == stamp.st_mtime_ns:
            pending.unlink()
    except FileNotFoundError:
        pass
    failed.unlink(missing_ok=True)
    gate.log(dirs, "sync", "", "ok", f"{count} notes in julz-claude")
    return f"synced {count} notes"


def main():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    notes = list(sk.claude_notes())

    def do_sync():
        return sk.sync(sk.load_key(), sk.CLAUDE_KB_NAME, "Notes Claude wrote, kept from the phone",
                       notes, claude=True)

    result = run_sync(gate.Dirs(GATE_DIR), STATE, fingerprint(notes), do_sync, time.time())
    print(result)
    if result.startswith("failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
