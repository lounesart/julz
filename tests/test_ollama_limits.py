"""Tests for systemd/ollama-limits.conf, SECURITY.md threat 144. Two models may stay loaded
(julz and the bge-m3 embedder), never more, and the cgroup caps from 16 Oct stay as they were,
so a model too big for the GPU kills ollama's runner, not my session."""
import re
import unittest
from pathlib import Path

CONF = Path(__file__).resolve().parent.parent / "systemd" / "ollama-limits.conf"


def settings():
    """Active lines only, comments dropped."""
    return [l.strip() for l in CONF.read_text().splitlines()
            if l.strip() and not l.strip().startswith("#")]


class OllamaLimitsTest(unittest.TestCase):
    def test_at_most_two_models_loaded(self):
        found = [l for l in settings() if "OLLAMA_MAX_LOADED_MODELS" in l]
        self.assertEqual(found, ['Environment="OLLAMA_MAX_LOADED_MODELS=2"'])

    def test_one_request_at_a_time_and_vram_kept_free(self):
        lines = settings()
        self.assertIn('Environment="OLLAMA_NUM_PARALLEL=1"', lines)
        self.assertIn('Environment="OLLAMA_GPU_OVERHEAD=536870912"', lines)

    def test_cgroup_caps_unchanged(self):
        lines = settings()
        for cap in ("MemoryHigh=6G", "MemoryMax=7G", "OOMScoreAdjust=500"):
            self.assertIn(cap, lines)

    def test_prompt_cache_capped_not_default(self):
        # llama-server keeps up to 8 GiB of prompts in host RAM by default (threat 145)
        found = [l for l in settings() if "LLAMA_ARG_CACHE_RAM" in l]
        self.assertEqual(found, ['Environment="LLAMA_ARG_CACHE_RAM=1024"'])

    def test_swap_capped_so_memorymax_still_bounds(self):
        # MemoryMax counts RAM only; with zram, swap is the way around it (threat 145)
        found = [l for l in settings() if l.startswith("MemorySwapMax=")]
        self.assertEqual(found, ["MemorySwapMax=1G"])

    def test_every_setting_in_the_service_section(self):
        lines = settings()
        self.assertEqual(lines[0], "[Service]")
        self.assertEqual([l for l in lines if re.match(r"\[.*\]$", l)], ["[Service]"])


if __name__ == "__main__":
    unittest.main()
