#!/usr/bin/env python3
"""Install a signed Julz release on the phone, only if it is ours. SECURITY.md threats 96, 97, 99.

1. check-apk.py: only the allowed permissions and exported components
2. apksigner: the signature verifies (scheme v2 or v3), there is exactly one signer, and its
   certificate SHA-256 equals the pin in release-cert.sha256. Another key never installs, so a
   swapped or tampered APK, or a debug build, stops here
3. adb install -r
Usage: ./install.py julz-release.apk
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIN = HERE / "release-cert.sha256"
APKSIGNER = Path.home() / "Android" / "Sdk" / "build-tools" / "36.1.0" / "apksigner"
DIGEST = re.compile(r"^Signer #(\d+) certificate SHA-256 digest: ([0-9a-f]{64})$", re.M)
SCHEME = re.compile(r"^Verified using v(2|3) scheme \([^)]*\): true$", re.M)


def check_signature(output: str, pin: str) -> list[str]:
    problems = []
    if not output.startswith("Verifies"):
        problems.append("signature does not verify")
    if not SCHEME.search(output):
        problems.append("not signed with scheme v2 or v3")
    signers = DIGEST.findall(output)
    if len(signers) != 1:  # apksigner prints one digest line per signer
        problems.append(f"expected exactly one signer, found {len(signers)}")
    elif signers[0][1] != pin:
        problems.append("signed with another key than the pinned one")
    return problems


def read_pin(path: Path = PIN) -> str:
    pin = path.read_text().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", pin):
        raise SystemExit(f"{path} must hold one SHA-256 in lowercase hex")
    return pin


def main(argv: list[str]) -> int:
    if len(argv) != 1 or not Path(argv[0]).is_file():
        print(__doc__, file=sys.stderr)
        return 2
    apk = argv[0]
    if subprocess.run([sys.executable, "-I", str(HERE / "check-apk.py"), apk]).returncode:
        return 1
    out = subprocess.run([str(APKSIGNER), "verify", "--verbose", "--print-certs", apk],
                         capture_output=True, text=True, timeout=120)
    text = "\n".join(l for l in out.stdout.splitlines() if not l.startswith("WARNING"))
    problems = check_signature(text if out.returncode == 0 else "", read_pin())
    for p in problems:
        print(f"install: {p}", file=sys.stderr)
    if problems:
        return 1
    print("install: signature is the pinned release key")
    return subprocess.run(["adb", "install", "-r", apk]).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
