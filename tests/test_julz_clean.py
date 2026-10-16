"""Tests for julz-clean.py: removing leftovers, SECURITY.md threats 44 to 46.
Ages are set with os.utime and log times, so nothing waits.
Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


clean = load("julz_clean", "julz-clean.py")
gate = clean.gate

NOW = 2_000_000_000.0
DAY = clean.DAY
GOOD = ("goal: add a usage line to the README\n"
        "project: julz-sandbox\n"
        "done_when: README has a Usage section\n")
H = gate.sha256(GOOD)
H2 = "b" * 64


def aged(path: Path, days: float):
    t = NOW - days * DAY
    os.utime(path, (t, t), follow_symlinks=False)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.dirs = gate.Dirs(self.base / "gate", outbox=self.base / "Outbox")
        self.dirs.ensure()
        self.inbox = self.base / "Inbox" / "claude"
        self.inbox.mkdir(parents=True)
        self.work = self.base / "gate" / "work"
        self.work.mkdir()
        self.outside = self.base / "my-project"  # stands for ~/Projects: must survive
        self.outside.mkdir()
        (self.outside / "precious.txt").write_text("my code")

    def tearDown(self):
        self.tmp.cleanup()

    def log_run(self, digest, days_ago):
        t = datetime.fromtimestamp(NOW - days_ago * DAY, timezone.utc).isoformat()
        with open(self.dirs.log, "a") as f:
            f.write(json.dumps({"time": t, "action": "run", "sha256": digest,
                                "status": "ok"}) + "\n")

    def work_copy(self, digest=H, days=10, run_days=None):
        w = self.work / digest
        w.mkdir()
        (w / "file.txt").write_text("x")
        if run_days is not None:
            self.log_run(digest, run_days)
        aged(w, days)
        return w

    def plan(self):
        return clean.plan(self.dirs, self.inbox, self.work, NOW)

    def run_clean(self):
        actions, notes = self.plan()
        clean.apply(actions, self.dirs, NOW)
        return actions, notes

    def kinds(self):
        return {(a.kind, a.path.name) for a in self.plan()[0]}

    def assert_outside_intact(self):
        self.assertEqual((self.outside / "precious.txt").read_text(), "my code")


class WorkTest(Base):
    def test_old_work_copy_removed(self):
        w = self.work_copy(run_days=8)
        self.run_clean()
        self.assertFalse(w.exists())
        self.assertIn('"clean"', self.dirs.log.read_text())

    def test_young_work_copy_kept(self):
        w = self.work_copy(run_days=3)
        self.run_clean()
        self.assertTrue(w.exists())

    def test_last_run_counts_not_folder_time(self):
        # Folder is old, but a run 2 days ago used it: keep
        w = self.work_copy(days=30, run_days=2)
        self.run_clean()
        self.assertTrue(w.exists())

    def test_continuation_run_keeps_root_copy(self):
        # The root ran 10 days ago, its continuation 2 days ago: the copy is still in use
        w = self.work_copy(run_days=10)
        cont = f"continue: {H}\nstep: 2\nneed_hash: {'0' * 64}\nanswer: done\n"
        (self.dirs.done / f"{gate.sha256(cont)}.md").write_text(cont)
        self.log_run(gate.sha256(cont), 2)
        self.run_clean()
        self.assertTrue(w.exists())

    def test_warned_once_before_removal(self):
        self.work_copy(run_days=6.5)
        self.assertIn(("warn", H), self.kinds())
        self.run_clean()
        self.assertNotIn(("warn", H), self.kinds())
        self.assertIn('"clean-warn"', self.dirs.log.read_text())

    def test_active_task_copy_kept(self):
        for status in ("waiting", "approved"):
            with self.subTest(status=status):
                w = self.work / H
                if not w.exists():
                    self.work_copy(run_days=20)
                gate.save_task(self.dirs, {"root": H, "status": status, "step": 2})
                self.run_clean()
                self.assertTrue(w.exists())

    def test_stderr_removed_after_7_days(self):
        old = self.work / f"{H}.stderr"
        old.write_text("e")
        aged(old, 8)
        young = self.work / f"{H2}.stderr"
        young.write_text("e")
        aged(young, 1)
        self.run_clean()
        self.assertFalse(old.exists())
        self.assertTrue(young.exists())

    def test_unknown_names_left_alone(self):
        odd = self.work / "notes"
        odd.mkdir()
        aged(odd, 100)
        _, notes = self.run_clean()
        self.assertTrue(odd.exists())
        self.assertTrue(any("unknown" in n for n in notes))


class LinkAttackTest(Base):
    """Threat 44: Claude writes anything inside a work copy, including links."""

    def test_link_inside_work_copy_not_followed(self):
        w = self.work_copy(run_days=8)
        (w / "escape").symlink_to(self.outside)
        (w / "escape-file").symlink_to(self.outside / "precious.txt")
        self.run_clean()
        self.assertFalse(w.exists())
        self.assert_outside_intact()

    def test_work_copy_that_is_a_link_removed_as_link(self):
        (self.work / H).symlink_to(self.outside)
        aged(self.work / H, 30)
        self.run_clean()
        self.assertFalse((self.work / H).is_symlink())
        self.assert_outside_intact()
        self.assertTrue(self.outside.is_dir())

    def test_work_root_that_is_a_link_refused(self):
        self.work.rmdir()
        victim = self.outside / H
        victim.mkdir()
        (victim / "f").write_text("mine")
        aged(victim, 30)
        self.work.symlink_to(self.outside)
        actions, notes = self.run_clean()
        self.assertTrue(victim.exists())
        self.assertTrue(any("refused" in n for n in notes))
        self.assertEqual([a for a in actions if self.outside in a.path.parents], [])

    def test_inbox_link_removed_not_target(self):
        link = self.inbox / "evil.md"
        link.symlink_to(self.outside / "precious.txt")
        aged(link, 30)
        self.run_clean()
        self.assertFalse(link.is_symlink())
        self.assert_outside_intact()

    def test_rmtree_is_link_safe_here(self):
        # The whole tree removal rests on this property of the platform
        self.assertTrue(clean.shutil.rmtree.avoids_symlink_attacks)


class GateFilesTest(Base):
    """Threat 45: never delete what a control reads."""

    def test_done_name_kept_forever_text_emptied(self):
        d = self.dirs.done / f"{H}.md"
        d.write_text(GOOD)
        aged(d, 400)
        self.run_clean()
        self.assertTrue(d.exists())
        self.assertEqual(d.read_text(), "")
        with self.assertRaises(gate.SpecError):  # run once still holds
            gate.store_approved(GOOD, self.dirs, {"julz-sandbox"})

    def test_young_done_text_kept(self):
        d = self.dirs.done / f"{H}.md"
        d.write_text(GOOD)
        aged(d, 5)
        self.run_clean()
        self.assertEqual(d.read_text(), GOOD)

    def test_runner_log_untouched(self):
        self.log_run(H, 500)
        aged(self.dirs.log, 500)
        before = self.dirs.log.read_text()
        self.run_clean()
        self.assertTrue(self.dirs.log.read_text().startswith(before))

    def test_old_approval_spent_never_runs(self):
        gate.store_approved(GOOD, self.dirs, {"julz-sandbox"})
        aged(self.dirs.approved / f"{H}.md", 2)
        self.run_clean()
        self.assertFalse((self.dirs.approved / f"{H}.md").exists())
        self.assertTrue((self.dirs.done / f"{H}.md").exists())
        with self.assertRaises(gate.SpecError):
            gate.store_approved(GOOD, self.dirs, {"julz-sandbox"})

    def test_young_approval_kept(self):
        gate.store_approved(GOOD, self.dirs, {"julz-sandbox"})
        aged(self.dirs.approved / f"{H}.md", 0.5)
        self.run_clean()
        self.assertTrue((self.dirs.approved / f"{H}.md").exists())

    def test_spent_continuation_expires_task(self):
        cont = f"continue: {H}\nstep: 2\nneed_hash: {'0' * 64}\nanswer: done\n"
        gate.save_task(self.dirs, {"root": H, "status": "approved", "step": 2})
        gate.publish(cont, self.dirs)
        aged(self.dirs.approved / f"{gate.sha256(cont)}.md", 2)
        self.run_clean()
        self.assertEqual(gate.load_task(self.dirs, H)["status"], "expired")

    def test_quarantine_kept_30_days(self):
        q = self.dirs.quarantine / f"{H}.md"
        q.write_text("held back")
        aged(q, 20)
        self.run_clean()
        self.assertTrue(q.exists())
        aged(q, 31)
        self.run_clean()
        self.assertFalse(q.exists())

    def test_interrupted_writes_removed(self):
        t1 = self.dirs.tmp / "x.123"
        t1.write_text("half")
        aged(t1, 1)
        t2 = self.dirs.tasks / f".{H}.1.tmp"
        t2.write_text("half")
        aged(t2, 1)
        young = self.dirs.tmp / "y.456"
        young.write_text("now")
        aged(young, 10 / (24 * 60))  # 10 minutes: a write that may still be going
        self.run_clean()
        self.assertFalse(t1.exists())
        self.assertFalse(t2.exists())
        self.assertTrue(young.exists())

    def test_finished_task_removed_active_kept(self):
        gate.save_task(self.dirs, {"root": H, "status": "done", "step": 2})
        gate.save_task(self.dirs, {"root": H2, "status": "waiting", "step": 2})
        aged(gate.task_path(self.dirs, H), 40)
        aged(gate.task_path(self.dirs, H2), 40)
        self.run_clean()
        self.assertFalse(gate.task_path(self.dirs, H).exists())
        self.assertTrue(gate.task_path(self.dirs, H2).exists())


class RetentionTest(Base):
    def test_inbox_after_7_days(self):
        old = self.inbox / "old.md"
        old.write_text(GOOD)
        aged(old, 8)
        young = self.inbox / "new.md"
        young.write_text(GOOD)
        aged(young, 2)
        self.run_clean()
        self.assertFalse(old.exists())
        self.assertTrue(young.exists())

    def test_outbox_after_30_days(self):
        old = self.dirs.outbox / f"{H}.md"
        old.write_text("r")
        aged(old, 31)
        young = self.dirs.outbox / f"{H2}.md"
        young.write_text("r")
        aged(young, 29)
        self.run_clean()
        self.assertFalse(old.exists())
        self.assertTrue(young.exists())

    def test_dry_run_changes_nothing(self):
        w = self.work_copy(run_days=30)
        actions, _ = self.plan()
        self.assertTrue(actions)
        self.assertTrue(w.exists())
        self.assertFalse(self.dirs.log.read_text().count('"clean"'))

    def test_every_action_logged(self):
        self.work_copy(run_days=30)
        q = self.dirs.quarantine / f"{H}.md"
        q.write_text("x")
        aged(q, 40)
        actions, _ = self.run_clean()
        lines = [json.loads(l) for l in self.dirs.log.read_text().splitlines()]
        self.assertEqual(sum(1 for e in lines if e["action"] == "clean"), len(actions))


SANDBOX_SNIPPET = """
import sys, os, importlib.util
sys.path.insert(0, sys.argv[1])
spec = importlib.util.spec_from_file_location("julz_clean", sys.argv[1] + "/julz-clean.py")
clean = importlib.util.module_from_spec(spec)
spec.loader.exec_module(clean)
from pathlib import Path
base = Path(sys.argv[2])
dirs = clean.gate.Dirs(base / "gate", outbox=base / "Outbox")
now = float(sys.argv[3])
actions, notes = clean.plan(dirs, base / "Inbox", base / "gate" / "work", now)
print(clean.apply(actions, dirs, now), len(actions))
"""


@unittest.skipUnless(clean.shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"),
                     "needs a user systemd session")
class SandboxLayoutTest(Base):
    """In julz-clean.service every folder is its own mount: spending an approval writes in
    done/ and deletes in approved/, so it must never rename across them (EXDEV)."""

    def test_clean_with_separate_mounts(self):
        import subprocess
        cont = f"continue: {H}\nstep: 2\nneed_hash: {'0' * 64}\nanswer: done\n"
        gate.save_task(self.dirs, {"root": H, "status": "approved", "step": 2})
        gate.publish(cont, self.dirs)
        aged(self.dirs.approved / f"{gate.sha256(cont)}.md", 2)
        w = self.work_copy(H2, run_days=30)
        argv = ["systemd-run", "--user", "--wait", "--pipe", "--quiet"]
        for d in (self.dirs.approved, self.dirs.done, self.dirs.tasks, self.dirs.quarantine,
                  self.dirs.outbox, self.work, self.inbox):
            argv += ["-p", f"BindPaths={d}"]
        argv += [sys.executable, "-I", "-c", SANDBOX_SNIPPET, str(ROOT), str(self.base),
                 str(NOW)]
        r = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-500:])
        done, planned = r.stdout.split()
        self.assertEqual(done, planned, self.dirs.log.read_text())
        self.assertTrue((self.dirs.done / f"{gate.sha256(cont)}.md").exists())
        self.assertEqual(gate.load_task(self.dirs, H)["status"], "expired")
        self.assertFalse(w.exists())


if __name__ == "__main__":
    unittest.main()
