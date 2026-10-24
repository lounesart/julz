#!/usr/bin/env python3
"""Give kept notes to julz: rebuild the julz-claude collection in Open WebUI after a Keep.

julz-keep stamps ~/.local/share/julz/sync/pending when it kept something, and
julz-keep-sync.path starts this. julz-keep-sync.timer starts it again every 10 minutes, so a
sync that failed (Open WebUI not running) is retried. Without a stamp it exits at once and
never reads the key. Security model: SECURITY.md threats 58 and 64.
- runs in julz-keep-sync.service: the Open WebUI key and Claude/ read only, nothing in the
  vault writable. julz-keep writes the vault and has no key; this has the key and writes
  nothing there
- touches only julz-claude, never my own julz-mem collection (that one stays by hand)
- a failure is pushed once, not every 10 minutes
Usage: ./julz-keep-sync.py
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import julz_gate as gate  # noqa: E402

GATE_DIR = Path.home() / ".local" / "share" / "julz"


def run_sync(dirs: gate.Dirs, do_sync) -> str:
    """One try. do_sync() returns the note count or raises. Returns what happened."""
    pending, failed = dirs.sync / "pending", dirs.sync / "failed"
    try:
        stamp = pending.lstat()
    except FileNotFoundError:
        return "nothing to sync"
    if not pending.is_file() or pending.is_symlink():
        pending.unlink()
        return "odd stamp removed"
    try:
        count = do_sync()
    except (Exception, SystemExit) as e:  # owui.api exits on an HTTP error
        reason = f"{type(e).__name__}: {str(e)[:120]}"
        if not failed.exists():  # push once; the stamp stays for the timer
            failed.write_text(reason + "\n")
            gate.log(dirs, "sync", "", "failed", reason)
        return f"failed, will retry: {reason}"
    # A Keep that landed during the sync re-stamped it: leave it, the next run picks it up
    if pending.lstat().st_mtime_ns == stamp.st_mtime_ns:
        pending.unlink()
    failed.unlink(missing_ok=True)
    gate.log(dirs, "sync", "", "ok", f"{count} notes in julz-claude")
    return f"synced {count} notes"


def main():
    spec = importlib.util.spec_from_file_location("sync_knowledge", HERE / "sync-knowledge.py")
    sk = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sk)

    def do_sync():
        return sk.sync(sk.load_key(), sk.CLAUDE_KB_NAME, "Notes Claude wrote, kept from the phone",
                       sk.claude_notes(), claude=True)

    result = run_sync(gate.Dirs(GATE_DIR), do_sync)
    print(result)
    if result.startswith("failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()
