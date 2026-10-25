"""Tests for julz-notify.py: pushes to the phone through ntfy, SECURITY.md threat 39.
A fake sender records messages, nothing reaches ntfy.sh.
Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


notify = load("julz_notify", "julz-notify.py")
gate = notify.gate

H = "4ed192f941fd21bc8b55e87b6e4be5eb40866ce82418aa1ced0b053eb5b7a78f"
SECRET = "SPEC-TEXT-MARKER"  # stands for anything a spec or report could say


def line(**entry):
    return json.dumps(entry) + "\n"


class Recorder:
    def __init__(self, fail_after=None):
        self.sent = []
        self.fail_after = fail_after

    def __call__(self, notice):
        if self.fail_after is not None and len(self.sent) >= self.fail_after:
            raise OSError("ntfy down")
        self.sent.append(notice)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.log = self.base / "runner.log"
        self.inbox = self.base / "Inbox" / "claude"
        self.inbox.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def all_text(self, notices):
        return " ".join(n.title + " " + n.body for n in notices)


class TemplateTest(Base):
    """Only fixed templates, hash prefixes and counts leave the laptop."""

    def test_reason_never_sent(self):
        # refuse reasons quote up to 40 chars of a spec line (julz_gate.log)
        for action, status in (("refuse", "refused"), ("run", "failed"), ("run", "quarantined"),
                               ("run", "ok"), ("reject", "ok"), ("enroll", "ok"),
                               ("need", "ok"), ("expire", "ok"), ("stop", "ok"),
                               ("task-end", "failed"), ("clean-warn", "ok"),
                               ("run", "stopped"), ("override", "ok")):
            with self.subTest(action=action, status=status):
                n = notify.log_notice({"action": action, "status": status, "sha256": H,
                                       "reason": SECRET})
                self.assertIsNotNone(n)
                self.assertNotIn(SECRET, n.title + n.body)

    def test_same_question_again_says_so(self):
        # 130: a fixed text picked by the exact reason, the reason itself never sent
        n = notify.log_notice({"action": "task-end", "status": "failed", "sha256": H,
                               "reason": "asked the same again"})
        self.assertIn("same", n.body)
        self.assertNotIn("asked the same again", n.title + n.body)
        other = notify.log_notice({"action": "task-end", "status": "failed", "sha256": H,
                                   "reason": "too many continuations"})
        self.assertNotIn("same", other.body)

    def test_notices_point_to_the_app(self):
        # Found 18 Oct: "Open the approver" sent me to the web page the app replaces (9b)
        for n in (notify.inbox_notice(1), notify.inbox_notice(2),
                  notify.log_notice({"action": "need", "status": "ok", "sha256": H}),
                  notify.log_notice({"action": "approve-channel", "status": "ok", "sha256": H,
                                     "reason": "phone"})):
            with self.subTest(body=n.body):
                self.assertIn("Approve in Julz", n.body)
                self.assertNotIn("approver", n.body.lower())

    def test_signed_lines_are_quiet(self):
        self.assertIsNone(notify.log_notice({"action": "signed", "status": "ok", "sha256": H,
                                             "reason": "stop, phone"}))

    def test_override_is_pushed_high(self):
        # Threat 52: every break glass use is announced, so a misuse is seen at once
        n = notify.log_notice({"action": "override", "status": "ok", "sha256": H})
        self.assertEqual(n.priority, "high")
        self.assertIn(H[:8], n.title)

    def test_keep_pushed_without_topic_or_files(self):
        # Threat 63 and B11: every Keep and refusal is pushed, never what was kept
        ok = notify.log_notice({"action": "keep", "status": "ok", "sha256": H,
                                "reason": "2 files to Claude/secret-topic/abcd1234"})
        bad = notify.log_notice({"action": "keep", "status": "failed", "sha256": H,
                                 "reason": "labs/private.md changed since signing"})
        self.assertIn(H[:8], ok.title)
        self.assertEqual(bad.priority, "high")
        for n in (ok, bad):
            self.assertNotIn("secret-topic", n.title + n.body)
            self.assertNotIn("private", n.title + n.body)
        self.assertIsNone(notify.log_notice({"action": "keep-signed", "status": "ok",
                                             "sha256": H}))

    def test_feedback_quiet_when_saved_one_notice_when_refused(self):
        # Threat 120: the list in the app shows a saved note; a refused one says so, no text
        self.assertIsNone(notify.log_notice({"action": "feedback", "status": "ok", "sha256": H}))
        self.assertIsNone(notify.log_notice({"action": "feedback-signed", "status": "ok", "sha256": H}))
        bad = notify.log_notice({"action": "feedback", "status": "refused", "sha256": H, "reason": "text too long"})
        self.assertIn("feedback", bad.title.lower())
        self.assertNotIn("long", bad.title + bad.body)

    def test_ticks_quiet_when_fine_one_notice_when_refused(self):
        # Threat 113: the list on the phone shows a good tick; a refused one says so, no text
        self.assertIsNone(notify.log_notice({"action": "tick", "status": "ok", "sha256": H}))
        self.assertIsNone(notify.log_notice({"action": "tick-signed", "status": "ok", "sha256": H,
                                             "reason": "3 tasks, device x"}))
        bad = notify.log_notice({"action": "tick", "status": "refused", "sha256": H,
                                 "reason": "task not found exactly once"})
        self.assertIn("tick", bad.title.lower())
        self.assertNotIn("found", bad.title + bad.body)
        # 127: a start the same way
        self.assertIsNone(notify.log_notice({"action": "start", "status": "ok", "sha256": H}))
        self.assertIsNone(notify.log_notice({"action": "start-signed", "status": "ok", "sha256": H, "reason": "1 tasks"}))
        bad = notify.log_notice({"action": "start", "status": "refused", "sha256": H, "reason": "task not found exactly once"})
        self.assertIn("start", bad.title.lower())
        self.assertNotIn("found", bad.title + bad.body)

    def test_note_changes_pushed_without_names_or_text(self):
        # Threats 65 and 69: every append and every blocked vault commit is pushed, so an
        # append that skipped my click still shows up; reviews alone are not worth a push
        ok = notify.log_notice({"action": "note", "status": "ok", "sha256": H})
        refused = notify.log_notice({"action": "note", "status": "refused", "sha256": H,
                                     "reason": SECRET})
        failed = notify.log_notice({"action": "reviewed", "status": "failed", "sha256": H,
                                    "reason": SECRET})
        blocked = notify.log_notice({"action": "vault-commit", "status": "failed", "sha256": H,
                                     "reason": SECRET})
        self.assertIn(H[:8], ok.title)
        self.assertIn("revert", ok.body)
        for n in (ok, refused, failed, blocked):
            self.assertNotIn(SECRET, n.title + n.body)
        self.assertEqual(blocked.priority, "high")
        self.assertIsNone(notify.log_notice({"action": "reviewed", "status": "ok",
                                             "sha256": H}))

    def test_moves_and_deletes_pushed_without_names(self):
        # Threat 73: every move and delete reaches the phone; a delete is the louder one
        moved = notify.log_notice({"action": "note-move", "status": "ok", "sha256": H})
        deleted = notify.log_notice({"action": "note-delete", "status": "ok", "sha256": H})
        refused = notify.log_notice({"action": "note-delete", "status": "refused",
                                     "sha256": H, "reason": SECRET})
        self.assertIn(H[:8], moved.title)
        self.assertEqual(deleted.priority, "high")
        self.assertIn("checkout", deleted.body)
        for n in (moved, deleted, refused):
            self.assertNotIn(SECRET, n.title + n.body)

    def test_solved_feedback_pushed_without_names(self):
        # Threat 85: a solve I did not make shows on my phone
        solved = notify.log_notice({"action": "feedback-solved", "status": "ok", "sha256": H})
        refused = notify.log_notice({"action": "feedback-solved", "status": "refused",
                                     "sha256": H, "reason": SECRET})
        self.assertIn(H[:8], solved.title)
        self.assertIn("feedback", solved.title)
        self.assertIn("revert", solved.body)
        for n in (solved, refused):
            self.assertNotIn(SECRET, n.title + n.body)

    def test_sync_pushed_without_details(self):
        ok = notify.log_notice({"action": "sync", "status": "ok", "sha256": "",
                                "reason": "12 notes in julz-claude"})
        bad = notify.log_notice({"action": "sync", "status": "failed", "sha256": "",
                                 "reason": "URLError: secret-host refused"})
        self.assertIn("ready", ok.title)
        self.assertEqual(bad.priority, "high")
        self.assertNotIn("secret-host", bad.title + bad.body)

    def test_bad_hash_shown_as_question_mark(self):
        n = notify.log_notice({"action": "run", "status": "ok", "sha256": SECRET})
        self.assertIn("?", n.title)
        self.assertNotIn(SECRET, n.title + n.body)

    def test_hash_is_shortened(self):
        n = notify.log_notice({"action": "run", "status": "ok", "sha256": H})
        self.assertIn(H[:8], n.title)
        self.assertNotIn(H[:9], n.title)

    def test_all_templates_ascii(self):
        # ntfy headers must be ASCII; also keeps odd characters out of my notification shade
        for entry in ({"action": "approve-channel", "reason": "phone"}, {"action": "reject"},
                      {"action": "enroll"}, {"action": "refuse"},
                      {"action": "run", "status": "ok"}, {"action": "run", "status": "quarantined"},
                      {"action": "run", "status": "failed"}, {"action": "need"},
                      {"action": "expire"}, {"action": "stop"},
                      {"action": "task-end", "status": "failed"}, {"action": "clean-warn"}):
            n = notify.log_notice({**entry, "sha256": H})
            (n.title + n.body + n.tags + n.priority).encode("ascii")
        notify.inbox_notice(3).title.encode("ascii")

    def test_quiet_lines(self):
        for entry in ({"action": "start"}, {"action": "approve"}, {"action": "unknown"},
                      {"action": "clean"}, {"action": "halt"},
                      {"action": "task-end", "status": "done"},
                      {"action": "approve-channel", "reason": "terminal"}):
            self.assertIsNone(notify.log_notice({"status": "ok", "sha256": H, **entry}))

    def test_stopped_run_is_not_a_failure(self):
        n = notify.log_notice({"action": "run", "status": "stopped", "sha256": H})
        self.assertIn("stopped", n.title)
        self.assertNotIn("failed", n.title)

    def test_security_events_are_loud(self):
        self.assertEqual(notify.log_notice({"action": "enroll", "status": "ok"}).priority,
                         "urgent")
        self.assertEqual(notify.log_notice({"action": "run", "status": "quarantined",
                                            "sha256": H}).priority, "urgent")


class LogTest(Base):
    def test_first_run_skips_history(self):
        self.log.write_text(line(action="run", status="ok", sha256=H))
        rec, state = Recorder(), {}
        notify.check_log(self.log, state, rec)
        self.assertEqual(rec.sent, [])
        self.assertEqual(state["log_offset"], self.log.stat().st_size)

    def test_new_lines_sent_once(self):
        self.log.write_text(line(action="start", status="ok", sha256=H))
        rec, state = Recorder(), {}
        notify.check_log(self.log, state, rec)
        with open(self.log, "a") as f:
            f.write(line(action="approve", status="ok", sha256=H))
            f.write(line(action="approve-channel", status="ok", sha256=H, reason="phone"))
            f.write(line(action="run", status="ok", sha256=H))
        notify.check_log(self.log, state, rec)
        notify.check_log(self.log, state, rec)
        self.assertEqual([n.title for n in rec.sent],
                         [f"Julz: approved {H[:8]}", f"Julz: run done {H[:8]}"])

    def test_failed_send_keeps_progress(self):
        self.log.write_text("")
        state = {}
        notify.check_log(self.log, state, Recorder())
        with open(self.log, "a") as f:
            f.write(line(action="reject", status="ok", sha256=H))
            f.write(line(action="run", status="ok", sha256=H))
        rec = Recorder(fail_after=1)
        with self.assertRaises(OSError):
            notify.check_log(self.log, state, rec)
        self.assertEqual(len(rec.sent), 1)
        rec2 = Recorder()
        notify.check_log(self.log, state, rec2)
        self.assertEqual([n.title for n in rec2.sent], [f"Julz: run done {H[:8]}"])

    def test_half_written_line_waits(self):
        self.log.write_text("")
        state = {}
        notify.check_log(self.log, state, Recorder())
        whole = line(action="run", status="ok", sha256=H)
        with open(self.log, "a") as f:
            f.write(whole[:20])
        rec = Recorder()
        notify.check_log(self.log, state, rec)
        self.assertEqual(rec.sent, [])
        with open(self.log, "a") as f:
            f.write(whole[20:])
        notify.check_log(self.log, state, rec)
        self.assertEqual(len(rec.sent), 1)

    def test_rotated_log_starts_over(self):
        self.log.write_text(line(action="start", status="ok", sha256=H) * 5)
        state = {}
        notify.check_log(self.log, state, Recorder())
        self.log.write_text(line(action="run", status="ok", sha256=H))
        rec = Recorder()
        notify.check_log(self.log, state, rec)
        self.assertEqual(len(rec.sent), 1)

    def rotate(self):
        """What gate.rotate does: the same file gets an archive name, a new one starts."""
        arch = self.base / "runner-20261016T000000Z.log"
        os.link(self.log, arch)
        self.log.unlink()
        return arch

    def test_rotation_between_checks_loses_nothing(self):
        self.log.write_text("")
        state = {}
        notify.check_log(self.log, state, Recorder())
        with open(self.log, "a") as f:
            f.write(line(action="reject", status="ok", sha256=H))
        self.rotate()
        self.log.write_text(line(action="run", status="ok", sha256=H))
        rec = Recorder()
        notify.check_log(self.log, state, rec)
        self.assertEqual(len(rec.sent), 2)
        self.assertEqual(rec.sent[-1].title, f"Julz: run done {H[:8]}")
        self.assertEqual(state["log_offset"], self.log.stat().st_size)
        notify.check_log(self.log, state, rec)
        self.assertEqual(len(rec.sent), 2)

    def test_failed_send_inside_archive_resumes_there(self):
        self.log.write_text("")
        state = {}
        notify.check_log(self.log, state, Recorder())
        with open(self.log, "a") as f:
            f.write(line(action="reject", status="ok", sha256=H) * 2)
        self.rotate()
        self.log.write_text(line(action="run", status="ok", sha256=H))
        with self.assertRaises(OSError):
            notify.check_log(self.log, state, Recorder(fail_after=1))
        rec = Recorder()
        notify.check_log(self.log, state, rec)
        self.assertEqual(len(rec.sent), 2)
        self.assertEqual(rec.sent[-1].title, f"Julz: run done {H[:8]}")

    def test_big_archive_read_to_its_end_first(self):
        self.log.write_text("")
        state = {}
        notify.check_log(self.log, state, Recorder())
        reject = line(action="reject", status="ok", sha256=H)
        with open(self.log, "a") as f:
            f.write(reject * 3)
        self.rotate()
        self.log.write_text(line(action="run", status="ok", sha256=H))
        rec = Recorder()
        limit = notify.MAX_LOG_READ
        notify.MAX_LOG_READ = len(reject) + 5  # one line and a bit per read
        try:
            for _ in range(5):
                notify.check_log(self.log, state, rec)
        finally:
            notify.MAX_LOG_READ = limit
        self.assertEqual(len(rec.sent), 4)
        self.assertEqual(rec.sent[-1].title, f"Julz: run done {H[:8]}")

    def test_archive_gone_starts_the_new_file(self):
        self.log.write_text("")
        state = {}
        notify.check_log(self.log, state, Recorder())
        with open(self.log, "a") as f:
            f.write(line(action="reject", status="ok", sha256=H))
        self.rotate().unlink()
        self.log.write_text(line(action="run", status="ok", sha256=H))
        rec = Recorder()
        notify.check_log(self.log, state, rec)
        self.assertEqual([n.title for n in rec.sent], [f"Julz: run done {H[:8]}"])

    def test_garbage_lines_skipped(self):
        self.log.write_text("")
        state = {}
        notify.check_log(self.log, state, Recorder())
        with open(self.log, "a") as f:
            f.write("not json\n[1, 2]\n" + line(action="run", status="ok", sha256=H))
        rec = Recorder()
        notify.check_log(self.log, state, rec)
        self.assertEqual(len(rec.sent), 1)


class NewNotesTest(Base):
    """209, threat 142: a Feed card when a note lands in Inbox/ or daily/. Julz writes Inbox,
    so counts only, rate limited, and it reads the snapshot, never the vault."""
    SECRET_NAME = "secret-diagnosis"

    def write(self, *notes):
        folders = {}
        for n in notes:
            folders.setdefault(n.rsplit("/", 1)[0], []).append(
                {"name": Path(n).stem, "note": n, "size": 1, "modified": "2026-10-24", "text": SECRET})
        self.notes = self.base / "notes.json"
        self.notes.write_text(json.dumps(
            {"folders": [{"folder": f, "notes": ns} for f, ns in folders.items()]}))

    def check(self, state, now, rec):
        notify.check_notes(self.notes, state, now, rec)

    def test_first_run_only_records(self):
        self.write("Inbox/a.md", "daily/b.md")
        rec, state = Recorder(), {}
        self.check(state, 1000.0, rec)
        self.assertEqual(rec.sent, [])
        self.assertIn("notes_seen", state)

    def test_new_note_sends_counts_only(self):
        self.write("Inbox/a.md")
        rec, state = Recorder(), {}
        self.check(state, 1000.0, rec)
        self.write("Inbox/a.md", f"Inbox/{self.SECRET_NAME}.md", "daily/c.md")
        self.check(state, 2000.0, rec)
        self.assertEqual(rec.sent, [notify.notes_notice(2, 2)])
        self.assertEqual(rec.sent[0].kind, "inbox")
        text = self.all_text(rec.sent)
        self.assertNotIn(self.SECRET_NAME, text)
        self.assertNotIn(SECRET, text)
        (text + rec.sent[0].tags).encode("ascii")

    def test_done_and_other_folders_are_not_news(self):
        self.write("Inbox/a.md")
        rec, state = Recorder(), {}
        self.check(state, 1000.0, rec)
        self.write("Inbox/a.md", "daily/done/old.md", "study/x.md", "Claude/cpts/y.md")
        self.check(state, 2000.0, rec)
        self.assertEqual(rec.sent, [])

    def test_a_sorted_note_is_not_news(self):
        self.write("Inbox/a.md")
        rec, state = Recorder(), {}
        self.check(state, 1000.0, rec)
        self.write("daily/a.md")  # moved from Inbox to daily
        self.check(state, 2000.0, rec)
        self.assertEqual(rec.sent, [])

    def test_rate_limited_but_not_lost(self):
        self.write("Inbox/a.md")
        rec, state = Recorder(), {}
        self.check(state, 1000.0, rec)
        self.write("Inbox/a.md", "Inbox/b.md")
        self.check(state, 2000.0, rec)
        self.write("Inbox/a.md", "Inbox/b.md", "Inbox/c.md")
        self.check(state, 2000.0 + notify.NOTES_EVERY - 1, rec)
        self.assertEqual(len(rec.sent), 1)
        self.check(state, 2000.0 + notify.NOTES_EVERY + 1, rec)
        self.assertEqual(rec.sent[-1], notify.notes_notice(1, 3))

    def test_flood_is_one_card_a_window(self):
        rec, state = Recorder(), {}
        self.write("Inbox/a.md")
        self.check(state, 1000.0, rec)
        names = ["Inbox/a.md"]
        for i in range(50):
            names.append(f"Inbox/n{i}.md")
            self.write(*names)
            self.check(state, 1001.0 + i, rec)
        self.assertEqual(len(rec.sent), 1)

    def test_bad_snapshot_changes_nothing(self):
        self.notes = self.base / "notes.json"
        for raw in ("", "not json", "[]", '{"folders": 3}', '{"folders": [{"notes": 1}]}',
                    '{"folders": [{"notes": [{"note": 3}]}]}', '{"folders": [{"notes": ["Inbox/a.md"]}]}'):
            self.notes.write_text(raw)
            rec, state = Recorder(), {"notes_seen": ["x"]}
            self.check(state, 1000.0, rec)
            self.assertEqual((rec.sent, state), ([], {"notes_seen": ["x"]}), raw)

    def full_snapshot(self, last):
        """The vault's worst case (213): every note and tag at its cap in Cyrillic, which JSON
        escapes to 6 bytes a letter, so far past the old 2 MB cut."""
        vault = notify.vault
        tags = ["т" * vault.MAX_TAG_CHARS] * vault.MAX_NOTE_TAGS
        notes = [{"name": f"n{i}", "note": f"Inbox/n{i}.md", "size": 1, "modified": "2026-10-25",
                  "text": "я" * vault.MAX_NOTE_TEXT, "tags": tags}
                 for i in range(vault.MAX_NOTES_SHOWN - 1)]
        notes.append({"name": last, "note": f"Inbox/{last}.md", "size": 1,
                      "modified": "2026-10-25", "text": "я" * vault.MAX_NOTE_TEXT, "tags": tags})
        self.notes = self.base / "notes.json"
        self.notes.write_text(json.dumps({"folders": [{"folder": "Inbox", "notes": notes}]}))

    def test_full_size_snapshot_still_counts(self):
        self.full_snapshot("first")
        rec, state = Recorder(), {}
        self.check(state, 1000.0, rec)
        self.full_snapshot("second")
        self.assertGreater(self.notes.stat().st_size, 2_000_000)
        self.assertLessEqual(self.notes.stat().st_size, notify.vault.MAX_NOTES_JSON)
        self.check(state, 2000.0, rec)
        self.assertEqual(rec.sent, [notify.notes_notice(1, notify.vault.MAX_NOTES_SHOWN)])

    def test_same_cap_as_the_approver(self):
        approver = load("julz_approve_web_213", "julz-approve-web.py")
        self.assertEqual(approver.MAX_NOTES_BYTES, notify.vault.MAX_NOTES_JSON)

    def test_over_cap_snapshot_changes_nothing(self):
        self.write("Inbox/a.md", "Inbox/b.md")
        raw = self.notes.read_text()
        self.notes.write_text(raw + " " * (notify.vault.MAX_NOTES_JSON + 1 - len(raw)))
        rec, state = Recorder(), {"notes_seen": ["x"]}
        self.check(state, 1000.0, rec)
        self.assertEqual((rec.sent, state), ([], {"notes_seen": ["x"]}))

    def test_symlink_is_not_followed(self):
        self.write("Inbox/a.md", "Inbox/b.md")
        real = self.base / "real.json"
        self.notes.rename(real)
        self.notes.symlink_to(real)
        rec, state = Recorder(), {"notes_seen": ["x"]}
        self.check(state, 1000.0, rec)
        self.assertEqual((rec.sent, state), ([], {"notes_seen": ["x"]}))

    def test_state_keeps_no_names(self):
        self.write(f"Inbox/{self.SECRET_NAME}.md")
        state = {}
        self.check(state, 1000.0, Recorder())
        self.assertNotIn(self.SECRET_NAME, json.dumps(state))

    def test_failed_send_is_tried_again(self):
        self.write("Inbox/a.md")
        state = {}
        self.check(state, 1000.0, Recorder())
        self.write("Inbox/a.md", "Inbox/b.md")
        with self.assertRaises(OSError):
            self.check(state, 2000.0, Recorder(fail_after=0))
        rec = Recorder()
        self.check(state, 2001.0, rec)
        self.assertEqual(rec.sent, [notify.notes_notice(1, 2)])

    def test_template_ascii_and_plural(self):
        self.assertEqual(notify.notes_notice(1, 1).title, "Julz: 1 new note")
        self.assertEqual(notify.notes_notice(2, 5).title, "Julz: 2 new notes")
        for n in (notify.notes_notice(1, 1), notify.notes_notice(9, 0)):
            (n.title + n.body + n.tags + n.priority).encode("ascii")


class NotesUnitFileTest(unittest.TestCase):
    """142: the card's units watch the snapshot and never see the vault."""

    def lines(self, unit):
        return [l for l in (ROOT / "systemd" / unit).read_text().splitlines() if not l.startswith("#")]

    def test_path_watches_the_snapshot(self):
        lines = self.lines("julz-notify-notes.path")
        self.assertIn("PathChanged=%h/.local/share/julz/vault/notes.json", lines)
        self.assertIn("Unit=julz-notify-notes.service", lines)

    def test_service_sees_no_note(self):
        lines = self.lines("julz-notify-notes.service")
        self.assertIn("ExecStart=/usr/bin/python3 -I %h/.local/lib/julz/current/julz-notify.py --notes", lines)
        self.assertIn("TemporaryFileSystem=%h:ro", lines)
        binds = [l for l in lines if l.startswith(("BindPaths=", "BindReadOnlyPaths="))]
        self.assertEqual(sorted(binds), sorted([
            "BindReadOnlyPaths=%h/.local/lib/julz", "BindReadOnlyPaths=%h/.config/julz/notify",
            "BindReadOnlyPaths=%h/.local/share/julz/vault", "BindPaths=%h/.local/share/julz/notify"]))


class InboxTest(Base):
    """Julz writes the inbox, so it can trigger this: rate limited, names only."""

    def spec(self, name, text=SECRET):
        (self.inbox / name).write_text(text)

    def test_rings_with_count(self):
        self.spec("a.md")
        self.spec("b.md")
        rec, state = Recorder(), {}
        notify.check_inbox(self.inbox, state, 1000.0, rec)
        self.assertEqual(rec.sent, [notify.inbox_notice(2)])
        self.assertNotIn(SECRET, self.all_text(rec.sent))

    def test_rate_limited(self):
        rec, state = Recorder(), {}
        for i in range(20):
            self.spec(f"s{i}.md")
            notify.check_inbox(self.inbox, state, 1000.0 + i * 10, rec)
        self.assertEqual(len(rec.sent), 1)
        self.spec("late.md")
        notify.check_inbox(self.inbox, state, 1000.0 + notify.INBOX_EVERY + 1, rec)
        self.assertEqual(len(rec.sent), 2)

    def test_same_count_quiet(self):
        self.spec("a.md")
        rec, state = Recorder(), {}
        notify.check_inbox(self.inbox, state, 1000.0, rec)
        notify.check_inbox(self.inbox, state, 99999.0, rec)
        self.assertEqual(len(rec.sent), 1)

    def test_empty_and_odd_names_quiet(self):
        self.spec("Bad Name.md")
        self.spec("notes.txt")
        rec, state = Recorder(), {}
        notify.check_inbox(self.inbox, state, 1000.0, rec)
        self.assertEqual(rec.sent, [])


class CardsTest(Base):
    """160: Julz writes Inbox/.proposals, so it can trigger this: counts the names Approve can
    show, never opens a file, rings only when the count rises."""
    NOW = 1_800_000_000

    def setUp(self):
        super().setUp()
        self.cards = self.base / "Inbox" / ".proposals"
        self.cards.mkdir()

    def card(self, age=0, tail="0123abcd", text=SECRET):
        name = f"{self.NOW - age}-{tail}.json"
        (self.cards / name).write_text(text)
        return name

    def test_counts_names_approve_shows(self):
        self.card(age=10)
        self.card(age=notify.PROPOSAL_TTL, tail="0123abce")
        self.card(age=-notify.PROPOSAL_SKEW, tail="0123abcf")
        self.assertEqual(notify.count_cards(self.cards, self.NOW), 3)

    def test_odd_names_old_and_future_not_counted(self):
        self.card(age=notify.PROPOSAL_TTL + 1)
        self.card(age=-notify.PROPOSAL_SKEW - 1, tail="0123abce")
        for name in ("Bad Name.json", f"{self.NOW}-0123ABCD.json", f"{self.NOW}-0123abcd.md",
                     f"{self.NOW}-0123abcd.json.tmp", f"{self.NOW}-0123abcd.json\n"):
            (self.cards / name).write_text(SECRET)
        (self.cards / f"{self.NOW}-0123abc0.json").mkdir()
        (self.cards / f"{self.NOW}-0123abc1.json").symlink_to(self.cards / f"{self.NOW}-0123ABCD.json")
        self.assertEqual(notify.count_cards(self.cards, self.NOW), 0)

    def test_count_capped(self):
        for i in range(notify.MAX_PROPOSALS + 5):
            self.card(tail=f"{i:08x}")
        self.assertEqual(notify.count_cards(self.cards, self.NOW), notify.MAX_PROPOSALS)

    def test_scan_capped(self):
        # Names that sort first and do not count must not hide the ones after them
        for i in range(notify.MAX_PROPOSAL_SCAN):
            (self.cards / f"0{i:09d}-0123abcd.json").write_text("")
        self.card()
        self.assertEqual(notify.count_cards(self.cards, self.NOW), 0)

    def test_no_folder_is_none(self):
        self.cards.rmdir()
        self.assertEqual(notify.count_cards(self.cards, self.NOW), 0)

    def test_rings_with_count_only(self):
        self.card()
        self.card(tail="0123abce")
        rec, state = Recorder(), {}
        notify.check_cards(self.cards, state, self.NOW, rec)
        self.assertEqual(rec.sent, [notify.cards_notice(2)])
        self.assertNotIn(SECRET, self.all_text(rec.sent))
        self.assertNotIn("0123abc", self.all_text(rec.sent) + json.dumps(state))

    def test_fall_is_quiet_rise_rings(self):
        a = self.card()
        self.card(tail="0123abce")
        rec, state = Recorder(), {}
        notify.check_cards(self.cards, state, self.NOW, rec)
        (self.cards / a).unlink()  # I signed one
        notify.check_cards(self.cards, state, self.NOW + notify.INBOX_EVERY + 1, rec)
        self.assertEqual(len(rec.sent), 1)
        self.card(tail="0123abcf")  # 1 to 2 is a new card, though 2 was seen before
        notify.check_cards(self.cards, state, self.NOW + 2 * notify.INBOX_EVERY + 2, rec)
        self.assertEqual(rec.sent[-1], notify.cards_notice(2))
        self.assertEqual(len(rec.sent), 2)

    def test_rate_limited(self):
        rec, state = Recorder(), {}
        for i in range(8):
            self.card(tail=f"{i:08x}")
            notify.check_cards(self.cards, state, self.NOW + i * 10, rec)
        self.assertEqual(len(rec.sent), 1)
        self.card(tail="0000ffff")
        notify.check_cards(self.cards, state, self.NOW + notify.INBOX_EVERY + 1, rec)
        self.assertEqual(len(rec.sent), 2)

    def test_none_quiet(self):
        rec, state = Recorder(), {}
        notify.check_cards(self.cards, state, self.NOW, rec)
        self.assertEqual(rec.sent, [])

    def test_failed_send_is_tried_again(self):
        self.card()
        state = {}
        with self.assertRaises(OSError):
            notify.check_cards(self.cards, state, self.NOW, Recorder(fail_after=0))
        rec = Recorder()
        notify.check_cards(self.cards, state, self.NOW + 1, rec)
        self.assertEqual(rec.sent, [notify.cards_notice(1)])

    def test_same_limits_as_approve(self):
        web = load("julz_approve_web_for_notify", "julz-approve-web.py")
        for name in ("MAX_PROPOSALS", "MAX_PROPOSAL_SCAN", "PROPOSAL_TTL", "PROPOSAL_SKEW"):
            self.assertEqual(getattr(notify, name), getattr(web, name), name)
        self.assertEqual(notify.CARDS, web.PROPOSALS)

    def test_template_ascii_and_plural(self):
        self.assertEqual(notify.cards_notice(1).title, "Julz: 1 card waiting")
        self.assertEqual(notify.cards_notice(3).title, "Julz: 3 cards waiting")
        n = notify.cards_notice(2)
        self.assertEqual(n.kind, "approval")
        (n.title + n.body + n.tags + n.priority).encode("ascii")


class CardsUnitFileTest(unittest.TestCase):
    """160: its own unit pair, the cards folder read only and nothing else of the vault."""

    def lines(self, unit):
        return [l for l in (ROOT / "systemd" / unit).read_text().splitlines() if not l.startswith("#")]

    def test_path_watches_the_cards(self):
        lines = self.lines("julz-notify-cards.path")
        self.assertIn("PathChanged=%h/Documents/julz-mem/Inbox/.proposals", lines)
        self.assertIn("Unit=julz-notify-cards.service", lines)

    def test_service_binds(self):
        lines = self.lines("julz-notify-cards.service")
        self.assertIn("ExecStart=/usr/bin/python3 -I %h/.local/lib/julz/current/julz-notify.py --cards", lines)
        self.assertIn("TemporaryFileSystem=%h:ro", lines)
        self.assertIn("RestrictAddressFamilies=AF_UNIX", lines)
        binds = [l for l in lines if l.startswith(("BindPaths=", "BindReadOnlyPaths="))]
        self.assertEqual(sorted(binds), sorted([
            "BindReadOnlyPaths=%h/.local/lib/julz", "BindReadOnlyPaths=%h/.config/julz/notify",
            "BindReadOnlyPaths=%h/Documents/julz-mem/Inbox/.proposals",
            "BindPaths=%h/.local/share/julz/notify"]))


class TopicTest(Base):
    def test_new_topic_is_random_and_private(self):
        path = self.base / "notify" / "ntfy.env"
        topic = notify.new_topic(path)
        self.assertRegex(topic, r"^julz-[0-9a-f]{32}$")
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(notify.load_topic(path), topic)
        with self.assertRaises(gate.GateError):
            notify.new_topic(path)  # never silently replaced

    def test_bad_topics_refused(self):
        path = self.base / "ntfy.env"
        for bad in ("NTFY_TOPIC=julz", "NTFY_TOPIC=mytopic", "NTFY_TOPIC=julz-abc/../x",
                    "NTFY_TOPIC=julz-" + "0" * 31):
            with self.subTest(bad=bad):
                path.write_text(bad)
                path.chmod(0o600)
                with self.assertRaises(gate.GateError):
                    notify.load_topic(path)

    def test_topic_file_open_to_others_refused(self):
        path = self.base / "notify" / "ntfy.env"
        notify.new_topic(path)
        path.chmod(0o644)
        with self.assertRaises(gate.GateError):
            notify.load_topic(path)

    def test_state_round_trip_private(self):
        path = self.base / "state" / "state.json"
        notify.save_state(path, {"log_offset": 5})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(notify.load_state(path), {"log_offset": 5})
        self.assertEqual(notify.load_state(self.base / "missing.json"), {})

    def test_two_notifiers_lose_no_update(self):
        # 209: one refresh starts --todos and --notes together; both rewrite the same state
        import threading
        import time
        path = self.base / "state" / "state.json"
        notify.save_state(path, {})

        def writer(key):
            with notify.state_lock(path):
                state = notify.load_state(path)
                time.sleep(0.2)
                state[key] = 1
                notify.save_state(path, state)

        threads = [threading.Thread(target=writer, args=(k,)) for k in ("todos", "notes_seen")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(notify.load_state(path), {"todos": 1, "notes_seen": 1})

    def test_main_loads_and_saves_only_under_the_lock(self):
        from contextlib import contextmanager
        from unittest import mock
        held, seen = [], []

        @contextmanager
        def fake_lock(path):
            held.append(path)
            yield
            held.pop()

        real_load, real_save = notify.load_state, notify.save_state

        def load(path):
            seen.append(("load", bool(held)))
            return real_load(path)

        def save(path, state):
            seen.append(("save", bool(held)))
            real_save(path, state)

        for mode in ("--todos", "--notes", "--inbox"):
            with mock.patch.multiple(notify, state_lock=fake_lock, load_state=load, save_state=save,
                                     STATE_FILE=self.base / "st" / "state.json",
                                     NOTES_FILE=self.base / "none.json", INBOX=self.inbox,
                                     make_sender=lambda *a: Recorder(),
                                     load_topic=lambda p: "julz-" + "0" * 32,
                                     load_local=lambda p: None), \
                    mock.patch.object(sys, "argv", ["julz-notify.py", mode]):
                notify.main()
        self.assertEqual(seen, [("load", True), ("save", True)] * 3)

    def test_state_lock_private_and_no_link(self):
        path = self.base / "state" / "state.json"
        with notify.state_lock(path):
            pass
        lock = path.with_name("state.lock")
        self.assertEqual(lock.stat().st_mode & 0o777, 0o600)
        lock.unlink()
        lock.symlink_to(self.base / "elsewhere")
        with self.assertRaises(OSError):
            with notify.state_lock(path):
                pass
        self.assertFalse((self.base / "elsewhere").exists())


class LocalServerTest(Base):
    """The self hosted server for the phone app (SECURITY.md 86): loopback only, notify token."""
    TOKEN = "tk_" + "n" * 29

    def setUp(self):
        super().setUp()
        self.local = self.base / "notify" / "local.env"
        self.local.parent.mkdir(parents=True)
        self.local.write_text(f"NTFY_URL=http://127.0.0.1:8090\nNTFY_TOKEN={self.TOKEN}\n")
        self.local.chmod(0o600)
        self.requests = []
        self.down = set()
        self.old = notify._send

        def fake(req, timeout=None):
            self.requests.append(req)
            if any(req.full_url.startswith(d) for d in self.down):
                raise OSError("down")

            class R:
                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False

                def read(self):
                    return b""
            return R()
        notify._send = fake

    def tearDown(self):
        notify._send = self.old
        super().tearDown()

    def send(self, notice, local=True):
        cfg = notify.load_local(self.local) if local else None
        notify.make_sender("julz-" + "a" * 32, cfg)(notice)

    def by_host(self, host):
        return [r for r in self.requests if r.full_url.startswith(host)]

    def test_sends_only_to_my_server_with_the_token(self):
        # ntfy.sh retired 18 Oct: the app gets every notice, the old copies only led to the page
        self.send(notify.inbox_notice(2))
        local, = self.requests
        self.assertEqual(local.full_url, "http://127.0.0.1:8090/julz-" + "a" * 32)
        self.assertEqual(local.get_header("Authorization"), f"Bearer {self.TOKEN}")
        self.assertIsNone(local.get_header("Click"))  # a notice never carries a link (86)
        self.assertEqual(local.get_header("Tags"), "k_approval")
        self.assertEqual(self.by_host("https://ntfy.sh"), [])

    def test_without_local_config_nothing_is_sent_and_it_fails(self):
        # Never a quiet fallback to a public server: the caller keeps its progress and retries
        self.local.unlink()
        self.assertIsNone(notify.load_local(self.local))
        with self.assertRaises(gate.GateError):
            self.send(notify.inbox_notice(1))
        self.assertEqual(self.requests, [])

    def test_local_config_refusals(self):
        cases = {
            "remote host": f"NTFY_URL=http://example.com:8090\nNTFY_TOKEN={self.TOKEN}\n",
            "other loopback port": f"NTFY_URL=http://127.0.0.1:80\nNTFY_TOKEN={self.TOKEN}\n",
            "https elsewhere": f"NTFY_URL=https://127.0.0.1.example:8090\nNTFY_TOKEN={self.TOKEN}\n",
            "bad token": "NTFY_URL=http://127.0.0.1:8090\nNTFY_TOKEN=tk_short\n",
            "missing token": "NTFY_URL=http://127.0.0.1:8090\n",
            "extra line": f"NTFY_URL=http://127.0.0.1:8090\nNTFY_TOKEN={self.TOKEN}\nX=1\n",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                self.local.write_text(text)
                with self.assertRaises(gate.GateError):
                    notify.load_local(self.local)
        self.local.write_text(f"NTFY_URL=http://127.0.0.1:8090\nNTFY_TOKEN={self.TOKEN}\n")
        self.local.chmod(0o644)
        with self.assertRaises(gate.GateError):
            notify.load_local(self.local)

    def test_server_down_fails(self):
        self.down = {"http://127.0.0.1:8090/"}
        with self.assertRaises(OSError):
            self.send(notify.inbox_notice(1))

    def test_unknown_kind_never_reaches_the_app(self):
        with self.assertRaises(gate.GateError):
            self.send(notify.Notice("Julz: x", "y", kind="evil"))
        self.assertEqual(self.by_host("http://127.0.0.1:8090/"), [])

    def test_kinds_for_the_app(self):
        line = lambda action, status="ok": notify.log_notice({"action": action, "status": status, "sha256": H})
        self.assertEqual(notify.inbox_notice(1).kind, "approval")
        self.assertEqual(line("need").kind, "approval")
        self.assertEqual(line("run").kind, "run")
        self.assertEqual(line("run", "quarantined").kind, "warning")
        self.assertEqual(line("run", "failed").kind, "warning")
        self.assertEqual(line("note-move").kind, "change")
        self.assertEqual(line("note-delete").kind, "warning")  # high priority
        for n in (notify.inbox_notice(3), line("reject"), line("feedback-solved")):
            self.assertIn(n.kind, notify.KINDS)


class TodoSnapshotTest(LocalServerTest):
    """Threat 100: open tasks go to my own server only, checked again, only when they changed."""

    def write(self, data):
        p = self.base / "todos.json"
        p.write_text(json.dumps(data) if not isinstance(data, str) else data)
        return p

    ID = "c" * 64

    def snap(self, lists):
        return {"date": "2026-10-17", "id": self.ID, "lists": lists}

    @staticmethod
    def lst(name, done, total, open_, done_items=(), note=None, doing=()):
        return {"name": name, "note": note or f"daily/{name}.md", "done": done, "total": total,
                "open": list(open_), "doing": list(doing), "done_items": list(done_items)}

    def run_todos(self, path, local=True):
        cfg = notify.load_local(self.local) if local else None
        notify.check_todos(path, self.state, cfg, "julz-" + "a" * 32)

    def setUp(self):
        super().setUp()
        self.state = {}
        self.good = self.snap([self.lst("physio", 2, 3, ["Review session notes"], ["Call the clinic"]),
                               self.lst("week", 3, 5, ["Walk 10k", "Book the exam"])])

    def test_posts_to_my_server_only_in_the_message_format(self):
        self.run_todos(self.write(self.good))
        self.assertEqual(self.by_host("https://ntfy.sh"), [])  # never ntfy.sh
        req, = self.by_host("http://127.0.0.1:8090/")
        self.assertEqual(req.get_header("Tags"), "k_todo")
        self.assertEqual(req.get_header("Title"), "Julz: 3 open todos")
        # v3: a head record with the snapshot id the phone signs against (113), then per list
        # name, done, total, how many open, how many in progress (127), the open tasks, those in
        # progress, the done ones. Never the note path
        self.assertEqual(req.data.decode(), f"v3\u241f{self.ID}"
                         "\u241ephysio\u241f2\u241f3\u241f1\u241f0\u241fReview session notes\u241fCall the clinic"
                         "\u241eweek\u241f3\u241f5\u241f2\u241f0\u241fWalk 10k\u241fBook the exam")
        self.assertNotIn("daily/", req.data.decode())

    def test_tasks_in_progress_travel_after_the_open_ones(self):
        self.run_todos(self.write(self.snap([self.lst("physio", 1, 3, ["Book physio"], ["Call"], doing=["Stretch daily"]),
                                             self.lst("rehab", 0, 1, [], doing=["Walk"])])))
        req, = self.requests
        self.assertEqual(req.get_header("Title"), "Julz: 3 open todos")  # in progress is still open
        self.assertEqual(req.data.decode(), f"v3\u241f{self.ID}"
                         "\u241ephysio\u241f1\u241f3\u241f1\u241f1\u241fBook physio\u241fStretch daily\u241fCall"
                         "\u241erehab\u241f0\u241f1\u241f0\u241f1\u241fWalk")

    def test_done_tasks_go_first_when_the_message_is_too_big(self):
        long = "\u0436" * 80  # Cyrillic: two bytes a character
        lists = [self.lst(f"l{i}", 5, 9, [long] * 4, [long] * 2) for i in range(5)]
        self.run_todos(self.write(self.snap(lists)))
        req, = self.requests
        body = req.data
        self.assertLessEqual(len(body), notify.MAX_TODO_BYTES)
        records = body.decode().split("\u241e")[1:]
        self.assertEqual(sum(int(r.split("\u241f")[3]) for r in records), 20)  # every open task stays
        self.assertLess(sum(len(r.split("\u241f")) - 5 for r in records), 30)  # some done ones went

    def test_only_when_it_changed(self):
        p = self.write(self.good)
        self.run_todos(p)
        self.run_todos(p)
        self.assertEqual(len(self.requests), 1)
        self.good["lists"][0]["open"] = ["Something new"]
        self.run_todos(self.write(self.good))
        self.assertEqual(len(self.requests), 2)

    def test_nothing_without_my_server(self):
        self.run_todos(self.write(self.good), local=False)
        self.assertEqual(self.requests, [])

    def test_no_open_tasks_says_so(self):
        self.run_todos(self.write(self.snap([])))
        req, = self.requests
        self.assertEqual(req.get_header("Title"), "Julz: no open todos")

    def test_a_bad_file_posts_nothing(self):
        ok = self.lst("x", 0, 1, ["fine"])
        for name, data in {
            "not json": "{",
            "extra key": {**self.good, "x": 1},
            "link in a task": self.snap([{**ok, "open": ["see https://evil.example"]}]),
            "separator in a task": self.snap([{**ok, "open": ["a \u241e b"]}]),
            "hidden character": self.snap([{**ok, "open": ["a\u202eb"]}]),
            "too long": self.snap([{**ok, "open": ["y" * 81]}]),
            "too many lists": self.snap([ok] * 9),
            "too many tasks": self.snap([{**ok, "total": 21, "open": ["t"] * 21}]),
            "too many with those in progress": self.snap([{**ok, "total": 21, "open": ["t"] * 10, "doing": ["u"] * 11}]),
            "link in a task in progress": self.snap([{**ok, "total": 2, "doing": ["see https://evil.example"]}]),
            "in progress not a list": self.snap([{**ok, "doing": "x"}]),
            "no in progress key": self.snap([{k: v for k, v in ok.items() if k != "doing"}]),
            "nothing open at all": self.snap([{**ok, "open": [], "doing": []}]),
            "done over total": self.snap([{**ok, "done": 5, "total": 1}]),
            "bad name": self.snap([{**ok, "name": "../x"}]),
            "number as task": self.snap([{**ok, "open": [5]}]),
            "bad id": {**self.snap([ok]), "id": "short"},
            "bad note path": self.snap([{**ok, "note": "../secret.md"}]),
            "no id": {"date": "2026-10-17", "lists": [ok]},
            "link in a done task": self.snap([{**ok, "done": 1, "total": 2,
                                               "done_items": ["see https://evil.example"]}]),
            "too many done": self.snap([{**ok, "done": 11, "total": 12, "done_items": ["d"] * 11}]),
        }.items():
            with self.subTest(name=name):
                self.state = {}
                self.run_todos(self.write(data))
                self.assertEqual(self.requests, [], name)


class WeeklyInboxTest(unittest.TestCase):
    """Sunday nudge to empty the Inbox. Count only: note names come from julz and ntfy.sh
    sees every push (B11, threat 39)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.inbox = Path(self.tmp.name) / "Inbox"
        (self.inbox / "claude").mkdir(parents=True)
        (self.inbox / ".requests").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_only_my_inbox_notes(self):
        (self.inbox / "physio.md").write_text(SECRET)
        (self.inbox / "daily.md").write_text("x")
        (self.inbox / "claude" / "spec.md").write_text("spec")  # specs have their own push
        (self.inbox / ".requests" / "r.md").write_text("x")
        (self.inbox / ".hidden.md").write_text("x")
        (self.inbox / "notes.txt").write_text("x")
        (self.inbox / "link.md").symlink_to(self.inbox / "daily.md")
        self.assertEqual(notify.inbox_notes(self.inbox), 2)

    def test_push_has_count_and_no_names(self):
        (self.inbox / f"{SECRET}.md").write_text(SECRET)
        rec = Recorder()
        notify.check_weekly(self.inbox, rec)
        self.assertEqual(len(rec.sent), 1)
        self.assertEqual(rec.sent[0].title, "Julz: 1 note in Inbox")
        self.assertIn("Sort them in Inbox in Julz", rec.sent[0].body)
        self.assertNotIn(SECRET, rec.sent[0].title + rec.sent[0].body)
        (self.inbox / "b.md").write_text("x")
        notify.check_weekly(self.inbox, rec)
        self.assertEqual(rec.sent[1].title, "Julz: 2 notes in Inbox")

    def test_empty_inbox_stays_quiet(self):
        rec = Recorder()
        notify.check_weekly(self.inbox, rec)
        notify.check_weekly(self.inbox / "missing", rec)
        self.assertEqual(rec.sent, [])

    def test_units(self):
        service = (ROOT / "systemd" / "julz-notify-weekly.service").read_text().splitlines()
        timer = (ROOT / "systemd" / "julz-notify-weekly.timer").read_text().splitlines()
        self.assertIn("ExecStart=/usr/bin/python3 -I %h/.local/lib/julz/current/julz-notify.py "
                      "--weekly", service)
        self.assertIn("BindReadOnlyPaths=%h/Documents/julz-mem/Inbox", service)
        self.assertFalse([l for l in service if l.startswith("BindPaths=")
                          and "julz-mem" in l])  # never writes the vault
        self.assertIn("TemporaryFileSystem=%h:ro", service)
        self.assertIn("OnCalendar=Sun *-*-* 18:00:00", timer)
        self.assertIn("Persistent=true", timer)  # laptop off on Sunday: it comes at boot


class DuePushTest(unittest.TestCase):
    """A push when 3 or more notes are due. It reads the count julz-vault wrote, never a note."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.file = Path(self.tmp.name) / "due.json"

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        self.file.write_text(data if isinstance(data, str) else json.dumps(data))

    def test_pushes_at_three_or_more(self):
        rec = Recorder()
        for n in (0, 2):
            self.write({"date": "2026-10-16", "due": n})
            notify.check_due(self.file, "2026-10-16", rec)
        self.assertEqual(rec.sent, [])
        self.write({"date": "2026-10-16", "due": 3})
        notify.check_due(self.file, "2026-10-16", rec)
        self.assertEqual(rec.sent[0].title, "Julz: 3 notes due for review")
        self.assertIn("quiz me", rec.sent[0].body)

    def test_stale_odd_or_missing_count_stays_quiet(self):
        rec = Recorder()
        for data in ({"date": "2026-10-15", "due": 9}, {"date": "2026-10-16", "due": "9"},
                     {"date": "2026-10-16", "due": -4}, {"date": "2026-10-16", "due": 10**9},
                     {"date": "2026-10-16", "due": True}, "not json", "[]",
                     {"date": "2026-10-16", "due": 5, "note": SECRET}):
            self.write(data)
            notify.check_due(self.file, "2026-10-16", rec)
        notify.check_due(self.file.with_name("missing.json"), "2026-10-16", rec)
        self.assertEqual(rec.sent, [])

    def test_units(self):
        service = (ROOT / "systemd" / "julz-notify-due.service").read_text().splitlines()
        timer = (ROOT / "systemd" / "julz-notify-due.timer").read_text().splitlines()
        self.assertIn("ExecStart=/usr/bin/python3 -I %h/.local/lib/julz/current/julz-notify.py "
                      "--due", service)
        binds = [l for l in service if l.startswith(("BindPaths=", "BindReadOnlyPaths="))]
        self.assertFalse([l for l in binds if "julz-mem" in l])  # never sees a note
        self.assertIn("BindReadOnlyPaths=%h/.local/share/julz/vault", service)
        self.assertIn("OnCalendar=*-*-* 19:00:00", timer)
        self.assertIn("Persistent=true", timer)


if __name__ == "__main__":
    unittest.main()


class UnixSocketTest(unittest.TestCase):
    """132: the sender talks HTTP over the private socket, never an internet socket."""

    def serve(self, status):
        import http.server, socketserver, threading
        seen = []

        class H(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append((self.path, dict(self.headers), self.rfile.read(int(self.headers["Content-Length"]))))
                self.send_response(status); self.send_header("Content-Length", "0"); self.end_headers()

            def log_message(self, *a):
                pass

        class S(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
            daemon_threads = True

            def get_request(self):
                conn, _ = self.socket.accept()
                return conn, ("local", 0)  # BaseHTTPRequestHandler wants a host and port

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "ntfy.sock"
        server = S(str(path), H)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return path, seen

    def test_posts_over_the_socket(self):
        path, seen = self.serve(200)
        req = notify.urllib.request.Request("http://127.0.0.1:8090/julz-" + "a" * 32, data=b"body",
                                            headers={"Title": "Julz: x", "Authorization": "Bearer tk"},
                                            method="POST")
        notify._send(req, timeout=5, sock=path)
        (url_path, headers, body), = seen
        self.assertEqual((url_path, body), ("/julz-" + "a" * 32, b"body"))
        self.assertEqual((headers["Title"], headers["Authorization"]), ("Julz: x", "Bearer tk"))

    def test_an_error_answer_raises(self):
        path, _ = self.serve(403)
        req = notify.urllib.request.Request("http://127.0.0.1:8090/t", data=b"x", method="POST")
        with self.assertRaises(OSError):
            notify._send(req, timeout=5, sock=path)

    def test_no_socket_raises(self):
        req = notify.urllib.request.Request("http://127.0.0.1:8090/t", data=b"x", method="POST")
        with self.assertRaises(OSError):
            notify._send(req, timeout=1, sock=Path(tempfile.gettempdir()) / "julz-no-such.sock")

    def test_same_socket_as_the_server(self):
        ntfy = load("julz_ntfy", "julz-ntfy.py")
        self.assertEqual(str(notify.PUSH_SOCKET), ntfy.PUSH_SOCKET)


NOTIFY_UNITS = [f"julz-notify-{u}.service" for u in ("log", "inbox", "weekly", "due", "todos", "notes")]


class NotifyUnitNetworkTest(unittest.TestCase):
    """132: no internet sockets in any notify unit, and no rule that only looks like one."""

    def lines(self, unit):
        return [l for l in (ROOT / "systemd" / unit).read_text().splitlines() if not l.startswith("#")]

    def test_unix_sockets_only(self):
        for unit in NOTIFY_UNITS:
            with self.subTest(unit=unit):
                lines = self.lines(unit)
                self.assertIn("RestrictAddressFamilies=AF_UNIX", lines)
                self.assertEqual([l for l in lines if l.startswith("RestrictAddressFamilies")],
                                 ["RestrictAddressFamilies=AF_UNIX"])
                self.assertFalse([l for l in lines if l.startswith("IPAddress")])  # ignored here
                self.assertFalse([l for l in lines if "approver.json" in l])
                self.assertIn("NoNewPrivileges=yes", lines)  # seccomp needs it unprivileged

    def test_server_makes_the_socket_folder(self):
        lines = self.lines("julz-ntfy.service")
        self.assertIn("RuntimeDirectory=julz-push", lines)
        self.assertIn("RuntimeDirectoryMode=0700", lines)


@unittest.skipUnless(__import__("shutil").which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"),
                     "needs a user systemd session")
class NotifyRealSandboxTest(unittest.TestCase):
    """A probe under the network lines of the real julz-notify-log.service."""

    def test_no_internet_socket_but_the_unix_socket_works(self):
        import socket, subprocess
        argv = ["systemd-run", "--user", "--wait", "--pipe", "--quiet"]
        for line in (ROOT / "systemd" / "julz-notify-log.service").read_text().splitlines():
            if line.split("=", 1)[0] in ("NoNewPrivileges", "ProtectSystem", "RestrictAddressFamilies",
                                         "SystemCallArchitectures", "LockPersonality"):
                argv += ["-p", line]
        probe = ("import socket, sys\n"
                 "for fam in (socket.AF_INET, socket.AF_INET6):\n"
                 "    try:\n"
                 "        socket.socket(fam); print('inet OPEN')\n"
                 "    except OSError: print('inet refused')\n"
                 "s = socket.socket(socket.AF_UNIX); s.connect(sys.argv[1]); print('unix ok')\n")
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "probe.sock")
            server = socket.socket(socket.AF_UNIX)
            server.bind(path)
            server.listen(1)
            try:
                r = subprocess.run(argv + [sys.executable, "-I", "-c", probe, path],
                                   capture_output=True, text=True, timeout=60)
            finally:
                server.close()
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        self.assertEqual(r.stdout.split(), ["inet", "refused", "inet", "refused", "unix", "ok"])
