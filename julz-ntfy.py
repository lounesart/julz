#!/usr/bin/env python3
"""The push server for the Julz phone app: ntfy on 127.0.0.1, SECURITY.md threats 86 and 87.

The binary is ntfy's own release, pinned by hash here. This wrapper is what the unit runs:
- every start checks the binary against the pinned hash, so a swapped file never runs (A08)
- the flags are built here: 127.0.0.1 only, everyone denied unless a token says otherwise,
  no web app, no sign up, no attachments
- two users: notify may only write the julz topic, phone may only read it. Their bcrypt hashes
  and tokens come from ~/.config/julz/ntfy/auth.env (mode 600) and reach ntfy through the
  environment only, never the command line, which every process of mine can read

Usage:
  ./julz-ntfy.py                     start the server (the unit does this)
  ./julz-ntfy.py --install TARBALL   check the release tarball and put the binary in place
  ./julz-ntfy.py --setup             make the users and tokens; prints paths, never a token
  ./julz-ntfy.py --rotate-phone      a new phone token (lost phone); then restart the server
"""
import hashlib
import os
import re
import secrets
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import julz_gate as gate  # noqa: E402

VERSION = "2.29.0"
TARBALL = f"ntfy_{VERSION}_linux_amd64.tar.gz"
MEMBER = f"ntfy_{VERSION}_linux_amd64/ntfy"
TARBALL_SHA256 = "7862bcb9bc422d9f442fffa72b6393386475f880079edd0978a5d31d3307314e"
BINARY_SHA256 = "89f016aa78ce51d739fcf99afc048ae17a48ad2d921da0c928c346c22d5932b4"
HOME = Path.home()
BIN_DIR = HOME / ".local" / "lib" / "julz-ntfy"
STATE = HOME / ".local" / "share" / "julz-ntfy"
AUTH_ENV = HOME / ".config" / "julz" / "ntfy" / "auth.env"
PHONE_TOKEN = HOME / ".config" / "julz" / "ntfy" / "phone-token"
TOPIC_FILE = HOME / ".config" / "julz" / "notify" / "ntfy.env"
LOCAL_ENV = HOME / ".config" / "julz" / "notify" / "local.env"
LISTEN = "127.0.0.1:8090"
# The notify units post here: they have no internet sockets at all (132). Its own runtime
# folder (julz-ntfy.service), so they never see the user db or the cache
PUSH_SOCKET = f"/run/user/{os.getuid()}/julz-push/ntfy.sock"
TOPIC = re.compile(r"julz-[0-9a-f]{32}")
TOKEN = re.compile(r"tk_[a-z0-9]{29}")
BCRYPT = re.compile(r"\$2[aby]\$1[0-4]\$[./A-Za-z0-9]{53}")
KEYS = ("NOTIFY_HASH", "NOTIFY_TOKEN", "PHONE_HASH", "PHONE_TOKEN")


def binary_path(bin_dir: Path = BIN_DIR) -> Path:
    return bin_dir / f"ntfy-{VERSION}"


def check_binary(path: Path) -> None:
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise gate.GateError(f"{path} missing: run ./julz-ntfy.py --install {TARBALL}") from None
    if not stat.S_ISREG(st.st_mode):
        raise gate.GateError(f"{path} is not a regular file")
    if hashlib.sha256(path.read_bytes()).hexdigest() != BINARY_SHA256:
        raise gate.GateError(f"{path} does not match the pinned hash, not starting")


def _private_text(path: Path) -> str:
    """A file only I can read, not a link."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        raise gate.GateError(f"{path} missing") from None
    if not stat.S_ISREG(st.st_mode) or stat.S_IMODE(st.st_mode) & 0o077:
        raise gate.GateError(f"{path} must be a regular file with mode 600")
    return path.read_text(encoding="utf-8")


def read_auth(path: Path) -> dict:
    values = {}
    for line in _private_text(path).splitlines():
        if not line.strip():
            continue
        key, sep, value = line.partition("=")
        if not sep or key in values:
            raise gate.GateError(f"{path}: unexpected line")
        values[key] = value
    if set(values) != set(KEYS):
        raise gate.GateError(f"{path} needs exactly {', '.join(KEYS)}")
    for key, value in values.items():
        pattern = TOKEN if key.endswith("TOKEN") else BCRYPT
        if not pattern.fullmatch(value):
            raise gate.GateError(f"{path}: {key} has the wrong shape")
    if values["NOTIFY_TOKEN"] == values["PHONE_TOKEN"]:
        raise gate.GateError(f"{path}: the two tokens must differ")
    return values


def load_topic(path: Path) -> str:
    topic = _private_text(path).strip().removeprefix("NTFY_TOPIC=")
    if not TOPIC.fullmatch(topic):
        raise gate.GateError(f"{path} must hold NTFY_TOPIC=julz-<32 hex>")
    return topic


def serve_args(binary: Path, state: Path) -> list[str]:
    return [str(binary), "serve",
            "--listen-http", LISTEN,
            "--listen-unix", PUSH_SOCKET,
            "--listen-unix-mode", "0600",
            "--auth-file", str(state / "user.db"),
            "--auth-default-access", "deny-all",
            "--cache-file", str(state / "cache.db"),
            "--cache-duration", "48h",
            "--web-root", "disable",
            "--visitor-subscription-limit", "5",
            "--log-level", "info"]


def serve_env(auth: dict, topic: str) -> dict:
    return {
        "NTFY_AUTH_USERS": f"notify:{auth['NOTIFY_HASH']}:user,phone:{auth['PHONE_HASH']}:user",
        "NTFY_AUTH_ACCESS": f"notify:{topic}:wo,phone:{topic}:ro",
        "NTFY_AUTH_TOKENS": f"notify:{auth['NOTIFY_TOKEN']},phone:{auth['PHONE_TOKEN']}",
    }


def serve(bin_dir: Path = BIN_DIR, state: Path = STATE, auth_path: Path = AUTH_ENV,
          topic_path: Path = TOPIC_FILE, execve=os.execve) -> None:
    binary = binary_path(bin_dir)
    check_binary(binary)
    env = serve_env(read_auth(auth_path), load_topic(topic_path))
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    state.chmod(0o700)
    execve(str(binary), serve_args(binary, state), env)


def install(tarball: Path, bin_dir: Path = BIN_DIR) -> Path:
    """Only the one binary leaves the tarball, and only if both hashes match."""
    if hashlib.sha256(Path(tarball).read_bytes()).hexdigest() != TARBALL_SHA256:
        raise gate.GateError(f"{tarball} does not match the pinned tarball hash")
    with tarfile.open(tarball, "r:gz") as tar:
        try:
            member = tar.getmember(MEMBER)
        except KeyError:
            raise gate.GateError(f"{MEMBER} not in the tarball") from None
        if not member.isfile():
            raise gate.GateError(f"{MEMBER} is not a regular file")
        data = tar.extractfile(member).read()
    if hashlib.sha256(data).hexdigest() != BINARY_SHA256:
        raise gate.GateError("the binary in the tarball does not match the pinned hash")
    bin_dir.mkdir(mode=0o755, parents=True, exist_ok=True)
    target = binary_path(bin_dir)
    tmp = bin_dir / f".ntfy.{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o755)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, target)
    return target


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def ntfy_hash(password: str) -> str:
    out = subprocess.run([str(binary_path()), "user", "hash"], input=f"{password}\n{password}\n",
                         capture_output=True, text=True, timeout=30, check=True).stdout
    return out.strip().splitlines()[-1]


def ntfy_token() -> str:
    out = subprocess.run([str(binary_path()), "token", "generate"], capture_output=True,
                         text=True, timeout=30, check=True).stdout
    return out.strip().splitlines()[-1]


def setup(auth_path: Path = AUTH_ENV, local_env: Path = LOCAL_ENV, phone_file: Path = PHONE_TOKEN,
          hasher=ntfy_hash, tokener=ntfy_token, out=print) -> None:
    """Never overwrites, never prints a token: output can end up in logs or a chat."""
    for p in (auth_path, local_env, phone_file):
        if os.path.lexists(p):
            raise gate.GateError(f"{p} exists, not overwriting it")
    values = {}
    for user in ("NOTIFY", "PHONE"):
        values[f"{user}_HASH"] = hasher(secrets.token_urlsafe(24))  # a password nobody uses
        values[f"{user}_TOKEN"] = tokener()
    for key, value in values.items():
        pattern = TOKEN if key.endswith("TOKEN") else BCRYPT
        if not pattern.fullmatch(value):
            raise gate.GateError(f"ntfy gave a {key} with the wrong shape, nothing written")
    _write_private(auth_path, "".join(f"{k}={values[k]}\n" for k in KEYS))
    _write_private(local_env, f"NTFY_URL=http://{LISTEN}\nNTFY_TOKEN={values['NOTIFY_TOKEN']}\n")
    _write_private(phone_file, values["PHONE_TOKEN"] + "\n")
    out(f"wrote {auth_path} and {local_env} (mode 600)")
    out(f"the phone token is in {phone_file}: read it in your own terminal when setting up the app")


def _replace_private(path: Path, text: str) -> None:
    """Write a new version next to the old one, then swap it in with one rename."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def rotate_phone(auth_path: Path = AUTH_ENV, phone_file: Path = PHONE_TOKEN,
                 tokener=ntfy_token, out=print) -> None:
    """A new phone token, for a lost phone or a leaked token (threat 88). Only the phone's
    token changes; the old one stops working once the server restarts."""
    values = read_auth(auth_path)
    new = tokener()
    if not TOKEN.fullmatch(new) or new in (values["NOTIFY_TOKEN"], values["PHONE_TOKEN"]):
        raise gate.GateError("ntfy gave an unusable token, nothing changed")
    values["PHONE_TOKEN"] = new
    _replace_private(auth_path, "".join(f"{k}={values[k]}\n" for k in KEYS))
    _replace_private(phone_file, new + "\n")
    out(f"new phone token in {phone_file}")
    out("restart the server: systemctl --user restart julz-ntfy.service")


def main(argv: list[str]) -> int:
    try:
        if argv[:1] == ["--install"] and len(argv) == 2:
            print(f"installed {install(Path(argv[1]))}")
        elif argv == ["--setup"]:
            setup()
        elif argv == ["--rotate-phone"]:
            rotate_phone()
        elif not argv:
            serve()
        else:
            print(__doc__, file=sys.stderr)
            return 2
    except (gate.GateError, OSError, subprocess.SubprocessError, tarfile.TarError) as e:
        print(f"julz-ntfy: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
