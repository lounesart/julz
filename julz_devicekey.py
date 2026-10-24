"""The Julz device key: approving natively in the phone app. SECURITY.md threats 107 to 110.

Pure logic, no HTTP, beside julz_webauthn.py, whose rules it shares:
- the key is made in the phone's hardware keystore, behind a strong fingerprint for each use;
  this side only ever sees its public half, an EC P-256 key (107)
- enrolling needs the same one time code from my terminal as a passkey; one device at a
  time, a new enrollment replaces the old key (108)
- a signature covers `julz-device-v1`, the action, the hash of the exact text the server
  built and a single use nonce of 2 minutes; the text is kept here and returned, so the
  caller acts on exactly that (107, 109)
Signatures are checked with `cryptography`; no crypto of our own (A02).
"""
import base64
import binascii
import hashlib
import json
import secrets
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

import julz_webauthn as wa

DOMAIN = b"julz-device-v1\0"
MAX_KEY_CHARS = 400  # a P-256 SubjectPublicKeyInfo is 91 bytes, 124 in base64
MAX_SIG_CHARS = 200  # a DER ECDSA P-256 signature is at most 72 bytes


def payload(action: str, text: str, nonce: str) -> bytes:
    """What the phone signs: the domain, the action and text (as for passkeys) and the nonce."""
    return DOMAIN + wa.bind(action, text) + bytes.fromhex(nonce)


def fingerprint_of(der: bytes) -> str:
    """Shown on the phone and printed by --device, to compare after enrolling (108)."""
    h = hashlib.sha256(der).hexdigest()[:16]
    return "-".join(h[i:i + 4] for i in range(0, 16, 4))


def parse_public_key(value) -> tuple[ec.EllipticCurvePublicKey, bytes]:
    """A base64 SubjectPublicKeyInfo of an EC P-256 key, or AuthError."""
    if not isinstance(value, str) or not value or len(value) > MAX_KEY_CHARS:
        raise wa.AuthError("device key missing or too long")
    try:
        der = base64.b64decode(value, validate=True)
        key = serialization.load_der_public_key(der)
    except (binascii.Error, ValueError, TypeError):
        raise wa.AuthError("device key is not a public key") from None
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise wa.AuthError("device key must be EC P-256")
    # Stored in one canonical form, so the fingerprint is the same on both sides
    der = key.public_bytes(serialization.Encoding.DER,
                           serialization.PublicFormat.SubjectPublicKeyInfo)
    return key, der


def revoke(path: Path) -> bool:
    """--revoke-device: forget the enrolled key. True if there was one."""
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return False


class DeviceKeys:
    """One enrolled device key. Nonces live in this process only, like passkey challenges."""

    def __init__(self, device_file: Path, enroll_file: Path, clock=time.time):
        self.device_file = Path(device_file)
        self.enroll_file = Path(enroll_file)
        self.clock = clock
        self.pending: dict[str, dict] = {}

    def _key(self) -> tuple[ec.EllipticCurvePublicKey, bytes] | None:
        try:
            data = json.loads(wa.gate.read_private_file(self.device_file, 0o077))
        except wa.gate.GateError:
            return None
        except ValueError:
            raise wa.AuthError("device key file is broken: --revoke-device and enroll again") from None
        return parse_public_key(data.get("public_key") if isinstance(data, dict) else None)

    def fingerprint(self) -> str | None:
        found = self._key()
        return fingerprint_of(found[1]) if found else None

    def enroll(self, code, public_key) -> str:
        """Check the key, spend the code, store the key in place of any old one (108)."""
        _, der = parse_public_key(public_key)
        wa.use_enroll_code(self.enroll_file, code, self.clock())
        wa.write_private(self.device_file, {"public_key": base64.b64encode(der).decode()},
                         replace=True)
        return fingerprint_of(der)

    def begin(self, action: str, text: str) -> dict:
        """Start one signed action on one exact text. The app shows `text` whole (109)."""
        if action not in wa.ACTIONS:
            raise wa.AuthError(f"unknown action {action[:20]!r}")
        if self._key() is None:
            raise wa.AuthError("no device key enrolled")
        now = self.clock()
        self.pending = {k: v for k, v in self.pending.items() if v["expires"] >= now}
        while len(self.pending) >= wa.MAX_PENDING:
            self.pending.pop(next(iter(self.pending)))
        nonce = secrets.token_bytes(32).hex()
        self.pending[nonce] = {"action": action, "text": text, "expires": now + wa.CHALLENGE_TTL}
        return {"nonce": nonce, "action": action, "text": text}

    def finish(self, nonce, action, signature) -> str:
        """Check the signature. Returns the exact text that was signed, or raises AuthError."""
        entry = self.pending.pop(str(nonce), None)  # single use, even if it fails below
        if entry is None:
            raise wa.AuthError("unknown or used nonce")
        if self.clock() > entry["expires"]:
            raise wa.AuthError("nonce expired")
        if action != entry["action"]:
            raise wa.AuthError("signed for a different action")
        found = self._key()
        if found is None:
            raise wa.AuthError("no device key enrolled")
        if not isinstance(signature, str) or not signature or len(signature) > MAX_SIG_CHARS:
            raise wa.AuthError("signature missing or too long")
        try:
            sig = base64.b64decode(signature, validate=True)
            found[0].verify(sig, payload(entry["action"], entry["text"], str(nonce)),
                            ec.ECDSA(hashes.SHA256()))
        except (binascii.Error, ValueError, InvalidSignature):
            raise wa.AuthError("device signature refused") from None
        return entry["text"]
