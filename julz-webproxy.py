#!/usr/bin/env python3
"""A small proxy in front of Open WebUI against one click messages, SECURITY.md threat 101.

Open WebUI reads ?q= from the address and sends it as my message unless submit=false is also
there. So a link to my own Julz, from an injected answer, a web page or a note, could send
"done: ..." or "solved 1, 2" as me. tailscale serve points here (127.0.0.1:3101) and this
passes everything on to Open WebUI (127.0.0.1:3100), except one case: a page load whose
address carries q or submit and that did not start on this site or from me typing it
(Sec-Fetch-Site other than none or same-origin, missing included) gets a redirect to the same
page without those two. The phone app and my own typing still prefill.

- one request per connection: every request is forwarded with Connection: close, so a second
  request on the same connection is never served unchecked
- WebSocket upgrades and streamed answers pass through as bytes
- it logs no headers and no bodies: cookies and tokens pass through it
"""
import asyncio
import re
import sys
from functools import partial
from urllib.parse import parse_qsl, quote, urlencode

LISTEN = ("127.0.0.1", 3101)
BACKEND = ("127.0.0.1", 3100)
MAX_HEAD = 32_768  # below asyncio's own 64 KB, so the limit is ours
TRUSTED_SITES = ("none", "same-origin")
PREFILL = ("q", "submit")
# Paths that are never a chat page, so a q there is someone else's parameter
NOT_PAGES = ("/api", "/ws", "/_app", "/static", "/ollama", "/openai", "/oauth", "/manifest",
             "/favicon")
SAFE_PATH = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*")
DROP = ("connection", "keep-alive", "proxy-connection", "upgrade")


def redirect_for(method: str, target: str, headers: dict) -> str | None:
    """Where to send a page load that would prefill from a link, or None to pass it on."""
    if method not in ("GET", "HEAD") or "?" not in target:
        return None
    path, _, query = target.partition("?")
    if path.startswith(NOT_PAGES):
        return None
    dest = headers.get("sec-fetch-dest")
    if dest is not None and dest != "document":
        return None
    pairs = parse_qsl(query, keep_blank_values=True)
    if not any(k in PREFILL for k, _ in pairs):
        return None
    if headers.get("sec-fetch-site") in TRUSTED_SITES:
        return None
    path = re.sub(r"^/+", "/", path)  # //host would leave this site
    if not SAFE_PATH.fullmatch(path):  # no backslash, no CR, nothing for a header
        path = "/"
    rest = [(k, v) for k, v in pairs if k not in PREFILL]
    return path + ("?" + urlencode(rest, quote_via=quote) if rest else "")


def _parse(head: bytes):
    lines = head.decode("latin-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) != 3 or not parts[0].isalpha() or not parts[2].startswith("HTTP/1.") \
            or not parts[1].startswith("/"):
        return None
    headers, kept = {}, []
    for line in lines[1:]:
        if not line:
            continue
        name, sep, value = line.partition(":")
        if not sep or not name or name != name.strip():
            return None
        headers[name.lower()] = value.strip()
        kept.append(line)
    return parts[0], parts[1], headers, lines[0], kept


async def _reply(writer, status: str, extra: str = ""):
    writer.write(f"HTTP/1.1 {status}\r\n{extra}Content-Length: 0\r\nConnection: close\r\n\r\n"
                 .encode("latin-1"))
    await writer.drain()


async def _pipe(reader, writer):
    try:
        while data := await reader.read(65_536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError):
        pass


async def handle(backend: tuple, reader, writer):
    try:
        try:
            head = await reader.readuntil(b"\r\n\r\n")
        except asyncio.LimitOverrunError:
            return await _reply(writer, "431 Request Header Fields Too Large")
        except (asyncio.IncompleteReadError, ConnectionError):
            return
        parsed = _parse(head[:-4])
        if parsed is None:
            return await _reply(writer, "400 Bad Request")
        method, target, headers, request_line, kept = parsed
        to = redirect_for(method, target, headers)
        if to is not None:
            print("julz-webproxy: dropped a prefill that came from a link", file=sys.stderr)
            return await _reply(writer, "303 See Other", f"Location: {to}\r\nCache-Control: no-store\r\n")
        upgrade = headers.get("upgrade", "").lower() == "websocket"
        lines = [request_line] + [l for l in kept if l.split(":", 1)[0].strip().lower() not in DROP]
        lines += ["Upgrade: websocket", "Connection: Upgrade"] if upgrade else ["Connection: close"]
        try:
            b_reader, b_writer = await asyncio.open_connection(*backend)
        except OSError:
            return await _reply(writer, "502 Bad Gateway")
        b_writer.write(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
        await b_writer.drain()
        up = asyncio.create_task(_pipe(reader, b_writer))
        await _pipe(b_reader, writer)  # Open WebUI closes after one response
        up.cancel()
        b_writer.close()
    finally:
        writer.close()


async def start(host: str, port: int, backend_host: str, backend_port: int):
    return await asyncio.start_server(partial(handle, (backend_host, backend_port)), host, port,
                                      limit=MAX_HEAD)


async def _main():
    server = await start(*LISTEN, *BACKEND)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(_main())
