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


# A screen that pins an area under its list (status, the signed text, the fingerprint button). The
# tab bar floats over every screen since v1.66 (22i), so that area must clear it, or the button
# hides under the bar (126: Todos lost its confirm, the last Inbox note its Move and Delete)
PINNED = re.compile(r"Column\((Modifier\.fillMaxSize\(\)[^\n]*)\)\s*\{\s*\n\s*Box\(Modifier\.weight\(1f\)\)")


def pinned_under_bar(sources: dict[str, str] | None = None) -> list[str]:
    if sources is None:
        sources = {f.name: f.read_text() for f in sorted(UI.glob("*.kt"))}
    return [name for name, text in sources.items() for m in PINNED.finditer(text) if "barClear()" not in m.group(1)]


class DesignLintTest(unittest.TestCase):
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

    def test_pinned_bottoms_clear_the_tab_bar(self):
        found = [f.name for f in sorted(UI.glob("*.kt")) for m in PINNED.finditer(f.read_text())]
        self.assertEqual(sorted(found), ["InboxScreen.kt", "TodosScreen.kt"], "a new pinned bottom? check it here")
        self.assertEqual(pinned_under_bar(), [], "\nPad the screen with barClear(): the bar floats over it")

    def test_the_bar_lint_catches_what_it_should(self):
        bad = "    Column(Modifier.fillMaxSize()) {\n    Box(Modifier.weight(1f)) {\n"
        good = "    Column(Modifier.fillMaxSize().padding(bottom = barClear())) {\n    Box(Modifier.weight(1f)) {\n"
        self.assertEqual(pinned_under_bar({"X.kt": bad, "Y.kt": good}), ["X.kt"])


if __name__ == "__main__":
    unittest.main()
