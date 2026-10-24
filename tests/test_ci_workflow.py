"""The GitHub workflow runs third party code on a public repo (179, threat 146).

Read as text: PyYAML is not among the CI's packages, and these are rules about the words.
"""
import importlib.util
import os
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = Path(os.environ.get("JULZ_CI_WORKFLOW", ROOT / ".github/workflows/ci.yml"))
REQUIREMENTS = ROOT / ".github/ci-requirements.txt"


class TestCiWorkflow(unittest.TestCase):
    def setUp(self):
        self.text = WORKFLOW.read_text()
        self.lines = self.text.splitlines()

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML is on the laptop, not in CI")
    def test_parses_as_yaml(self):
        # An unquoted ": " in a run line is a mapping and breaks the file on GitHub
        import yaml
        jobs = yaml.safe_load(self.text)["jobs"]
        self.assertEqual(sorted(jobs), ["gitleaks", "tests"])
        for job in jobs.values():
            self.assertTrue(all(isinstance(s.get("run", ""), str) for s in job["steps"]))

    def test_actions_pinned_by_sha(self):
        uses = [line.strip() for line in self.lines if re.match(r"\s*(-\s+)?uses:", line)]
        self.assertTrue(uses)
        for line in uses:
            # A tag can be moved to another commit (tj-actions); a full SHA cannot
            self.assertRegex(line, r"^(-\s+)?uses: [\w.-]+/[\w.-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+$")

    def test_token_reads_contents_only(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read\n")
        self.assertEqual(self.text.count("permissions:"), 1)
        self.assertNotIn("write", self.text)

    def test_no_secrets_and_safe_triggers(self):
        self.assertNotRegex(self.text, r"secrets\s*[.\[]")
        self.assertRegex(self.text, r"(?m)^on:\n  push:\n  pull_request:\n(?!  )")
        for bad in ("pull_request_target", "workflow_run"):
            self.assertNotIn(bad, self.text)

    def test_no_event_text_in_scripts(self):
        # A PR title or branch name pasted into run: is shell injection
        self.assertNotIn("github.event", self.text)
        self.assertNotIn("head_ref", self.text)

    def test_checkout_keeps_no_token(self):
        checkouts = [i for i, line in enumerate(self.lines) if "uses: actions/checkout@" in line]
        self.assertTrue(checkouts)
        for i in checkouts:
            self.assertIn("persist-credentials: false", "\n".join(self.lines[i:i + 4]))

    def test_gitleaks_binary_checked(self):
        sha = re.search(r'GITLEAKS_SHA256: "([0-9a-f]{64})"', self.text)
        self.assertTrue(sha)
        self.assertRegex(self.text, r'GITLEAKS_VERSION: "\d+\.\d+\.\d+"')
        self.assertIn('echo "$GITLEAKS_SHA256  gitleaks.tar.gz" | sha256sum -c -', self.text)
        # The check comes before anything from the tarball is used
        self.assertLess(self.text.index("sha256sum -c"), self.text.index("tar -xzf"))

    def test_pip_installs_hashed_wheels_only(self):
        pip = [line for line in self.lines if "pip install" in line]
        self.assertEqual(len(pip), 1)
        for flag in ("--require-hashes", "--only-binary :all:", "-r .github/ci-requirements.txt"):
            self.assertIn(flag, pip[0])

    def test_requirements_pinned_with_hashes(self):
        blocks = re.split(r"\n(?=\S)", REQUIREMENTS.read_text().split("\n\n")[-1].strip())
        names = []
        for block in blocks:
            if block.startswith("#"):
                continue
            head = block.splitlines()[0]
            self.assertRegex(head, r"^[\w-]+==[\w.]+ \\$")
            self.assertRegex(block, r"--hash=sha256:[0-9a-f]{64}")
            names.append(head.split("==")[0])
        self.assertEqual(sorted(names), ["cffi", "cryptography", "fido2", "joserfc", "pycparser"])


if __name__ == "__main__":
    unittest.main()
