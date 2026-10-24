#!/usr/bin/env python3
"""Give my notes to julz: keep the julz-mem collection in Open WebUI the same as the vault.

julz-mem-sync.timer starts this every 15 minutes, and julz-mem-sync.path when something writes
~/.local/state/julz-memsync/pending (a menu action of hers later, BACKLOG 210). It hashes the
vault first; with no stamp, the same fingerprint as the last good sync and a check under a day
old it exits before it reads the key. Otherwise a diff sync, adds before removes
(sync-knowledge.py). Security model: SECURITY.md threats 58, 64 and 143.
- runs in julz-mem-sync.service: the vault read only with Inbox/, Outbox/, Claude/,
  Templates/, feedback/ and .git hidden, the key read only, nothing in the vault writable
- touches only julz-mem; julz-claude is julz-keep-sync's
- a failure is pushed once, a success is quiet
Usage: ./julz-mem-sync.py
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
STATE = Path.home() / ".local" / "state" / "julz-memsync"
DAY = 86400

spec = importlib.util.spec_from_file_location("sync_knowledge", HERE / "sync-knowledge.py")
sk = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sk)


def fingerprint(notes) -> str:
    """One hash for the names and bytes of every note that would be synced. No key needed."""
    h = hashlib.sha256()
    for path, rel in sorted(notes, key=lambda n: str(n[1])):
        name = sk.upload_name(rel, claude=False)
        h.update(f"{name}\0{hashlib.sha256(path.read_bytes()).hexdigest()}\n".encode())
    return h.hexdigest()


def _last(synced: Path) -> dict:
    try:
        data = json.loads(synced.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def run(state: Path, dirs: gate.Dirs, fp: str, do_sync, now: float) -> str:
    """One try. do_sync() returns the note count or raises. Returns what happened."""
    pending, synced, failed = state / "pending", state / "synced", state / "failed"
    try:
        stamp = pending.lstat()
    except FileNotFoundError:
        stamp = None
    if stamp is not None and (not pending.is_file() or pending.is_symlink()):
        pending.unlink()
        return "odd stamp removed"
    last = _last(synced)
    if stamp is None and last.get("fingerprint") == fp and 0 <= now - last.get("checked", 0) < DAY:
        return "up to date"
    try:
        count = do_sync()
    except (Exception, SystemExit) as e:  # owui.api exits on an HTTP error
        reason = f"{type(e).__name__}: {str(e)[:120]}"
        if not failed.exists():  # push once; the next tick tries again
            failed.write_text(reason + "\n")
            gate.log(dirs, "mem-sync", "", "failed", reason)
        return f"failed, will retry: {reason}"
    tmp = synced.with_name(".synced.tmp")
    tmp.write_text(json.dumps({"fingerprint": fp, "checked": now}) + "\n")
    os.replace(tmp, synced)
    # A stamp that landed during the sync was written after this sync read the vault: keep it
    try:
        if stamp is not None and pending.lstat().st_mtime_ns == stamp.st_mtime_ns:
            pending.unlink()
    except FileNotFoundError:
        pass
    failed.unlink(missing_ok=True)
    gate.log(dirs, "mem-sync", "", "ok", f"{count} notes in julz-mem")
    return f"synced {count} notes"


def main():
    STATE.mkdir(mode=0o700, parents=True, exist_ok=True)
    notes = list(sk.vault_notes())

    def do_sync():
        return sk.sync(sk.load_key(), sk.KB_NAME, "Notes vault ~/Documents/julz-mem", notes,
                       claude=False)

    result = run(STATE, gate.Dirs(GATE_DIR), fingerprint(notes), do_sync, time.time())
    print(result)
    if result.startswith("failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
