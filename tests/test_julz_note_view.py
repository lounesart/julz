"""Obsidian-like note view in the chat: tools/julz_notes.py note_html (SECURITY.md 84).
Everything is escaped first; links never clickable, images never loaded."""
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

from test_julz_notes import load_tool_module

NOTE = """---
tags:
  - network-plus
  - dhcp
status: learning
---

# DHCP

Hands out **IP** and *mask*, uses `UDP 67`, ==remember this==.

> [!tip] Remember
> DORA: Discover, Offer, Request, Ack

> a plain quote

| Port | Role |
|---|---|
| 67 | server |
| 68 | client |

- [x] read it
- [ ] lab it
- a point
1. first

See [[study/network-plus/dns|DNS]] and [[subnetting]].
Docs at [the RFC](https://evil.example/x?a=1&b=2) and ![diagram](https://evil.example/leak.png)

```
<script>alert(1)</script> **not bold**
```

---
<img src=x onerror=alert(1)> and <b>raw html</b>
"""


class NoteHtmlTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = load_tool_module()
        cls.html = cls.mod.note_html("study/network-plus/dhcp.md", "your note", NOTE)

    def test_properties_panel_with_tag_pills(self):
        h = self.html
        self.assertIn('class="props"', h)
        self.assertIn('<span class="tag">#network-plus</span>', h)
        self.assertIn("learning", h)
        self.assertNotIn("tags:", h)  # front matter is not shown raw

    def test_headings_inline_and_highlight(self):
        h = self.html
        self.assertIn("<h1>DHCP</h1>", h)
        self.assertIn("<strong>IP</strong>", h)
        self.assertIn("<em>mask</em>", h)
        self.assertIn("<code>UDP 67</code>", h)
        self.assertIn("<mark>remember this</mark>", h)

    def test_callout_quote_table_tasks_lists(self):
        h = self.html
        self.assertIn('<div class="callout tip">', h)
        self.assertIn("Remember", h)
        self.assertIn("DORA: Discover, Offer, Request, Ack", h)
        self.assertIn("<blockquote>a plain quote</blockquote>", h)
        self.assertIn("<th>Port</th>", h)
        self.assertIn("<td>68</td>", h)
        self.assertIn('class="task done"', h)
        self.assertIn('class="task"', h)
        self.assertIn("<li>a point</li>", h)
        self.assertIn("<ol>", h)
        self.assertIn("<hr>", h)

    def test_wikilinks_show_their_name(self):
        self.assertIn('<span class="wl">DNS</span>', self.html)
        self.assertIn('<span class="wl">subnetting</span>', self.html)

    def test_links_are_text_and_images_never_load(self):
        h = self.html
        self.assertNotIn("href=", h)
        self.assertNotIn("src=", h.replace("&lt;img src=x", ""))  # only the escaped raw tag
        self.assertNotIn("url(", h)
        self.assertIn("the RFC", h)
        self.assertIn("[image: diagram]", h)
        self.assertNotIn("<img", h)

    def test_code_and_raw_html_stay_text(self):
        h = self.html
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; **not bold**", h)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", h)
        self.assertIn("&lt;b&gt;raw html&lt;/b&gt;", h)
        self.assertEqual(h.count("<script>"), 1)  # only our own height script

    def test_inline_code_and_tags_escaped(self):
        # found by the mutation check: both were XSS paths no test covered
        h = self.mod.note_html("daily/x.md", "your note",
                               "---\ntags: [<img src=x onerror=alert(1)>]\n---\n\nuse `<b>bold</b>` here\n")
        self.assertNotIn("<img", h)
        self.assertNotIn("<b>bold", h)
        self.assertIn("<code>&lt;b&gt;bold&lt;/b&gt;</code>", h)

    def test_path_and_hidden_chars_escaped(self):
        h = self.mod.note_html("daily/<b>x.md", "your note", "# a\u202eb\n")
        self.assertNotIn("<b>x", h)
        self.assertNotIn("\u202e", h)


class ReadNoteViewTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self.tmp.name) / "vault"
        (self.vault / "study").mkdir(parents=True)
        (self.vault / "Inbox").mkdir()
        (self.vault / "study" / "dhcp.md").write_text(NOTE)
        os.environ.update(JULZ_VAULT=str(self.vault), JULZ_INBOX=str(self.vault / "Inbox"),
                          JULZ_LOG=str(Path(self.tmp.name) / "a.log"))
        self.tools = load_tool_module().Tools()

    def tearDown(self):
        self.tmp.cleanup()

    async def test_read_note_embeds_inside_open_webui(self):
        fake = types.ModuleType("fastapi.responses")

        class HTMLResponse:
            def __init__(self, content, headers=None):
                self.content, self.headers = content, headers
        fake.HTMLResponse = HTMLResponse
        sys.modules["fastapi"] = types.ModuleType("fastapi")
        sys.modules["fastapi.responses"] = fake
        try:
            for path in ("dhcp", "study/dhcp.md"):
                embed, context = await self.tools.read_note(path)
                self.assertIn("<h1>DHCP</h1>", embed.content)
                self.assertIn("DORA", context)  # julz still has the text to answer from
                low = context.lower()
                self.assertIn("do not repeat", low)
                # found live: "the user sees it" made julz say she cannot open notes
                self.assertIn("you already opened study/dhcp.md", low)
                self.assertIn("never say you cannot open notes", low)
                self.assertNotIn("rendered above", low)
        finally:
            del sys.modules["fastapi"], sys.modules["fastapi.responses"]

    async def test_read_note_text_elsewhere(self):
        out = await self.tools.read_note("dhcp")
        self.assertIsInstance(out, str)
        self.assertIn("DORA", out)


if __name__ == "__main__":
    unittest.main()
