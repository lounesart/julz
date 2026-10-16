"""Tests for julz-notify.py: pushes to the phone through ntfy, SECURITY.md threat 39.
A fake sender records messages, nothing reaches ntfy.sh.
Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
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
                               ("run", "stopped")):
            with self.subTest(action=action, status=status):
                n = notify.log_notice({"action": action, "status": status, "sha256": H,
                                       "reason": SECRET})
                self.assertIsNotNone(n)
                self.assertNotIn(SECRET, n.title + n.body)

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
                         [f"julz: approved {H[:8]}", f"julz: run done {H[:8]}"])

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
        self.assertEqual([n.title for n in rec2.sent], [f"julz: run done {H[:8]}"])

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

    def test_garbage_lines_skipped(self):
        self.log.write_text("")
        state = {}
        notify.check_log(self.log, state, Recorder())
        with open(self.log, "a") as f:
            f.write("not json\n[1, 2]\n" + line(action="run", status="ok", sha256=H))
        rec = Recorder()
        notify.check_log(self.log, state, rec)
        self.assertEqual(len(rec.sent), 1)


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


if __name__ == "__main__":
    unittest.main()
