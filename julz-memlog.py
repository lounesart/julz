#!/usr/bin/env python3
"""Log how much RAM each part of julz uses, to find what grows. SECURITY.md threat 112.

Every run reads /proc once and adds one CSV row per group: the time, a label from LABELS,
the summed VmRSS plus VmSwap in kB (held in RAM or in zram) and the number of processes.
Totals from /proc/meminfo come as _used, _available, _shmem and _swap; _zombie counts
processes left as zombies.
- a command line is only matched against the fixed rules in classify(); no text from /proc
  ever reaches the CSV, so a token or path in someone's arguments stays where it was
- rows older than KEEP go on every run; the file is written to a temp file and renamed
- RSS counts shared pages in each process: the numbers show growth, not an exact bill
- ollama's model sits in the GPU, but its llama-server runner keeps saved prompts in host
  RAM (up to 8 GiB by default, threat 145); before 24 Oct the runner was counted as other
Usage: ./julz-memlog.py               (systemd: julz-memlog.timer, every 10 minutes)
       ./julz-memlog.py --report [H]  growth per hour over the last H hours (48)
"""
import csv
import os
import sys
import tempfile
import time
from pathlib import Path

HOUR = 3600
KEEP = 14 * 24 * HOUR
HEADER = ["time", "group", "kb", "procs"]
GROUPS = ["open-webui", "ollama", "speaches", "searxng", "ntfy", "julz", "claude", "other"]
LABELS = GROUPS + ["_used", "_available", "_shmem", "_swap", "_zombie"]
OLLAMA_RUNNER = "/usr/lib/ollama/llama-server"
LOG = Path(os.environ.get("STATE_DIRECTORY") or Path.home() / ".local/state/julz-memlog") / "rss.csv"


def classify(argv: list[str]) -> str:
    """One label from GROUPS for a command line; the text itself is never kept."""
    exe = os.path.basename(argv[0]) if argv else ""
    joined = " ".join(argv)
    if "open_webui" in joined:
        return "open-webui"
    if exe == "ollama" or (argv and argv[0] == OLLAMA_RUNNER):
        return "ollama"
    if "speaches" in joined:
        return "speaches"
    if "searxng" in joined:
        return "searxng"
    if "/.local/lib/julz-ntfy/" in joined:
        return "ntfy"
    if "/.local/lib/julz/" in joined:
        return "julz"
    if exe == "claude":
        return "claude"
    return "other"


def _meminfo(proc: Path) -> dict[str, int]:
    out = {}
    for line in (proc / "meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        out[key] = int(rest.split()[0])
    return out


def sample(proc: Path = Path("/proc")) -> dict[str, tuple[int, int]]:
    """{label: (kB, processes)}. A process that ends while it is read is skipped."""
    groups: dict[str, list[int]] = {}
    zombies = 0
    for d in proc.iterdir():
        if not d.name.isdigit():
            continue
        try:
            status = (d / "status").read_text()
            raw = (d / "cmdline").read_bytes()
        except OSError:
            continue
        fields = dict(l.split(":", 1) for l in status.splitlines() if ":" in l)
        if fields.get("State", "").strip().startswith("Z"):
            zombies += 1
            continue
        if "VmRSS" not in fields:
            continue  # kernel threads
        argv = [a.decode(errors="replace") for a in raw.split(b"\0") if a]
        g = groups.setdefault(classify(argv), [0, 0])
        g[0] += int(fields["VmRSS"].split()[0]) + int(fields.get("VmSwap", "0 kB").split()[0])
        g[1] += 1
    out = {k: (v[0], v[1]) for k, v in groups.items()}
    m = _meminfo(proc)
    out["_used"] = (m["MemTotal"] - m["MemAvailable"], 0)
    out["_available"] = (m["MemAvailable"], 0)
    out["_shmem"] = (m.get("Shmem", 0), 0)
    out["_swap"] = (m.get("SwapTotal", 0) - m.get("SwapFree", 0), 0)
    out["_zombie"] = (0, zombies)
    return out


def _read(log: Path) -> list[list[str]]:
    try:
        with log.open(newline="") as f:
            return [r for r in csv.reader(f) if r and r != HEADER]
    except FileNotFoundError:
        return []


def record(log: Path, s: dict[str, tuple[int, int]], now: float) -> None:
    rows = [r for r in _read(log) if int(r[0]) >= now - KEEP]
    rows += [[str(int(now)), label, str(kb), str(n)]
             for label, (kb, n) in sorted(s.items()) if label in LABELS]
    log.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=log.parent, prefix=".rss.")
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    os.replace(tmp, log)


def _slope(points: list[tuple[float, float]]) -> float:
    """Least squares, kB per second."""
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    var = sum((p[0] - mx) ** 2 for p in points)
    return sum((p[0] - mx) * (p[1] - my) for p in points) / var if var else 0.0


def report(log: Path, hours: float = 48, now: float | None = None) -> str:
    now = time.time() if now is None else now
    rows = [r for r in _read(log) if int(r[0]) >= now - hours * HOUR]
    if not rows:
        return f"no log yet in {log}"
    times = sorted({int(r[0]) for r in rows})
    if times[-1] - times[0] < HOUR:
        return "not enough samples yet: needs at least an hour of them"
    by: dict[str, list[tuple[int, int, int]]] = {}
    for t, label, kb, n in rows:
        by.setdefault(label, []).append((int(t), int(kb), int(n)))
    span = (times[-1] - times[0]) / HOUR
    lines = [f"{len(times)} samples over {span:.1f} h, MB",
             f"{'group':<12}{'first':>8}{'last':>8}{'max':>8}{'MB/h':>8}  procs"]
    for label in LABELS:
        pts = sorted(by.get(label, []))
        if not pts:
            continue
        mb_h = _slope([(t, kb) for t, kb, _ in pts]) * HOUR / 1024
        lines.append(f"{label:<12}{pts[0][1] / 1024:>8.0f}{pts[-1][1] / 1024:>8.0f}"
                     f"{max(p[1] for p in pts) / 1024:>8.0f}{mb_h:>+8.1f}  "
                     f"{pts[0][2]} -> {pts[-1][2]}")
    return "\n".join(lines)


def main(args: list[str]) -> int:
    if args[:1] == ["--report"]:
        print(report(LOG, float(args[1]) if len(args) > 1 else 48))
        return 0
    if args:
        print(__doc__, file=sys.stderr)
        return 2
    record(LOG, sample(), time.time())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
