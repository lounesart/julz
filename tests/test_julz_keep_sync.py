"""Tests for julz-keep-sync.py: kept notes into the julz-claude collection (SECURITY.md 58, 64).
Run: python3 -m unittest discover -s tests -v"""
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
spec = importlib.util.spec_from_file_location("julz_keep_sync", ROOT / "julz-keep-sync.py")
ks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ks)
gate = ks.gate


class RunSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dirs = gate.Dirs(Path(self.tmp.name) / "gate")
        self.dirs.ensure()
        self.state = Path(self.tmp.name) / "state"
        self.state.mkdir()
        self.pending = self.dirs.sync / "pending"
        self.failed = self.state / "failed"
        self.synced = self.state / "synced"
        self.calls = 0
        self.now = 1_800_000_000.0

    def tearDown(self):
        self.tmp.cleanup()

    def run_sync(self, do_sync, fp="A", now=None):
        return ks.run_sync(self.dirs, self.state, fp, do_sync, self.now if now is None else now)

    def stamp(self):
        self.pending.write_text("1\n")

    def record(self, fp="A", checked=None):
        self.synced.write_text(json.dumps({"fingerprint": fp,
                                           "checked": self.now if checked is None else checked}))

    def recorded(self):
        return json.loads(self.synced.read_text())["fingerprint"]

    def log(self):
        if not self.dirs.log.exists():
            return []
        return [json.loads(l) for l in self.dirs.log.read_text().splitlines()]

    def ok(self):
        self.calls += 1
        return 12

    def boom(self):
        self.calls += 1
        raise ConnectionRefusedError("open webui down")

    def test_no_stamp_no_change_no_sync(self):
        # The timer runs this every 10 minutes: with Claude/ unchanged it must not touch the key
        self.record("A")
        self.assertEqual(self.run_sync(self.ok, "A"), "nothing to sync")
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.log(), [])

    def test_removal_by_hand_syncs_without_stamp(self):
        # BACKLOG 13: a Claude note I delete changes the fingerprint, no Keep stamps anything
        self.record("A")
        self.assertEqual(self.run_sync(self.ok, "B"), "synced 12 notes")
        self.assertEqual(self.calls, 1)
        self.assertEqual(self.recorded(), "B")
        self.assertEqual(self.run_sync(self.ok, "B"), "nothing to sync")
        self.assertEqual(self.calls, 1)

    def test_first_run_syncs(self):
        self.assertEqual(self.run_sync(self.ok), "synced 12 notes")
        self.assertEqual(self.recorded(), "A")

    def test_day_old_check_syncs(self):
        self.record("A", checked=self.now - ks.DAY)
        self.assertEqual(self.run_sync(self.ok, "A"), "synced 12 notes")
        self.record("A", checked=self.now - ks.DAY + 1)
        self.assertEqual(self.run_sync(self.ok, "A"), "nothing to sync")

    def test_check_from_the_future_syncs(self):
        # A clock set back must not freeze the sync for good
        self.record("A", checked=self.now + 60)
        self.assertEqual(self.run_sync(self.ok, "A"), "synced 12 notes")

    def test_odd_record_syncs(self):
        for text in ("not json", "[1]", ""):
            self.synced.write_text(text)
            self.calls = 0
            self.run_sync(self.ok, "A")
            self.assertEqual(self.calls, 1, text)

    def test_failure_records_nothing(self):
        self.record("A")
        self.assertTrue(self.run_sync(self.boom, "B").startswith("failed"))
        self.assertEqual(self.recorded(), "A")  # the next tick tries again
        self.assertEqual(self.run_sync(self.ok, "B"), "synced 12 notes")
        self.assertEqual(self.recorded(), "B")

    def test_state_stays_out_of_the_watched_folder(self):
        # julz-keep-sync.path watches sync/: a write there would start this unit again
        self.run_sync(self.boom, "A")
        self.run_sync(self.ok, "A")
        self.assertEqual(os.listdir(self.dirs.sync), [])

    def test_stamp_syncs_even_when_unchanged(self):
        self.record("A")
        self.stamp()
        self.assertEqual(self.run_sync(self.ok, "A"), "synced 12 notes")
        self.assertFalse(self.pending.exists())
        self.assertEqual([(e["action"], e["status"]) for e in self.log()], [("sync", "ok")])

    def test_failure_keeps_stamp_and_pushes_once(self):
        self.stamp()
        for _ in range(3):
            self.assertTrue(self.run_sync(self.boom).startswith("failed"))
        self.assertTrue(self.pending.exists())
        self.assertEqual([(e["action"], e["status"]) for e in self.log()], [("sync", "failed")])
        self.assertEqual(self.run_sync(self.ok), "synced 12 notes")
        self.assertFalse(self.failed.exists())  # the next failure is pushed again

    def test_http_error_exit_is_a_failure(self):
        # owui.api calls sys.exit on an HTTP error: that must count as failed, not done
        self.stamp()

        def exits():
            sys.exit("POST /api/v1/files -> HTTP 500")
        self.assertTrue(self.run_sync(exits).startswith("failed"))
        self.assertTrue(self.pending.exists())

    def test_keep_during_sync_syncs_again(self):
        self.stamp()

        def keep_lands_meanwhile():
            os.utime(self.pending, ns=(1, 1))  # julz-keep stamped again during the sync
            return 3
        self.run_sync(keep_lands_meanwhile)
        self.assertTrue(self.pending.exists())

    def test_linked_stamp_removed_unused(self):
        target = Path(self.tmp.name) / "target"
        target.write_text("x")
        self.pending.symlink_to(target)
        self.assertEqual(self.run_sync(self.ok), "odd stamp removed")
        self.assertEqual(self.calls, 0)
        self.assertTrue(target.exists())


class FingerprintTest(unittest.TestCase):
    """Claude/ as it would be uploaded: a removal, an edit or a rename changes it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ("a.md", "b.md"):
            (self.root / name).write_text(f"# {name}\n")

    def tearDown(self):
        self.tmp.cleanup()

    def fp(self):
        return ks.fingerprint(ks.sk.claude_notes(self.root))

    def test_same_notes_same_print(self):
        self.assertEqual(self.fp(), self.fp())

    def test_removal_edit_and_rename_change_it(self):
        seen = {self.fp()}
        (self.root / "b.md").unlink()
        seen.add(self.fp())
        (self.root / "a.md").write_text("# a, edited\n")
        seen.add(self.fp())
        (self.root / "a.md").rename(self.root / "c.md")
        seen.add(self.fp())
        self.assertEqual(len(seen), 4)

    def test_named_as_uploaded(self):
        # The upload name, Claude__ prefix and all: a note moved into a subfolder is a change
        (self.root / "sub").mkdir()
        before = self.fp()
        (self.root / "a.md").rename(self.root / "sub" / "a.md")
        self.assertNotEqual(before, self.fp())


def unit_lines(unit):
    return (ROOT / "systemd" / unit).read_text().splitlines()


def unit_paths(unit, key):
    out = set()
    for line in unit_lines(unit):
        if line.startswith(key + "="):
            out.update(line[len(key) + 1:].split())
    return out


class SyncUnitFileTest(unittest.TestCase):
    """Threat 64: the unit with the key writes nothing in the vault and sees no other secret."""
    U = "julz-keep-sync.service"

    def test_binds(self):
        self.assertEqual(unit_paths(self.U, "BindPaths"),
                         {"%h/.local/share/julz/sync", "%h/.local/share/julz/log"})
        self.assertEqual(unit_paths(self.U, "BindReadOnlyPaths"),
                         {"%h/.local/lib/julz", "%h/.config/julz/api.env",
                          "%h/Documents/julz-mem/Claude"})
        self.assertIn("TemporaryFileSystem=%h:ro", unit_lines(self.U))

    def test_own_state_folder(self):
        # Threat 154: the fingerprint lives outside sync/, which julz-keep-sync.path watches
        self.assertIn("StateDirectory=julz-keepsync", unit_lines(self.U))
        self.assertEqual(ks.STATE, Path.home() / ".local" / "state" / "julz-keepsync")
        path = [l for l in unit_lines("julz-keep-sync.path") if l.startswith("Path")]
        self.assertEqual(path, ["PathChanged=%h/.local/share/julz/sync"])

    def test_no_pretend_network_rule(self):
        # IPAddressDeny is ignored in user units (tested 2026-10-16): never write it as if
        # it held. SECURITY.md threat 64 says the network is open over IPv4
        directives = [l for l in unit_lines(self.U) if not l.startswith("#")]
        self.assertFalse([l for l in directives if l.startswith("IPAddress")])
        self.assertIn("RestrictAddressFamilies=AF_INET AF_UNIX", directives)


@unittest.skipUnless(shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"),
                     "needs a user systemd session")
class SyncRealSandboxTest(unittest.TestCase):
    """A probe under the sandbox lines of the real julz-keep-sync.service."""

    def test_walls_hold(self):
        probe = (
            "import socket, sys\n"
            "from pathlib import Path\n"
            "home = Path(sys.argv[1])\n"
            "def can(f):\n"
            "    try: f(); return 'yes'\n"
            "    except OSError: return 'no'\n"
            "print('read-key', can(lambda: (home / '.config/julz/api.env').read_text()))\n"
            "print('read-note', can(lambda: (home / 'Documents/julz-mem/Claude/n.md').read_text()))\n"
            "print('read-token', can(lambda: (home / '.config/julz/claude-token.env').read_text()))\n"
            "print('write-claude', can(lambda: open(home / 'Documents/julz-mem/Claude/x.md', 'w')))\n"
            "print('write-vault', can(lambda: open(home / 'Documents/julz-mem/x.md', 'w')))\n"
            "print('write-key', can(lambda: open(home / '.config/julz/api.env', 'a')))\n"
            "print('write-sync', can(lambda: open(home / '.local/share/julz/sync/p', 'w')))\n"
            "print('ipv6', can(lambda: socket.socket(socket.AF_INET6)))\n")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            gate.Dirs(home / ".local/share/julz").ensure()
            cfg = home / ".config" / "julz"
            cfg.mkdir(parents=True)
            (cfg / "api.env").write_text("OPENWEBUI_API_KEY=fake\n")
            (cfg / "claude-token.env").write_text("token\n")
            claude = home / "Documents" / "julz-mem" / "Claude"
            claude.mkdir(parents=True)
            (claude / "n.md").write_text("# n\n")
            (home / "Projects").mkdir()
            argv = ["systemd-run", "--user", "--wait", "--pipe", "--quiet", "-E", f"HOME={home}"]
            for line in unit_lines("julz-keep-sync.service"):
                key = line.split("=", 1)[0]
                # StateDirectory is left out: it would follow the real manager's home, not this one
                if key in ("NoNewPrivileges", "ProtectSystem", "UMask", "TemporaryFileSystem",
                           "BindPaths", "BindReadOnlyPaths", "RestrictAddressFamilies"):
                    line = line.replace("%h/.local/lib/julz", str(ROOT))
                    argv += ["-p", line.replace("%h", str(home))]
            r = subprocess.run(argv + [sys.executable, "-I", "-c", probe, str(home)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            got = dict(l.split() for l in r.stdout.splitlines())
            self.assertEqual(got, {"read-key": "yes", "read-note": "yes", "read-token": "no",
                                   "write-claude": "no", "write-vault": "no", "write-key": "no",
                                   "write-sync": "yes", "ipv6": "no"})


if __name__ == "__main__":
    unittest.main()
