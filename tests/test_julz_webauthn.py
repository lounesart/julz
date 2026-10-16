"""Attack tests for julz_webauthn.py: approving from the phone, SECURITY.md threats 31 to 35, 42.
A software authenticator (P-256 key in memory) stands in for the phone. It builds the same
bytes a browser and passkey would, and each test bends one of them.
Run: python3 -m unittest discover -s tests -v"""
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fido2.cose import ES256
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import (AttestationObject, AttestedCredentialData, AuthenticatorData,
                            CollectedClientData)

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # julz_webauthn imports julz_gate


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT / file)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wa = load("julz_webauthn", "julz_webauthn.py")

HOST = "laptop.tail1234.ts.net"
ORIGIN = f"https://{HOST}:8443"
WEBUI_ORIGIN = f"https://{HOST}"  # Open WebUI on 443, same host name
SPEC = ("goal: add a usage line to the README\n"
        "project: julz-sandbox\n"
        "done_when: README has a Usage section\n")
OTHER_SPEC = SPEC.replace("usage line", "push step")
FLAG = AuthenticatorData.FLAG


class SoftKey:
    """A passkey in memory. Defaults behave like a phone with a fingerprint check."""

    def __init__(self, rp_id=HOST, counter=0):
        self.rp_id = rp_id
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.cred_id = os.urandom(16)
        self.counter = counter
        self.step = 0  # how much the counter grows per use; 0 like a synced passkey

    def flags(self, uv):
        return FLAG.UP | (FLAG.UV if uv else 0)

    def register(self, options, origin=ORIGIN, uv=True, kind="webauthn.create"):
        challenge = websafe_decode(options["publicKey"]["challenge"])
        cose = ES256.from_cryptography_key(self.key.public_key())
        cred = AttestedCredentialData.create(b"\0" * 16, self.cred_id, cose)
        auth = AuthenticatorData.create(hashlib.sha256(self.rp_id.encode()).digest(),
                                        self.flags(uv) | FLAG.AT, self.counter, cred)
        client = CollectedClientData.create(kind, challenge, origin)
        return {"id": websafe_encode(self.cred_id), "rawId": websafe_encode(self.cred_id),
                "type": "public-key",
                "response": {"clientDataJSON": client.b64,
                             "attestationObject": websafe_encode(
                                 AttestationObject.create("none", auth, {}))}}

    def sign(self, options, origin=ORIGIN, uv=True, kind="webauthn.get", challenge=None):
        challenge = challenge or websafe_decode(options["publicKey"]["challenge"])
        self.counter += self.step
        auth = AuthenticatorData.create(hashlib.sha256(self.rp_id.encode()).digest(),
                                        self.flags(uv), self.counter)
        client = CollectedClientData.create(kind, challenge, origin)
        sig = self.key.sign(bytes(auth) + client.hash, ec.ECDSA(hashes.SHA256()))
        return {"id": websafe_encode(self.cred_id), "rawId": websafe_encode(self.cred_id),
                "type": "public-key",
                "response": {"clientDataJSON": client.b64,
                             "authenticatorData": websafe_encode(auth),
                             "signature": websafe_encode(sig)}}


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.cred_file = base / "config" / "passkey.json"
        self.enroll_file = base / "state" / "enroll.json"
        self.clock = Clock()
        self.pk = wa.Passkeys(ORIGIN, self.cred_file, self.enroll_file, clock=self.clock)
        self.key = SoftKey()

    def tearDown(self):
        self.tmp.cleanup()

    def code(self):
        return wa.new_enroll_code(self.enroll_file, self.clock())

    def enroll(self, key=None):
        key = key or self.key
        options = self.pk.enroll_begin(self.code())
        return self.pk.enroll_complete(key.register(options))

    def refused(self, fn, *args):
        with self.assertRaises(wa.AuthError):
            fn(*args)


class OriginConfigTest(Base):
    """Threat 33: the approver may never share its origin with Open WebUI."""

    def test_good_origin(self):
        self.assertEqual(wa.check_origin(ORIGIN), HOST)

    def test_bad_origins_refused(self):
        for origin in (WEBUI_ORIGIN, f"https://{HOST}:443", f"http://{HOST}:8443",
                       f"{ORIGIN}/", f"{ORIGIN}/approve", f"https://{HOST.upper()}:8443",
                       f"https://user@{HOST}:8443", "https://:8443", f"https://{HOST}:99999"):
            with self.subTest(origin=origin):
                self.refused(wa.check_origin, origin)


class EnrollTest(Base):
    """Threat 35: only I can register a passkey, and only one."""

    def test_enroll_with_code_works(self):
        cred_id = self.enroll()
        self.assertEqual(cred_id, self.key.cred_id.hex())
        self.assertEqual(self.cred_file.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.enroll_file.exists())  # code spent

    def test_no_code_refused(self):
        self.refused(self.pk.enroll_begin, "0123456789")

    def test_wrong_code_refused_and_counts(self):
        self.code()
        self.refused(self.pk.enroll_begin, "0000000000")
        entry = json.loads(self.enroll_file.read_text())
        self.assertEqual(entry["tries_left"], wa.ENROLL_TRIES - 1)

    def test_code_dies_after_tries(self):
        code = self.code()
        for _ in range(wa.ENROLL_TRIES):
            self.refused(self.pk.enroll_begin, "0000000000")
        self.refused(self.pk.enroll_begin, code)  # even the right one, now

    def test_expired_code_refused(self):
        code = self.code()
        self.clock.now += wa.ENROLL_TTL + 1
        self.refused(self.pk.enroll_begin, code)

    def test_code_single_use(self):
        code = self.code()
        self.pk.enroll_begin(code)
        self.refused(self.pk.enroll_begin, code)

    def test_code_stored_as_hash_only(self):
        code = self.code()
        self.assertNotIn(code, self.enroll_file.read_text())

    def test_second_passkey_refused(self):
        self.enroll()
        self.refused(self.pk.enroll_begin, self.code())
        # even if the check before it is skipped, the file write refuses to replace
        other = SoftKey()
        with self.assertRaises(wa.AuthError):
            wa.save_credential(self.cred_file, AttestedCredentialData.create(
                b"\0" * 16, other.cred_id, ES256.from_cryptography_key(other.key.public_key())),
                0, new=True)
        cred, _ = wa.load_credential(self.cred_file)
        self.assertEqual(cred.credential_id, self.key.cred_id)

    def test_enroll_without_fingerprint_refused(self):
        options = self.pk.enroll_begin(self.code())
        self.refused(self.pk.enroll_complete, self.key.register(options, uv=False))
        self.assertFalse(self.cred_file.exists())

    def test_enroll_from_webui_origin_refused(self):
        options = self.pk.enroll_begin(self.code())
        self.refused(self.pk.enroll_complete, self.key.register(options, origin=WEBUI_ORIGIN))
        self.assertFalse(self.cred_file.exists())

    def test_enroll_complete_single_use(self):
        options = self.pk.enroll_begin(self.code())
        response = self.key.register(options)
        self.pk.enroll_complete(response)
        self.cred_file.unlink()
        self.refused(self.pk.enroll_complete, response)

    def test_enroll_too_late_refused(self):
        options = self.pk.enroll_begin(self.code())
        self.clock.now += wa.CHALLENGE_TTL + 1
        self.refused(self.pk.enroll_complete, self.key.register(options))

    def test_credential_file_open_to_others_refused(self):
        self.enroll()
        self.cred_file.chmod(0o644)
        with self.assertRaises(wa.gate.GateError):
            self.pk.begin("approve", SPEC)

    def test_credential_symlink_refused(self):
        self.enroll()
        real = self.cred_file.with_name("real.json")
        self.cred_file.rename(real)
        self.cred_file.symlink_to(real)
        with self.assertRaises(wa.gate.GateError):
            self.pk.begin("approve", SPEC)


class ApproveTest(Base):
    """Threat 31: only an assertion from my passkey approves. Threat 32: it approves one
    action on one text, once."""

    def setUp(self):
        super().setUp()
        self.enroll()

    def test_good_assertion_returns_signed_text(self):
        nonce, options = self.pk.begin("approve", SPEC)
        self.assertEqual(self.pk.finish(nonce, "approve", self.key.sign(options)), SPEC)

    def test_challenge_binds_action_and_text(self):
        _, options = self.pk.begin("approve", SPEC)
        challenge = websafe_decode(options["publicKey"]["challenge"])
        self.assertEqual(challenge[:32], wa.bind("approve", SPEC))
        self.assertEqual(len(challenge), 64)

    def test_no_passkey_no_begin(self):
        wa.revoke(self.cred_file)
        self.refused(self.pk.begin, "approve", SPEC)

    def test_no_assertion_refused(self):
        nonce, _ = self.pk.begin("approve", SPEC)
        self.refused(self.pk.finish, nonce, "approve", {})

    def test_other_key_refused(self):
        nonce, options = self.pk.begin("approve", SPEC)
        intruder = SoftKey()
        intruder.cred_id = self.key.cred_id  # same id, different key
        self.refused(self.pk.finish, nonce, "approve", intruder.sign(options))
        nonce, options = self.pk.begin("approve", SPEC)
        self.refused(self.pk.finish, nonce, "approve", SoftKey().sign(options))

    def test_bad_signature_refused(self):
        nonce, options = self.pk.begin("approve", SPEC)
        response = self.key.sign(options)
        sig = bytearray(websafe_decode(response["response"]["signature"]))
        sig[-1] ^= 1
        response["response"]["signature"] = websafe_encode(bytes(sig))
        self.refused(self.pk.finish, nonce, "approve", response)

    def test_without_fingerprint_refused(self):
        nonce, options = self.pk.begin("approve", SPEC)
        self.refused(self.pk.finish, nonce, "approve", self.key.sign(options, uv=False))

    def test_replay_refused(self):
        nonce, options = self.pk.begin("approve", SPEC)
        response = self.key.sign(options)
        self.pk.finish(nonce, "approve", response)
        self.refused(self.pk.finish, nonce, "approve", response)

    def test_failed_try_spends_challenge(self):
        nonce, options = self.pk.begin("approve", SPEC)
        self.refused(self.pk.finish, nonce, "approve", self.key.sign(options, uv=False))
        self.refused(self.pk.finish, nonce, "approve", self.key.sign(options))

    def test_assertion_for_other_spec_refused(self):
        nonce_a, options_a = self.pk.begin("approve", SPEC)
        nonce_b, _ = self.pk.begin("approve", OTHER_SPEC)
        self.refused(self.pk.finish, nonce_b, "approve", self.key.sign(options_a))

    def test_reject_signature_cannot_approve(self):
        nonce, options = self.pk.begin("reject", SPEC)
        self.refused(self.pk.finish, nonce, "approve", self.key.sign(options))

    def test_forged_challenge_refused(self):
        # A client that signs its own challenge for a real nonce gets nothing
        nonce, options = self.pk.begin("approve", SPEC)
        fake = wa.bind("approve", OTHER_SPEC) + bytes.fromhex(nonce)
        self.refused(self.pk.finish, nonce, "approve", self.key.sign(options, challenge=fake))

    def test_expired_refused(self):
        nonce, options = self.pk.begin("approve", SPEC)
        self.clock.now += wa.CHALLENGE_TTL + 1
        self.refused(self.pk.finish, nonce, "approve", self.key.sign(options))

    def test_unknown_nonce_refused(self):
        _, options = self.pk.begin("approve", SPEC)
        self.refused(self.pk.finish, "00" * 32, "approve", self.key.sign(options))

    def test_unknown_action_refused(self):
        self.refused(self.pk.begin, "run-as-root", SPEC)

    def test_flood_keeps_newest_working(self):
        for _ in range(wa.MAX_PENDING * 3):
            self.pk.begin("approve", OTHER_SPEC)
        self.assertLessEqual(len(self.pk.pending), wa.MAX_PENDING)
        nonce, options = self.pk.begin("approve", SPEC)
        self.assertEqual(self.pk.finish(nonce, "approve", self.key.sign(options)), SPEC)

    def test_revoked_passkey_refused(self):
        nonce, options = self.pk.begin("approve", SPEC)
        self.assertTrue(wa.revoke(self.cred_file))
        self.refused(self.pk.finish, nonce, "approve", self.key.sign(options))


class OriginBindingTest(Base):
    """Threat 33: a passkey prompt raised by Open WebUI's page must never approve."""

    def setUp(self):
        super().setUp()
        self.enroll()

    def test_webui_origin_refused(self):
        for origin in (WEBUI_ORIGIN, f"https://{HOST}:443", f"https://{HOST}:8444",
                       f"https://evil.{HOST}:8443", "https://evil.example:8443"):
            with self.subTest(origin=origin):
                nonce, options = self.pk.begin("approve", SPEC)
                self.refused(self.pk.finish, nonce, "approve",
                             self.key.sign(options, origin=origin))

    def test_create_type_refused(self):
        nonce, options = self.pk.begin("approve", SPEC)
        self.refused(self.pk.finish, nonce, "approve",
                     self.key.sign(options, kind="webauthn.create"))

    def test_other_rp_id_refused(self):
        nonce, options = self.pk.begin("approve", SPEC)
        other = SoftKey(rp_id="evil.example")
        other.key, other.cred_id = self.key.key, self.key.cred_id
        self.refused(self.pk.finish, nonce, "approve", other.sign(options))


class CounterTest(Base):
    """A counter that is used must go up; a step back means a cloned key."""

    def setUp(self):
        super().setUp()
        self.enroll()

    def approve(self):
        nonce, options = self.pk.begin("approve", SPEC)
        return self.pk.finish(nonce, "approve", self.key.sign(options))

    def test_zero_counter_always_ok(self):
        # Google Password Manager passkeys send 0 every time
        self.approve()
        self.approve()

    def test_rising_counter_saved(self):
        self.key.step = 1
        self.approve()
        self.approve()
        self.assertEqual(wa.load_credential(self.cred_file)[1], 2)

    def test_counter_going_back_refused(self):
        self.key.step = 5
        self.approve()
        self.key.counter = 1
        self.key.step = 0
        self.refused(self.approve)


if __name__ == "__main__":
    unittest.main()
