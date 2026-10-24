"""Tiny Open WebUI API client shared by the Julz scripts. Standard library only."""
import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:3100"
# julz-sync's key: knowledge and files, no model (SECURITY.md 14)
ENV_FILE = Path.home() / ".config" / "julz" / "api.env"
# user@julz.local's key: the model, and read on the collections, for the evals and julz-chat
CHAT_ENV_FILE = ENV_FILE.with_name("chat.env")
KB_NAME = "julz-mem"
# Notes Claude wrote and I kept (PLAN-keep.md). Never mixed into julz-mem (threat 58)
CLAUDE_KB_NAME = "julz-claude"
# 30 files a page: 200 pages is 6000 notes, far past the vault, and stops a runaway listing
MAX_PAGES = 200


def load_key(env_file=ENV_FILE):
    # The key acts as one of my accounts, so refuse to use it from a file others can read
    if env_file.stat().st_mode & 0o077:
        sys.exit(f"{env_file} must be mode 600 (chmod 600 {env_file})")
    for line in env_file.read_text().splitlines():
        if line.startswith("OPENWEBUI_API_KEY="):
            return line.split("=", 1)[1].strip()
    sys.exit(f"OPENWEBUI_API_KEY missing in {env_file}")


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
    ctype = "text/plain" if filename.endswith(".txt") else "text/markdown"
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: {ctype}\r\n\r\n"
    ).encode() + path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    return api(key, "POST", "/api/v1/files/?process=true&process_in_background=false",
               body=body, content_type=f"multipart/form-data; boundary={boundary}")


def kb_files(key, kb_id):
    """Every file in a knowledge base. 0.11.4 gives 30 a page with a total and ignores limit
    (BACKLOG 205), so read every page before anyone removes: a removal shifts the pages up."""
    files, total = {}, None
    for page in range(1, MAX_PAGES + 1):
        resp = api(key, "GET", f"/api/v1/knowledge/{kb_id}/files?page={page}")
        total = resp.get("total")
        new = [f for f in resp["items"] if f["id"] not in files]
        files.update((f["id"], f) for f in new)
        if not new or (total is not None and len(files) >= total):
            break
    else:
        sys.exit(f"knowledge {kb_id}: still more files after {MAX_PAGES} pages")
    if total is not None and len(files) < total:
        # A short list would leave stale copies in her memory; fail before removing any
        sys.exit(f"knowledge {kb_id}: listed {len(files)} of {total} files")
    return list(files.values())


def find_kb(key, name=KB_NAME):
    resp = api(key, "GET", "/api/v1/knowledge/")
    items = resp["items"] if isinstance(resp, dict) else resp
    return next((kb for kb in items if kb["name"] == name), None)
