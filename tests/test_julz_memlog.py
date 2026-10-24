"""Tests for julz-memlog.py: the memory log, SECURITY.md threat 112.
A fake /proc in a temp folder, so nothing depends on what runs on this laptop.
Run: python3 -m unittest discover -s tests -v"""
import csv
import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


memlog = load("julz_memlog", "julz-memlog.py")

HOUR = 3600
NOW = 2_000_000_000
SECRET = "tk_S3cr3tT0ken"
MEMINFO = ("MemTotal:       16000000 kB\nMemFree:          600000 kB\n"
           "MemAvailable:    7000000 kB\nShmem:           1000000 kB\n"
           "SwapTotal:       8000000 kB\nSwapFree:        5000000 kB\n")


def fake_proc(root: Path, procs):
    """procs: (pid, argv, rss_kb, state[, swap_kb]). rss None means no VmRSS line (kernel thread)."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "meminfo").write_text(MEMINFO)
    for pid, argv, rss, state, *swap in procs:
        d = root / str(pid)
        d.mkdir()
        (d / "cmdline").write_bytes(b"\0".join(a.encode() for a in argv) + (b"\0" if argv else b""))
        status = f"Name:\t{argv[0][:15] if argv else 'kthread'}\nState:\t{state} (x)\n"
        if rss is not None:
            status += f"VmRSS:\t{rss} kB\n"
        if swap:
            status += f"VmSwap:\t{swap[0]} kB\n"
        (d / "status").write_text(status)
    return root


class Classify(unittest.TestCase):
    def test_known_groups(self):
        cases = {
            ("/usr/local/bin/python3", "-m", "uvicorn", "open_webui.main:app"): "open-webui",
            ("/usr/bin/ollama", "serve"): "ollama",
            ("/usr/bin/ollama", "runner", "--model", "x"): "ollama",
            ("/usr/lib/ollama/llama-server", "--model", "x", "--cache-ram", "1024"): "ollama",
            ("/home/ubuntu/speaches/.venv/bin/python", "uvicorn", "speaches.main"): "speaches",
            ("searxng worker-1",): "searxng",
            ("/home/v/.local/lib/julz-ntfy/ntfy-2.29.0", "serve"): "ntfy",
            ("/usr/bin/python3", "-I", "/home/v/.local/lib/julz/current/julz-run.py"): "julz",
            ("claude",): "claude",
            ("/usr/lib/firefox/firefox",): "other",
        }
        for argv, label in cases.items():
            self.assertEqual(memlog.classify(list(argv)), label, argv)

    def test_llama_server_elsewhere_is_not_ollama(self):
        # only ollama's own runner path counts, threat 145
        self.assertEqual(memlog.classify(["/home/v/llama.cpp/build/bin/llama-server"]), "other")
        self.assertEqual(memlog.classify(["llama-server"]), "other")
        self.assertEqual(memlog.classify(["/usr/lib/ollamax/llama-server"]), "other")

    def test_julz_in_another_folder_is_not_julz(self):
        self.assertEqual(memlog.classify(["python3", "/tmp/julz/julz-run.py"]), "other")


class Sample(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.proc = fake_proc(self.tmp / "proc", [
            (10, ["/usr/bin/ollama", "serve"], 40000, "S"),
            (11, ["/usr/bin/ollama", "runner"], 60000, "S"),
            (16, ["/usr/lib/ollama/llama-server", "--port", "1"], 3000000, "S", 6000000),
            (12, ["/usr/lib/firefox/firefox"], 1000, "S"),
            (13, ["/home/v/.local/lib/julz-ntfy/ntfy", "--auth-file", SECRET], 500, "S"),
            (14, [], None, "S"),
            (15, ["claude"], None, "Z"),
        ])

    def test_sums_per_group_and_counts(self):
        s = memlog.sample(self.proc)
        self.assertEqual(s["ollama"], (9100000, 3))  # RSS plus swap, 24 Oct runner shape
        self.assertEqual(s["other"], (1000, 1))
        self.assertEqual(s["ntfy"], (500, 1))

    def test_totals_and_zombies(self):
        s = memlog.sample(self.proc)
        self.assertEqual(s["_used"], (9000000, 0))
        self.assertEqual(s["_shmem"], (1000000, 0))
        self.assertEqual(s["_zombie"], (0, 1))
        self.assertEqual(s["_swap"], (3000000, 0))

    def test_no_swap_lines_means_zero(self):
        root = self.tmp / "noswap"
        fake_proc(root, [(10, ["/usr/bin/ollama", "serve"], 40000, "S")])
        (root / "meminfo").write_text(MEMINFO.split("SwapTotal")[0])
        s = memlog.sample(root)
        self.assertEqual(s["ollama"], (40000, 1))
        self.assertEqual(s["_swap"], (0, 0))

    def test_swap_total_is_recorded(self):
        self.assertIn("_swap", memlog.LABELS)

    def test_a_process_gone_mid_read_is_skipped(self):
        (self.proc / "12" / "status").unlink()
        self.assertNotIn("other", memlog.sample(self.proc))


class Log(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.csv = self.tmp / "rss.csv"
        self.proc = fake_proc(self.tmp / "proc", [
            (13, ["/home/v/.local/lib/julz-ntfy/ntfy", "--auth-file", SECRET, "/x/path"], 500, "S"),
            (16, ["/usr/bin/python3", f"--token={SECRET}"], 700, "S"),
        ])

    def rows(self):
        with self.csv.open() as f:
            return list(csv.reader(f))

    def test_no_text_from_proc_reaches_the_log(self):
        memlog.record(self.csv, memlog.sample(self.proc), NOW)
        text = self.csv.read_text()
        self.assertNotIn(SECRET, text)
        self.assertNotIn("auth-file", text)
        self.assertNotIn("/x/path", text)
        labels = {r[1] for r in self.rows()[1:]}
        self.assertLessEqual(labels, set(memlog.LABELS))

    def test_an_unknown_label_is_dropped(self):
        memlog.record(self.csv, {f"--token={SECRET}": (1, 1), "julz": (2, 1)}, NOW)
        self.assertNotIn(SECRET, self.csv.read_text())

    def test_old_rows_go_new_rows_stay(self):
        memlog.record(self.csv, {"julz": (1, 1)}, NOW - 15 * 24 * HOUR)
        memlog.record(self.csv, {"julz": (2, 1)}, NOW - 13 * 24 * HOUR)
        memlog.record(self.csv, {"julz": (3, 1)}, NOW)
        self.assertEqual([r[2] for r in self.rows()[1:]], ["2", "3"])
        self.assertEqual(self.rows()[0], memlog.HEADER)

    def test_no_temp_file_left(self):
        memlog.record(self.csv, {"julz": (1, 1)}, NOW)
        self.assertEqual([p.name for p in self.tmp.iterdir() if p.is_file()], ["rss.csv"])


class Report(unittest.TestCase):
    def setUp(self):
        self.csv = Path(tempfile.mkdtemp()) / "rss.csv"

    def test_growth_per_hour(self):
        for h in range(7):
            memlog.record(self.csv, {"open-webui": (1000000 + h * 51200, 1),
                                     "ollama": (50000, 1)}, NOW + h * HOUR)
        out = memlog.report(self.csv, hours=48, now=NOW + 6 * HOUR)
        line = next(l for l in out.splitlines() if l.startswith("open-webui"))
        self.assertIn("+50.0", line)
        flat = next(l for l in out.splitlines() if l.startswith("ollama"))
        self.assertIn("+0.0", flat)

    def test_too_short_says_so(self):
        memlog.record(self.csv, {"julz": (1, 1)}, NOW)
        self.assertIn("not enough", memlog.report(self.csv, hours=48, now=NOW))

    def test_no_log_yet(self):
        self.assertIn("no log", memlog.report(self.csv, hours=48, now=NOW))


if __name__ == "__main__":
    unittest.main()
