"""Keep: which text files Claude wrote may go into julz's knowledge (PLAN-keep.md).

Host side only. Security model: SECURITY.md threats 54 to 63.
- code picks the files, never the report: every .md or .txt in the work copy that Claude
  added or changed, compared with the project file by file (no walk of the whole project)
- every file is untrusted (B13): validate and reject, never sanitize, so what I sign is what
  lands on disk. A failed file is listed with its reason and the rest are kept
- no links of any kind, strict names, no hidden characters (LLM04, CWE-22, CWE-59)
- no markdown images or links, no HTML, URLs only to reserved hosts (threat 56)
- no secrets: a note is read again and again, a key in it would leak every time (LLM02)
- the walk has limits, so a huge work copy cannot hold the gate lock for minutes (62)
The manifest is written at done. I sign its hash, and the Keep rebuilds it and compares (57).
"""
import filecmp
import hashlib
import ipaddress
import json
import os
import re
import shutil
import stat
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

import julz_gate as gate

MAX_FILE = 64 * 1024
MAX_FILES = 20
MAX_TOTAL = 512 * 1024
MAX_ENTRIES = 5000  # everything the walk sees, files and folders, before it stops
MAX_DEPTH = 4  # parts in a kept path: labs/a/b/x.md
MAX_MANIFEST_BYTES = 1_000_000
MAX_CARDS = 10
MAX_SHOWN_REJECTED = 50
MAX_TOPICS = 20
KEEP_FIELDS = ("keep", "topic", "manifest", "pick")
KEEP_TTL = 24 * 3600  # a signed Keep not used by then is removed unused (threat 59)
TOPIC = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
PART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,79}")
ENDINGS = (".md", ".txt")

# Names that can never be a real public site (RFC 2606, RFC 6761). Matched as the whole host
# or a dot suffix, so example.com.evil.net and evil-example.com do not pass
RESERVED_NAMES = ("example.com", "example.net", "example.org", "example", "test", "invalid",
                  "localhost")
# An explicit list, not ipaddress.is_private: its meaning changed in Python 3.13, and my
# tailnet (100.64.0.0/10) must not pass
RESERVED_NETS = tuple(ipaddress.IPv4Network(n) for n in (
    "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",  # RFC 1918
    "127.0.0.0/8",  # loopback
    "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24"))  # documentation, RFC 5737

IMAGE = re.compile(r"!\[")
INLINE_LINK = re.compile(r"\]\(")
REF_LINK = re.compile(r"(?m)^ {0,3}\[[^\]\n]+\]:")
AUTOLINK = re.compile(r"<[A-Za-z][A-Za-z0-9+.-]*:")
# A tag name followed by space, / or >. Real `ip a` output like <BROADCAST,MULTICAST,UP>
# passes. Placeholders like <target> do not: Claude can write TARGET instead
HTML = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?=[\s/>])|<[!?]")
URL = re.compile(r"(?i)(?<![A-Za-z0-9+.-])(?:[a-z][a-z0-9+.-]*://|www\.)[^\s<>\"'`]*")
URL_TAIL = ".,;:!?)]'\""


class KeepError(gate.SpecError):
    """A refused Keep. A SpecError, so the approver answers it like any refused action."""


# ---------- checks ----------

def check_topic(topic) -> str | None:
    """The topic is the only free text in the path, typed on the phone (threat 55)."""
    if not isinstance(topic, str) or not TOPIC.fullmatch(topic):
        return "topic must be 1 to 40 of a-z, 0-9 and -, starting with a letter or digit"
    return None


def check_name(rel: str) -> str | None:
    parts = rel.split("/")
    if not rel or len(parts) > MAX_DEPTH:
        return f"path must have 1 to {MAX_DEPTH} parts"
    if not all(PART.fullmatch(p) for p in parts):
        return "name may only use letters, digits, . _ and -, starting with a letter or digit"
    if not parts[-1].endswith(ENDINGS):
        return "only .md and .txt"
    return None


def reserved_host(host: str) -> bool:
    if any(host == r or host.endswith("." + r) for r in RESERVED_NAMES):
        return True
    try:
        ip = ipaddress.IPv4Address(host)  # refuses 2130706433 and 0177.0.0.1
    except ValueError:
        return False
    return any(ip in net for net in RESERVED_NETS)


def check_url(url: str) -> str | None:
    try:
        u = urlsplit(url)
        u.port  # raises on a port that is not a number or out of range
    except ValueError:
        return "URL that does not parse"
    if u.scheme not in ("http", "https"):
        return f"URL scheme {u.scheme[:20]!r}"
    if "@" in u.netloc:
        return "URL with a user name"
    host = (u.hostname or "").rstrip(".")
    if not host:
        return "URL without a host"
    if not reserved_host(host):  # non ASCII never matches: the names are ASCII, so are IPs
        return f"URL to {host[:60]!r}, not a reserved host"
    return None


def check_text(text: str, secrets=()) -> str | None:
    for ch in text:
        if ch not in "\n\t" and unicodedata.category(ch) in gate.BAD_CATEGORIES:
            return f"hidden or control character U+{ord(ch):04X}"
    if any(s and s in text for s in secrets):
        return "holds a secret"
    if gate.looks_secret(text):
        return "looks like a secret"
    for pattern, reason in ((IMAGE, "markdown image"), (INLINE_LINK, "markdown link"),
                            (REF_LINK, "markdown link reference"), (AUTOLINK, "autolink"),
                            (HTML, "HTML")):
        if pattern.search(text):
            return reason
    for m in URL.finditer(text):
        url = m.group().rstrip(URL_TAIL)
        if url[:4].lower() == "www.":
            url = "http://" + url
        reason = check_url(url)
        if reason:
            return reason
    return None


# ---------- manifest ----------

def _unchanged(project: Path, rel: str, p: Path, st: os.stat_result) -> bool:
    try:
        old = (project / rel).lstat()
    except OSError:
        return False
    if stat.S_ISLNK(old.st_mode) and stat.S_ISLNK(st.st_mode):
        return os.readlink(project / rel) == os.readlink(p)
    if stat.S_ISREG(old.st_mode) and stat.S_ISREG(st.st_mode) and old.st_size == st.st_size:
        return filecmp.cmp(project / rel, p, shallow=False)
    return False


def _candidates(work: Path) -> list[str] | None:
    """Every .md and .txt name in the work copy, or None past MAX_ENTRIES. Links are never
    followed, hidden folders and anything deeper than MAX_DEPTH are not entered."""
    found, entries = [], 0
    for dirpath, dirnames, filenames in os.walk(work):
        rel_dir = Path(dirpath).relative_to(work)
        entries += len(dirnames) + len(filenames)
        if entries > MAX_ENTRIES:
            return None
        if len(rel_dir.parts) >= MAX_DEPTH - 1:
            dirnames[:] = []
        else:
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        found += [(rel_dir / n).as_posix() for n in filenames if n.lower().endswith(ENDINGS)]
    return sorted(found)


def _check_file(p: Path, rel: str, st: os.stat_result, secrets) -> tuple[str | None, bytes]:
    reason = check_name(rel)
    if reason:
        return reason, b""
    if stat.S_ISLNK(st.st_mode):
        return "link", b""
    if not stat.S_ISREG(st.st_mode):
        return "not a regular file", b""
    if st.st_size > MAX_FILE:  # before reading: a 10 MB file is never read
        return f"over {MAX_FILE} bytes", b""
    try:
        data = gate.read_regular(p, MAX_FILE)
        text = data.decode("utf-8")
    except gate.GateError:
        return "cannot read", b""
    except UnicodeDecodeError:
        return "not UTF-8", b""
    return check_text(text, secrets), data


def build_manifest(project: Path, work: Path, task: str, secrets=()) -> dict:
    project, work = Path(project), Path(work)
    manifest = {"task": task, "keep": [], "rejected": [], "stopped": None}
    if work.is_symlink() or not work.is_dir():
        raise KeepError("work copy is missing")
    names = _candidates(work)
    if names is None:
        manifest["stopped"] = f"over {MAX_ENTRIES} entries in the work copy"
        return manifest
    total = 0
    for rel in names:
        p = work / rel
        try:
            st = p.lstat()
        except OSError:
            continue  # gone since the walk
        if _unchanged(project, rel, p, st):
            continue  # not Claude's: mine, as it was
        reason, data = _check_file(p, rel, st, secrets)
        if not reason and len(manifest["keep"]) >= MAX_FILES:
            reason = f"over {MAX_FILES} files"
        elif not reason and total + len(data) > MAX_TOTAL:
            reason = f"over {MAX_TOTAL} bytes in total"
        if reason:
            shown = rel if rel.isprintable() else repr(rel)
            manifest["rejected"].append({"path": shown, "reason": reason})
            continue
        total += len(data)
        manifest["keep"].append({"path": rel, "size": len(data),
                                 "sha256": hashlib.sha256(data).hexdigest()})
    return manifest


def manifest_hash(manifest: dict) -> str:
    """What I sign. Canonical JSON, so the same manifest always gives the same hash."""
    text = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(text.encode()).hexdigest()


def write_manifest(folder: Path, manifest: dict):
    """manifests/<task>.json, replaced at every done. A planted link is replaced, never
    followed: the temp file is created new and renamed over the name."""
    task = manifest.get("task")
    if not isinstance(task, str) or not gate.HEX64.fullmatch(task):
        raise KeepError("bad task id")
    folder = Path(folder)
    tmp = folder / f".{task}.tmp"
    try:
        tmp.unlink()  # left over from a crash; unlink removes a link, not its target
    except FileNotFoundError:
        pass
    gate.write_new(tmp, json.dumps(manifest, sort_keys=True, indent=1) + "\n", 0o600,
                   KeepError("manifest temp file exists"))
    os.replace(tmp, folder / f"{task}.json")


def load_manifest(dirs: gate.Dirs, root: str) -> dict:
    """The manifest of one task, checked in full: only the runner writes it, but the Keep
    copies by its paths, so a broken one is refused, never half used."""
    data = gate.read_regular(dirs.manifests / f"{root}.json", MAX_MANIFEST_BYTES)
    try:
        m = json.loads(data)
    except ValueError:
        raise KeepError("manifest is broken") from None
    if not (isinstance(m, dict) and m.get("task") == root and isinstance(m.get("keep"), list)
            and isinstance(m.get("rejected"), list) and len(m["keep"]) <= MAX_FILES):
        raise KeepError("manifest is broken")
    paths = set()
    for f in m["keep"]:
        if not (isinstance(f, dict) and set(f) == {"path", "size", "sha256"}
                and isinstance(f["path"], str) and check_name(f["path"]) is None
                and f["path"] not in paths and type(f["size"]) is int
                and 0 <= f["size"] <= MAX_FILE and isinstance(f["sha256"], str)
                and gate.HEX64.fullmatch(f["sha256"])):
            raise KeepError("manifest is broken")
        paths.add(f["path"])
    return m


# ---------- the signed Keep ----------

def keep_text(root: str, topic: str, mhash: str, picked: list[str]) -> str:
    """What I sign: the task, the topic I typed, the manifest I saw and the files I ticked,
    by name and in manifest order. Names hold no spaces (check_name), so a space splits them."""
    return f"keep: {root}\ntopic: {topic}\nmanifest: {mhash}\npick: {' '.join(picked)}\n"


def pick_in_order(m: dict, picked) -> list[str]:
    """The ticked paths in manifest order. Each must be in the manifest, once."""
    if not isinstance(picked, list) or not picked \
            or not all(isinstance(p, str) for p in picked):
        raise KeepError("choose at least one file")
    paths = [f["path"] for f in m["keep"]]
    if len(set(picked)) != len(picked) or not set(picked) <= set(paths):
        raise KeepError("a chosen file is not in the list: reload")
    return [p for p in paths if p in set(picked)]


def check_keep(text: str, dirs: gate.Dirs, root: str | None = None) -> tuple:
    """Everything a Keep must still be, checked when it is signed and again before the copy.
    Returns (root, topic, task, manifest entries I picked)."""
    fields = gate.parse_fields(text, KEEP_FIELDS)
    r = fields["keep"]
    if not gate.HEX64.fullmatch(r) or (root is not None and r != root):
        raise KeepError("Keep names a bad task")
    reason = check_topic(fields["topic"])
    if reason:
        raise KeepError(reason)
    task = gate.load_task(dirs, r)
    if task.get("status") != "done":
        raise KeepError("task is not done")
    if task.get("kept"):
        raise KeepError("task was kept already")
    m = load_manifest(dirs, r)
    picked = pick_in_order(m, fields["pick"].split(" "))
    if text != keep_text(r, fields["topic"], manifest_hash(m), picked):
        raise KeepError("changed since you saw it: reload")
    return r, fields["topic"], task, [f for f in m["keep"] if f["path"] in set(picked)]


def keep_cards(dirs: gate.Dirs) -> list[dict]:
    """Done tasks with something to keep, newest manifest first, for the approver page."""
    out = []
    if not dirs.tasks.is_dir():
        return out
    for path in dirs.tasks.iterdir():
        root = path.stem
        if path.suffix != ".json" or not gate.HEX64.fullmatch(root):
            continue
        try:
            task = gate.load_task(dirs, root)
            if task.get("status") != "done" or task.get("kept") \
                    or os.path.lexists(dirs.keep / root):
                continue
            m = load_manifest(dirs, root)
            mtime = (dirs.manifests / f"{root}.json").lstat().st_mtime
        except (gate.GateError, OSError):
            continue
        if not m["keep"]:
            continue
        rejected = [{"path": str(r.get("path", ""))[:200], "reason": str(r.get("reason", ""))[:200]}
                    for r in m["rejected"][:MAX_SHOWN_REJECTED] if isinstance(r, dict)]
        out.append({"root": root, "goal": str(task.get("goal", ""))[:200],
                    "project": str(task.get("project", ""))[:40],
                    "files": [{"path": f["path"], "size": f["size"]} for f in m["keep"]],
                    "rejected": rejected, "rejected_count": len(m["rejected"]),
                    "stopped": m.get("stopped") if isinstance(m.get("stopped"), str) else None,
                    "sha256": manifest_hash(m), "time": mtime})
    return sorted(out, key=lambda c: -c["time"])[:MAX_CARDS]


def used_topics(dirs: gate.Dirs) -> list[str]:
    """Topics of earlier Keeps, from the task files, for tap to fill on the card. Checked
    again: a broken task file never puts odd text on the page."""
    found = set()
    if not dirs.tasks.is_dir():
        return []
    for path in dirs.tasks.iterdir():
        if path.suffix != ".json" or not gate.HEX64.fullmatch(path.stem):
            continue
        try:
            topic = gate.load_task(dirs, path.stem).get("topic")
        except gate.GateError:
            continue
        if check_topic(topic) is None:
            found.add(topic)
    return sorted(found)[:MAX_TOPICS]


def store_keep(text: str, dirs: gate.Dirs, channel: str = "phone") -> str:
    """I signed a Keep (threat 57). Call only after the assertion checked out. The marker is
    used once by julz-keep, and a second Keep for the same task is refused."""
    root, topic, _, _ = check_keep(text, dirs)
    # Written whole in keep/.tmp, then linked in: julz-keep.path fires the moment a name
    # appears, and a half written marker would be read, refused and used up (CWE-362).
    # Same folder, so the link never crosses a mount; link refuses an existing name
    tmp_dir = dirs.keep / ".tmp"
    tmp_dir.mkdir(mode=0o700, exist_ok=True)
    tmp = tmp_dir / f"{root}.{time.time_ns()}"
    gate.write_new(tmp, text, 0o600, KeepError("temp file exists"))
    try:
        os.link(tmp, dirs.keep / root)
    except FileExistsError:
        raise KeepError("Keep already signed for this task") from None
    finally:
        tmp.unlink()
    gate.log(dirs, "keep-signed", root, "ok", channel)
    return root


# ---------- the copy (julz-keep.service) ----------

def _remove(path: Path):
    """Remove a file, a link (as a link) or a folder of ours. rmtree never follows links."""
    try:
        st = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(st.st_mode):
        shutil.rmtree(path)
    else:
        path.unlink()


def _real_dir(path: Path) -> bool:
    try:
        return stat.S_ISDIR(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def _signed_files(work: Path, entries: list[dict]) -> list[tuple[str, bytes]]:
    """Read every picked file once, check it again and compare with the manifest. The bytes
    returned are the bytes hashed, so nothing can change between the check and the copy."""
    files = []
    for f in entries:
        rel = f["path"]
        d = work
        for part in rel.split("/")[:-1]:
            d = d / part
            if not _real_dir(d):
                raise KeepError(f"{rel}: link or missing folder in the path")
        try:
            st = (work / rel).lstat()
        except FileNotFoundError:
            raise KeepError(f"{rel} is gone") from None
        reason, data = _check_file(work / rel, rel, st, ())
        if reason:
            raise KeepError(f"{rel}: {reason}")
        if len(data) != f["size"] or hashlib.sha256(data).hexdigest() != f["sha256"]:
            raise KeepError(f"{rel} changed since signing")
        files.append((rel, data))
    return files


def _destination(claude: Path, topic: str, name: str) -> Path:
    """Claude/<topic>/<task8>, with no link anywhere on the way (threat 55)."""
    if not _real_dir(claude):
        raise KeepError("Claude folder is missing or a link")
    topic_dir = claude / topic
    if not os.path.lexists(topic_dir):
        os.mkdir(topic_dir, 0o755)
        os.chmod(topic_dir, 0o755)
    if not _real_dir(topic_dir):
        raise KeepError("topic folder is a link or not a folder")
    dest = topic_dir / name
    # Checked, not left to rename: rename replaces an existing empty folder without a word
    if os.path.lexists(dest):
        raise KeepError(f"already kept there: Claude/{topic}/{name}")
    return dest


def _write_tree(tmp: Path, files: list[tuple[str, bytes]]):
    for rel, data in files:
        d = tmp
        for part in rel.split("/")[:-1]:
            d = d / part
            if not d.exists():
                os.mkdir(d, 0o755)
                os.chmod(d, 0o755)
        fd = os.open(tmp / rel, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
                     | os.O_CLOEXEC, 0o644)
        with os.fdopen(fd, "wb") as out:
            os.fchmod(out.fileno(), 0o644)  # a note: readable, never executable
            out.write(data)


def _keep_one(text: str, root: str, dirs: gate.Dirs, work_root: Path, claude: Path,
              now: float) -> tuple[int, str]:
    _, topic, task, entries = check_keep(text, dirs, root)
    work = work_root / root
    if not _real_dir(work):
        raise KeepError("work copy is missing")
    files = _signed_files(work, entries)
    dest = _destination(claude, topic, root[:8])
    # Built hidden inside Claude/ and renamed into place: same filesystem (no EXDEV), and a
    # failure leaves no half folder for julz to read (threat 59)
    tmp = claude / f".tmp-{root}"
    _remove(tmp)
    os.mkdir(tmp, 0o700)
    try:
        _write_tree(tmp, files)
        os.chmod(tmp, 0o755)
        os.rename(tmp, dest)
    except BaseException:
        _remove(tmp)
        raise
    task.update(kept=now, topic=topic)
    gate.save_task(dirs, task)
    return len(files), topic


def request_sync(dirs: gate.Dirs, now: float):
    """Stamp sync/pending: julz-keep-sync.path starts the sync that gives the notes to julz.
    This unit has no network and no key; the one that has them only reads Claude/ (64)."""
    fd = os.open(dirs.sync / "pending", os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
                 | os.O_CLOEXEC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"{now}\n")


def run_keeps(dirs: gate.Dirs, work_root: Path, claude: Path, now: float) -> list[tuple]:
    """Use every signed Keep once, under the gate lock. Raises GateBusy while a run goes;
    the marker stays and the timer tries again. Returns [(root, "ok" or "failed")]."""
    results = []
    with gate.lock(dirs):
        if not _real_dir(dirs.keep):
            return results
        for p in sorted(dirs.keep.iterdir()):
            root = p.name
            st = p.lstat()
            if root == ".tmp" and stat.S_ISDIR(st.st_mode):
                continue  # store_keep writes here; the cleaner removes leftovers
            if not gate.HEX64.fullmatch(root) or not stat.S_ISREG(st.st_mode):
                _remove(p)  # nothing the approver writes looks like this
                continue
            try:
                if now - st.st_mtime > KEEP_TTL:
                    raise KeepError("expired: not used within 24 hours")
                text = gate.decode(gate.read_regular(p, gate.MAX_SPEC_BYTES))
                count, topic = _keep_one(text, root, dirs, Path(work_root), Path(claude), now)
                gate.log(dirs, "keep", root, "ok", f"{count} files to Claude/{topic}/{root[:8]}")
                results.append((root, "ok"))
                try:
                    request_sync(dirs, now)
                except OSError:  # the notes are kept either way; sync by hand then
                    gate.log(dirs, "sync", root, "failed", "could not ask for a sync")
            except (gate.GateError, OSError) as e:
                reason = str(e) if isinstance(e, gate.GateError) else \
                    f"{type(e).__name__}: {e.strerror or e}"
                gate.log(dirs, "keep", root, "failed", reason[:200])
                results.append((root, "failed"))
            finally:
                p.unlink(missing_ok=True)
    return results
