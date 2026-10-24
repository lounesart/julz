#!/usr/bin/env python3
"""Put a tested, committed julz live. The units run ~/.local/lib/julz/current, never this
working tree, so editing code here changes nothing until I deploy. SECURITY.md threat 79.

Usage:
  ./deploy.py             deploy HEAD of main; it must be clean and tagged (git tag v1.2)
  ./deploy.py --dev       deploy HEAD of any branch, untagged; still clean and tested
  ./deploy.py --rollback  go back to the release before the live one (one step)
  ./deploy.py --status    what is live

Steps: refuse uncommitted changes, export HEAD with git archive (tracked files only, no
.git, no stray key files), run the whole suite inside the export, copy changed unit files,
switch the current link in one rename, reload systemd, restart the approver. Afterwards it
names what it cannot do itself: a tool to paste into Open WebUI, models to rebuild, a sudo step.
"""
import fcntl
import filecmp
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent
LIB = Path.home() / ".local" / "lib" / "julz"
UNITS = Path.home() / ".config" / "systemd" / "user"
KEEP_RELEASES = 5
LONG_RUNNING = ("julz-approver.service", "julz-chat.service")
PASTE = ("tools/", "functions/")  # Open WebUI keeps its own copy: I paste these by hand
REBUILD = ("modelfiles/",)  # build-models.sh may pull a model, an install: I run it
SUDO = ("run-webui.sh", "run-searxng.sh", "run-speaches.sh", "systemd/ollama-limits.conf")


class DeployError(Exception):
    pass


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
    lines = [f"paste {rel} into Open WebUI (Workspace, Tools or Functions)"
             for rel in _changed(old, new, PASTE) if (new / rel).exists()]
    if _changed(old, new, REBUILD):
        lines.append("modelfiles changed: run ./build-models.sh")
    lines += [f"sudo needed: {rel} changed, run it yourself" for rel in _changed(old, new, SUDO)]
    lines += [f"new unit {u}: systemctl --user enable --now {u}" for u in new_units
              if u.endswith((".path", ".timer")) or u in LONG_RUNNING]
    return lines


def _log(lib: Path, entry: dict):
    entry = {"time": datetime.now(timezone.utc).isoformat(timespec="seconds"), **entry}
    with open(lib / "deploys.log", "a", encoding="utf-8") as f:
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
           systemctl=default_systemctl) -> str:
    if git(repo, "status", "--porcelain"):
        raise DeployError("uncommitted changes: commit them first, a deploy never takes "
                          "unreviewed bytes")
    if not dev and git(repo, "rev-parse", "--abbrev-ref", "HEAD") != "main":
        raise DeployError("only main deploys; use --dev to try a branch")
    label = "dev" if dev else git(repo, "describe", "--exact-match", "--tags", "HEAD", check=False)
    if not label:
        raise DeployError("HEAD of main has no tag: git tag v1.x first, or use --dev")
    commit = git(repo, "rev-parse", "HEAD")
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
        elif args in ([], ["--dev"]):
            print(deploy(REPO, LIB, UNITS, dev=args == ["--dev"]))
        else:
            sys.exit(__doc__)
    except DeployError as e:
        sys.exit(f"refused: {e}")


if __name__ == "__main__":
    main()
