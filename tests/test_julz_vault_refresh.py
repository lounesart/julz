"""julz_vault.refresh: the phone's snapshots within seconds of a save, nothing else (209, threat 142)."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from test_julz_vault import ROOT, TODAY, VaultBase, unit_lines, unit_paths, vault_mod

TODO = "---\ntags:\n  - todo\n---\n\n# Shop\n\n- [ ] buy bread\n"
FINISHED = "---\ntags:\n  - todo\n---\n\n# Old\n\n- [x] call mum (done 2026-10-15)\n"
SNAPSHOTS = ("due.json", "todos.json", "done-week.json", "inbox.json", "notes.json",
             "feedback.json", "goals.json")


class VaultRefreshTest(VaultBase):
    def setUp(self):
        super().setUp()
        (self.vault / "daily").mkdir()
        (self.vault / "feedback").mkdir()
        (self.vault / "daily" / "old.md").write_text(FINISHED)
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "refresh fixture")
        (self.vault / "Inbox" / "shop.md").write_text(TODO)  # a save julz just made

    def tree(self):
        return {str(p.relative_to(self.vault)): (p.read_bytes() if p.is_file() else None)
                for p in sorted(self.vault.rglob("*")) if ".git" not in p.parts}

    def test_writes_the_snapshots_with_the_new_note(self):
        vault_mod.refresh(self.vault, self.state, TODAY)
        for name in SNAPSHOTS:
            self.assertTrue((self.state / name).is_file(), name)
        inbox = json.loads((self.state / "inbox.json").read_text())
        self.assertEqual([n["note"] for n in inbox["notes"]], ["Inbox/shop.md"])
        todos = json.loads((self.state / "todos.json").read_text())
        self.assertIn(["buy bread"], [lst["open"] for lst in todos["lists"]])

    def test_same_snapshots_as_a_full_run(self):
        vault_mod.refresh(self.vault, self.state, TODAY)
        quick = {n: (self.state / n).read_text() for n in ("inbox.json", "notes.json")}
        (self.vault / "Inbox" / "shop.md").unlink()  # run commits it otherwise; same tree both ways
        vault_mod.refresh(self.vault, self.state, TODAY)
        quick_after = (self.state / "inbox.json").read_text()
        self.run_vault()
        self.assertEqual((self.state / "inbox.json").read_text(), quick_after)
        self.assertNotEqual(quick["inbox.json"], quick_after)

    def test_changes_nothing_in_the_vault(self):
        # A pending request and a finished todo: a full run would apply, archive and commit
        self.request({"op": "append", "note": "study/dhcp.md", "text": "planted"})
        before, head = self.tree(), self.git("rev-parse", "HEAD")
        vault_mod.refresh(self.vault, self.state, TODAY)
        self.assertEqual(self.tree(), before)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        self.assertFalse((self.state / "vault-status.json").exists())  # no git read either

    def test_waits_for_a_running_full_run(self):
        held = threading.Event()

        def hold():
            with vault_mod.lock(self.state):
                held.set()
                time.sleep(0.4)

        t = threading.Thread(target=hold)
        t.start()
        held.wait()
        start = time.monotonic()
        vault_mod.refresh(self.vault, self.state, TODAY)
        waited = time.monotonic() - start
        t.join()
        self.assertGreaterEqual(waited, 0.3)
        self.assertTrue((self.state / "inbox.json").is_file())

    def test_full_run_still_refuses_to_wait(self):
        got = []
        with vault_mod.lock(self.state):
            # In a thread, so a run that waits fails this test instead of hanging the suite
            t = threading.Thread(target=lambda: got.append(
                vault_mod.run(self.vault, self.dirs, self.state, TODAY)), daemon=True)
            t.start()
            t.join(5)
            self.assertFalse(t.is_alive(), "the full run waited for the lock")
        self.assertEqual(got, [None])


class RefreshUnitFileTest(unittest.TestCase):
    """Threat 142: its own unit pair, the vault read only, a burst is one run."""
    U = "julz-vault-refresh.service"

    def test_watches_inbox_and_daily_and_starts_only_the_refresh(self):
        lines = unit_lines("julz-vault-refresh.path")
        self.assertEqual(sorted(l for l in lines if l.startswith("Path")),
                         ["PathChanged=%h/Documents/julz-mem/Inbox",
                          "PathChanged=%h/Documents/julz-mem/daily"])
        self.assertIn(f"Unit={self.U}", lines)
        # A failed refresh must never stop signed requests: the old trigger keeps its own unit
        self.assertIn("Unit=julz-vault.service", unit_lines("julz-vault.path"))

    def test_vault_read_only_only_snapshots_writable(self):
        self.assertEqual(unit_paths(self.U, "BindPaths"), {"%h/.local/share/julz/vault"})
        self.assertEqual(unit_paths(self.U, "BindReadOnlyPaths"),
                         {"%h/.local/lib/julz", "%h/Documents/julz-mem"})
        lines = unit_lines(self.U)
        for line in ("TemporaryFileSystem=%h:ro", "PrivateNetwork=yes", "ProtectSystem=strict",
                     "RestrictAddressFamilies=AF_UNIX", "NoNewPrivileges=yes",
                     "ExecStart=/usr/bin/python3 -I %h/.local/lib/julz/current/julz-vault.py --refresh"):
            self.assertIn(line, lines)

    def test_a_burst_is_one_run_under_the_start_limit(self):
        lines = unit_lines(self.U)
        # The wait is in julz-vault.py --refresh: an ExecStartPre loses PrivateNetwork (below)
        limit = {l.split("=", 1)[0]: int(l.split("=", 1)[1].rstrip("s")) for l in lines
                 if l.startswith(("StartLimitIntervalSec=", "StartLimitBurst="))}
        # one start per 3 s at most: the burst must stay above interval / 3
        self.assertGreater(limit["StartLimitBurst"], limit["StartLimitIntervalSec"] / 3)

    def test_refresh_mode_waits_for_the_burst_to_settle(self):
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("julz_vault_cli", ROOT / "julz-vault.py")
        cli = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cli)
        calls = []
        with mock.patch.object(cli.time, "sleep", lambda s: calls.append(("sleep", s))), \
                mock.patch.object(cli.vault, "refresh", lambda *a: calls.append(("refresh",))), \
                mock.patch.object(sys, "argv", ["julz-vault.py", "--refresh"]):
            cli.main()
        self.assertEqual(calls, [("sleep", 3), ("refresh",)])


class NoPreCommandWithPrivateNetworkTest(unittest.TestCase):
    """Found live 24 Oct: in a user unit an ExecStartPre makes the main command run in the
    host network namespace (\"PrivateNetwork=yes is configured, but ... proceeding without\")."""

    def test_no_unit_pairs_them(self):
        for unit in sorted((ROOT / "systemd").glob("julz-*.service")):
            lines = unit.read_text().splitlines()
            if "PrivateNetwork=yes" in lines:
                with self.subTest(unit=unit.name):
                    self.assertFalse([l for l in lines if l.startswith(("ExecStartPre", "ExecStartPost"))])


@unittest.skipUnless(shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"),
                     "needs a user systemd session")
class RefreshRealSandboxTest(unittest.TestCase):
    """The real julz-vault.py --refresh under the sandbox lines of its unit."""

    def test_refresh_runs_and_cannot_write_the_vault(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            v = home / "Documents" / "julz-mem"
            (v / "Inbox").mkdir(parents=True)
            (v / "daily").mkdir()
            (v / "Inbox" / "shop.md").write_text("# Shop\n\n- [ ] buy bread\n")
            (home / ".local/share/julz/vault").mkdir(parents=True)
            lib = home / ".local/lib/julz"
            lib.mkdir(parents=True)
            (lib / "current").symlink_to(ROOT)
            argv = ["systemd-run", "--user", "--wait", "--pipe", "--quiet", "-E", f"HOME={home}"]
            for line in unit_lines("julz-vault-refresh.service"):
                if line.split("=", 1)[0] in ("NoNewPrivileges", "ProtectSystem", "PrivateNetwork",
                                             "UMask", "TemporaryFileSystem", "BindPaths",
                                             "BindReadOnlyPaths", "RestrictAddressFamilies"):
                    argv += ["-p", line.replace("%h/.local/lib/julz", str(lib)).replace("%h", str(home))]
            script = ("import subprocess, sys\n"
                      "r = subprocess.run([sys.executable, '-I', sys.argv[1] + '/julz-vault.py', '--refresh'])\n"
                      "print('refresh', 'ok' if r.returncode == 0 else 'failed')\n"
                      "try:\n"
                      "    open(sys.argv[2] + '/Inbox/planted.md', 'w'); print('write-vault yes')\n"
                      "except OSError: print('write-vault no')\n")
            r = subprocess.run(argv + [sys.executable, "-I", "-c", script, str(lib / "current"), str(v)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertEqual(r.stdout.split(), ["refresh", "ok", "write-vault", "no"], r.stdout + r.stderr)
            inbox = json.loads((home / ".local/share/julz/vault/inbox.json").read_text())
            self.assertEqual([n["note"] for n in inbox["notes"]], ["Inbox/shop.md"])


if __name__ == "__main__":
    unittest.main()
