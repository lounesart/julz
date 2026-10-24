"""Tests for julz-mem-sync.py: my notes reach julz-mem on their own (BACKLOG 129, 210,
SECURITY.md 143). Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("julz_mem_sync", ROOT / "julz-mem-sync.py")
ms = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ms)
gate = ms.gate
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location("julz_notify", ROOT / "julz-notify.py")
notify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notify)

NOW = 1_800_000_000.0


class FingerprintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.v = Path(self.tmp.name)
        (self.v / "a.md").write_text("a")
        (self.v / "b.md").write_text("b")

    def tearDown(self):
        self.tmp.cleanup()

    def fp(self):
        return ms.fingerprint([(self.v / n, Path(n)) for n in ("a.md", "b.md")])

    def test_same_vault_same_fingerprint(self):
        self.assertEqual(self.fp(), self.fp())

    def test_an_edit_changes_it(self):
        before = self.fp()
        (self.v / "b.md").write_text("b2")
        self.assertNotEqual(self.fp(), before)

    def test_a_rename_changes_it(self):
        before = self.fp()
        # a2.md still sorts first: only the name changes, not the order
        self.assertNotEqual(ms.fingerprint([(self.v / "a.md", Path("a2.md")),
                                            (self.v / "b.md", Path("b.md"))]), before)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.dirs = gate.Dirs(base / "gate")
        self.dirs.ensure()
        self.state = base / "state"
        self.state.mkdir()
        self.pending = self.state / "pending"
        self.calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def ok(self):
        self.calls += 1
        return 32

    def boom(self):
        self.calls += 1
        sys.exit("POST /api/v1/files -> HTTP 500: secret-host")

    def run_(self, fp="fp1", sync=None, now=NOW):
        return ms.run(self.state, self.dirs, fp, sync or self.ok, now)

    def log(self):
        if not self.dirs.log.exists():
            return []
        return [(e["action"], e["status"]) for e in
                (json.loads(l) for l in self.dirs.log.read_text().splitlines())]

    def test_first_run_syncs(self):
        self.assertEqual(self.run_(), "synced 32 notes")
        self.assertEqual(self.log(), [("mem-sync", "ok")])

    def test_same_vault_never_touches_the_key(self):
        # The timer ticks every 15 minutes: with nothing new it must not read the key (64)
        self.run_()
        self.assertEqual(self.run_(now=NOW + 900), "up to date")
        self.assertEqual(self.calls, 1)

    def test_changed_vault_syncs(self):
        self.run_()
        self.assertEqual(self.run_(fp="fp2", now=NOW + 900), "synced 32 notes")
        self.assertEqual(self.calls, 2)

    def test_daily_check_even_when_unchanged(self):
        # Something outside could change the collection (a resync by hand, an Open WebUI reset)
        self.run_()
        self.run_(now=NOW + 86400 + 1)
        self.assertEqual(self.calls, 2)

    def test_clock_gone_back_checks(self):
        self.run_()
        self.run_(now=NOW - 3600)
        self.assertEqual(self.calls, 2)

    def test_stamp_syncs_and_is_cleared(self):
        self.run_()
        self.pending.write_text("1\n")
        self.assertEqual(self.run_(now=NOW + 60), "synced 32 notes")
        self.assertFalse(self.pending.exists())

    def test_stamp_during_sync_stays(self):
        self.pending.write_text("1\n")

        def stamped_meanwhile():
            os.utime(self.pending, ns=(1, 1))
            return 3
        self.run_(sync=stamped_meanwhile)
        self.assertTrue(self.pending.exists())

    def test_odd_stamp_removed_unused(self):
        target = Path(self.tmp.name) / "target"
        target.write_text("x")
        self.pending.symlink_to(target)
        self.assertEqual(self.run_(), "odd stamp removed")
        self.assertEqual(self.calls, 0)
        self.assertTrue(target.exists())

    def test_failure_retries_and_pushes_once(self):
        for i in range(3):
            self.assertTrue(self.run_(sync=self.boom, now=NOW + i).startswith("failed"))
        self.assertEqual(self.calls, 3)  # no fingerprint was saved, so every tick tries again
        self.assertEqual(self.log(), [("mem-sync", "failed")])
        self.run_(now=NOW + 10)
        self.assertFalse((self.state / "failed").exists())  # the next failure pushes again

    def test_failure_keeps_the_stamp(self):
        self.pending.write_text("1\n")
        self.run_(sync=self.boom)
        self.assertTrue(self.pending.exists())

    def test_broken_state_file_syncs(self):
        (self.state / "synced").write_text("{not json")
        self.assertEqual(self.run_(), "synced 32 notes")


class NoticeTest(unittest.TestCase):
    def test_success_is_quiet(self):
        self.assertIsNone(notify.log_notice({"action": "mem-sync", "status": "ok", "sha256": "",
                                             "reason": "32 notes in julz-mem"}))

    def test_failure_pushed_without_details(self):
        n = notify.log_notice({"action": "mem-sync", "status": "failed", "sha256": "",
                               "reason": "SystemExit: HTTP 500: secret-host"})
        self.assertEqual(n.priority, "high")
        self.assertIn("memory", n.title.lower())
        self.assertNotIn("secret-host", n.title + n.body)


def unit_lines(unit):
    return (ROOT / "systemd" / unit).read_text().splitlines()


def unit_paths(unit, key):
    out = set()
    for line in unit_lines(unit):
        if line.startswith(key + "="):
            out.update(line[len(key) + 1:].split())
    return out


HIDDEN = ("Inbox", "Outbox", "Claude", "Templates", "feedback", ".git")


class MemSyncUnitFileTest(unittest.TestCase):
    """Threat 143: the vault read only, the skip list also a wall, the key as 64."""
    U = "julz-mem-sync.service"

    def test_binds(self):
        self.assertEqual(unit_paths(self.U, "BindPaths"), {"%h/.local/share/julz/log"})
        self.assertEqual(unit_paths(self.U, "BindReadOnlyPaths"),
                         {"%h/.local/lib/julz", "%h/.config/julz/api.env", "%h/Documents/julz-mem"})
        self.assertEqual(unit_paths(self.U, "InaccessiblePaths"),
                         {f"-%h/Documents/julz-mem/{d}" for d in HIDDEN})
        lines = unit_lines(self.U)
        for line in ("TemporaryFileSystem=%h:ro", "ProtectSystem=strict", "NoNewPrivileges=yes",
                     "StateDirectory=julz-memsync", "RestrictAddressFamilies=AF_INET AF_UNIX",
                     "ExecStart=/usr/bin/python3 -I %h/.local/lib/julz/current/julz-mem-sync.py"):
            self.assertIn(line, lines)

    def test_skip_list_and_walls_agree(self):
        # The code's skip list and the unit's walls name the same folders (58, 143)
        import inspect
        src = inspect.getsource(ms.sk.vault_notes)
        for d in HIDDEN[:-1]:
            self.assertIn(f'"{d}"', src)

    def test_no_pretend_network_rule(self):
        directives = [l for l in unit_lines(self.U) if not l.startswith("#")]
        self.assertFalse([l for l in directives if l.startswith(("IPAddress", "ExecStartPre"))])

    def test_started_by_its_timer_and_its_own_stamp(self):
        path = unit_lines("julz-mem-sync.path")
        self.assertEqual([l for l in path if l.startswith("Path")],
                         ["PathChanged=%h/.local/state/julz-memsync/pending"])
        self.assertIn(f"Unit={self.U}", path)
        self.assertIn(f"Unit={self.U}", unit_lines("julz-mem-sync.timer"))
        # Never the sync/ folder: keep-sync's path watches it, the two would start each other
        self.assertNotIn("%h/.local/share/julz/sync", " ".join(unit_lines(self.U)))


@unittest.skipUnless(shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"),
                     "needs a user systemd session")
class MemSyncRealSandboxTest(unittest.TestCase):
    """A probe under the sandbox lines of the real julz-mem-sync.service."""

    def test_walls_hold(self):
        probe = (
            "import os, socket, sys\n"
            "from pathlib import Path\n"
            "home = Path(sys.argv[1]); v = home / 'Documents/julz-mem'\n"
            "def can(f):\n"
            "    try: f(); return 'yes'\n"
            "    except OSError: return 'no'\n"
            "print('read-key', can(lambda: (home / '.config/julz/api.env').read_text()))\n"
            "print('read-note', can(lambda: (v / 'study/n.md').read_text()))\n"
            "print('read-daily', can(lambda: (v / 'daily/d.md').read_text()))\n"
            "for d in ('Inbox', 'Outbox', 'Claude', 'Templates', 'feedback', '.git'):\n"
            "    print('see-' + d, can(lambda: os.listdir(v / d)))\n"
            "print('read-token', can(lambda: (home / '.config/julz/claude-token.env').read_text()))\n"
            "print('write-vault', can(lambda: open(v / 'x.md', 'w')))\n"
            "print('write-key', can(lambda: open(home / '.config/julz/api.env', 'a')))\n"
            "print('write-log', can(lambda: open(home / '.local/share/julz/log/p', 'w')))\n"
            "print('write-sync', can(lambda: open(home / '.local/share/julz/sync/pending', 'w')))\n"
            "print('ipv6', can(lambda: socket.socket(socket.AF_INET6)))\n")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            gate.Dirs(home / ".local/share/julz").ensure()
            cfg = home / ".config" / "julz"
            cfg.mkdir(parents=True)
            (cfg / "api.env").write_text("OPENWEBUI_API_KEY=fake\n")
            (cfg / "claude-token.env").write_text("token\n")
            v = home / "Documents" / "julz-mem"
            for d in ("study", "daily") + HIDDEN:
                (v / d).mkdir(parents=True)
                (v / d / "n.md").write_text("# n\n")
            (v / "daily" / "d.md").write_text("# d\n")
            argv = ["systemd-run", "--user", "--wait", "--pipe", "--quiet", "-E", f"HOME={home}"]
            for line in unit_lines("julz-mem-sync.service"):
                key = line.split("=", 1)[0]
                # StateDirectory is left out: it would follow the real manager's home, not this one
                if key in ("NoNewPrivileges", "ProtectSystem", "UMask", "TemporaryFileSystem",
                           "BindPaths", "BindReadOnlyPaths", "InaccessiblePaths",
                           "RestrictAddressFamilies"):
                    line = line.replace("%h/.local/lib/julz", str(ROOT))
                    argv += ["-p", line.replace("%h", str(home))]
            r = subprocess.run(argv + [sys.executable, "-I", "-c", probe, str(home)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            got = dict(l.split() for l in r.stdout.splitlines())
            want = {"read-key": "yes", "read-note": "yes", "read-daily": "yes",
                    "read-token": "no", "write-vault": "no", "write-key": "no",
                    "write-log": "yes", "write-sync": "no", "ipv6": "no"}
            want.update({f"see-{d}": "no" for d in HIDDEN})
            self.assertEqual(got, want)


if __name__ == "__main__":
    unittest.main()
