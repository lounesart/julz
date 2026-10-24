#!/usr/bin/env python3
"""Create the pocket key pair, once.

Private key: ~/Private/pocket-key.jwk, inside the gocryptfs pocket, so it is only readable
while the pocket is mounted. Public key: ~/.config/julz/pocket.pub.jwk, mounted read-only
into Open WebUI. The pocket_drop tool can encrypt with it but never decrypt (JWE, X25519).
Usage: ./pocket-keygen.py   (pocket must be mounted)
"""
import json
import os
import sys
from pathlib import Path

from joserfc.jwk import OKPKey

POCKET = Path.home() / "Private"
PRIVATE = POCKET / "pocket-key.jwk"
PUBLIC = Path.home() / ".config" / "julz" / "pocket.pub.jwk"


def write_new(path: Path, data: dict, mode: int):
    # O_EXCL: fail if the file exists, checked and created in one step (no TOCTOU race, CWE-367).
    # Overwriting the private key would make every earlier drop unreadable.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
        f.write("\n")


def main():
    # Without the mount, ~/Private is a plain folder and the key would sit on disk unencrypted
    if not os.path.ismount(POCKET):
        sys.exit(f"{POCKET} is not mounted. Run: gocryptfs ~/.pocket.enc ~/Private")
    for p in (PRIVATE, PUBLIC):
        if p.exists():
            sys.exit(f"{p} already exists, refusing to replace a key")

    key = OKPKey.generate_key("X25519")
    PUBLIC.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    write_new(PRIVATE, key.as_dict(private=True), 0o600)
    # Public on purpose: the container user (uid 1000) must read it through the mount
    write_new(PUBLIC, key.as_dict(private=False), 0o644)
    print(f"private: {PRIVATE}")
    print(f"public:  {PUBLIC}")


if __name__ == "__main__":
    main()
