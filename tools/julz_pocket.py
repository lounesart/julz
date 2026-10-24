"""
title: Julz pocket
description: Drop private text into my encrypted pocket. Julz can write it but never read it back.
version: 0.1.0
"""
# Paste this file into Open WebUI: Workspace, Tools, +. No requirements line on purpose:
# joserfc already ships in the image, so nothing is installed from PyPI (A08, LLM03).
# Security model (SECURITY.md, pocket):
# - encrypt only: the container holds the public key, the private key lives in the gocryptfs
#   pocket on the host. JWE, ECDH-ES on X25519 with A256GCM, no crypto of our own (A02)
# - a key file with a private part is refused, so a wrong mount cannot hand Julz the secret
# - file names are time plus random, never the title (no metadata in the folder listing)
# - size and rate limits, and every drop is logged with name and size only (threat 7)
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from joserfc import jwe
from joserfc.jwk import OKPKey

MAX_TITLE_CHARS = 100
MAX_TEXT_BYTES = 50_000
MAX_DROPS_PER_MINUTE = 5
JWE_HEADER = {"alg": "ECDH-ES", "enc": "A256GCM"}


class Tools:
    def __init__(self):
        # Env overrides exist for the tests; in the container the defaults are the mounts
        self.pub_file = Path(os.environ.get("JULZ_POCKET_PUB", "/data/pocket.pub.jwk"))
        self.drop_dir = Path(os.environ.get("JULZ_POCKET_DROP", "/data/pocket-drop"))
        self.log_file = Path(os.environ.get("JULZ_LOG", "/data/julz-log/actions.log"))
        self._drops = []

    def _public_key(self) -> OKPKey:
        data = json.loads(self.pub_file.read_text(encoding="utf-8"))
        if "d" in data:
            raise ValueError("key file holds a private key")
        if data.get("kty") != "OKP" or data.get("crv") != "X25519":
            raise ValueError("key file is not an X25519 public key")
        return OKPKey.import_key(data)

    def _log(self, action: str, **fields):
        entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "action": action, **fields}
        with open(self.log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _rate_limited(self) -> bool:
        now = time.monotonic()
        self._drops = [t for t in self._drops if now - t < 60]
        return len(self._drops) >= MAX_DROPS_PER_MINUTE

    async def pocket_drop(self, title: str, text: str) -> str:
        """
        Put private text into my encrypted pocket, for example a password hint, a personal
        thought or something I said to keep safe. You cannot read the pocket afterwards,
        so tell me it is stored and do not repeat the text back.
        :param title: a few words describing the item, for example "router admin hint"
        :param text: the text to keep
        :return: what happened
        """
        title = " ".join(title.split())[:MAX_TITLE_CHARS]
        data = text.encode("utf-8")
        if not data.strip():
            return "Refused: nothing to store."
        if len(data) > MAX_TEXT_BYTES:
            return f"Refused: text is over {MAX_TEXT_BYTES // 1000} KB."
        if self._rate_limited():
            return "Refused: too many drops in the last minute."
        try:
            key = self._public_key()
        except (OSError, ValueError) as e:
            self._log("pocket_drop_refused", reason=str(e))
            return "Refused: the pocket key is missing or wrong. Tell me to check the setup."

        now = datetime.now(timezone.utc)
        payload = json.dumps({"v": 1, "time": now.isoformat(timespec="seconds"),
                              "title": title, "text": text}, ensure_ascii=False)
        token = jwe.encrypt_compact(JWE_HEADER, payload.encode("utf-8"), key)

        name = f"{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(4)}.jwe"
        # O_EXCL and O_NOFOLLOW: a new file only, never through a planted symlink
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(self.drop_dir / name, flags, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(token)
        self._drops.append(time.monotonic())
        self._log("pocket_drop", file=name, bytes=len(token))
        return "Stored in the pocket, encrypted. I cannot read it back."
