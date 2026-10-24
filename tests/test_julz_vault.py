"""julz_vault: the host side of notes v2 (SECURITY.md 65 to 70).
A real git repo in a temp folder. A fake pre-commit hook stands in for gitleaks."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import julz_gate as gate  # noqa: E402
import julz_vault as vault_mod  # noqa: E402

TODAY = date(2026, 10, 16)
HOOK = "#!/bin/sh\ngit diff --cached | grep -q FAKESECRET && exit 1\nexit 0\n"
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


class VaultBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.old_env = {k: os.environ.get(k) for k in GIT_ENV}
        os.environ.update(GIT_ENV)
        self.vault = base / "julz-mem"
        self.study = self.vault / "study"
        self.study.mkdir(parents=True)
        (self.vault / "Claude").mkdir()
        (self.vault / "Outbox").mkdir()
        self.requests = self.vault / "Inbox" / ".requests"
        self.requests.mkdir(parents=True)
        self.outside = base / "outside.md"
        self.outside.write_text("OUTSIDE\n")
        (self.study / "dhcp.md").write_text(
            "---\ntags: [network-plus]\nstatus: learning\nreviewed: 2026-10-01\n---\n\n"
            "# DHCP\nDORA.\n")
        (self.study / "osi.md").write_text("# OSI\nSeven layers.")  # no newline at the end
        (self.vault / "Claude" / "acls.md").write_text("# ACLs\n")
        (self.vault / ".gitignore").write_text("Inbox/.requests/\n.tmp-*/\n")
        hooks = base / "hooks"
        hooks.mkdir()
        (hooks / "pre-commit").write_text(HOOK)
        (hooks / "pre-commit").chmod(0o755)
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.hooksPath", str(hooks))
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "start")
        self.dirs = gate.Dirs(base / "gate")
        self.state = base / "state"
        self.n = 0

    def tearDown(self):
        for k, v in self.old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self.tmp.cleanup()

    # ----- helpers -----

    def git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(self.vault), *args], check=True,
                              capture_output=True, text=True).stdout

    def commits(self) -> list[str]:
        return self.git("log", "--format=%s").splitlines()

    def files_in(self, rev="HEAD") -> list[str]:
        return self.git("show", "--name-only", "--format=", rev).split()

    def request(self, payload, name=None, raw=None):
        self.n += 1
        name = name or f"17606{self.n:05d}-{self.n:08x}.json"
        data = raw if raw is not None else json.dumps(payload).encode()
        (self.requests / name).write_bytes(data)
        return name

    def run_vault(self):
        return vault_mod.run(self.vault, self.dirs, self.state, TODAY)

    def log(self) -> list[dict]:
        if not self.dirs.log.exists():
            return []
        return [json.loads(l) for l in self.dirs.log.read_text().splitlines()]


class VaultTest(VaultBase):
    # ----- append -----

    def test_append_adds_a_dated_block_and_commits_it_alone(self):
        before = (self.study / "dhcp.md").read_text()
        self.request({"op": "append", "note": "study/dhcp.md", "text": "Relay agents help."})
        self.run_vault()
        after = (self.study / "dhcp.md").read_text()
        self.assertTrue(after.startswith(before))  # nothing above changed
        self.assertEqual(after[len(before):],
                         "\n## Added by julz, 2026-10-16\n\nRelay agents help.\n")
        self.assertRegex(self.commits()[0], r"^julz: added to study/dhcp\.md \(request [0-9a-f]{8}\)$")
        self.assertEqual(self.files_in(), ["study/dhcp.md"])
        self.assertEqual(list(self.requests.iterdir()), [])
        entry = self.log()[-1]
        self.assertEqual((entry["action"], entry["status"]), ("note", "ok"))

    def test_append_to_a_note_without_final_newline(self):
        self.request({"op": "append", "note": "study/osi.md", "text": "Please Do Not Throw"})
        self.run_vault()
        self.assertEqual((self.study / "osi.md").read_text(),
                         "# OSI\nSeven layers.\n\n## Added by julz, 2026-10-16\n\n"
                         "Please Do Not Throw\n")

    def test_append_text_is_checked_like_a_keep(self):
        bad = ["see [x](https://evil.com)", "![i](https://a.example/x.png)", "<b>hi</b>",
               "https://evil.com/?d=1", "zero\u200bwidth", "bidi\u202e", "",
               "   ", "x" * (vault_mod.MAX_APPEND_CHARS + 1),
               "AKIA" + "ABCDEFGHIJKLMNOP"]
        for text in bad:
            self.request({"op": "append", "note": "study/dhcp.md", "text": text})
        before = (self.study / "dhcp.md").read_text()
        results = self.run_vault()
        self.assertEqual((self.study / "dhcp.md").read_text(), before)
        self.assertEqual([r[1] for r in results], ["refused"] * len(bad))
        self.assertEqual(self.commits(), ["start"])
        self.assertEqual(list(self.requests.iterdir()), [])

    def test_reserved_lab_url_is_allowed(self):
        self.request({"op": "append", "note": "study/dhcp.md",
                      "text": "Lab server at http://192.168.1.10/ and http://router.test/"})
        self.assertEqual(self.run_vault()[0][1], "ok")

    # ----- targets -----

    def test_targets_outside_my_notes_are_refused(self):
        (self.study / "link.md").symlink_to(self.outside)
        (self.study / "sub").mkdir()
        (self.study / "sub" / "deep.md").write_text("# Deep\n")
        (self.study / ".hidden.md").write_text("h\n")
        (self.study / "notes.txt").write_text("t\n")
        for note in ["../outside.md", "study/../../outside.md", "/etc/passwd",
                     "Claude/acls.md", "Outbox/x.md", "study/missing.md", "study/link.md",
                     "study/.hidden.md", "study/notes.txt", "study", "study/sub",
                     "study/dhcp.md\x00", 7, None, ["study/dhcp.md"]]:
            self.request({"op": "append", "note": note, "text": "x"})
        results = self.run_vault()
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertEqual(self.outside.read_text(), "OUTSIDE\n")
        self.assertEqual((self.vault / "Claude" / "acls.md").read_text(), "# ACLs\n")
        # the fixtures above are my own changes and get their commit; julz gets none
        self.assertFalse([c for c in self.commits() if c.startswith("julz")])

    def test_a_folder_named_like_a_note_is_refused(self):
        (self.study / "trap.md").mkdir()
        self.request({"op": "append", "note": "study/trap.md", "text": "x"})
        self.assertEqual(self.run_vault()[0][1:], ("refused", "not a regular file"))

    def test_subfolders_of_study_are_mine_too(self):
        (self.study / "network-plus").mkdir()
        (self.study / "network-plus" / "vlan.md").write_text("# VLAN\n")
        self.request({"op": "append", "note": "study/network-plus/vlan.md", "text": "802.1Q"})
        self.assertEqual(self.run_vault()[0][1], "ok")

    def test_symlinked_folder_is_refused(self):
        (self.vault / "elsewhere").mkdir()
        (self.vault / "elsewhere" / "x.md").write_text("# X\n")
        (self.study / "away").symlink_to(self.vault / "elsewhere")
        self.request({"op": "append", "note": "study/away/x.md", "text": "x"})
        self.assertEqual(self.run_vault()[0][1], "refused")
        self.assertEqual((self.vault / "elsewhere" / "x.md").read_text(), "# X\n")

    # ----- request shape -----

    def test_bad_requests_are_removed_and_logged(self):
        self.request(None, raw=b"not json")
        self.request(None, raw=b"\xff\xfe")
        self.request(["op", "append"])
        self.request({"op": "append", "note": "study/dhcp.md"})  # no text
        self.request({"op": "append", "note": "study/dhcp.md", "text": "x", "extra": 1})
        self.request({"op": "delete", "note": "study/dhcp.md"})
        self.request({"op": "reviewed", "note": "study/dhcp.md", "text": "sneaky"})
        self.request(None, raw=b"{" + b" " * vault_mod.MAX_REQUEST_BYTES + b"}")
        self.request({"op": "append", "note": "study/dhcp.md", "text": "x"}, name="evil.json")
        (self.requests / "link.json").symlink_to(self.outside)
        before = (self.study / "dhcp.md").read_text()
        results = self.run_vault()
        self.assertEqual(len(results), 10)
        self.assertTrue(all(r[1] == "refused" for r in results), results)
        self.assertEqual((self.study / "dhcp.md").read_text(), before)
        self.assertEqual(list(self.requests.iterdir()), [])
        self.assertEqual(self.outside.read_text(), "OUTSIDE\n")
        self.assertEqual(len([e for e in self.log() if e["status"] == "refused"]), 10)

    def test_request_through_a_symlink_is_not_followed(self):
        planted = self.outside.with_name("planted.json")
        planted.write_text(json.dumps({"op": "append", "note": "study/dhcp.md", "text": "x"}))
        (self.requests / "1760600000-abcdef01.json").symlink_to(planted)
        before = (self.study / "dhcp.md").read_text()
        self.assertEqual(self.run_vault()[0][1], "refused")
        self.assertEqual((self.study / "dhcp.md").read_text(), before)
        self.assertTrue(planted.exists())  # the link goes, its target stays

    def test_a_request_still_being_written_is_left_alone(self):
        tmp = self.requests / ".tmp-1760600000-abcdef01.json"
        tmp.write_text("{")
        self.assertEqual(self.run_vault(), [])
        self.assertTrue(tmp.exists())

    def test_old_leftover_temp_file_is_removed(self):
        tmp = self.requests / ".tmp-1760600000-abcdef01.json"
        tmp.write_text("{")
        os.utime(tmp, (1, 1))
        self.run_vault()
        self.assertFalse(tmp.exists())

    def test_at_most_twenty_per_run_and_flood_is_cut(self):
        for i in range(vault_mod.MAX_PER_RUN + 5):
            self.request({"op": "reviewed", "note": "study/dhcp.md"})
        self.assertEqual(len(self.run_vault()), vault_mod.MAX_PER_RUN)
        self.assertEqual(len(list(self.requests.iterdir())), 5)
        for i in range(vault_mod.MAX_WAITING + 10):
            self.request({"op": "reviewed", "note": "study/dhcp.md"})
        self.run_vault()
        self.assertLessEqual(len(list(self.requests.iterdir())),
                             vault_mod.MAX_WAITING - vault_mod.MAX_PER_RUN)
        self.assertEqual(sum(e.get("reason", "").startswith("flood") for e in self.log()), 1)

    # ----- reviewed -----

    def test_reviewed_changes_only_the_date_line(self):
        self.request({"op": "reviewed", "note": "study/dhcp.md"})
        self.run_vault()
        self.assertEqual((self.study / "dhcp.md").read_text(),
                         "---\ntags: [network-plus]\nstatus: learning\nreviewed: 2026-10-16\n"
                         "---\n\n# DHCP\nDORA.\n")
        self.assertEqual(self.commits()[0][:31], "julz: reviewed study/dhcp.md (r")
        entry = self.log()[-1]
        self.assertEqual((entry["action"], entry["status"]), ("reviewed", "ok"))

    def test_reviewed_adds_front_matter_when_missing(self):
        self.request({"op": "reviewed", "note": "study/osi.md"})
        self.run_vault()
        self.assertEqual((self.study / "osi.md").read_text(),
                         "---\nreviewed: 2026-10-16\n---\n\n# OSI\nSeven layers.")

    def test_reviewed_adds_the_line_to_existing_front_matter(self):
        (self.study / "dns.md").write_text("---\nstatus: solid\n---\n# DNS\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "dns")
        self.request({"op": "reviewed", "note": "study/dns.md"})
        self.run_vault()
        self.assertEqual((self.study / "dns.md").read_text(),
                         "---\nstatus: solid\nreviewed: 2026-10-16\n---\n# DNS\n")

    def test_reviewed_twice_the_same_day_makes_no_empty_commit(self):
        self.request({"op": "reviewed", "note": "study/dhcp.md"})
        self.request({"op": "reviewed", "note": "study/dhcp.md"})
        self.run_vault()
        self.assertEqual(len(self.commits()), 2)

    # ----- commits -----

    def test_my_edits_get_their_own_commit_before_julz(self):
        with open(self.study / "dhcp.md", "a") as f:
            f.write("My own line.\n")
        (self.vault / "Outbox" / "r.md").write_text("report\n")
        self.request({"op": "append", "note": "study/dhcp.md", "text": "From julz."})
        self.run_vault()
        subjects = self.commits()
        self.assertTrue(subjects[0].startswith("julz: added to study/dhcp.md"))
        self.assertEqual(subjects[1], "vault: changes in Outbox (1), study (1)")
        mine = self.git("show", "HEAD~1", "--format=", "--", "study/dhcp.md")
        self.assertIn("My own line.", mine)
        self.assertNotIn("From julz.", mine)

    def test_nothing_changed_means_no_commit(self):
        self.run_vault()
        self.assertEqual(self.commits(), ["start"])

    def test_requests_and_temp_folders_are_never_committed(self):
        (self.vault / "Claude" / ".tmp-abc").mkdir()
        (self.vault / "Claude" / ".tmp-abc" / "x.md").write_text("half\n")
        tmp = self.requests / ".tmp-1760600000-abcdef01.json"
        tmp.write_text("{")
        (self.study / "new.md").write_text("# New\n")
        self.run_vault()
        self.assertEqual(self.files_in(), ["study/new.md"])

    def test_blocked_commit_is_logged_once(self):
        (self.study / "keys.md").write_text("FAKESECRET\n")
        self.run_vault()
        self.run_vault()
        self.assertEqual(self.commits(), ["start"])
        failed = [e for e in self.log() if e["action"] == "vault-commit"]
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0]["status"], "failed")
        (self.study / "keys.md").write_text("FAKESECRET again\n")
        self.run_vault()
        self.assertEqual(len([e for e in self.log() if e["action"] == "vault-commit"]), 2)

    def test_busy_lock_does_nothing(self):
        self.request({"op": "reviewed", "note": "study/dhcp.md"})
        with vault_mod.lock(self.state):
            self.assertIsNone(self.run_vault())
        self.assertEqual(len(list(self.requests.iterdir())), 1)

    def test_log_never_holds_note_names_or_text(self):
        self.request({"op": "append", "note": "study/dhcp.md", "text": "Private words."})
        self.request({"op": "append", "note": "../outside.md", "text": "x"})
        self.run_vault()
        raw = self.dirs.log.read_text()
        self.assertNotIn("Private words", raw)
        self.assertNotIn("dhcp", raw)
        self.assertNotIn("outside", raw)


ROOT = Path(__file__).resolve().parent.parent


def unit_lines(unit):
    return (ROOT / "systemd" / unit).read_text().splitlines()


def unit_paths(unit, key):
    out = set()
    for line in unit_lines(unit):
        if line.startswith(key + "="):
            out.update(line[len(key) + 1:].split())
    return out


class VaultUnitFileTest(unittest.TestCase):
    """B16: the vault writer has no network and no key, and writes only the vault."""
    U = "julz-vault.service"

    def test_binds(self):
        self.assertEqual(unit_paths(self.U, "BindPaths"),
                         {"%h/Documents/julz-mem", "%h/.local/share/julz/log",
                          "%h/.local/share/julz/vault"})
        self.assertEqual(unit_paths(self.U, "BindReadOnlyPaths"),
                         {"%h/.local/lib/julz", "%h/.gitconfig", "%h/.config/git"})
        lines = unit_lines(self.U)
        for line in ("TemporaryFileSystem=%h:ro", "PrivateNetwork=yes",
                     "RestrictAddressFamilies=AF_UNIX", "NoNewPrivileges=yes"):
            self.assertIn(line, lines)

    def test_path_unit_watches_the_requests(self):
        self.assertIn("PathChanged=%h/Documents/julz-mem/Inbox/.requests",
                      unit_lines("julz-vault.path"))


@unittest.skipUnless(shutil.which("systemd-run") and os.environ.get("XDG_RUNTIME_DIR"),
                     "needs a user systemd session")
class VaultRealSandboxTest(unittest.TestCase):
    """A probe under the sandbox lines of the real julz-vault.service: git commits work with
    my identity and hook, nothing else in home is reachable."""

    def test_walls_hold_and_git_works(self):
        probe = (
            "import socket, subprocess, sys\n"
            "from pathlib import Path\n"
            "home = Path(sys.argv[1])\n"
            "def can(f):\n"
            "    try: f(); return 'yes'\n"
            "    except OSError: return 'no'\n"
            "v = home / 'Documents/julz-mem'\n"
            "print('write-vault', can(lambda: open(v / 'study/new.md', 'w').write('# n\\n')))\n"
            "print('read-key', can(lambda: (home / '.config/julz/api.env').read_text()))\n"
            "print('write-gitconfig', can(lambda: open(home / '.gitconfig', 'a')))\n"
            "print('write-code', can(lambda: open(home / 'Projects/x', 'w')))\n"
            "print('inet', can(lambda: socket.socket(socket.AF_INET)))\n"
            "r = subprocess.run(['git', '-C', str(v), 'add', '-A'])\n"
            "r = subprocess.run(['git', '-C', str(v), 'commit', '-q', '-m', 'probe'])\n"
            "print('commit', 'yes' if r.returncode == 0 else 'no')\n"
            "print('hook-ran', 'yes' if (home / '.local/share/julz/log/hook').exists() else 'no')\n")
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".local/share/julz/log").mkdir(parents=True)
            (home / ".local/share/julz/vault").mkdir()
            cfg = home / ".config" / "julz"
            cfg.mkdir(parents=True)
            (cfg / "api.env").write_text("OPENWEBUI_API_KEY=fake\n")
            hooks = home / ".config" / "git" / "hooks"
            hooks.mkdir(parents=True)
            (hooks / "pre-commit").write_text(
                f"#!/bin/sh\ntouch {home}/.local/share/julz/log/hook\nexit 0\n")
            (hooks / "pre-commit").chmod(0o755)
            (home / ".gitconfig").write_text(
                f"[user]\n\tname = t\n\temail = t@example.invalid\n"
                f"[core]\n\thooksPath = {hooks}\n")
            v = home / "Documents" / "julz-mem"
            (v / "study").mkdir(parents=True)
            env = {**os.environ, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"}
            env.pop("GIT_CONFIG_GLOBAL", None)
            subprocess.run(["git", "-C", str(v), "init", "-q"], check=True, env=env)
            (home / "Projects").mkdir()
            argv = ["systemd-run", "--user", "--wait", "--pipe", "--quiet", "-E", f"HOME={home}"]
            for line in unit_lines("julz-vault.service"):
                key = line.split("=", 1)[0]
                if key in ("NoNewPrivileges", "ProtectSystem", "PrivateNetwork", "UMask",
                           "TemporaryFileSystem", "BindPaths", "BindReadOnlyPaths",
                           "RestrictAddressFamilies"):
                    line = line.replace("%h/.local/lib/julz", str(ROOT))
                    argv += ["-p", line.replace("%h", str(home))]
            r = subprocess.run(argv + [sys.executable, "-I", "-c", probe, str(home)],
                               capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
            got = dict(l.split() for l in r.stdout.splitlines() if len(l.split()) == 2)
            self.assertEqual(got, {"write-vault": "yes", "read-key": "no",
                                   "write-gitconfig": "no", "write-code": "no", "inet": "no",
                                   "commit": "yes", "hook-ran": "yes"}, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
