"""Tests for julz_keep.py: which files a Keep may copy (SECURITY.md threats 54 to 57, 62).
Run: python3 -m unittest discover -s tests -v"""
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import julz_keep as keep  # noqa: E402

TASK = "a" * 64
# Built at runtime so no token shaped literal sits in the repo for scanners to flag
TOKEN = "sk-ant-oat01-" + "fake_token_for_tests_" * 4


class TopicTest(unittest.TestCase):
    def test_refused(self):
        for topic in ("../x", "a/b", "A", "-x", "a" * 41, "", "net plus", "x.y", None):
            with self.subTest(topic=topic):
                self.assertIsNotNone(keep.check_topic(topic))

    def test_accepted(self):
        for topic in ("network-plus", "a", "a" * 40, "ccna2"):
            with self.subTest(topic=topic):
                self.assertIsNone(keep.check_topic(topic))


class NameTest(unittest.TestCase):
    def test_refused(self):
        for name in ("../x.md", "/abs.md", ".hidden.md", "a/.b/c.md", "x.py", "x.md.sh",
                     "a b.md", "x.MD", "a/b/c/d/e.md", "a//b.md", "-x.md", "x\n.md", ""):
            with self.subTest(name=name):
                self.assertIsNotNone(keep.check_name(name))

    def test_accepted(self):
        for name in ("labs/01-osi-model.md", "README.md", "notes.txt", "a/b/c/d.md",
                     "v1.2_notes.md"):
            with self.subTest(name=name):
                self.assertIsNone(keep.check_name(name))


class UrlTest(unittest.TestCase):
    def test_refused(self):
        for url in ("HTTP://evil.net", "http://example.com.evil.net", "http://evil-example.com",
                    "http://example.com@evil.net", "http://user@example.com",
                    "http://xn--exmple-cua.com", "http://exаmple.com",
                    "http://100.64.1.1", "http://8.8.8.8", "http://172.32.0.1",
                    "ftp://example.com", "file:///etc/passwd", "http://2130706433",
                    "http://0177.0.0.1", "http://[::1]/", "http://example.com:99999",
                    "http://", "https://notexample.com", "http://１２７.0.0.1"):
            with self.subTest(url=url):
                self.assertIsNotNone(keep.check_url(url))

    def test_accepted(self):
        for url in ("http://example.com", "https://lab.test/x", "http://192.168.2.50",
                    "http://example.com.", "http://localhost:8080/", "https://a.b.example",
                    "http://10.0.0.1", "http://172.31.255.1", "http://203.0.113.5",
                    "http://127.0.0.1", "https://www.example.org/a?b=c", "http://x.invalid",
                    "http://198.51.100.7", "http://192.0.2.1"):
            with self.subTest(url=url):
                self.assertIsNone(keep.check_url(url))


class TextTest(unittest.TestCase):
    def test_hidden_characters_refused(self):
        for ch in ("\u200b", "\u200d", "\u202e", "\u2066", "\ufeff", "\x07", "\r", "\x1b",
                   "", "\U000e0041"):
            with self.subTest(ch=repr(ch)):
                self.assertIn("character", keep.check_text(f"# Lab\nping{ch} host\n"))

    def test_markup_reasons(self):
        # The card shows the reason, so each rule must name its own
        self.assertEqual(keep.check_text("![x](http://example.com/a.png)\n"), "markdown image")
        self.assertEqual(keep.check_text("![x][1]\n"), "markdown image")
        self.assertEqual(keep.check_text("[docs](http://example.com)\n"), "markdown link")

    def test_markup_refused(self):
        for text in ("![x](http://example.com/a.png)", "see [docs](http://example.com)",
                     "[1]: http://example.com", "   [docs]: /x", "<https://example.com>",
                     "<mailto:a@example.com>", "<img src=x>", '<a href="x">', "<!-- hi -->",
                     "<br/>", "<br>", "</div>", "<target>", "<script>alert(1)</script>",
                     "<?xml version='1.0'?>"):
            with self.subTest(text=text):
                self.assertIsNotNone(keep.check_text(f"# Lab\n{text}\n"))

    def test_urls_in_text(self):
        self.assertIsNotNone(keep.check_text("curl http://evil.net/x\n"))
        self.assertIsNotNone(keep.check_text("go to www.evil.com now\n"))
        self.assertIsNone(keep.check_text("curl http://example.com\n"))
        self.assertIsNone(keep.check_text("curl -I https://example.com, then stop.\n"))
        self.assertIsNone(keep.check_text("open www.example.org.\n"))
        self.assertIsNone(keep.check_text("(see http://192.168.2.50)\n"))

    def test_secrets_refused(self):
        self.assertIsNotNone(keep.check_text(f"token {TOKEN}\n"))
        self.assertIsNotNone(keep.check_text("-----BEGIN OPENSSH PRIVATE KEY-----\n"))
        self.assertIsNotNone(keep.check_text("key " + "Ab1" * 12 + "\n"))
        self.assertIsNotNone(keep.check_text("my secret xyz\n", secrets=["secret xyz"]))

    def test_normal_guide_accepted(self):
        text = ("# Lab 1\n\n```\n$ ip a\n2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500\n"
                "< HTTP/2 200\nReply from 192.168.10.2: bytes=32 time<1ms TTL=128\n```\n"
                "Tabs\tare fine. a < b > c. Привет, zażółć gęślą jaźń. sha256 "
                + "0123456789abcdef" * 4 + "\n- [ ] task box\n- [x] done\n")
        self.assertIsNone(keep.check_text(text))


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.project, self.work = base / "project", base / "work"
        self.project.mkdir()
        (self.project / "README.md").write_text("# project\n")
        (self.project / "old.txt").write_text("before\n")
        (self.project / "My Notes.md").write_text("mine\n")
        self.outside = base / "outside.md"
        self.outside.write_text("not in the work copy\n")
        self.copy()

    def tearDown(self):
        self.tmp.cleanup()

    def copy(self):
        shutil.copytree(self.project, self.work, symlinks=True)

    def write(self, rel, text):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def build(self, **kw):
        return keep.build_manifest(self.project, self.work, TASK, **kw)

    def kept(self, m):
        return [f["path"] for f in m["keep"]]

    def rejected(self, m):
        return {f["path"]: f["reason"] for f in m["rejected"]}

    def test_added_and_changed_kept_unchanged_skipped(self):
        self.write("labs/01-osi.md", "# OSI\n")
        self.write("old.txt", "after\n")
        self.write("tool.py", "print(1)\n")
        m = self.build()
        self.assertEqual(m["task"], TASK)
        self.assertEqual(self.kept(m), ["labs/01-osi.md", "old.txt"])
        self.assertEqual(m["rejected"], [])  # My Notes.md is mine and unchanged, so no noise
        first = m["keep"][0]
        self.assertEqual(first["size"], 6)
        self.assertEqual(first["sha256"], hashlib.sha256(b"# OSI\n").hexdigest())

    def test_linked_file_refused(self):
        (self.work / "leak.md").symlink_to(self.outside)
        self.assertEqual(self.rejected(self.build()), {"leak.md": "link"})

    def test_linked_folder_not_followed(self):
        (self.work / "labs").symlink_to(self.outside.parent)
        m = self.build()
        self.assertFalse(any("outside" in p for p in self.kept(m)))
        self.assertFalse(any("outside" in p for p in self.rejected(m)))

    def test_bad_names_refused(self):
        self.write(".hidden.md", "x\n")
        self.write("a b.md", "x\n")
        self.write("x\u202e.md", "x\n")
        self.write("NOTES.MD", "x\n")
        r = self.rejected(self.build())
        self.assertEqual(set(r), {".hidden.md", "a b.md", repr("x\u202e.md"), "NOTES.MD"})

    def test_hidden_folder_skipped(self):
        self.write(".obsidian/x.md", "x\n")
        self.write(".git/HEAD.md", "x\n")
        m = self.build()
        self.assertEqual((self.kept(m), m["rejected"]), ([], []))

    def test_bad_content_refused_rest_kept(self):
        self.write("a.md", "fine\n")
        self.write("b.md", "![](https://evil/?q=notes)\n")
        (self.work / "c.md").write_bytes(b"\xff\xfe not utf-8\n")
        self.write("d.txt", f"token {TOKEN}\n")
        m = self.build(secrets=[TOKEN])
        self.assertEqual(self.kept(m), ["a.md"])
        self.assertEqual(set(self.rejected(m)), {"b.md", "c.md", "d.txt"})
        self.assertNotIn(TOKEN, json.dumps(m))

    def test_big_file_refused_without_reading(self):
        p = self.work / "big.md"
        with open(p, "wb") as f:
            f.truncate(10 * 1024 * 1024)  # sparse: fast, and reading it would be slow
        self.assertIn("over", self.rejected(self.build())["big.md"])

    def test_file_count_limit(self):
        for i in range(keep.MAX_FILES + 1):
            self.write(f"n{i:02}.md", "x\n")
        m = self.build()
        self.assertEqual(len(m["keep"]), keep.MAX_FILES)
        self.assertEqual(self.rejected(m), {f"n{keep.MAX_FILES:02}.md": f"over {keep.MAX_FILES} files"})

    def test_total_size_limit(self):
        size = 60 * 1024
        for i in range(10):
            self.write(f"n{i}.md", "x" * (size - 1) + "\n")
        m = self.build()
        fit = keep.MAX_TOTAL // size
        self.assertEqual(len(m["keep"]), fit)
        self.assertEqual(len(m["rejected"]), 10 - fit)
        self.assertTrue(all("total" in r for r in self.rejected(m).values()))

    def test_rejected_file_uses_no_budget(self):
        self.write("a-bad.md", "x" * (keep.MAX_FILE + 1))
        for i in range(keep.MAX_FILES):
            self.write(f"n{i:02}.md", "x\n")
        self.assertEqual(len(self.build()["keep"]), keep.MAX_FILES)

    def test_too_many_entries_stops(self):
        d = self.work / "many"
        d.mkdir()
        for i in range(keep.MAX_ENTRIES + 1):
            (d / f"{i}").touch()
        self.write("good.md", "x\n")
        m = self.build()
        self.assertEqual(m["keep"], [])
        self.assertIn("entries", m["stopped"])

    def test_deep_nest_fast_and_not_kept(self):
        p = self.work
        for i in range(50):
            p = p / "d"
        p.mkdir(parents=True)
        (p / "deep.md").write_text("x\n")
        m = self.build()
        self.assertEqual((m["keep"], m["rejected"]), ([], []))

    def test_linked_work_copy_refused(self):
        link = Path(self.tmp.name) / "linked"
        link.symlink_to(self.work)
        with self.assertRaises(keep.KeepError):
            keep.build_manifest(self.project, link, TASK)

    def test_hash_is_canonical(self):
        # The Keep rebuilds the manifest and must get the hash I signed, whatever the key order
        a = {"task": TASK, "keep": [{"path": "a.md", "size": 1, "sha256": "0" * 64}],
             "rejected": [], "stopped": None}
        b = {"stopped": None, "rejected": [], "task": TASK,
             "keep": [{"sha256": "0" * 64, "size": 1, "path": "a.md"}]}
        self.assertEqual(keep.manifest_hash(a), keep.manifest_hash(b))

    def test_hash_changes_with_one_byte(self):
        self.write("a.md", "fine\n")
        h1 = keep.manifest_hash(self.build())
        self.assertEqual(h1, keep.manifest_hash(self.build()))
        self.write("a.md", "fine!\n")
        self.assertNotEqual(h1, keep.manifest_hash(self.build()))


class WriteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "manifests"
        self.dir.mkdir(mode=0o700)

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, n=0):
        return {"task": TASK, "keep": [], "rejected": [{"path": "x", "reason": str(n)}]}

    def test_writes_private_and_replaces(self):
        keep.write_manifest(self.dir, self.manifest(1))
        keep.write_manifest(self.dir, self.manifest(2))
        p = self.dir / f"{TASK}.json"
        self.assertEqual(json.loads(p.read_text()), self.manifest(2))
        self.assertEqual(stat.S_IMODE(p.stat().st_mode), 0o600)
        self.assertEqual(os.listdir(self.dir), [f"{TASK}.json"])

    def test_bad_task_refused(self):
        for task in ("../x", "A" * 64, "a" * 63, "a" * 64 + "\n", None):
            m = self.manifest()
            m["task"] = task
            with self.subTest(task=task), self.assertRaises(keep.KeepError):
                keep.write_manifest(self.dir, m)

    def test_planted_link_not_followed(self):
        victim = Path(self.tmp.name) / "victim"
        victim.write_text("keep me\n")
        (self.dir / f"{TASK}.json").symlink_to(victim)
        (self.dir / f".{TASK}.tmp").symlink_to(victim)
        keep.write_manifest(self.dir, self.manifest())
        self.assertEqual(victim.read_text(), "keep me\n")
        self.assertFalse((self.dir / f"{TASK}.json").is_symlink())


class KeepBase(unittest.TestCase):
    """A done task with a manifest, its work copy, and a vault with Claude/."""

    def setUp(self):
        self.NOW = time.time()  # markers get a real mtime, and expiry compares with it
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.dirs = keep.gate.Dirs(self.base / "gate")
        self.dirs.ensure()
        self.work_root = self.base / "work"
        self.claude = self.base / "vault" / "Claude"
        self.claude.mkdir(parents=True)
        self.project = self.base / "project"
        self.project.mkdir()
        self.work = self.work_root / TASK
        (self.work / "labs").mkdir(parents=True)
        (self.work / "labs" / "01-osi.md").write_text("# OSI\nlayers\n")
        (self.work / "notes.txt").write_text("plain notes\n")
        self.save_task(status="done")
        self.write_manifest()

    def tearDown(self):
        self.tmp.cleanup()

    def save_task(self, **kw):
        keep.gate.save_task(self.dirs, {"root": TASK, "project": "julz-sandbox",
                                        "goal": "write lab guides", "step": 1, **kw})

    def write_manifest(self):
        m = keep.build_manifest(self.project, self.work, TASK)
        keep.write_manifest(self.dirs.manifests, m)
        return m

    def card(self):
        cards = keep.keep_cards(self.dirs)
        self.assertEqual(len(cards), 1)
        return cards[0]

    ALL = ["labs/01-osi.md", "notes.txt"]

    def text(self, topic="network-plus", pick=None):
        c = self.card()
        return keep.keep_text(TASK, topic, c["sha256"], self.ALL if pick is None else pick)

    def sign(self, topic="network-plus", pick=None):
        """What the approver does after a valid assertion."""
        return keep.store_keep(self.text(topic, pick), self.dirs)

    def run_keeps(self, now=None):
        return keep.run_keeps(self.dirs, self.work_root, self.claude, now or self.NOW)

    def marker(self):
        return self.dirs.keep / TASK

    def dest(self, topic="network-plus"):
        return self.claude / topic / TASK[:8]

    def log(self):
        if not self.dirs.log.exists():
            return []
        return [json.loads(l) for l in self.dirs.log.read_text().splitlines()]

    def nothing_copied(self):
        self.assertEqual([p.name for p in self.claude.iterdir()
                          if p.name != "network-plus"], [])
        self.assertFalse(self.dest().exists())
        self.assertNotIn("kept", keep.gate.load_task(self.dirs, TASK))


class CardTest(KeepBase):
    def test_done_task_shows_its_files(self):
        c = self.card()
        self.assertEqual(c["root"], TASK)
        self.assertEqual(c["goal"], "write lab guides")
        self.assertEqual([f["path"] for f in c["files"]], ["labs/01-osi.md", "notes.txt"])
        self.assertEqual(c["sha256"], keep.manifest_hash(keep.load_manifest(self.dirs, TASK)))

    def test_no_card(self):
        cases = {
            "waiting": lambda: self.save_task(status="waiting"),
            "kept": lambda: self.save_task(status="done", kept=self.NOW, topic="x"),
            "no manifest": lambda: (self.dirs.manifests / f"{TASK}.json").unlink(),
            "pending": lambda: self.sign(),
            "nothing to keep": lambda: keep.write_manifest(
                self.dirs.manifests, {"task": TASK, "keep": [], "rejected": [], "stopped": None}),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                self.tearDown()
                self.setUp()
                change()
                self.assertEqual(keep.keep_cards(self.dirs), [])

    def test_broken_manifest_refused(self):
        # Each case breaks exactly one thing in a valid manifest, so each check is proven
        good = keep.load_manifest(self.dirs, TASK)
        entry = good["keep"][0]

        def with_entry(**change):
            return {**good, "keep": [{**entry, **change}]}

        many = [{"path": f"n{i}.md", "size": 1, "sha256": "0" * 64}
                for i in range(keep.MAX_FILES + 1)]
        cases = {
            "not json": "not json", "a list": [],
            "other task": {**good, "task": "b" * 64},
            "no rejected": {k: v for k, v in good.items() if k != "rejected"},
            "path escape": with_entry(path="../x.md"),
            "same path twice": {**good, "keep": [entry, entry]},
            "negative size": with_entry(size=-1),
            "size too big": with_entry(size=keep.MAX_FILE + 1),
            "size as text": with_entry(size="5"),
            "size as bool": with_entry(size=True),
            "short hash": with_entry(sha256="0" * 63),
            "hash not hex": with_entry(sha256="Z" * 64),
            "extra key": with_entry(mode="755"),
            "too many files": {**good, "keep": many},
        }
        p = self.dirs.manifests / f"{TASK}.json"
        for name, body in cases.items():
            with self.subTest(case=name):
                p.write_text(body if isinstance(body, str) else json.dumps(body))
                with self.assertRaises(keep.KeepError):
                    keep.load_manifest(self.dirs, TASK)
                self.assertEqual(keep.keep_cards(self.dirs), [])
        p.write_text(json.dumps(good))
        keep.load_manifest(self.dirs, TASK)  # and the valid one still loads


class TopicListTest(KeepBase):
    def test_topics_of_earlier_keeps_only(self):
        self.assertEqual(keep.used_topics(self.dirs), [])
        self.sign()
        self.run_keeps()
        for root, topic in (("b" * 64, "ccna"), ("c" * 64, "<img src=x>"), ("d" * 64, "A")):
            keep.gate.save_task(self.dirs, {"root": root, "status": "done", "kept": 1.0,
                                            "topic": topic})
        (self.dirs.tasks / f"{'e' * 64}.json").write_text("not json")
        self.assertEqual(keep.used_topics(self.dirs), ["ccna", "network-plus"])


class StoreKeepTest(KeepBase):
    def test_signed_keep_logs_its_channel(self):
        keep.store_keep(self.text(), self.dirs, "device 33bf-a02d-e778-282a")
        self.assertEqual(self.log()[-1]["reason"], "device 33bf-a02d-e778-282a")

    def test_keep_without_channel_says_phone(self):
        self.sign()
        self.assertEqual(self.log()[-1]["reason"], "phone")

    def test_signed_keep_writes_marker(self):
        text = self.text()
        self.assertEqual(self.sign(), TASK)
        self.assertEqual(self.marker().read_text(), text)
        self.assertEqual(stat.S_IMODE(self.marker().stat().st_mode), 0o600)
        self.assertEqual(self.log()[-1]["action"], "keep-signed")

    def test_refused(self):
        good = self.text()
        h = self.card()["sha256"]
        cases = {
            "bad topic": keep.keep_text(TASK, "../etc", h, self.ALL),
            "extra field": good + "files: 3\n",
            "other hash": keep.keep_text(TASK, "network-plus", "0" * 64, self.ALL),
            "bad root": good.replace(TASK, "A" * 64),
            "unknown task": good.replace(TASK, "b" * 64),
            "file not in manifest": keep.keep_text(TASK, "network-plus", h, ["../x.md"]),
            "file twice": keep.keep_text(TASK, "network-plus", h, ["notes.txt", "notes.txt"]),
            "out of manifest order": keep.keep_text(TASK, "network-plus", h, self.ALL[::-1]),
            "empty pick": keep.keep_text(TASK, "network-plus", h, []),
            "two spaces": good.replace("01-osi.md notes", "01-osi.md  notes"),
        }
        for name, text in cases.items():
            with self.subTest(case=name), self.assertRaises(keep.gate.SpecError):
                keep.store_keep(text, self.dirs)
        self.assertFalse(self.marker().exists())

    def test_manifest_changed_after_card(self):
        text = self.text()
        (self.work / "notes.txt").write_text("changed by a later run\n")
        self.write_manifest()
        with self.assertRaisesRegex(keep.gate.SpecError, "changed"):
            keep.store_keep(text, self.dirs)

    def test_not_done_or_kept(self):
        for task in ({"status": "waiting"}, {"status": "discarded"},
                     {"status": "done", "kept": 1.0, "topic": "x"}):
            with self.subTest(task=task):
                text = self.text()
                self.save_task(**task)
                with self.assertRaises(keep.gate.SpecError):
                    keep.store_keep(text, self.dirs)
                self.save_task(status="done")

    def test_nothing_to_keep_refused(self):
        empty = {"task": TASK, "keep": [], "rejected": [], "stopped": None}
        keep.write_manifest(self.dirs.manifests, empty)
        for pick in ([], ["notes.txt"]):
            with self.subTest(pick=pick), self.assertRaises(keep.gate.SpecError):
                keep.store_keep(keep.keep_text(TASK, "network-plus",
                                               keep.manifest_hash(empty), pick), self.dirs)

    def test_second_keep_refused(self):
        text = self.text()
        keep.store_keep(text, self.dirs)
        with self.assertRaisesRegex(keep.gate.SpecError, "already"):
            keep.store_keep(text, self.dirs)


class RunKeepTest(KeepBase):
    def test_copies_exactly_the_signed_files(self):
        self.sign()
        self.assertEqual(self.run_keeps(), [(TASK, "ok")])
        self.assertEqual((self.dest() / "labs" / "01-osi.md").read_text(), "# OSI\nlayers\n")
        self.assertEqual((self.dest() / "notes.txt").read_text(), "plain notes\n")
        task = keep.gate.load_task(self.dirs, TASK)
        self.assertEqual((task["kept"], task["topic"]), (self.NOW, "network-plus"))
        self.assertFalse(self.marker().exists())
        self.assertEqual([p.name for p in self.claude.iterdir()], ["network-plus"])  # no .tmp
        last = self.log()[-1]
        self.assertEqual((last["action"], last["status"]), ("keep", "ok"))
        self.assertTrue((self.dirs.sync / "pending").is_file())  # julz-keep-sync is asked

    def test_copies_only_the_ticked_files(self):
        self.sign(pick=["notes.txt"])
        (self.work / "labs" / "01-osi.md").write_text("changed, but not chosen\n")
        self.assertEqual(self.run_keeps(), [(TASK, "ok")])
        self.assertEqual(sorted(p.name for p in self.dest().rglob("*")), ["notes.txt"])
        self.assertIn("1 files", self.log()[-1]["reason"])

    def test_second_task_same_topic(self):
        self.sign()
        self.run_keeps()
        other = "b" * 64
        shutil.copytree(self.work, self.work_root / other)
        keep.gate.save_task(self.dirs, {"root": other, "project": "julz-sandbox",
                                        "goal": "more", "step": 1, "status": "done"})
        keep.write_manifest(self.dirs.manifests,
                            keep.build_manifest(self.project, self.work_root / other, other))
        c = [c for c in keep.keep_cards(self.dirs) if c["root"] == other][0]
        keep.store_keep(keep.keep_text(other, "network-plus", c["sha256"], self.ALL), self.dirs)
        self.assertEqual(self.run_keeps(), [(other, "ok")])
        self.assertEqual(sorted(p.name for p in (self.claude / "network-plus").iterdir()),
                         ["aaaaaaaa", "bbbbbbbb"])

    def refused(self, reason_part):
        self.assertEqual(self.run_keeps(), [(TASK, "failed")])
        self.nothing_copied()
        self.assertFalse(self.marker().exists())  # used once, whatever happened
        last = self.log()[-1]
        self.assertEqual((last["action"], last["status"]), ("keep", "failed"))
        self.assertIn(reason_part, last["reason"])
        self.assertFalse((self.dirs.sync / "pending").exists())  # nothing kept, no sync

    def test_file_changed_after_signing(self):
        self.sign()
        (self.work / "notes.txt").write_text("plain notes!\n")
        self.refused("changed")

    def test_manifest_edited_after_signing(self):
        self.sign()
        m = keep.load_manifest(self.dirs, TASK)
        m["keep"].append({"path": "extra.md", "size": 1, "sha256": "0" * 64})
        keep.write_manifest(self.dirs.manifests, m)
        self.refused("changed")

    def test_file_swapped_for_link(self):
        self.sign()
        secret = self.base / "secret.txt"
        secret.write_text("plain notes\n")  # same bytes, still refused
        (self.work / "notes.txt").unlink()
        (self.work / "notes.txt").symlink_to(secret)
        self.refused("link")

    def test_folder_swapped_for_link(self):
        self.sign()
        elsewhere = self.base / "elsewhere"
        shutil.move(self.work / "labs", elsewhere)
        (self.work / "labs").symlink_to(elsewhere)
        self.refused("link")

    def test_work_copy_gone(self):
        self.sign()
        shutil.rmtree(self.work)
        self.refused("work copy")

    def test_task_deleted_from_phone_meanwhile(self):
        self.sign()
        self.save_task(status="discarded")
        self.refused("not done")

    def test_destination_exists(self):
        self.sign()
        self.dest().mkdir(parents=True)
        self.assertEqual(self.run_keeps(), [(TASK, "failed")])
        self.assertEqual(list(self.dest().iterdir()), [])

    def test_linked_topic_folder(self):
        self.sign()
        outside = self.base / "outside"
        outside.mkdir()
        (self.claude / "network-plus").symlink_to(outside)
        self.assertEqual(self.run_keeps(), [(TASK, "failed")])
        self.assertEqual(list(outside.iterdir()), [])

    def test_linked_claude_folder(self):
        self.sign()
        outside = self.base / "outside"
        outside.mkdir()
        self.claude.rmdir()
        self.claude.symlink_to(outside)
        self.assertEqual(self.run_keeps(), [(TASK, "failed")])
        self.assertEqual(list(outside.iterdir()), [])

    def test_expired_marker_removed_unused(self):
        self.sign()
        old = self.NOW - keep.KEEP_TTL - 1
        os.utime(self.marker(), (old, old))
        self.refused("expired")

    def test_marker_under_another_name_refused(self):
        # The marker's name and the task in its text must agree
        other = "b" * 64
        (self.dirs.keep / other).write_text(self.text())
        self.assertEqual(self.run_keeps(), [(other, "failed")])
        self.nothing_copied()
        self.assertIn("bad task", self.log()[-1]["reason"])

    def test_odd_markers_removed(self):
        (self.dirs.keep / "not-a-task").write_text("x")
        (self.dirs.keep / ("c" * 64)).symlink_to(self.base / "vault")
        self.assertEqual(self.run_keeps(), [])
        self.assertEqual(list(self.dirs.keep.iterdir()), [])
        self.assertTrue((self.base / "vault").is_dir())

    def test_temp_folder_left_alone(self):
        # store_keep writes here before it links the marker in whole (CWE-362)
        self.sign()
        self.assertEqual(os.listdir(self.dirs.keep / ".tmp"), [])  # its temp file is gone
        half = self.dirs.keep / ".tmp" / f"{TASK}.123"
        half.write_text("keep: ")
        self.assertEqual(self.run_keeps(), [(TASK, "ok")])
        self.assertTrue(half.exists())

    def test_failure_mid_copy_leaves_nothing(self):
        self.sign()
        from unittest import mock
        with mock.patch.object(keep.os, "rename", side_effect=OSError("disk full")):
            self.assertEqual(self.run_keeps(), [(TASK, "failed")])
        self.assertEqual(sorted(p.name for p in self.claude.rglob("*")), ["network-plus"])
        self.assertNotIn("kept", keep.gate.load_task(self.dirs, TASK))

    def test_busy_lock_keeps_marker(self):
        self.sign()
        with keep.gate.lock(self.dirs), self.assertRaises(keep.gate.GateBusy):
            self.run_keeps()
        self.assertTrue(self.marker().exists())
        self.assertEqual(self.run_keeps(), [(TASK, "ok")])

    def test_files_are_readable_notes(self):
        self.sign()
        self.run_keeps()
        mode = stat.S_IMODE((self.dest() / "notes.txt").stat().st_mode)
        self.assertEqual(mode & 0o222, 0o200)  # only I can write
        self.assertFalse(mode & 0o111)  # never executable


def unit_lines(unit):
    return (ROOT / "systemd" / unit).read_text().splitlines()


def unit_paths(unit, key):
    out = set()
    for line in unit_lines(unit):
        if line.startswith(key + "="):
            out.update(line[len(key) + 1:].split())
    return out


class KeepUnitFileTest(unittest.TestCase):
    """Threat 60: what each unit can see, read from the real unit files."""
    G = "%h/.local/share/julz"

    def test_keep_unit_is_narrow(self):
        u = "julz-keep.service"
        self.assertIn("PrivateNetwork=yes", unit_lines(u))
        self.assertIn("TemporaryFileSystem=%h:ro", unit_lines(u))
        self.assertEqual(unit_paths(u, "BindPaths"),
                         {f"{self.G}/keep", f"{self.G}/tasks", f"{self.G}/log",
                          f"{self.G}/run.lock", f"{self.G}/sync", "%h/Documents/julz-mem/Claude"})
        self.assertEqual(unit_paths(u, "BindReadOnlyPaths"),
                         {"%h/.local/lib/julz", f"{self.G}/work", f"{self.G}/manifests"})
        text = "\n".join(l for l in unit_lines(u) if not l.startswith("#"))
        for secret in ("Environment", ".config", "token", "credentials"):
            self.assertNotIn(secret, text)

    def test_approver_sees_no_work_copy_or_vault(self):
        u = "julz-approver.service"
        every = unit_paths(u, "BindPaths") | unit_paths(u, "BindReadOnlyPaths")
        self.assertFalse([p for p in every if p.startswith(f"{self.G}/work")])
        self.assertFalse([p for p in every if "julz-mem/Claude" in p or p.endswith("julz-mem")])
        self.assertIn(f"{self.G}/manifests", unit_paths(u, "BindReadOnlyPaths"))
        self.assertIn(f"{self.G}/keep", unit_paths(u, "BindPaths"))

    def test_cleaner_binds_keep_folders(self):
        rw = unit_paths("julz-clean.service", "BindPaths")
        self.assertIn(f"{self.G}/keep", rw)
        self.assertIn(f"{self.G}/manifests", rw)

    def test_gate_folders_bound_by_units_are_made_by_ensure(self):
        # A bind of a missing folder stops the unit at start: everything bound must exist
        with tempfile.TemporaryDirectory() as tmp:
            dirs = keep.gate.Dirs(Path(tmp))
            dirs.ensure()
            made = {p.name for p in Path(tmp).iterdir()}
        for unit in ("julz-keep.service", "julz-approver.service", "julz-clean.service"):
            for p in unit_paths(unit, "BindPaths") | unit_paths(unit, "BindReadOnlyPaths"):
                if p.startswith(self.G + "/") and p.count("/") == 4:
                    name = p.rsplit("/", 1)[1]
                    with self.subTest(unit=unit, path=p):
                        self.assertTrue(name in made or name in ("work", "run.lock", "webauthn"))


KEEP_UNIT_SKIP = not (shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"))


@unittest.skipIf(KEEP_UNIT_SKIP, "needs a user systemd session")
class KeepRealSandboxTest(unittest.TestCase):
    """julz-keep.py under the sandbox lines of the real julz-keep.service (the run.lock
    lesson of 2026-10-16: a unit test is not the unit)."""

    def sandbox_argv(self, home):
        argv = ["systemd-run", "--user", "--wait", "--pipe", "--quiet", "-E", f"HOME={home}"]
        for line in unit_lines("julz-keep.service"):
            key = line.split("=", 1)[0]
            # PrivateTmp is left out: the test home itself lives in /tmp
            if key in ("NoNewPrivileges", "ProtectSystem", "PrivateNetwork", "UMask",
                       "TemporaryFileSystem", "BindPaths", "BindReadOnlyPaths",
                       "RestrictAddressFamilies"):
                line = line.replace("%h/.local/lib/julz", str(ROOT))
                argv += ["-p", line.replace("%h", str(home))]
        return argv

    def make_home(self, home):
        g = home / ".local" / "share" / "julz"
        keep.gate.Dirs(g).ensure()
        (g / "run.lock").touch()
        (g / "work" / TASK / "labs").mkdir(parents=True)
        (g / "work" / TASK / "labs" / "a.md").write_text("# A\n")
        (home / "Documents" / "julz-mem" / "Claude").mkdir(parents=True)
        (home / "Projects").mkdir()
        return g

    def test_walls_hold(self):
        import subprocess
        probe = (
            "import socket, sys\n"
            "from pathlib import Path\n"
            "home = Path(sys.argv[1])\n"
            "tries = {'vault': home / 'Documents/julz-mem/evil.md',\n"
            "         'work': home / '.local/share/julz/work/" + TASK + "/labs/a.md',\n"
            "         'manifests': home / '.local/share/julz/manifests/x.json',\n"
            "         'home': home / '.bashrc'}\n"
            "for name, p in tries.items():\n"
            "    try:\n"
            "        open(p, 'a').close(); print(name, 'WRITABLE')\n"
            "    except OSError: print(name, 'refused')\n"
            "try:\n"
            "    socket.socket(socket.AF_INET).connect(('127.0.0.1', 8765)); print('net OPEN')\n"
            "except OSError: print('net refused')\n")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.make_home(home)
            r = subprocess.run(self.sandbox_argv(home) + [sys.executable, "-I", "-c", probe,
                                                          str(home)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertEqual(r.stdout.split(), ["vault", "refused", "work", "refused",
                                                "manifests", "refused", "home", "refused",
                                                "net", "refused"])

    def test_keep_in_its_sandbox(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            dirs = keep.gate.Dirs(self.make_home(home))
            claude = home / "Documents" / "julz-mem" / "Claude"
            project = home / "project"
            project.mkdir()
            keep.gate.save_task(dirs, {"root": TASK, "project": "p", "goal": "g", "step": 1,
                                       "status": "done"})
            m = keep.build_manifest(project, dirs.log.parent.parent / "work" / TASK, TASK)
            keep.write_manifest(dirs.manifests, m)
            keep.store_keep(keep.keep_text(TASK, "lab", keep.manifest_hash(m), ["labs/a.md"]),
                            dirs)
            r = subprocess.run(self.sandbox_argv(home)
                               + [sys.executable, "-I", str(ROOT / "julz-keep.py")],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            self.assertIn(f"keep {TASK[:8]}: ok", r.stdout, dirs.log.read_text())
            self.assertEqual((claude / "lab" / TASK[:8] / "labs" / "a.md").read_text(), "# A\n")
            self.assertTrue(keep.gate.load_task(dirs, TASK)["kept"])


if __name__ == "__main__":
    unittest.main()
