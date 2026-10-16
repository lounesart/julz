"""Passkey checks for approving from the phone. SECURITY.md threats 31 to 35 and 42.

Pure logic, no HTTP: julz-approve-web.py serves the page and calls this.
- the container shares the host network, so it can reach the approver: a request arriving
  proves nothing, only an assertion from the one registered passkey does (threat 31)
- the challenge is sha256(action, text) plus a random nonce, single use, 2 minutes; the text
  that was signed is kept here and returned, so the caller stores exactly that (threat 32)
- the origin must match exactly, port included. fido2's default check compares only the host
  name, and Open WebUI runs on the same name on 443, so its page could ask for my passkey
  with a challenge of its own (threat 33)
- enrollment needs a one time code printed in my terminal, and only one passkey may exist (35)
Uses python-fido2 from Arch extra; no crypto of our own (A02).
"""
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit

from fido2.server import Fido2Server
from fido2.utils import websafe_decode, websafe_encode
from fido2.webauthn import (AttestedCredentialData, AuthenticationResponse,
                            UserVerificationRequirement)

import julz_gate as gate

CHALLENGE_TTL = 120
ENROLL_TTL = 600
ENROLL_TRIES = 5
MAX_PENDING = 16
# stop ends a waiting task, halt stops the run going now: never the same signature
ACTIONS = ("approve", "reject", "stop", "continue", "halt", "discard")
USER = {"id": b"julz-owner", "name": "julz", "displayName": "julz owner"}
UV_REQUIRED = UserVerificationRequirement.REQUIRED


class AuthError(gate.GateError):
    pass


def check_origin(origin: str) -> str:
    """The approver's own origin: https, a host name and an explicit port other than 443.
    On 443 it would share its origin with Open WebUI. Returns the host name (the RP id)."""
    try:
        u = urlsplit(origin)
        port = u.port
    except ValueError:
        raise AuthError("origin is not a valid URL") from None
    if u.scheme != "https" or not u.hostname or port in (None, 443):
        raise AuthError("origin must be https://<name>:<port>, port not 443")
    if origin != f"https://{u.hostname}:{port}":
        raise AuthError("origin must be exactly https://<name>:<port>, lowercase, no path")
    return u.hostname


def bind(action: str, text: str) -> bytes:
    """What the passkey signs besides the nonce: the action and the exact text."""
    return hashlib.sha256(action.encode() + b"\0" + text.encode()).digest()


# ---------- files ----------

def write_private(path: Path, data: dict, replace: bool):
    """Write JSON mode 600 through a temp file. replace=False refuses if path exists,
    atomically (link fails on an existing name), so two enrollments cannot both win."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(8)}")
    gate.write_new(tmp, json.dumps(data), 0o600, AuthError("temp file exists"))
    try:
        if replace:
            os.replace(tmp, path)
        else:
            try:
                os.link(tmp, path)
            except FileExistsError:
                raise AuthError("a passkey is already registered: --revoke it first") from None
    finally:
        tmp.unlink(missing_ok=True)


def load_credential(path: Path) -> tuple[AttestedCredentialData, int] | None:
    """The registered passkey and its last sign counter, or None if there is none.
    Must be my own file, mode 600, not a symlink: whoever writes it decides who approves."""
    if not os.path.lexists(path):
        return None
    data = gate.read_private_file(Path(path), 0o077)
    try:
        entry = json.loads(data)
        cred = AttestedCredentialData(websafe_decode(entry["credential"]))
        count = entry["sign_count"]
    except Exception:
        raise AuthError(f"{path} is not a valid passkey file") from None
    if not isinstance(count, int) or count < 0:
        raise AuthError(f"{path} has a bad sign counter")
    return cred, count


def save_credential(path: Path, cred: AttestedCredentialData, count: int, new: bool):
    write_private(path, {"credential": websafe_encode(bytes(cred)), "sign_count": count},
                  replace=not new)


def revoke(path: Path) -> bool:
    """Forget the passkey (lost phone, threat 42). Returns whether there was one."""
    try:
        os.unlink(path)
        return True
    except FileNotFoundError:
        return False


# ---------- enrollment code ----------

def new_enroll_code(path: Path, now: float) -> str:
    """Make a one time code for the terminal. Only its hash is stored."""
    code = secrets.token_hex(5)  # 10 characters, 40 bits, 5 tries, 10 minutes
    write_private(path, {"sha256": hashlib.sha256(code.encode()).hexdigest(),
                         "expires": now + ENROLL_TTL, "tries_left": ENROLL_TRIES},
                  replace=True)
    return code


def use_enroll_code(path: Path, code: str, now: float):
    """Spend the code or raise. A right code is gone after this; so is a code that ran out
    of tries or time."""
    if not os.path.lexists(path):
        raise AuthError("no enrollment code: run julz-approve-web.py --enroll")
    try:
        entry = json.loads(gate.read_private_file(Path(path), 0o077))
        digest, expires, tries = entry["sha256"], entry["expires"], entry["tries_left"]
    except (ValueError, KeyError, TypeError):
        os.unlink(path)
        raise AuthError("enrollment code file is broken: make a new code") from None
    if now > expires:
        os.unlink(path)
        raise AuthError("enrollment code expired")
    given = hashlib.sha256(str(code).strip().lower().encode()).hexdigest()
    if hmac.compare_digest(given, digest):
        os.unlink(path)
        return
    if tries <= 1:
        os.unlink(path)
        raise AuthError("wrong enrollment code, no tries left")
    write_private(path, {**entry, "tries_left": tries - 1}, replace=True)
    raise AuthError("wrong enrollment code")


# ---------- the passkey gate ----------

class Passkeys:
    """One registered passkey. Challenges live in this process only, so the approver must
    be a single process handling one request at a time."""

    def __init__(self, origin: str, cred_file: Path, enroll_file: Path, clock=time.time):
        self.origin = origin
        self.rp_id = check_origin(origin)
        self.cred_file = Path(cred_file)
        self.enroll_file = Path(enroll_file)
        self.clock = clock
        self.server = Fido2Server({"id": self.rp_id, "name": "julz approver"},
                                  attestation="none", verify_origin=self._same_origin)
        self.pending: dict[str, dict] = {}
        self.enrolling: dict | None = None

    def _same_origin(self, origin: str) -> bool:
        # Exact match, port included (threat 33). Never fido2's default host name check
        return origin == self.origin

    def _credential(self) -> tuple[AttestedCredentialData, int]:
        found = load_credential(self.cred_file)
        if found is None:
            raise AuthError("no passkey registered")
        return found

    # enrollment (threat 35)

    def enroll_begin(self, code: str) -> dict:
        if load_credential(self.cred_file) is not None:
            raise AuthError("a passkey is already registered: --revoke it first")
        use_enroll_code(self.enroll_file, code, self.clock())
        options, state = self.server.register_begin(USER, user_verification=UV_REQUIRED)
        self.enrolling = {"state": state, "expires": self.clock() + CHALLENGE_TTL}
        return dict(options)

    def enroll_complete(self, response: dict) -> str:
        entry, self.enrolling = self.enrolling, None  # single use, even if it fails below
        if entry is None or self.clock() > entry["expires"]:
            raise AuthError("no enrollment in progress")
        try:
            auth_data = self.server.register_complete(entry["state"], response)
        except Exception as e:
            raise AuthError(f"registration refused: {type(e).__name__}: {e}"[:200]) from None
        save_credential(self.cred_file, auth_data.credential_data, auth_data.counter, new=True)
        return auth_data.credential_data.credential_id.hex()

    # signed actions (threats 31, 32)

    def begin(self, action: str, text: str) -> tuple[str, dict]:
        """Start signing one action on one exact text. Returns (nonce, browser options)."""
        if action not in ACTIONS:
            raise AuthError(f"unknown action {action[:20]!r}")
        cred, _ = self._credential()
        now = self.clock()
        self.pending = {k: v for k, v in self.pending.items() if v["expires"] >= now}
        # Anyone on 127.0.0.1 can call this: a flood pushes out old challenges, nothing more
        while len(self.pending) >= MAX_PENDING:
            self.pending.pop(next(iter(self.pending)))
        nonce = secrets.token_bytes(32)
        options, state = self.server.authenticate_begin(
            [cred], user_verification=UV_REQUIRED, challenge=bind(action, text) + nonce)
        self.pending[nonce.hex()] = {"action": action, "text": text, "state": state,
                                     "expires": now + CHALLENGE_TTL}
        return nonce.hex(), dict(options)

    def finish(self, nonce: str, action: str, response: dict) -> str:
        """Check the assertion. Returns the exact text that was signed, for the caller to
        act on. Raises AuthError for anything else."""
        entry = self.pending.pop(str(nonce), None)  # single use, even if it fails below
        if entry is None:
            raise AuthError("unknown or used challenge")
        if self.clock() > entry["expires"]:
            raise AuthError("challenge expired")
        if action != entry["action"]:
            raise AuthError("signed for a different action")
        cred, count = self._credential()
        try:
            assertion = AuthenticationResponse.from_dict(response)
            self.server.authenticate_complete(entry["state"], [cred], assertion)
        except Exception as e:
            raise AuthError(f"assertion refused: {type(e).__name__}: {e}"[:200]) from None
        new_count = assertion.response.authenticator_data.counter
        # Synced passkeys send 0 every time. A counter that is used must go up, or the key
        # was cloned (WebAuthn spec, step "signCount")
        if (count or new_count) and new_count <= count:
            raise AuthError("sign counter did not increase: cloned passkey?")
        if new_count != count:
            save_credential(self.cred_file, cred, new_count, new=False)
        return entry["text"]
