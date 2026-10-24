"""The Julz device key: approving natively in the phone app. SECURITY.md threats 107 to 110.
The phone is played by `cryptography`: an EC P-256 key signing SHA256withECDSA, as the
Android keystore does. Run: python3 -m unittest discover -s tests -v"""
import base64
import json
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa

from test_julz_notify import load

dk = load("julz_devicekey", "julz_devicekey.py")
wa = dk.wa  # the same module object, so AuthError is the same class


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class Phone:
    """A device key as the app holds it."""

    def __init__(self, curve=ec.SECP256R1()):
        self.key = ec.generate_private_key(curve)

    def public(self) -> str:
        der = self.key.public_key().public_bytes(serialization.Encoding.DER,
                                                 serialization.PublicFormat.SubjectPublicKeyInfo)
        return base64.b64encode(der).decode()

    def sign(self, begun: dict) -> str:
        data = dk.payload(begun["action"], begun["text"], begun["nonce"])
        return base64.b64encode(self.key.sign(data, ec.ECDSA(hashes.SHA256()))).decode()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.clock = Clock()
        self.enroll_file = base / "enroll.json"
        self.keys = dk.DeviceKeys(base / "device.json", self.enroll_file, clock=self.clock)
        self.phone = Phone()

    def tearDown(self):
        self.tmp.cleanup()

    def code(self):
        return wa.new_enroll_code(self.enroll_file, self.clock())

    def enroll(self, phone=None):
        return self.keys.enroll(self.code(), (phone or self.phone).public())


class EnrollTest(Base):
    """Threat 108: only with a fresh code from my terminal, one device at a time."""

    def test_a_good_code_enrolls_and_both_sides_show_one_fingerprint(self):
        shown_on_phone = self.enroll()
        self.assertRegex(shown_on_phone, r"^[0-9a-f]{4}(-[0-9a-f]{4}){3}$")
        self.assertEqual(self.keys.fingerprint(), shown_on_phone)  # what --device prints

    def test_no_wrong_or_used_code_refused(self):
        with self.assertRaises(wa.AuthError):
            self.keys.enroll("abc", self.phone.public())  # no code made yet
        code = self.code()
        with self.assertRaises(wa.AuthError):
            self.keys.enroll("0000000000", self.phone.public())
        self.keys.enroll(code, self.phone.public())
        with self.assertRaises(wa.AuthError):
            self.keys.enroll(code, Phone().public())  # spent

    def test_an_expired_code_refused(self):
        code = self.code()
        self.clock.t += wa.ENROLL_TTL + 1
        with self.assertRaises(wa.AuthError):
            self.keys.enroll(code, self.phone.public())
        self.assertIsNone(self.keys.fingerprint())

    def test_a_new_enrollment_replaces_the_old_key(self):
        self.enroll()
        second = Phone()
        self.enroll(second)
        begun = self.keys.begin("approve", "goal: x\n")
        with self.assertRaises(wa.AuthError):
            self.keys.finish(begun["nonce"], "approve", self.phone.sign(begun))  # old phone
        begun = self.keys.begin("approve", "goal: x\n")
        self.assertEqual(self.keys.finish(begun["nonce"], "approve", second.sign(begun)), "goal: x\n")

    def test_only_p256_keys(self):
        others = [ec.generate_private_key(ec.SECP384R1()).public_key(),
                  ed25519.Ed25519PrivateKey.generate().public_key(),
                  rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()]
        for pub in others:
            der = pub.public_bytes(serialization.Encoding.DER,
                                   serialization.PublicFormat.SubjectPublicKeyInfo)
            with self.subTest(key=type(pub).__name__):
                with self.assertRaises(wa.AuthError):
                    self.keys.enroll(self.code(), base64.b64encode(der).decode())
        for junk in ("", "not base64!", base64.b64encode(b"x" * 91).decode(), None, 5):
            with self.subTest(junk=junk):
                with self.assertRaises(wa.AuthError):
                    self.keys.enroll(self.code(), junk)
        self.assertIsNone(self.keys.fingerprint())

    def test_revoke_leaves_no_key(self):
        self.enroll()
        self.assertTrue(dk.revoke(self.keys.device_file))
        self.assertIsNone(self.keys.fingerprint())
        with self.assertRaises(wa.AuthError):
            self.keys.begin("approve", "goal: x\n")

    def test_the_key_file_is_private(self):
        self.enroll()
        self.assertEqual(self.keys.device_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(set(json.loads(self.keys.device_file.read_text())), {"public_key"})


class SignTest(Base):
    """Threat 107: the gate obeys a device signature only over its own text, action and nonce."""

    def setUp(self):
        super().setUp()
        self.enroll()
        self.text = "goal: add a usage line\nproject: julz-sandbox\ndone_when: README has Usage\n"

    def test_a_good_signature_returns_the_text_once(self):
        begun = self.keys.begin("approve", self.text)
        self.assertEqual(begun["text"], self.text)  # the app shows exactly this (109)
        sig = self.phone.sign(begun)
        self.assertEqual(self.keys.finish(begun["nonce"], "approve", sig), self.text)
        with self.assertRaises(wa.AuthError):
            self.keys.finish(begun["nonce"], "approve", sig)  # single use

    def test_signed_over_something_else_refused(self):
        for change in ("text", "action", "nonce"):
            with self.subTest(change=change):
                begun = self.keys.begin("approve", self.text)
                other = dict(begun)
                if change == "text":
                    other["text"] = self.text.replace("usage", "delete")
                elif change == "action":
                    other["action"] = "reject"
                else:
                    other["nonce"] = "00" * 32
                with self.assertRaises(wa.AuthError):
                    self.keys.finish(begun["nonce"], "approve", self.phone.sign(other))

    def test_finishing_as_another_action_refused(self):
        begun = self.keys.begin("reject", self.text)
        with self.assertRaises(wa.AuthError):
            self.keys.finish(begun["nonce"], "approve", self.phone.sign({**begun, "action": "approve"}))

    def test_expired_and_unknown_nonces_refused(self):
        begun = self.keys.begin("approve", self.text)
        self.clock.t += wa.CHALLENGE_TTL + 1
        with self.assertRaises(wa.AuthError):
            self.keys.finish(begun["nonce"], "approve", self.phone.sign(begun))
        with self.assertRaises(wa.AuthError):
            self.keys.finish("ab" * 32, "approve", "AAAA")

    def test_another_key_garbage_and_missing_signatures_refused(self):
        for sig in (Phone().sign, lambda b: "", lambda b: "!!", lambda b: None, lambda b: 5,
                    lambda b: base64.b64encode(b"\x30\x06\x02\x01\x01\x02\x01\x01").decode()):
            begun = self.keys.begin("approve", self.text)
            with self.subTest(sig=sig):
                with self.assertRaises(wa.AuthError):
                    self.keys.finish(begun["nonce"], "approve", sig(begun))

    def test_unknown_actions_refused(self):
        with self.assertRaises(wa.AuthError):
            self.keys.begin("rm -rf", self.text)

    def test_the_payload_binds_action_text_and_nonce(self):
        n = "11" * 32
        p = dk.payload("approve", self.text, n)
        self.assertTrue(p.startswith(b"julz-device-v1\0"))
        self.assertEqual(p, b"julz-device-v1\0" + wa.bind("approve", self.text) + bytes.fromhex(n))
        with self.assertRaises(ValueError):
            dk.payload("approve", self.text, "not hex")

    def test_a_flood_of_begins_only_pushes_out_old_nonces(self):
        first = self.keys.begin("approve", self.text)
        for _ in range(wa.MAX_PENDING):
            self.keys.begin("approve", self.text)
        with self.assertRaises(wa.AuthError):
            self.keys.finish(first["nonce"], "approve", self.phone.sign(first))


if __name__ == "__main__":
    unittest.main()
