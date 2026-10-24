#!/usr/bin/env python3
"""Decrypt pocket drops into the mounted pocket, then delete the ciphertext.

Reads ~/.pocket-drop/*.jwe (written by the pocket_drop tool), writes each item to
~/Private/drops/<time>-<title>.md with mode 600. A drop that fails to decrypt is kept and
reported: wrong key or tampering (A256GCM is authenticated).
Usage: ./pocket-open.py   (pocket must be mounted)
"""
import json
import os
import re
import stat
import sys
from pathlib import Path

from joserfc import jwe
from joserfc.errors import JoseError
from joserfc.jwk import OKPKey

POCKET = Path.home() / "Private"
KEY_FILE = POCKET / "pocket-key.jwk"
DROP_DIR = Path.home() / ".pocket-drop"
OUT_DIR = POCKET / "drops"

# A drop holds at most 50 KB of text; base64 and JSON grow it, 200 KB is plenty
MAX_DROP_BYTES = 200_000
DROP_NAME = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{8}\.jwe$")
SAFE_TITLE = re.compile(r"[^\w\- ]+")


def require_mount(path: Path):
    # Without the mount, ~/Private is a plain folder: no key, and plaintext would land on disk
    if not os.path.ismount(path):
        sys.exit(f"{path} is not mounted. Run: gocryptfs ~/.pocket.enc ~/Private")


def load_private_key(path: Path) -> OKPKey:
    return OKPKey.import_key(json.loads(path.read_text(encoding="utf-8")))


def safe_title(title: str) -> str:
    # The title comes from the model, maybe from a hostile page: no slashes, dots or
    # control characters reach the file name (CWE-22)
    cleaned = SAFE_TITLE.sub("", title).strip()[:60].strip()
    return cleaned.replace(" ", "-") or "untitled"


def read_drop(path: Path) -> str | None:
    """Return the token, or None if the entry is not a plain, small drop file."""
    # The container can write anything into the drop folder. O_NOFOLLOW refuses a symlink
    # to a host file, fstat checks the file we actually opened (no TOCTOU, CWE-367)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return None
    with os.fdopen(fd, "rb") as f:
        st = os.fstat(f.fileno())
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_DROP_BYTES:
            return None
        return f.read(MAX_DROP_BYTES + 1).decode("ascii", errors="replace")


def open_drops(drop_dir: Path, out_dir: Path, key: OKPKey) -> tuple[list[str], list[str]]:
    """Decrypt every drop. Returns (opened file names, problems)."""
    opened, problems = [], []
    out_dir.mkdir(mode=0o700, exist_ok=True)
    for path in sorted(drop_dir.iterdir()):
        if not DROP_NAME.match(path.name):
            problems.append(f"{path.name}: not a drop name, left alone")
            continue
        token = read_drop(path)
        if token is None:
            problems.append(f"{path.name}: symlink, not a file or too big, left alone")
            continue
        try:
            item = json.loads(jwe.decrypt_compact(token, key).plaintext)
            title, text, when = item["title"], item["text"], item["time"]
            if not all(isinstance(v, str) for v in (title, text, when)):
                raise ValueError("bad field types")
        except (JoseError, ValueError, KeyError, TypeError) as e:
            problems.append(f"{path.name}: cannot decrypt or bad content ({type(e).__name__}), kept")
            continue

        stamp = path.name.split("-")[0]
        target = out_dir / f"{stamp}-{safe_title(title)}.md"
        n = 1
        while target.exists():
            target = out_dir / f"{stamp}-{safe_title(title)}-{n}.md"
            n += 1
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"# {title}\n\n{when}\n\n{text}\n")
        # Ciphertext goes only after the plaintext is safely in the pocket
        path.unlink()
        opened.append(target.name)
    return opened, problems


def main():
    require_mount(POCKET)
    if not DROP_DIR.is_dir():
        sys.exit(f"{DROP_DIR} does not exist")
    opened, problems = open_drops(DROP_DIR, OUT_DIR, load_private_key(KEY_FILE))
    for name in opened:
        print(f"opened  {name}")
    for p in problems:
        print(f"WARNING {p}")
    if not opened and not problems:
        print("no drops")
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
