"""sync-knowledge.py `sync` as a diff, make before break (BACKLOG 129, SECURITY.md 143).
On 20 Oct a full resync removed every file first, died on the fifth upload and left her
memory 4 of 32. A diff uploads first and removes only after every add worked.
Run: python3 -m unittest discover -s tests -v"""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import owui  # noqa: E402
from test_sync_filter import load_sync_module  # noqa: E402


def sha(text: str) -> str:
    """The hash of what sync uploads for a note in study/: the note with its chunk headers (163)."""
    return hashlib.sha256(load_sync_module().with_headers(text, Path("study")).encode()).hexdigest()


class FakeKb:
    """One knowledge base, one page. Records every change in order."""

    def __init__(self, files=(), fail_upload_of=None):
        # files: (id, filename, file_hash or None for a file without meta)
        self.files = {i: {"id": i, "filename": n, "meta": {"file_hash": h} if h else {}}
                      for i, n, h in files}
        self.calls, self.fail_upload_of, self.n, self.sent = [], fail_upload_of, 0, {}

    def api(self, key, method, path, data=None, **kw):
        if method == "GET" and "/files" in path:
            return {"items": list(self.files.values()), "total": len(self.files)}
        if path.endswith("/file/remove"):
            self.calls.append(("remove", self.files.pop(data["file_id"])["filename"]))
            return {}
        if path.endswith("/file/add"):
            self.calls.append(("add", self.files[data["file_id"]]["filename"]))
            return {}
        raise AssertionError(f"unexpected call {method} {path}")

    def upload(self, key, data, name):
        if name == self.fail_upload_of:
            raise SystemExit(f"POST /api/v1/files -> HTTP 500 for {name}")
        self.n += 1
        fid = f"up{self.n}"
        # Open WebUI keeps the uploaded file outside the collection until it is added
        self.files[fid] = {"id": fid, "filename": name,
                           "meta": {"file_hash": hashlib.sha256(data).hexdigest()}}
        self.sent[fid] = data
        self.calls.append(("upload", name))
        return {"id": fid}

    def names(self):
        return sorted(f["filename"] for f in self.files.values())


class DiffSyncTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        (self.vault / "study").mkdir()
        self.mod = load_sync_module()

    def tearDown(self):
        self.tmp.cleanup()

    def note(self, rel, text):
        (self.vault / rel).write_text(text)

    def notes(self):
        return [(self.vault / r, Path(r)) for r in
                sorted(str(p.relative_to(self.vault)) for p in self.vault.rglob("*.md"))]

    def sync(self, kb):
        with mock.patch.object(owui, "api", kb.api), \
                mock.patch.object(self.mod, "api", kb.api), \
                mock.patch.object(self.mod, "upload_file", kb.upload), \
                mock.patch.object(self.mod, "find_kb", lambda key, name: {"id": "kb"}), \
                mock.patch("builtins.print"):
            return self.mod.sync("k", "julz-mem", "", self.notes(), claude=False)

    def test_unchanged_notes_are_left_alone(self):
        self.note("study/dns.md", "# DNS")
        kb = FakeKb([("a", "study__dns.md", sha("# DNS"))])
        self.assertEqual(self.sync(kb), 1)
        self.assertEqual(kb.calls, [])

    def test_changed_note_added_before_the_old_is_removed(self):
        self.note("study/dns.md", "# DNS v2")
        kb = FakeKb([("a", "study__dns.md", sha("# DNS"))])
        self.sync(kb)
        self.assertEqual(kb.calls, [("upload", "study__dns.md"), ("add", "study__dns.md"),
                                    ("remove", "study__dns.md")])
        self.assertEqual(list(kb.files), ["up1"])

    def test_new_note_added_deleted_note_removed(self):
        self.note("study/new.md", "# new")
        kb = FakeKb([("a", "study__gone.md", sha("# gone"))])
        self.sync(kb)
        self.assertEqual(kb.names(), ["study__new.md"])

    def test_every_add_comes_before_any_remove(self):
        for i in range(4):
            self.note(f"study/n{i}.md", f"# new {i}")
        kb = FakeKb([(f"o{i}", f"study__old{i}.md", sha("x")) for i in range(4)])
        self.sync(kb)
        kinds = [c[0] for c in kb.calls]
        self.assertEqual(kinds.index("remove"), len(kinds) - 4)
        self.assertEqual(kb.names(), [f"study__n{i}.md" for i in range(4)])

    def test_failed_upload_removes_nothing(self):
        # 20 Oct, the other way round: a run that dies must leave her old memory whole
        self.note("study/a.md", "# a v2")
        self.note("study/b.md", "# b")
        kb = FakeKb([("a", "study__a.md", sha("# a")), ("s", "study__stale.md", sha("s"))],
                    fail_upload_of="study__b.md")
        with self.assertRaises(SystemExit):
            self.sync(kb)
        self.assertFalse([c for c in kb.calls if c[0] == "remove"])
        self.assertIn("study__stale.md", kb.names())

    def test_duplicate_from_a_dead_run_is_cleaned(self):
        # A run that died after an add left old and new side by side: keep the one that matches
        self.note("study/dns.md", "# DNS v2")
        kb = FakeKb([("old", "study__dns.md", sha("# DNS")), ("new", "study__dns.md", sha("# DNS v2"))])
        self.sync(kb)
        self.assertEqual(kb.calls, [("remove", "study__dns.md")])
        self.assertEqual(list(kb.files), ["new"])

    def test_two_matching_copies_keep_one(self):
        self.note("study/dns.md", "# DNS")
        kb = FakeKb([("a", "study__dns.md", sha("# DNS")), ("b", "study__dns.md", sha("# DNS"))])
        self.sync(kb)
        self.assertEqual(len(kb.files), 1)

    def test_file_without_hash_is_replaced(self):
        self.note("study/dns.md", "# DNS")
        kb = FakeKb([("a", "study__dns.md", None)])
        self.sync(kb)
        self.assertEqual(list(kb.files), ["up1"])

    def test_empty_vault_never_empties_the_collection(self):
        # An unreadable vault (a mount gone wrong) looks like "every note deleted"
        kb = FakeKb([("a", "study__dns.md", sha("# DNS"))])
        with self.assertRaises(SystemExit) as e:
            self.sync(kb)
        self.assertIn("empty", str(e.exception))
        self.assertEqual(kb.calls, [])

    def test_empty_vault_and_empty_collection_is_fine(self):
        self.assertEqual(self.sync(FakeKb()), 0)


if __name__ == "__main__":
    unittest.main()
