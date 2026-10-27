#!/usr/bin/env python3
"""Put a tested, committed julz live. The units run ~/.local/lib/julz/current, never this
working tree, so editing code here changes nothing until I deploy. SECURITY.md threat 79.

Usage:
  ./deploy.py             deploy HEAD of main; it must be clean and tagged (git tag v1.2)
  ./deploy.py --dev       deploy HEAD of any branch, untagged; still clean and tested
  ./deploy.py --rollback  go back to the release before the live one (one step)
  ./deploy.py --status    what is live
  ./deploy.py --tools     push the live release's tools and functions to Open WebUI: signs in
                          with my password, shows each diff, asks, checks the hash (threat 147)

Steps: refuse uncommitted changes, export HEAD with git archive (tracked files only, no
.git, no stray key files), run the whole suite inside the export, copy changed unit files,
switch the current link in one rename, reload systemd, restart the approver. Afterwards it
names what it cannot do itself: tools to push with --tools, models to rebuild, a sudo step.
"""
import ast
import difflib
import fcntl
import filecmp
import getpass
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
LIB = Path.home() / ".local" / "lib" / "julz"
UNITS = Path.home() / ".config" / "systemd" / "user"
KEEP_RELEASES = 5
LONG_RUNNING = ("julz-approver.service", "julz-chat.service")
# Folders a unit binds that nothing else makes before it starts: the cards Julz asks for
# (208, threat 156). The container writes Inbox, so a link there is refused, never followed
BOUND_FOLDERS = (Path.home() / "Documents" / "julz-mem" / "Inbox" / ".proposals",)
PASTE = ("tools/", "functions/")  # Open WebUI keeps its own copy: --tools pushes them (147)
OWUI = "http://127.0.0.1:3100"
# 0.11.4's replace_imports rewrites these before storing, so the hash check could never pass
REWRITTEN = ("from utils", "from apps", "from main", "from config")
# Open WebUI made the id from the name I typed when I first pasted it; the rest match the file
OWUI_IDS = {"functions/julz_saves": "julz_honest_saves"}
# Shown above the diff when only layout or comments differ, so y is safe
FORMAT_ONLY = "same code, only formatting or comments differ: y makes the hash match\n"
REBUILD = ("modelfiles/",)  # build-models.sh may pull a model, an install: I run it
SUDO = ("run-webui.sh", "run-searxng.sh", "run-speaches.sh", "systemd/ollama-limits.conf", "searxng/")
# Config a container reads from the release it was created from: its launcher runs again (268)
RERUN = {"searxng/": "run-searxng.sh"}


class DeployError(Exception):
    pass


class HttpError(DeployError):
    def __init__(self, code: int, detail: str):
        super().__init__(f"HTTP {code}: {detail[:200]}")
        self.code = code


def git(repo: Path, *args, check=True) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise DeployError(f"git {args[0]} failed: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def default_tests(release: Path) -> bool:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    r = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"],
                       cwd=release, env=env, capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        print(r.stderr[-2000:], file=sys.stderr)
    return r.returncode == 0


def default_systemctl(*args):
    subprocess.run(["systemctl", *args], check=True)


@contextmanager
def lock(lib: Path):
    lib.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(lib / "deploy.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeployError("another deploy is running") from None
        yield
    finally:
        os.close(fd)


def export(repo: Path, commit: str, dest: Path):
    data = subprocess.run(["git", "-C", str(repo), "archive", "--format=tar", commit],
                          capture_output=True, check=True).stdout
    dest.mkdir(mode=0o755, parents=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")  # no paths outside dest, no device files (CWE-22)


def live(lib: Path) -> Path | None:
    cur = lib / "current"
    return Path(os.readlink(cur)) if cur.is_symlink() else None


def switch(lib: Path, release: Path):
    tmp = lib / f".current.{os.getpid()}"
    tmp.unlink(missing_ok=True)
    os.symlink(release, tmp)
    os.replace(tmp, lib / "current")  # one rename: a unit sees the old or the new release


def install_units(release: Path, units: Path) -> list[str]:
    """Copy the release's julz-* unit files. Returns the names that are new here."""
    new = []
    for f in sorted((release / "systemd").glob("julz-*")):
        target = units / f.name
        if not target.exists():
            new.append(f.name)
        tmp = units / f".{f.name}.{os.getpid()}"
        shutil.copyfile(f, tmp)
        os.replace(tmp, target)
    return new


def _changed(old: Path | None, new: Path, prefixes) -> list[str]:
    if old is None:
        return []
    names = set()
    for root in (old, new):
        for p in root.rglob("*"):
            rel = p.relative_to(root).as_posix()
            if p.is_file() and any(rel == x or rel.startswith(x) for x in prefixes):
                names.add(rel)
    out = []
    for rel in sorted(names):
        a, b = old / rel, new / rel
        if not (a.exists() and b.exists() and filecmp.cmp(a, b, shallow=False)):
            out.append(rel)
    return out


def reminders(old: Path | None, new: Path, new_units: list[str]) -> list[str]:
    lines = [f"{rel} changed: ./deploy.py --tools"
             for rel in _changed(old, new, PASTE) if (new / rel).exists()]
    if _changed(old, new, REBUILD):
        lines.append("modelfiles changed: run ./build-models.sh")
    lines += [f"sudo needed: {rel} changed, run "
              f"{next((s for p, s in RERUN.items() if rel.startswith(p)), 'it')} yourself"
              for rel in _changed(old, new, SUDO)]
    lines += [f"new unit {u}: systemctl --user enable --now {u}" for u in new_units
              if u.endswith((".path", ".timer")) or u in LONG_RUNNING]
    return lines


def _log(lib: Path, entry: dict, name: str = "deploys.log"):
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with open(lib / name, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def _last(lib: Path) -> dict | None:
    try:
        lines = (lib / "deploys.log").read_text().splitlines()
    except FileNotFoundError:
        return None
    return json.loads(lines[-1]) if lines else None


def prune(lib: Path):
    keep = {live(lib)}
    last = _last(lib)
    if last and last.get("previous"):
        keep.add(lib / "releases" / last["previous"])
    releases = sorted((p for p in (lib / "releases").iterdir() if not p.name.startswith(".")),
                      key=lambda p: p.stat().st_mtime, reverse=True)
    for p in releases[KEEP_RELEASES:]:
        if p not in keep:
            shutil.rmtree(p)


def deploy(repo: Path, lib: Path, units: Path, dev: bool = False, run_tests=default_tests,
           systemctl=default_systemctl, folders=BOUND_FOLDERS) -> str:
    if git(repo, "status", "--porcelain"):
        raise DeployError("uncommitted changes: commit them first, a deploy never takes "
                          "unreviewed bytes")
    if not dev and git(repo, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise DeployError("only main deploys; use --dev to try a branch")
    label = "dev" if dev else git(repo, "describe", "--exact-match", "--tags", "HEAD", check=False)
    if not label:
        raise DeployError("HEAD of main has no tag: git tag v1.x first, or use --dev")
    commit = git(repo, "rev-parse", "HEAD")
    for folder in folders:
        if folder.is_symlink() or (folder.exists() and not folder.is_dir()):
            raise DeployError(f"{folder} is not a plain folder: look at it first, nothing changed")
        folder.mkdir(mode=0o700, exist_ok=True)
    with lock(lib):
        releases = lib / "releases"
        releases.mkdir(mode=0o755, parents=True, exist_ok=True)
        final = releases / commit[:12]
        if not final.exists():
            tmp = releases / f".tmp-{commit[:12]}-{os.getpid()}"
            shutil.rmtree(tmp, ignore_errors=True)
            export(repo, commit, tmp)
            if not run_tests(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
                raise DeployError("tests failed in the export: nothing changed, the live "
                                  "release stays")
            os.rename(tmp, final)
        old = live(lib)
        new_units = install_units(final, units)
        switch(lib, final)
        systemctl("--user", "daemon-reload")
        for unit in LONG_RUNNING:
            systemctl("--user", "try-restart", unit)
        _log(lib, {"commit": commit, "label": label, "previous": old.name if old else None})
        prune(lib)
        todo = reminders(old, final, new_units)
    out = [f"live: {commit[:12]} ({label})"]
    out += ["still for you:", *[f"  - {t}" for t in todo]] if todo else ["nothing else to do"]
    return "\n".join(out)


def rollback(lib: Path, units: Path, systemctl=default_systemctl) -> str:
    with lock(lib):
        last = _last(lib)
        if not last or not last.get("previous") or last.get("label") == "rollback":
            raise DeployError("nothing to roll back to (one step back only)")
        target = lib / "releases" / last["previous"]
        if not target.is_dir():
            raise DeployError("the release before is gone")
        cur = live(lib)
        install_units(target, units)
        switch(lib, target)
        systemctl("--user", "daemon-reload")
        for unit in LONG_RUNNING:
            systemctl("--user", "try-restart", unit)
        _log(lib, {"commit": target.name, "label": "rollback",
                   "previous": cur.name if cur else None})
    return f"live again: {target.name}"


def default_http(method: str, path: str, token: str | None = None, data: dict | None = None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(OWUI + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read() or "null")
    except urllib.error.HTTPError as e:
        raise HttpError(e.code, e.read().decode(errors="replace")) from None
    except urllib.error.URLError as e:
        raise DeployError(f"Open WebUI did not answer: {e.reason}") from None


def default_confirm(name: str, diff: str) -> bool:
    print(diff)
    return input(f"push {name} to Open WebUI? [y/N] ").strip().lower() == "y"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _same_code(a: str, b: str) -> bool:
    """Equal syntax trees. ast drops comments and layout; a copy that does not parse counts
    as a real change. Parsing never runs the code."""
    try:
        return ast.dump(ast.parse(a)) == ast.dump(ast.parse(b))
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False


def tools_release(lib: Path) -> Path | None:
    """--tools pushes from the live release, never this working tree (79)."""
    return live(lib)


def push_tools(release: Path, lib: Path, http, email: str, password: str, confirm) -> str:
    """Plan then apply: each tool or function that differs from Open WebUI's copy is shown and
    pushed after my yes, then read back and checked by hash. SECURITY.md threat 147."""
    items = [(f"{d}/{p.stem}", p) for d in ("tools", "functions")
             for p in sorted((release / d).glob("*.py"))]
    for name, p in items:
        if any(x in p.read_text() for x in REWRITTEN):
            raise DeployError(f"{name}: Open WebUI rewrites its imports, so the live copy "
                              "could never match; nothing pushed")
    token = (http("POST", "/api/v1/auths/signin", data={"email": email, "password": password})
             or {}).get("token")
    if not token:
        raise DeployError("sign in gave no token")
    out = []
    try:
        for name, p in items:
            kind, tid = name.split("/")
            tid = OWUI_IDS.get(name, tid)
            src = p.read_text()
            try:
                current = http("GET", f"/api/v1/{kind}/id/{tid}", token)
            except HttpError as e:
                if e.code not in (401, 404):
                    raise
                current = None
            if not current or current.get("content") is None:
                out.append(f"not in Open WebUI: {name}, create it once by hand")
                continue
            if _sha(current["content"]) == _sha(src):
                out.append(f"same: {name}")
                continue
            diff = "".join(difflib.unified_diff(current["content"].splitlines(True),
                                                src.splitlines(True), "live", "release"))
            if _same_code(current["content"], src):
                diff = FORMAT_ONLY + diff
            if not confirm(name, diff):
                out.append(f"kept live: {name}")
                continue
            # Name and meta as they are; no access_grants, so 0.11.4 leaves them alone
            form = {"id": tid, "name": current["name"], "content": src,
                    "meta": current.get("meta") or {}}
            http("POST", f"/api/v1/{kind}/id/{tid}/update", token, data=form)
            after = http("GET", f"/api/v1/{kind}/id/{tid}", token) or {}
            if _sha(after.get("content") or "") != _sha(src):
                raise DeployError(f"{name}: the live copy does not match the release after "
                                  "the push; check it in Open WebUI")
            _log(lib, {"tool": name, "commit": release.name, "sha256": _sha(src)}, "tools.log")
            out.append(f"pushed: {name}")
    finally:
        try:
            http("POST", "/api/v1/auths/signout", token)
        except DeployError as e:
            print(f"sign out failed: {e}", file=sys.stderr)
    return "\n".join(out)


def main():
    args = sys.argv[1:]
    try:
        if args == ["--status"]:
            cur = live(LIB)
            print(f"live: {cur.name if cur else 'nothing deployed'}")
            last = _last(LIB)
            if last:
                print(f"last: {last['time']} {last['label']} {last['commit'][:12]}")
        elif args == ["--rollback"]:
            print(rollback(LIB, UNITS))
        elif args == ["--tools"]:
            release = tools_release(LIB)
            if release is None:
                raise DeployError("nothing deployed yet")
            print(f"tools from the live release {release.name}")
            email = input("Open WebUI admin email: ").strip()
            password = getpass.getpass("Open WebUI password (KeePassXC): ")
            print(push_tools(release, LIB, default_http, email, password, default_confirm))
        elif args in ([], ["--dev"]):
            print(deploy(REPO, LIB, UNITS, dev=args == ["--dev"]))
        else:
            sys.exit(__doc__)
    except DeployError as e:
        sys.exit(f"refused: {e}")


if __name__ == "__main__":
    main()
