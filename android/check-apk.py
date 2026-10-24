#!/usr/bin/env python3
"""Check a built Julz APK against SECURITY.md threats 89, 97 and 99, before it goes on the phone.

A library can add permissions or exported components to the merged manifest without a line in
our code. This reads the APK itself with aapt2 and fails unless the permissions are exactly the
allowed list and the only exported components are the launcher icon aliases of MainActivity (135). A debuggable APK fails
too (debug builds skip FLAG_SECURE, 89), unless --debug says a debug build is being checked.
Usage: ./check-apk.py [--debug] app/build/outputs/apk/release/app-release.apk
"""
import os
import re
import subprocess
import sys
from pathlib import Path

AAPT2 = Path.home() / "Android" / "Sdk" / "build-tools" / "36.1.0" / "aapt2"
PACKAGE = "app.julz"
# Grows only with the code that needs it, each with its threat row
ALLOWED_PERMISSIONS = {
    f"{PACKAGE}.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION",  # AndroidX, signature level, app internal
    "android.permission.INTERNET",  # the stream to my own server (86, 92)
    "android.permission.FOREGROUND_SERVICE",  # staying alive (92)
    "android.permission.FOREGROUND_SERVICE_SPECIAL_USE",  # without the 6 hour cap (92)
    "android.permission.POST_NOTIFICATIONS",  # counts only notifications (90)
    "android.permission.RECEIVE_BOOT_COMPLETED",  # listening again after a reboot (92)
    "android.permission.USE_BIOMETRIC",  # the fingerprint for the device key (107)
}
# The launcher: one alias of MainActivity per accent, one enabled at a time (135). MainActivity
# itself is not exported; an exported alias must open MainActivity and nothing else
ICONS = ("Magenta", "RedStone", "Acid", "Cyan", "Sand", "Lavender", "Orange")
EXPORTED_OK = {f"{PACKAGE}.Icon{n}" for n in ICONS}
MAIN = f"{PACKAGE}.MainActivity"

COMPONENT = re.compile(r"^\s*E: (activity|activity-alias|service|receiver|provider) ")
NAME = re.compile(r'android:name\(0x01010003\)="([^"]+)"')
TARGET = re.compile(r'android:targetActivity\(0x01010202\)="([^"]+)"')
EXPORTED = re.compile(r"android:exported\(0x01010010\)=(true|false|0xffffffff|0x0)")
DEBUGGABLE = re.compile(r"android:debuggable\(0x0101000f\)=(true|0xffffffff)")
USES = re.compile(r"^uses-permission: name='([^']+)'")


def permissions(dump: str) -> set:
    return {m.group(1) for line in dump.splitlines() if (m := USES.match(line))}


def full(name: str | None) -> str | None:
    return PACKAGE + name if name and name.startswith(".") else name


def exported(xmltree: str) -> set:
    """Names of components marked exported. minSdk 35 requires the flag on anything with an
    intent filter, so a component without it is not exported."""
    return {c["name"] for c in components(xmltree) if c["exported"]}


def components(xmltree: str) -> list[dict]:
    """Each component with its kind, name, exported flag and, for an alias, its target."""
    items, current, depth = [], None, 0
    for line in xmltree.splitlines():
        indent = len(line) - len(line.lstrip())
        if COMPONENT.match(line):
            kind = COMPONENT.match(line).group(1)
            current, depth = {"kind": kind, "name": None, "exported": False, "target": None}, indent
            items.append(current)
            continue
        if current is not None and line.strip().startswith("E: "):
            if indent <= depth:
                current = None  # a sibling or parent element: this component ended
            else:
                current["children"] = True  # its own attributes come before its children
        if current is None or current.get("children"):
            continue
        if current["name"] is None and (m := NAME.search(line)):
            current["name"] = m.group(1)
        if (m := EXPORTED.search(line)) and m.group(1) in ("true", "0xffffffff"):
            current["exported"] = True
        if current["target"] is None and (m := TARGET.search(line)):
            current["target"] = m.group(1)
    return items


def check(perm_dump: str, xmltree: str, debug_ok: bool = False) -> list[str]:
    problems = []
    if not debug_ok and DEBUGGABLE.search(xmltree):
        problems.append("debuggable build: no FLAG_SECURE, never for the phone outside development")
    extra = permissions(perm_dump) - ALLOWED_PERMISSIONS
    if extra:
        problems.append("permissions not allowed: " + ", ".join(sorted(extra)))
    names = {n if not n.startswith(".") else PACKAGE + n for n in exported(xmltree)}
    extra = names - EXPORTED_OK
    if extra:
        problems.append("exported components not allowed: " + ", ".join(sorted(extra)))
    for c in components(xmltree):
        if c["kind"] == "activity-alias" and c["exported"] and full(c["target"]) != MAIN:
            problems.append(f"exported alias {full(c['name'])} opens {c['target']!r}, not MainActivity")
    return problems


def main(argv: list[str]) -> int:
    debug_ok = argv[:1] == ["--debug"]
    argv = argv[1:] if debug_ok else argv
    if len(argv) != 1 or not os.path.isfile(argv[0]):
        print(__doc__, file=sys.stderr)
        return 2
    run = lambda *a: subprocess.run([str(AAPT2), "dump", *a, argv[0]], capture_output=True,
                                    text=True, check=True, timeout=60).stdout
    problems = check(run("permissions"), run("xmltree", "--file", "AndroidManifest.xml"),
                     debug_ok)
    for p in problems:
        print(f"check-apk: {p}", file=sys.stderr)
    if not problems:
        print("check-apk: permissions and exported components as allowed")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
