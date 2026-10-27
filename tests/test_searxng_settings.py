"""SearXNG's settings.yml (268): on 27 Oct Google, DuckDuckGo, Brave, Qwant and Wikipedia all
refused this IP, so every search came back empty. Bing and Yahoo still answered."""
import unittest
from pathlib import Path

import yaml

SETTINGS = Path(__file__).resolve().parent.parent / "searxng" / "settings.yml"


class SearxngSettingsTest(unittest.TestCase):
    def setUp(self):
        self.s = yaml.safe_load(SETTINGS.read_text())

    def test_bing_and_yahoo_are_on(self):
        on = {e["name"] for e in self.s["engines"] if e.get("disabled") is False}
        self.assertEqual(on, {"bing", "yahoo"})

    def test_the_default_engines_stay(self):
        # They rejoin by themselves when a ban ends: no keep_only, no remove
        self.assertIs(self.s["use_default_settings"], True)

    def test_still_local_and_json(self):
        self.assertIs(self.s["server"]["limiter"], False)
        self.assertIs(self.s["server"]["public_instance"], False)
        self.assertIn("json", self.s["search"]["formats"])


if __name__ == "__main__":
    unittest.main()
