"""Tests for julz-ntfy.py: the self hosted push server for the phone app, SECURITY.md 86, 87.
Nothing here starts ntfy: exec is faked, the binary is a few bytes with a patched hash.
Run: python3 -m unittest discover -s tests -v"""
import hashlib
import io
import os
import stat
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from test_julz_notify import load

ntfy = load("julz_ntfy", "julz-ntfy.py")
gate = ntfy.gate
ROOT = Path(__file__).resolve().parent.parent

TOPIC = "julz-" + "a" * 32
HASH_A = "$2a$10$" + "A" * 53
HASH_B = "$2a$10$" + "B" * 53
TOKEN_A = "tk_" + "a" * 29
TOKEN_B = "tk_" + "b" * 29
AUTH = (f"NOTIFY_HASH={HASH_A}\nNOTIFY_TOKEN={TOKEN_A}\n"
        f"PHONE_HASH={HASH_B}\nPHONE_TOKEN={TOKEN_B}\n")
BINARY = b"\x7fELF fake ntfy"


def write(path: Path, text: str, mode=0o600) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(mode)
    return path


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.auth = write(self.base / "ntfy" / "auth.env", AUTH)
        self.topic = write(self.base / "notify" / "ntfy.env", f"NTFY_TOPIC={TOPIC}\n")
        self.bin_dir = self.base / "lib"
        self.bin_dir.mkdir()
        self.binary = self.bin_dir / f"ntfy-{ntfy.VERSION}"
        self.binary.write_bytes(BINARY)
        self.binary.chmod(0o755)
        self.old = (ntfy.BINARY_SHA256, ntfy.TARBALL_SHA256)
        ntfy.BINARY_SHA256 = hashlib.sha256(BINARY).hexdigest()

    def tearDown(self):
        ntfy.BINARY_SHA256, ntfy.TARBALL_SHA256 = self.old
        self.tmp.cleanup()


class ServeTest(Base):
    def serve(self):
        calls = []
        ntfy.serve(self.bin_dir, self.base / "state", self.auth, self.topic,
                   execve=lambda *a: calls.append(a))
        return calls

    def test_flags_keep_the_server_closed(self):
        args = ntfy.serve_args(self.binary, self.base / "state")
        flags = dict(zip(args[2::2], args[3::2]))
        self.assertEqual(args[:2], [str(self.binary), "serve"])
        self.assertEqual(flags["--listen-http"], "127.0.0.1:8090")  # never every interface (87)
        self.assertEqual(flags["--auth-default-access"], "deny-all")  # no token, no access (86)
        self.assertEqual(flags["--web-root"], "disable")
        self.assertEqual(flags["--cache-duration"], "48h")  # missed notices catch up (92)
        for off in ("--enable-signup", "--enable-login", "--enable-reservations",
                    "--attachment-cache-dir", "--behind-proxy", "--upstream-base-url",
                    "--base-url", "--enable-metrics"):
            self.assertNotIn(off, args, off)

    def test_also_listens_on_a_private_socket(self):
        # 132: the notify units have no internet sockets, they post here
        args = ntfy.serve_args(self.binary, self.base / "state")
        flags = dict(zip(args[2::2], args[3::2]))
        self.assertEqual(flags["--listen-unix"], f"/run/user/{os.getuid()}/julz-push/ntfy.sock")
        self.assertEqual(flags["--listen-unix-mode"], "0600")
        self.assertFalse(flags["--listen-unix"].startswith(str(self.base / "state")))

    def test_access_is_write_only_and_read_only_on_one_topic(self):
        env = ntfy.serve_env(ntfy.read_auth(self.auth), TOPIC)
        self.assertEqual(env["NTFY_AUTH_ACCESS"], f"notify:{TOPIC}:wo,phone:{TOPIC}:ro")
        self.assertEqual(env["NTFY_AUTH_USERS"], f"notify:{HASH_A}:user,phone:{HASH_B}:user")
        self.assertEqual(env["NTFY_AUTH_TOKENS"], f"notify:{TOKEN_A},phone:{TOKEN_B}")
        self.assertNotIn("admin", ",".join(env.values()))

    def test_starts_with_tokens_in_the_environment_only(self):
        (path, args, env), = self.serve()
        self.assertEqual(path, str(self.binary))
        self.assertNotIn(TOKEN_A, " ".join(args))  # the command line is readable by every process
        self.assertIn(TOKEN_A, env["NTFY_AUTH_TOKENS"])
        self.assertEqual(set(env), {"NTFY_AUTH_USERS", "NTFY_AUTH_ACCESS", "NTFY_AUTH_TOKENS"})
        self.assertEqual(stat.S_IMODE((self.base / "state").stat().st_mode), 0o700)

    def test_a_changed_binary_never_starts(self):
        self.binary.write_bytes(BINARY + b"x")
        with self.assertRaises(gate.GateError):
            self.serve()

    def test_a_linked_binary_never_starts(self):
        real = self.base / "real"
        self.binary.rename(real)
        self.binary.symlink_to(real)
        with self.assertRaises(gate.GateError):
            self.serve()

    def test_auth_file_refusals(self):
        cases = {
            "open to others": (AUTH, 0o644),
            "missing key": (AUTH.replace(f"PHONE_TOKEN={TOKEN_B}\n", ""), 0o600),
            "extra key": (AUTH + "ADMIN_TOKEN=" + TOKEN_A + "\n", 0o600),
            "bad token": (AUTH.replace(TOKEN_B, "tk_short"), 0o600),
            "token with a comma": (AUTH.replace(TOKEN_B, "tk_" + "b" * 28 + ","), 0o600),
            "bad hash": (AUTH.replace(HASH_B, "plain-password"), 0o600),
            "same token twice": (AUTH.replace(TOKEN_B, TOKEN_A), 0o600),
        }
        for name, (text, mode) in cases.items():
            write(self.auth, text, mode)
            with self.assertRaises(gate.GateError, msg=name):
                self.serve()

    def test_linked_auth_file_refused(self):
        real = write(self.base / "elsewhere.env", AUTH)
        self.auth.unlink()
        self.auth.symlink_to(real)
        with self.assertRaises(gate.GateError):
            self.serve()

    def test_auth_file_that_is_a_folder_refused(self):
        # mode 700 passes the mode check: only the regular file check stops it
        self.auth.unlink()
        self.auth.mkdir(mode=0o700)
        with self.assertRaises(gate.GateError):
            self.serve()

    def test_bad_topic_refused(self):
        write(self.topic, "NTFY_TOPIC=julz-*\n")
        with self.assertRaises(gate.GateError):
            self.serve()


class InstallTest(Base):
    def tarball(self, members: dict, links=()) -> Path:
        path = self.base / ntfy.TARBALL
        with tarfile.open(path, "w:gz") as tar:
            for name, data in members.items():
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
            for name, target in links:
                info = tarfile.TarInfo(name)
                info.type = tarfile.SYMTYPE
                info.linkname = target
                tar.addfile(info)
        ntfy.TARBALL_SHA256 = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def test_installs_only_the_binary(self):
        self.binary.unlink()
        tb = self.tarball({ntfy.MEMBER: BINARY, "ntfy_x/../../evil": b"x", "README.md": b"r"})
        out = ntfy.install(tb, self.bin_dir)
        self.assertEqual(out, self.binary)
        self.assertEqual(self.binary.read_bytes(), BINARY)
        self.assertEqual(stat.S_IMODE(self.binary.stat().st_mode), 0o755)
        self.assertEqual(sorted(p.name for p in self.bin_dir.iterdir()), [self.binary.name])
        self.assertFalse((self.base / "evil").exists())

    def test_tarball_with_another_hash_refused(self):
        tb = self.tarball({ntfy.MEMBER: BINARY})
        ntfy.TARBALL_SHA256 = "0" * 64
        with self.assertRaises(gate.GateError):
            ntfy.install(tb, self.bin_dir)

    def test_binary_with_another_hash_refused(self):
        self.binary.unlink()
        tb = self.tarball({ntfy.MEMBER: BINARY + b"changed"})
        with self.assertRaises(gate.GateError):
            ntfy.install(tb, self.bin_dir)
        self.assertFalse(self.binary.exists())

    def test_binary_as_a_link_refused(self):
        tb = self.tarball({}, links=[(ntfy.MEMBER, "/usr/bin/sh")])
        with self.assertRaises(gate.GateError):
            ntfy.install(tb, self.bin_dir)


class SetupTest(Base):
    def setUp(self):
        super().setUp()
        self.auth.unlink()
        self.local = self.base / "notify" / "local.env"
        self.phone = self.base / "ntfy" / "phone-token"
        self.hashes = iter([HASH_A, HASH_B])
        self.tokens = iter([TOKEN_A, TOKEN_B])
        self.shown = []

    def setup_(self):
        ntfy.setup(self.auth, self.local, self.phone, hasher=lambda pw: next(self.hashes),
                   tokener=lambda: next(self.tokens), out=self.shown.append)

    def test_writes_private_files_and_never_prints_a_token(self):
        self.setup_()
        self.assertEqual(ntfy.read_auth(self.auth)["NOTIFY_TOKEN"], TOKEN_A)
        for f in (self.auth, self.local, self.phone):
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600, f.name)
        self.assertIn(f"NTFY_TOKEN={TOKEN_A}", self.local.read_text())
        self.assertNotIn(TOKEN_B, self.local.read_text())  # julz-notify never holds the phone token
        self.assertEqual(self.phone.read_text().strip(), TOKEN_B)
        shown = "\n".join(self.shown)
        self.assertNotIn(TOKEN_A, shown)  # output may land in a terminal log or a chat
        self.assertNotIn(TOKEN_B, shown)
        self.assertIn(str(self.phone), shown)
        self.assertNotIn(TOKEN_B, self.topic.read_text())

    def test_never_overwrites(self):
        self.setup_()
        before = self.auth.read_text()
        with self.assertRaises(gate.GateError):
            ntfy.setup(self.auth, self.local, self.phone, hasher=lambda pw: HASH_B,
                       tokener=lambda: TOKEN_B, out=self.shown.append)
        self.assertEqual(self.auth.read_text(), before)

    def test_bad_token_from_the_generator_refused(self):
        self.tokens = iter(["tk_bad", TOKEN_B])
        with self.assertRaises(gate.GateError):
            self.setup_()
        self.assertFalse(self.auth.exists())


class RotatePhoneTest(SetupTest):
    """Threat 88: a lost phone's token is revoked by giving the phone a new one."""
    TOKEN_C = "tk_" + "c" * 29

    def rotate(self, token=None):
        ntfy.rotate_phone(self.auth, self.phone, tokener=lambda: token or self.TOKEN_C,
                          out=self.shown.append)

    def test_only_the_phone_token_changes(self):
        self.setup_()
        before = ntfy.read_auth(self.auth)
        self.rotate()
        after = ntfy.read_auth(self.auth)
        self.assertEqual(after["PHONE_TOKEN"], self.TOKEN_C)
        for key in ("NOTIFY_HASH", "NOTIFY_TOKEN", "PHONE_HASH"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(self.phone.read_text().strip(), self.TOKEN_C)
        for f in (self.auth, self.phone):
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
        shown = "\n".join(self.shown)
        self.assertNotIn(self.TOKEN_C, shown)
        self.assertNotIn(TOKEN_B, shown)
        self.assertIn("restart", shown)

    def test_a_bad_or_reused_token_changes_nothing(self):
        self.setup_()
        before = (self.auth.read_text(), self.phone.read_text())
        for bad in ("tk_short", TOKEN_A, TOKEN_B):  # malformed, the notify token, the old one
            with self.assertRaises(gate.GateError, msg=bad):
                self.rotate(bad)
        self.assertEqual((self.auth.read_text(), self.phone.read_text()), before)

    def test_needs_a_setup_first(self):
        with self.assertRaises(gate.GateError):
            self.rotate()


class UnitTest(unittest.TestCase):
    def test_runs_as_the_unit_runs_it(self):
        # the unit starts it with python3 -I, which leaves its own folder off the import path
        import subprocess
        r = subprocess.run([sys.executable, "-I", str(ROOT / "julz-ntfy.py"), "--no-such-mode"],
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertNotIn("Traceback", r.stderr)

    def test_unit_is_sandboxed(self):
        text = (ROOT / "systemd" / "julz-ntfy.service").read_text()
        for line in ("NoNewPrivileges=yes", "ProtectSystem=strict", "PrivateTmp=yes",
                     "TemporaryFileSystem=%h:ro", "UMask=0077", "CapabilityBoundingSet=",
                     "MemoryMax=", "RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX"):
            self.assertIn(line, text, line)
        settings = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
        self.assertNotIn("Documents", settings)  # no vault, no notes
        self.assertNotIn(".config/julz/approver", settings)  # no passkey state
        self.assertNotIn("claude", settings.lower())  # no Claude token


if __name__ == "__main__":
    unittest.main()
