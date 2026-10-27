"""The phone app's design integrity (22d): screens use the design system's tokens, never a colour,
corner or font size typed by hand, so a theme, Industrial or big text reaches every screen.
Theme.kt holds the values; the few component internals below are allowed by name, each with
its reason. Run: python3 -m unittest discover -s tests -v"""
import re
import unittest
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "android" / "app" / "src" / "main" / "java" / "app" / "julz" / "ui"
RULES = {
    "a colour typed by hand": re.compile(r"Color\(0x[0-9A-Fa-f]{8}\)"),
    # also corners drawn by hand: a CornerRadius in draw code is out of Industrial's reach
    "a corner typed by hand": re.compile(r"RoundedCornerShape\(\s*\d+(?:\.\d+)?\.dp\s*\)|CutCornerShape\(\s*\d|CornerRadius\("),
    "a font size typed by hand": re.compile(r"(?:fontSize|lineHeight)\s*=\s*\d+(?:\.\d+)?\.sp"),
    "an icon circle drawn by hand": re.compile(r"size\(44\.dp\)"),
}
# (file, text on the line, why it may stay)
ALLOWED = [
    ("Components.kt", "Box(Modifier.size(44.dp).background(tint?.copy", "IconBadge itself, the one icon circle"),
    ("Components.kt", "RoundedCornerShape(2.dp)).background(J.lineStrong)", "the sheet's 40 by 4 handle"),
    ("OtherScreens.kt", "Box(Modifier.size(44.dp).clip(J.rS)", "a theme's colour swatch in Look and feel, not an icon"),
    ("MarkdownView.kt", "RoundedCornerShape(6.dp)", "a task checkbox and the quote bar inside a note"),
    ("WorkCards.kt", "RoundedCornerShape(6.dp)", "Keep's file checkbox"),
    ("GoalsTab.kt", "RoundedCornerShape(3.dp)", "a goal's progress bar"),
    ("FeedScreens.kt", "RoundedCornerShape(5.dp)", "a day's bar in the week chart"),
]


def findings() -> list[str]:
    out = []
    for f in sorted(UI.glob("*.kt")):
        if f.name == "Theme.kt":
            continue
        for no, line in enumerate(f.read_text().splitlines(), 1):
            if line.strip().startswith(("//", "*", "/**")):
                continue
            for what, rule in RULES.items():
                if rule.search(line) and not any(f.name == af and text in line for af, text, _ in ALLOWED):
                    out.append(f"{f.name}:{no}: {what}: {line.strip()[:90]}")
    return out


# A size typed by hand (26 Oct, session 63: the wheel shipped with 192, 76 and 280 dp picked by eye,
# next to the 36 dp SmallPill it should have matched). Space and sizes come from Theme.kt's role
# tokens (inset, gap, stack, small, tap...); a hairline or stroke of 0 to 2 dp is not layout. The
# sizes already in the code are the baseline, per file, as Android Lint keeps one: a new one fails,
# and a removed one must lower its number here, so the baseline only shrinks
SIZE = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)\.dp\b")
STROKES = {"0", "1", "1.5", "2"}
SIZE_BASELINE = {
    "App.kt": 7, "Components.kt": 10, "FeedScreens.kt": 7, "GoalsTab.kt": 7, "Guides.kt": 2, "History.kt": 4,
    "MarkdownView.kt": 10, "NativeChat.kt": 8, "NotesScreen.kt": 1, "OtherScreens.kt": 5, "TodosScreen.kt": 4,
    "WorkCards.kt": 4,
}


def sizes_by_hand(sources: dict[str, str] | None = None) -> dict[str, int]:
    if sources is None:
        sources = {f.name: f.read_text() for f in sorted(UI.glob("*.kt")) if f.name != "Theme.kt"}
    out = {}
    for name, text in sources.items():
        n = sum(1 for line in text.splitlines() if not line.strip().startswith(("//", "*", "/**"))
                for m in SIZE.finditer(line) if m.group(1) not in STROKES)
        if n:
            out[name] = n
    return out


# A screen that pins an area under its list (status, the signed text, the fingerprint button). The
# tab bar floats over every screen since v1.66 (22i), so that area must clear it, or the button
# hides under the bar (126: Todos lost its confirm, the last Inbox note its Move and Delete)
PINNED = re.compile(r"Column\((Modifier\.fillMaxSize\(\)[^\n]*)\)\s*\{\s*\n\s*Box\(Modifier\.weight\(1f\)\)")


def pinned_under_bar(sources: dict[str, str] | None = None) -> list[str]:
    if sources is None:
        sources = {f.name: f.read_text() for f in sorted(UI.glob("*.kt"))}
    return [name for name, text in sources.items() for m in PINNED.finditer(text) if "barClear()" not in m.group(1)]


# A band floating at a screen's bottom (257: the Messages wheel under the thumb) sits on top of the
# tab bar's place, so it pads by barClear() on its own line, unless its screen already pads by it
# (a pinned bottom, Todos). The bar itself and the sheets, which cover the bar, are the two that may not
FLOATING = re.compile(r"Modifier\.align\(Alignment\.BottomCenter\)\.fillMaxWidth\(\)[^\n]*")
FLOATING_ALLOWED = {"App.kt": "the band the tab bar sits on", "Components.kt": "a sheet, drawn over the bar"}


def floating_under_bar(sources: dict[str, str] | None = None) -> list[str]:
    if sources is None:
        sources = {f.name: f.read_text() for f in sorted(UI.glob("*.kt"))}
    padded = lambda text: any("barClear()" in m.group(1) for m in PINNED.finditer(text))
    return [f"{name}:{text.count(chr(10), 0, m.start()) + 1}" for name, text in sources.items()
            if name not in FLOATING_ALLOWED and not padded(text) for m in FLOATING.finditer(text) if "barClear()" not in m.group(0)]


# A line drawn with border() (254): on Industrial's cut corners Compose paints it through a bitmap the
# size of the element (a long code block asked for 210 MB, 25 Oct), and a Messages landing spent 6 to
# 8 ms of GPU on those of its rows. outline() in Components.kt strokes the same line with no bitmap.
# The border() calls left are the baseline, per file, Theme.kt included; it only shrinks
BORDER = re.compile(r"\.border\(")
BORDER_BASELINE = {
    "Components.kt": 5, "GoalsTab.kt": 3, "History.kt": 1, "InboxScreen.kt": 1, "NativeChat.kt": 4,
    "OtherScreens.kt": 1, "TodosScreen.kt": 3, "WorkCards.kt": 1,
}


def borders(sources: dict[str, str] | None = None) -> dict[str, int]:
    if sources is None:
        sources = {f.name: f.read_text() for f in sorted(UI.glob("*.kt"))}
    out = {}
    for name, text in sources.items():
        n = sum(len(BORDER.findall(l)) for l in text.splitlines() if not l.strip().startswith(("//", "*", "/**")))
        if n:
            out[name] = n
    return out


# A text field keeps the keyboard when tapped (228): Shell ends editing on a tap outside every
# keepsKeyboard() area, so a field without it would lose focus on its own tap and flicker
FIELD = re.compile(r"\b(?:OutlinedTextField|BasicTextField)\(")


def fields_without_keep(sources: dict[str, str] | None = None) -> list[str]:
    if sources is None:
        sources = {f.name: f.read_text() for f in sorted(UI.glob("*.kt"))}
    return [f"{name}:{text.count(chr(10), 0, m.start()) + 1}" for name, text in sources.items()
            for m in FIELD.finditer(text) if "keepsKeyboard()" not in text[m.end():m.end() + 300]]


class DesignLintTest(unittest.TestCase):
    def test_every_field_keeps_the_keyboard(self):
        self.assertEqual(fields_without_keep(), [], "\nAdd .keepsKeyboard() to the field's modifier (228)")

    def test_the_field_lint_catches_what_it_should(self):
        bad = "OutlinedTextField(x, { x = it }, Modifier.fillMaxWidth(), label = { Text(\"X\") })\n"
        good = "OutlinedTextField(x, { x = it }, Modifier.fillMaxWidth().keepsKeyboard(), label = { Text(\"X\") })\n"
        self.assertEqual(fields_without_keep({"X.kt": bad, "Y.kt": good}), ["X.kt:1"])
    def test_no_new_size_by_hand(self):
        over = {f: n for f, n in sizes_by_hand().items() if n > SIZE_BASELINE.get(f, 0)}
        self.assertEqual(over, {}, "\nUse a role token from Theme.kt (docs/design/README.md, Layout system), or name a new one there")

    def test_size_baseline_only_shrinks(self):
        # a size replaced by a token lowers its file's number, so the baseline stays the truth
        self.assertEqual(sizes_by_hand(), SIZE_BASELINE)

    def test_the_size_lint_catches_what_it_should(self):
        src = "Box(Modifier.width(192.dp).border(1.dp, J.line).padding(J.sp3).height(J.small))\n// 76.dp in a comment\n"
        self.assertEqual(sizes_by_hand({"X.kt": src}), {"X.kt": 1})

    def test_screens_use_the_tokens(self):
        self.assertEqual(findings(), [], "\nUse a token from Theme.kt, or allow it here with a reason")

    def test_every_allowance_is_still_used(self):
        # an allowance nothing needs any more goes, so the list stays the truth
        for f, text, why in ALLOWED:
            self.assertIn(text, (UI / f).read_text(), f"{f}: {why}: no longer used, remove it")

    def test_the_lint_catches_what_it_should(self):
        for bad in ('.background(Color(0xFF123456))', ".clip(RoundedCornerShape(12.dp))", "drawRoundRect(c, cornerRadius = CornerRadius(8f))",
                    "style = J.sec.copy(fontSize = 15.sp)", "Box(Modifier.size(44.dp))"):
            self.assertTrue(any(r.search(bad) for r in RULES.values()), bad)

    def test_lines_are_outlines(self):
        # no new border(), and one replaced by outline() lowers its file's number here
        self.assertEqual(borders(), BORDER_BASELINE, "\nDraw the line with outline(width, colour, shape) (254)")

    def test_the_border_lint_catches_what_it_should(self):
        src = "Box(Modifier.border(1.dp, J.line, J.pill))\n// .border( in a comment\nBox(Modifier.outline(1.dp, J.line, J.pill))\n"
        self.assertEqual(borders({"X.kt": src}), {"X.kt": 1})

    def test_pinned_bottoms_clear_the_tab_bar(self):
        found = [f.name for f in sorted(UI.glob("*.kt")) for m in PINNED.finditer(f.read_text())]
        self.assertEqual(sorted(found), ["InboxScreen.kt", "TodosScreen.kt"], "a new pinned bottom? check it here")
        self.assertEqual(pinned_under_bar(), [], "\nPad the screen with barClear(): the bar floats over it")

    def test_the_bar_lint_catches_what_it_should(self):
        bad = "    Column(Modifier.fillMaxSize()) {\n    Box(Modifier.weight(1f)) {\n"
        good = "    Column(Modifier.fillMaxSize().padding(bottom = barClear())) {\n    Box(Modifier.weight(1f)) {\n"
        self.assertEqual(pinned_under_bar({"X.kt": bad, "Y.kt": good}), ["X.kt"])

    def test_floating_bands_clear_the_tab_bar(self):
        self.assertEqual(floating_under_bar(), [], "\nPad the floating band with barClear(): the bar sits under it (257)")
        found = [f.name for f in sorted(UI.glob("*.kt")) if f.name not in FLOATING_ALLOWED and FLOATING.search(f.read_text())]
        self.assertEqual(found, ["FeedScreens.kt", "TodosScreen.kt"], "a new floating band? check it on the phone too")

    def test_the_floating_lint_catches_what_it_should(self):
        bad = "Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(bottom = J.sp4)) {\n"
        good = "Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth().padding(bottom = barClear())) {\n"
        self.assertEqual(floating_under_bar({"X.kt": bad, "Y.kt": good, "App.kt": bad}), ["X.kt:1"])
        screen = "    Column(Modifier.fillMaxSize().padding(bottom = barClear())) {\n    Box(Modifier.weight(1f)) {\n" + bad
        self.assertEqual(floating_under_bar({"Z.kt": screen}), [])


if __name__ == "__main__":
    unittest.main()
