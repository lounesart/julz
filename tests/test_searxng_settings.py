"""SearXNG's settings.yml (268): on 27 Oct Google, DuckDuckGo, Brave, Qwant and Wikipedia all
refused this IP, so every search came back empty. Bing and Yahoo still answered.

Read line by line, not with PyYAML: CI installs only hashed packages (threat 146) and the file is
small and flat. SearXNG parses the real YAML when it starts."""
import re
import unittest
from pathlib import Path

SETTINGS = Path(__file__).resolve().parent.parent / "searxng" / "settings.yml"


def lines() -> list[str]:
    """The file without comments and blank lines, indentation kept."""
    out = []
    for line in SETTINGS.read_text().splitlines():
        line = line.split(" #")[0].rstrip() if not line.lstrip().startswith("#") else ""
        if line.strip():
            out.append(line)
    return out


def section(name: str) -> list[str]:
    """The indented lines under a top level key."""
    body, inside = [], False
    for line in lines():
        if not line.startswith(" "):
            inside = line == f"{name}:"
            continue
        if inside:
            body.append(line.strip())
    return body


def engines() -> dict[str, list[str]]:
    """Each engine by name with the keys under it."""
    out, name = {}, None
    for line in section("engines"):
        m = re.fullmatch(r"- name: (\S+)", line)
        if m:
            name = m.group(1)
            out[name] = []
        elif name:
            out[name].append(line)
    return out


class SearxngSettingsTest(unittest.TestCase):
    def test_bing_and_yahoo_are_on(self):
        on = {n for n, keys in engines().items() if "disabled: false" in keys}
        self.assertEqual(on, {"bing", "yahoo"})
        self.assertEqual(set(engines()), {"bing", "yahoo"})

    def test_the_default_engines_stay(self):
        # They rejoin by themselves when a ban ends: no keep_only, no remove
        self.assertIn("use_default_settings: true", lines())
        self.assertFalse([l for l in lines() if "keep_only" in l or "remove:" in l])

    def test_still_local_and_json(self):
        self.assertIn("limiter: false", section("server"))
        self.assertIn("public_instance: false", section("server"))
        self.assertIn("- json", section("search"))

    def test_the_reader_sees_a_change(self):
        # The parser itself: a flipped engine or a dropped json format must show
        text = SETTINGS.read_text()
        self.assertIn("    disabled: false", text)
        self.assertIn("    - json", text)


if __name__ == "__main__":
    unittest.main()
