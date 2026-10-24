"""Tests for listing a knowledge base's files page by page (BACKLOG 205).
Open WebUI 0.11.4 returns 30 files a page with a total and ignores limit, so a resync that read
one page left stale copies beside the new ones in her memory (threat 17).
Run: python3 -m unittest discover -s tests -v"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import owui  # noqa: E402
from test_sync_filter import load_sync_module  # noqa: E402

PAGE = 30


class FakeOwui:
    """One knowledge base. Removing a file shifts the later pages up, as the real server does."""

    def __init__(self, n, total=True, ignore_page=False, endless=False):
        self.files = [f"old{i}" for i in range(n)]
        self.total, self.ignore_page, self.endless = total, ignore_page, endless
        self.gets = 0
        self.uploads = 0

    def api(self, key, method, path, data=None, **kw):
        if method == "GET" and "/files" in path:
            self.gets += 1
            page = 1
            if "page=" in path and not self.ignore_page:
                page = int(path.split("page=")[1].split("&")[0])
            if self.endless:
                items = [f"new{page}-{i}" for i in range(PAGE)]
            else:
                items = self.files[(page - 1) * PAGE:page * PAGE]
            reply = {"items": [{"id": i, "filename": i, "meta": {}} for i in items], "directories": [], "breadcrumbs": []}
            if self.total:
                reply["total"] = len(self.files)
            return reply
        if path.endswith("/file/remove"):
            self.files.remove(data["file_id"])
            return {}
        if path.endswith("/file/add"):
            self.files.append(data["file_id"])
            return {}
        raise AssertionError(f"unexpected call {method} {path}")

    def upload(self, key, path, name):
        self.uploads += 1
        return {"id": f"up{self.uploads}"}


class KbFilesTest(unittest.TestCase):
    def files(self, fake):
        with mock.patch.object(owui, "api", fake.api):
            return [f["id"] for f in owui.kb_files("k", "kb")]

    def test_second_page_is_read(self):
        # julz-claude on 20 Oct: 36 files, 6 of them on page 2
        self.assertEqual(self.files(FakeOwui(36)), [f"old{i}" for i in range(36)])

    def test_exactly_one_page(self):
        # julz-mem sits at 30: the total ends it without asking for an empty page 2
        fake = FakeOwui(30)
        self.assertEqual(len(self.files(fake)), 30)
        self.assertEqual(fake.gets, 1)

    def test_empty_base(self):
        self.assertEqual(self.files(FakeOwui(0)), [])

    def test_no_total_pages_until_empty(self):
        self.assertEqual(len(self.files(FakeOwui(65, total=False))), 65)

    def test_server_ignoring_page_stops_short_and_loud(self):
        # The same 30 on every page: never loop, never pretend 30 is all of 36
        with self.assertRaises(SystemExit) as e:
            self.files(FakeOwui(36, ignore_page=True))
        self.assertIn("30 of 36", str(e.exception))

    def test_endless_pages_are_capped(self):
        fake = FakeOwui(0, total=False, endless=True)
        with self.assertRaises(SystemExit):
            self.files(fake)
        self.assertEqual(fake.gets, owui.MAX_PAGES)


class ResyncTest(unittest.TestCase):
    def setUp(self):
        self.mod = load_sync_module()
        self.tmp = tempfile.TemporaryDirectory()
        self.note = Path(self.tmp.name) / "n.md"
        self.note.write_text("# n")

    def tearDown(self):
        self.tmp.cleanup()

    def resync(self, fake, notes):
        with mock.patch.object(owui, "api", fake.api), \
                mock.patch.object(self.mod, "api", fake.api), \
                mock.patch.object(self.mod, "upload_file", fake.upload), \
                mock.patch.object(self.mod, "find_kb", lambda key, name: {"id": "kb"}), \
                mock.patch("builtins.print"):
            return self.mod.sync("k", "julz-claude", "", notes, claude=True)

    def test_resync_leaves_no_old_copy(self):
        fake = FakeOwui(36)
        notes = [(self.note, Path(f"cpts/n{i}.md")) for i in range(37)]
        self.assertEqual(self.resync(fake, notes), 37)
        # The diff adds first, so the new copies sit after the old until those go
        self.assertEqual(fake.files, [f"up{i}" for i in range(1, 38)])

    def test_short_listing_removes_nothing(self):
        # Better a failed sync the Keep timer retries and warns about than half a cleanup
        fake = FakeOwui(36, ignore_page=True)
        with self.assertRaises(SystemExit):
            self.resync(fake, [(self.note, Path("a.md"))])
        self.assertEqual(len(fake.files), 36)
        self.assertEqual(fake.uploads, 0)


if __name__ == "__main__":
    unittest.main()
