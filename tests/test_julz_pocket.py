"""Attack tests for tools/julz_pocket.py and pocket-open.py.
Run: python3 -m unittest discover -s tests -v"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from joserfc import jwe
from joserfc.jwk import OKPKey

ROOT = Path(__file__).resolve().parent.parent


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pocket = load("julz_pocket", "tools/julz_pocket.py")
opener = load("pocket_open", "pocket-open.py")

SECRET = "the router hint is blue-otter-42"


class PocketTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.key = OKPKey.generate_key("X25519")
        self.pub = base / "pocket.pub.jwk"
        self.pub.write_text(json.dumps(self.key.as_dict(private=False)))
        self.drops = base / "drop"
        self.drops.mkdir()
        self.out = base / "private" / "drops"
        self.out.parent.mkdir()
        self.log = base / "actions.log"
        os.environ.update(JULZ_POCKET_PUB=str(self.pub), JULZ_POCKET_DROP=str(self.drops),
                          JULZ_LOG=str(self.log))
        self.tool = pocket.Tools()

    def tearDown(self):
        self.tmp.cleanup()

    async def drop(self, title="router", text=SECRET):
        return await self.tool.pocket_drop(title, text)

    def drop_files(self):
        return sorted(self.drops.iterdir())

    # ---------- the tool side (container) ----------

    async def test_drop_is_encrypted_and_logged_without_content(self):
        self.assertIn("Stored", await self.drop())
        [f] = self.drop_files()
        self.assertEqual(oct(f.stat().st_mode & 0o777), "0o600")
        raw = f.read_text()
        self.assertNotIn("blue-otter", raw)
        self.assertNotIn("router", f.name)  # title never in the file name
        log = self.log.read_text()
        self.assertNotIn("blue-otter", log)
        self.assertNotIn("router", log)
        self.assertIn(f.name, log)

    async def test_tool_cannot_decrypt_its_own_drop(self):
        await self.drop()
        token = self.drop_files()[0].read_text()
        public_only = OKPKey.import_key(json.loads(self.pub.read_text()))
        with self.assertRaises(Exception):
            jwe.decrypt_compact(token, public_only)

    async def test_private_key_in_mount_is_refused(self):
        self.pub.write_text(json.dumps(self.key.as_dict(private=True)))
        self.assertIn("Refused", await self.drop())
        self.assertEqual(self.drop_files(), [])

    async def test_missing_key_is_refused(self):
        self.pub.unlink()
        self.assertIn("Refused", await self.drop())

    async def test_size_and_empty_limits(self):
        self.assertIn("Refused", await self.drop(text="x" * (pocket.MAX_TEXT_BYTES + 1)))
        self.assertIn("Refused", await self.drop(text="   "))
        self.assertEqual(self.drop_files(), [])

    async def test_rate_limit(self):
        for _ in range(pocket.MAX_DROPS_PER_MINUTE):
            self.assertIn("Stored", await self.drop())
        self.assertIn("Refused", await self.drop())

    # ---------- the opener side (host) ----------

    async def test_round_trip_removes_ciphertext(self):
        await self.drop(title="router admin hint")
        opened, problems = opener.open_drops(self.drops, self.out, self.key)
        self.assertEqual(problems, [])
        [out] = self.out.iterdir()
        self.assertEqual(out.name, opened[0])
        self.assertTrue(out.name.endswith("-router-admin-hint.md"))
        self.assertEqual(oct(out.stat().st_mode & 0o777), "0o600")
        self.assertIn(SECRET, out.read_text())
        self.assertEqual(self.drop_files(), [])

    async def test_wrong_key_keeps_drop(self):
        await self.drop()
        other = OKPKey.generate_key("X25519")
        opened, problems = opener.open_drops(self.drops, self.out, other)
        self.assertEqual(opened, [])
        self.assertEqual(len(problems), 1)
        self.assertEqual(len(self.drop_files()), 1)
        self.assertEqual(list(self.out.iterdir()), [])

    async def test_tampered_drop_is_rejected(self):
        await self.drop()
        [f] = self.drop_files()
        parts = f.read_text().split(".")
        ct = parts[3]
        parts[3] = ("A" if ct[0] != "A" else "B") + ct[1:]  # flip the first ciphertext char
        f.write_text(".".join(parts))
        opened, problems = opener.open_drops(self.drops, self.out, self.key)
        self.assertEqual(opened, [])
        self.assertIn("cannot decrypt", problems[0])

    async def test_forged_drop_with_valid_crypto_but_bad_payload(self):
        # Anyone with the public key can encrypt, so the content is untrusted too
        token = jwe.encrypt_compact(pocket.JWE_HEADER, b'["not", "a", "dict"]',
                                    OKPKey.import_key(self.key.as_dict(private=False)))
        (self.drops / "20261015T000000Z-deadbeef.jwe").write_text(token)
        opened, problems = opener.open_drops(self.drops, self.out, self.key)
        self.assertEqual(opened, [])
        self.assertEqual(len(problems), 1)

    async def test_hostile_title_stays_in_folder(self):
        await self.drop(title="../../../.bashrc\x00\nevil")
        opened, problems = opener.open_drops(self.drops, self.out, self.key)
        self.assertEqual(problems, [])
        [out] = self.out.iterdir()
        self.assertEqual(out.parent, self.out)
        self.assertNotIn("..", out.name)
        self.assertFalse((self.out.parent.parent / ".bashrc").exists())

    async def test_symlink_drop_is_not_followed(self):
        target = Path(self.tmp.name) / "host-file"
        target.write_text("host data")
        link = self.drops / "20261015T000000Z-deadbeef.jwe"
        link.symlink_to(target)
        opened, problems = opener.open_drops(self.drops, self.out, self.key)
        self.assertEqual(opened, [])
        self.assertIn("symlink", problems[0])
        self.assertTrue(link.is_symlink())
        self.assertEqual(target.read_text(), "host data")

    async def test_oversized_and_odd_names_left_alone(self):
        (self.drops / "20261015T000000Z-deadbeef.jwe").write_text("A" * (opener.MAX_DROP_BYTES + 1))
        (self.drops / "notes.txt").write_text("hello")
        opened, problems = opener.open_drops(self.drops, self.out, self.key)
        self.assertEqual(opened, [])
        self.assertEqual(len(problems), 2)
        self.assertEqual(len(self.drop_files()), 2)

    async def test_same_title_twice_does_not_overwrite(self):
        await self.drop(title="same", text="first")
        await self.drop(title="same", text="second")
        opened, _ = opener.open_drops(self.drops, self.out, self.key)
        self.assertEqual(len(opened), 2)
        texts = sorted(p.read_text() for p in self.out.iterdir())
        self.assertTrue(any("first" in t for t in texts) and any("second" in t for t in texts))

    def test_opener_refuses_unmounted_pocket(self):
        with self.assertRaises(SystemExit):
            opener.require_mount(Path(self.tmp.name))


if __name__ == "__main__":
    unittest.main()
