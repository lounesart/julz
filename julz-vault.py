#!/usr/bin/env python3
"""Apply julz's note requests and keep ~/Documents/julz-mem in git (julz_vault.py).

julz's notes tool drops a request into Inbox/.requests/ after I confirm in the chat, and
julz-vault.path starts this. julz-vault.timer starts it every 15 minutes too, which commits my
own edits. Security model: SECURITY.md threats 65 to 70.
- runs in julz-vault.service: no network, no key, no token, an empty read only home; the
  vault, the runner log and its own state folder are the only writable places
- my changes are committed first, then each request is checked, applied and committed alone
Usage: ./julz-vault.py             apply requests, commit, rebuild the snapshots
       ./julz-vault.py --refresh   only the snapshots, read only (julz-vault-refresh.path, 209)
"""
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402
import julz_vault as vault  # noqa: E402

HOME = Path.home()
VAULT = HOME / "Documents" / "julz-mem"
GATE_DIR = HOME / ".local" / "share" / "julz"
STATE_DIR = GATE_DIR / "vault"
# A burst of saves is one refresh. Here, not in an ExecStartPre: that one loses PrivateNetwork
SETTLE = 3


def main():
    if sys.argv[1:] == ["--refresh"]:
        time.sleep(SETTLE)
        vault.refresh(VAULT, STATE_DIR, date.today())
        return
    if sys.argv[1:]:
        sys.exit(__doc__)
    results = vault.run(VAULT, gate.Dirs(GATE_DIR), STATE_DIR, date.today())
    if results is None:
        print("julz-vault is already running")
        return
    for h, status, reason in results:
        print(f"request {h}: {status} {reason}".rstrip())
    if not results:
        print("no requests")


if __name__ == "__main__":
    main()
