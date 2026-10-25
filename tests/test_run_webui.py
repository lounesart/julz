"""run-webui.sh hides from the container what Julz must never read (threats 69, 153): the vault's
.git and the bad answers kept as eval cases each sit under an empty read only tmpfs. The notes
tool skips feedback/eval too, but the mount holds for any other code in the container.
Run: python3 -m unittest discover -s tests -v"""
import re
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "run-webui.sh"
TMPFS = re.compile(r"--mount type=tmpfs,destination=(\S+?),\S*tmpfs-mode=([0-7]+)")
HIDDEN = ("/data/julz-mem/.git", "/data/julz-mem/feedback/eval")
MKDIR = 'sudo -u "$ME" mkdir -p "$USER_HOME/Documents/julz-mem/feedback/eval"'


def tmpfs_modes(text: str) -> dict[str, int]:
    return {dest: int(mode, 8) for dest, mode in TMPFS.findall(text)}


class RunWebuiTest(unittest.TestCase):
    def setUp(self):
        self.text = SCRIPT.read_text()

    def test_hidden_paths_are_empty_read_only_tmpfs(self):
        modes = tmpfs_modes(self.text)
        for dest in HIDDEN:
            self.assertIn(dest, modes)
            self.assertEqual(modes[dest] & 0o222, 0, f"{dest} must not be writable")

    def test_eval_folder_is_made_as_me_before_the_container(self):
        # Docker cannot make a mount point inside the read only vault bind, and a mkdir as
        # root would leave a root owned folder in my vault
        self.assertIn(MKDIR, self.text)
        self.assertLess(self.text.index(MKDIR), self.text.index("docker run -d"))

    def test_feedback_is_never_bound_writable(self):
        self.assertFalse(re.search(r"-v \S*feedback\S*:rw", self.text))

    def test_the_parser_catches_what_it_should(self):
        self.assertEqual(tmpfs_modes("--mount type=tmpfs,destination=/x,tmpfs-size=1m,tmpfs-mode=0700"),
                         {"/x": 0o700})
        self.assertEqual(tmpfs_modes("-v /x:/x:ro"), {})


if __name__ == "__main__":
    unittest.main()
