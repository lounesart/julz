"""Tiny Open WebUI API client shared by the Julz scripts. Standard library only."""
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:3100"
ENV_FILE = Path.home() / ".config" / "julz" / "api.env"
KB_NAME = "julz-mem"


def load_key():
    # The key acts as my admin account, so refuse to use it from a file others can read
    if ENV_FILE.stat().st_mode & 0o077:
        sys.exit(f"{ENV_FILE} must be mode 600 (chmod 600 {ENV_FILE})")
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("OPENWEBUI_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit(f"OPENWEBUI_API_KEY missing in {ENV_FILE}")


def api(key, method, path, data=None, body=None, content_type=None, timeout=120):
    headers = {"Authorization": f"Bearer {key}"}
    if data is not None:
        body = json.dumps(data).encode()
        content_type = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read() or "null")
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}")


def upload_file(key, path, filename):
    """Upload one file and wait until it is embedded (process_in_background=false)."""
    if any(c in filename for c in '"\r\n'):
        raise ValueError(f"unsafe file name: {filename!r}")
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: text/markdown\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return api(key, "POST", "/api/v1/files/?process=true&process_in_background=false",
               body=body, content_type=f"multipart/form-data; boundary={boundary}")


def find_kb(key):
    resp = api(key, "GET", "/api/v1/knowledge/")
    items = resp["items"] if isinstance(resp, dict) else resp
    return next((kb for kb in items if kb["name"] == KB_NAME), None)
