#!/usr/bin/env python3
"""Drive the chat inside a debug build of the Julz app over adb (SECURITY.md threat 105).

The debug app turns on WebView inspection; this connects to the app's own DevTools socket
through a random local port that is forwarded for one command only and removed after.
A release build has no such socket, so this does nothing there.

Usage:
  ./devtools.py eval 'document.title'
  ./devtools.py send 'Repeat this link exactly: https://www.bbc.com/weather'
  ./devtools.py last            the last reply, its text and links
  ./devtools.py tap-link bbc    a real tap (adb input) on the first link in the last reply
                                whose address contains the word
  ./devtools.py tap-text Cancel a real tap on the app's own element with that text or name
  ./devtools.py top             which app is in front
"""
import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET

PACKAGE = "app.julz"
SOCKET = re.compile(r"@(webview_devtools_remote_(\d+))$")
BOUNDS = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def adb(*args: str) -> str:
    return subprocess.run(["adb", *args], capture_output=True, text=True, timeout=30, check=True).stdout


def devtools_socket(unix_table: str, pid: str) -> str | None:
    """The app's own socket only: webview_devtools_remote_<pid of app.julz>."""
    for line in unix_table.splitlines():
        m = SOCKET.search(line.strip())
        if m and m.group(2) == pid:
            return m.group(1)
    return None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Cdp:
    """A minimal WebSocket client (RFC 6455) for the Chrome DevTools protocol: text frames,
    masked from us, unmasked from the page, no extensions."""

    def __init__(self, port: int, path: str):
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise ConnectionError("no WebSocket answer")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise ConnectionError(head.split(b"\r\n", 1)[0].decode(errors="replace"))
        self.buffer = head.split(b"\r\n\r\n", 1)[1]
        self.next_id = 0

    def _read(self, n: int) -> bytes:
        while len(self.buffer) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buffer += chunk
        out, self.buffer = self.buffer[:n], self.buffer[n:]
        return out

    def _send(self, text: str):
        data = text.encode()
        mask = os.urandom(4)
        n = len(data)
        head = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                                bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                                bytes([0x80 | 127]) + struct.pack(">Q", n))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _receive(self) -> str:
        message = b""
        while True:
            b0, b1 = self._read(2)
            n = b1 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._read(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(n)
            if b0 & 0x0F == 0x8:
                raise ConnectionError("closed by the page")
            message += payload
            if b0 & 0x80:
                return message.decode()

    def evaluate(self, expression: str):
        self.next_id += 1
        self._send(json.dumps({"id": self.next_id, "method": "Runtime.evaluate", "params": {
            "expression": expression, "returnByValue": True, "awaitPromise": True}}))
        while True:
            answer = json.loads(self._receive())
            if answer.get("id") == self.next_id:
                result = answer.get("result", {})
                if "exceptionDetails" in result:
                    raise RuntimeError(result["exceptionDetails"].get("text", "page error"))
                return result.get("result", {}).get("value")


def connect(port: int) -> Cdp:
    pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json", timeout=10))
    page = next((p for p in pages if p.get("type") == "page" and p.get("url", "").startswith("https://")), None)
    if page is None:
        raise SystemExit("devtools: no chat page open in the app (open the Chat tab first)")
    path = "/" + page["webSocketDebuggerUrl"].split("/", 3)[3]
    return Cdp(port, path)


# The last reply in Open WebUI: its text and its links with their places on the page
LAST = """(() => {
  const all = [...document.querySelectorAll('[id^="message-"]')].filter(e =>
    e.id !== 'message-input-container' && !e.classList.contains('user-message'));
  const box = all[all.length - 1];
  if (!box) return null;
  const links = [...box.querySelectorAll('a[href]')].map(a => { const r = a.getBoundingClientRect();
    return {href: a.href, text: a.innerText, x: r.left + r.width / 2, y: r.top + r.height / 2}; });
  return {text: box.innerText, links: links, dpr: devicePixelRatio, w: innerWidth, h: innerHeight};
})()"""

SEND = """(async (text) => {
  const box = document.querySelector('#chat-input');
  if (!box) return 'no chat input';
  box.focus();
  document.execCommand('selectAll', false, null);
  document.execCommand('insertText', false, text);
  await new Promise(r => setTimeout(r, 400));
  const button = document.querySelector('#send-message-button');
  if (!button) return 'no send button';
  button.click();
  return 'sent';
})(%s)"""


def screen_nodes() -> list:
    """The app's elements on the screen, from the accessibility tree."""
    adb("shell", "uiautomator", "dump", "/sdcard/julz-ui.xml")
    xml = adb("shell", "cat", "/sdcard/julz-ui.xml")
    adb("shell", "rm", "-f", "/sdcard/julz-ui.xml")
    return [n for n in ET.fromstring(xml).iter("node") if n.get("package") == PACKAGE]


def bounds(node) -> tuple[int, int, int, int]:
    return tuple(int(v) for v in BOUNDS.match(node.get("bounds")).groups())


def webview_bounds() -> tuple[int, int, int, int]:
    for node in screen_nodes():
        if node.get("class") == "android.webkit.WebView":
            return bounds(node)
    raise SystemExit("devtools: the chat is not on the screen (a dialog in front?)")


def tap_text(text: str) -> int:
    # An open keyboard covers the tab bar: a tap there lands on a key. Back then only hides it
    if "mInputShown=true" in adb("shell", "dumpsys", "input_method"):
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(0.5)
    for node in screen_nodes():
        if text in (node.get("text"), node.get("content-desc")):
            left, top, right, bottom = bounds(node)
            adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
            print(f"tap {text!r}")
            return 0
    print(f"devtools: nothing called {text!r} on the screen", file=sys.stderr)
    return 1


def top_app() -> str:
    for line in adb("shell", "dumpsys", "activity", "activities").splitlines():
        if "topResumedActivity" in line:
            m = re.search(r"([\w.]+)/", line)
            return m.group(1) if m else "?"
    return "?"


def run(command: str, arg: str | None, cdp: Cdp) -> int:
    if command == "eval":
        print(json.dumps(cdp.evaluate(arg), ensure_ascii=False, indent=1))
    elif command == "send":
        print(cdp.evaluate(SEND % json.dumps(arg)))
    elif command == "last":
        print(json.dumps(cdp.evaluate(LAST), ensure_ascii=False, indent=1))
    elif command == "tap-link":
        last = cdp.evaluate(LAST) or {}
        link = next((l for l in last.get("links", []) if arg in l["href"]), None)
        if link is None:
            print("devtools: no such link in the last reply", file=sys.stderr)
            return 1
        left, top, right, bottom = webview_bounds()
        scale = (right - left) / last["w"]
        x, y = int(left + link["x"] * scale), int(top + link["y"] * scale)
        print(f"tap {link['href']} at {x},{y}")
        adb("shell", "input", "tap", str(x), str(y))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


def main(argv: list[str]) -> int:
    # Screen only, no page: these need no inspection socket
    if argv[:1] == ["tap-text"] and len(argv) == 2:
        return tap_text(argv[1])
    if argv == ["top"]:
        print(top_app())
        return 0
    if not argv or argv[0] not in ("eval", "send", "last", "tap-link") or \
            (argv[0] != "last" and len(argv) != 2):
        print(__doc__, file=sys.stderr)
        return 2
    pid = adb("shell", "pidof", PACKAGE).strip()
    if not pid.isdigit():
        print("devtools: the app is not running", file=sys.stderr)
        return 1
    name = devtools_socket(adb("shell", "cat", "/proc/net/unix"), pid)
    if name is None:
        print("devtools: no inspection socket (a release build, or the chat was never opened)", file=sys.stderr)
        return 1
    port = free_port()
    adb("forward", f"tcp:{port}", f"localabstract:{name}")
    try:
        return run(argv[0], argv[1] if len(argv) > 1 else None, connect(port))
    finally:
        adb("forward", "--remove", f"tcp:{port}")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
