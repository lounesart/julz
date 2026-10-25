"""sync-knowledge.py chunk headers (BACKLOG 133, SECURITY.md 163). Open WebUI splits a note at its
headings, and a chunk lost which note and part it was: on 25 Oct the chunk with the CPTS name
never reached her though the file was cited. The uploaded copy gets a line under each #, ## and
### heading; the vault file is never changed, and a heading cannot smuggle hidden characters.
Run: python3 -m unittest discover -s tests -v"""
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from unittest import mock  # noqa: E402

import owui  # noqa: E402
from test_sync_diff import FakeKb  # noqa: E402
from test_sync_filter import load_sync_module  # noqa: E402

mod = load_sync_module()
NOTE = """---
tags:
  - cpts
---

# HTB CPTS overview

The HTB Certified Penetration Testing Specialist.

## What the cert is

A hands-on exam.

### Format

Several days.

## How it fits my path

After Security+.
"""


def added(text, folder="cpts"):
    """The lines with_headers put in, in order."""
    out = mod.with_headers(text, Path(folder)).splitlines()
    for line in text.splitlines():
        out.remove(line)
    return out


class HeadersTest(unittest.TestCase):
    def test_a_line_under_each_heading_with_its_path(self):
        self.assertEqual(added(NOTE), [
            "In cpts > HTB CPTS overview",
            "In cpts > HTB CPTS overview > What the cert is",
            "In cpts > HTB CPTS overview > What the cert is > Format",
            "In cpts > HTB CPTS overview > How it fits my path"])

    def test_the_line_comes_right_after_its_heading(self):
        lines = mod.with_headers(NOTE, Path("cpts")).splitlines()
        i = lines.index("## What the cert is")
        self.assertEqual(lines[i + 1], "In cpts > HTB CPTS overview > What the cert is")

    def test_every_line_of_the_note_is_kept_in_order(self):
        lines = mod.with_headers(NOTE, Path("cpts")).splitlines()
        kept = [line for line in lines if not line.startswith("In cpts")]
        self.assertEqual(kept, NOTE.splitlines())

    def test_nested_folder_and_a_note_at_the_root(self):
        self.assertEqual(added("# DNS\n", "study/network-plus"), ["In study/network-plus > DNS"])
        self.assertEqual(added("# DNS\n", "."), ["In DNS"])

    def test_a_new_title_resets_the_path(self):
        self.assertEqual(added("# A\n## a1\n# B\n### b3\n"),
                         ["In cpts > A", "In cpts > A > a1", "In cpts > B", "In cpts > B > b3"])

    def test_deeper_headings_and_hashtags_add_nothing(self):
        self.assertEqual(added("# A\n#### deep\n#tag\n##nospace\n"), ["In cpts > A"])

    def test_a_comment_in_a_code_fence_is_not_a_heading(self):
        text = "# Nmap\n```bash\n# scan the top ports\nnmap -F host\n```\n~~~\n## not this\n~~~\n## Next\n"
        self.assertEqual(added(text), ["In cpts > Nmap", "In cpts > Nmap > Next"])

    def test_front_matter_is_left_alone(self):
        text = "---\ntitle: x\n# not a heading\n---\n# Real\n"
        self.assertEqual(added(text), ["In cpts > Real"])
        self.assertTrue(mod.with_headers(text, Path("cpts")).startswith("---\ntitle: x\n# not a heading\n---\n"))

    def test_hidden_and_control_characters_are_dropped(self):
        # Trojan Source style bidi and zero width marks (CWE-1007), an ANSI escape
        self.assertEqual(added("# ev\u202eil\u200b \x1b[31mred\t  tab\n"), ["In cpts > evil [31mred tab"])

    def test_any_whitespace_is_one_space(self):
        # A tab between words keeps them apart; a line separator (Zl, not Cc or Cf) never stays
        self.assertEqual(added("# a\tb\u2028c\u00a0d\n"), ["In cpts > a b c d"])

    def test_the_line_is_capped(self):
        line = added("# " + "A" * 500 + "\n## " + "B" * 500 + "\n")[1]
        self.assertEqual(len(line), mod.HEADER_MAX)

    def test_an_empty_heading_adds_nothing(self):
        self.assertEqual(added("#  \n## \u200b\n# A\n"), ["In cpts > A"])

    def test_trailing_hashes_of_a_closed_heading_are_dropped(self):
        self.assertEqual(added("## Ports ##\n"), ["In cpts > Ports"])


class SyncUploadsHeadersTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name)
        (self.vault / "study").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def note(self, rel, text):
        (self.vault / rel).write_text(text)

    def sync(self, kb):
        notes = [(p, p.relative_to(self.vault)) for p in sorted(self.vault.rglob("*.md"))]
        with mock.patch.object(owui, "api", kb.api), \
                mock.patch.object(mod, "api", kb.api), \
                mock.patch.object(mod, "upload_file", kb.upload), \
                mock.patch.object(mod, "find_kb", lambda key, name: {"id": "kb"}), \
                mock.patch("builtins.print"):
            return mod.sync("k", "julz-mem", "", notes, claude=False)

    def test_upload_carries_the_lines_and_the_vault_is_untouched(self):
        self.note("study/dns.md", "# DNS\nA records.\n")
        kb = FakeKb()
        self.sync(kb)
        meta = kb.files["up1"]["meta"]
        sent = kb.sent["up1"]
        self.assertEqual(sent, b"# DNS\nIn study > DNS\nA records.\n")
        self.assertEqual(meta["file_hash"], hashlib.sha256(sent).hexdigest())
        self.assertEqual((self.vault / "study/dns.md").read_text(), "# DNS\nA records.\n")

    def test_a_synced_note_is_not_uploaded_again(self):
        self.note("study/dns.md", "# DNS\n")
        kb = FakeKb([("a", "study__dns.md", hashlib.sha256(b"# DNS\nIn study > DNS\n").hexdigest())])
        self.sync(kb)
        self.assertEqual(kb.calls, [])


if __name__ == "__main__":
    unittest.main()
