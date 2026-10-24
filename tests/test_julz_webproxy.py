"""Tests for julz-webproxy.py, the proxy in front of Open WebUI (SECURITY.md 101).
A fake Open WebUI on a random port records what reaches it; nothing touches the real one.
Run: python3 -m unittest discover -s tests -v"""
import asyncio
import unittest
from pathlib import Path

from test_julz_notify import load

proxy = load("julz_webproxy", "julz-webproxy.py")
ROOT = Path(__file__).resolve().parent.parent


class DecideTest(unittest.TestCase):
    def head(self, target, site="cross-site", dest="document", method="GET"):
        h = {}
        if site is not None:
            h["sec-fetch-site"] = site
        if dest is not None:
            h["sec-fetch-dest"] = dest
        return proxy.redirect_for(method, target, h)

    def test_link_from_elsewhere_loses_q_and_submit(self):
        self.assertEqual(self.head("/?q=solved%201,%202"), "/")
        self.assertEqual(self.head("/c/abc?q=x&submit=true&models=julz"), "/c/abc?models=julz")
        self.assertEqual(self.head("/?submit=true"), "/")
        self.assertEqual(self.head("/?Q=x"), None)  # parameter names are case sensitive in the app
        for site in ("cross-site", "same-site", None, "weird"):
            self.assertEqual(self.head("/?q=x", site=site), "/", site)

    def test_own_page_typed_address_and_app_keep_the_prefill(self):
        for site in ("none", "same-origin"):
            self.assertIsNone(self.head("/?q=done%3A%20book&submit=false", site=site), site)

    def test_only_page_loads_are_touched(self):
        self.assertIsNone(self.head("/api/v1/chats?q=x"))
        self.assertIsNone(self.head("/ws/socket.io/?q=x"))
        self.assertIsNone(self.head("/_app/immutable/x.js?q=x"))
        self.assertIsNone(self.head("/?q=x", dest="script"))
        self.assertIsNone(self.head("/?q=x", method="POST"))
        self.assertIsNone(self.head("/"))
        self.assertEqual(self.head("/?q=x", dest=None), "/")  # no fetch metadata: fail closed

    def test_redirect_target_stays_on_this_site(self):
        self.assertEqual(self.head("//evil.example/?q=x"), "/evil.example/")
        self.assertEqual(self.head("/\\evil.example?q=x"), "/")
        # nothing from the request reaches the Location header unchecked (CWE-113)
        self.assertEqual(self.head("/a\rSet-Cookie:x?q=1"), "/")
        self.assertEqual(self.head("/a<script>?q=1"), "/")


class ProxyTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.seen = []

        async def backend(reader, writer):
            head = await reader.readuntil(b"\r\n\r\n")
            self.seen.append(head.decode())
            if b"upgrade: websocket" in head.lower():
                writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n")
                await writer.drain()
                data = await reader.read(100)
                writer.write(b"echo:" + data)
                await writer.drain()
            else:
                length = 0
                for line in head.decode().split("\r\n"):
                    if line.lower().startswith("content-length:"):
                        length = int(line.split(":")[1])
                body = await reader.readexactly(length) if length else b""
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\n\r\npart1")
                await writer.drain()
                writer.write(b"part2:" + body)
                await writer.drain()
            writer.close()

        self.backend = await asyncio.start_server(backend, "127.0.0.1", 0)
        bport = self.backend.sockets[0].getsockname()[1]
        self.proxy = await proxy.start("127.0.0.1", 0, "127.0.0.1", bport)
        self.port = self.proxy.sockets[0].getsockname()[1]

    async def asyncTearDown(self):
        self.proxy.close()
        self.backend.close()

    async def raw(self, data: bytes, then: bytes = b"") -> bytes:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(data)
        await writer.drain()
        if then:
            await asyncio.sleep(0.05)
            writer.write(then)
            await writer.drain()
        out = await asyncio.wait_for(reader.read(), 5)
        writer.close()
        return out

    async def test_cross_site_link_is_redirected_and_never_reaches_open_webui(self):
        out = await self.raw(b"GET /?q=solved%201&submit=true HTTP/1.1\r\nHost: x\r\n"
                             b"Sec-Fetch-Site: cross-site\r\nSec-Fetch-Dest: document\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 303"), out[:40])
        self.assertIn(b"\r\nLocation: /\r\n", out)
        self.assertEqual(self.seen, [])

    async def test_typed_address_passes_with_q_and_streams(self):
        out = await self.raw(b"GET /?q=hi&submit=false HTTP/1.1\r\nHost: x\r\nSec-Fetch-Site: none\r\n"
                             b"Sec-Fetch-Dest: document\r\nConnection: keep-alive\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 200"))
        self.assertIn(b"part1part2:", out)
        head = self.seen[0].lower()
        self.assertIn("get /?q=hi&submit=false", head)
        self.assertIn("connection: close", head)  # one request per connection
        self.assertNotIn("keep-alive", head)

    async def test_post_body_passes(self):
        out = await self.raw(b"POST /api/chat HTTP/1.1\r\nHost: x\r\nContent-Length: 5\r\n\r\nhello")
        self.assertIn(b"part2:hello", out)

    async def test_websocket_upgrade_passes_both_ways(self):
        out = await self.raw(b"GET /ws/socket.io/?EIO=4 HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n"
                             b"Connection: Upgrade\r\n\r\n", then=b"ping")
        self.assertIn(b"101 Switching", out)
        self.assertIn(b"echo:ping", out)
        self.assertIn("connection: upgrade", self.seen[0].lower())

    async def test_second_request_on_the_connection_is_never_served(self):
        out = await self.raw(b"GET / HTTP/1.1\r\nHost: x\r\nSec-Fetch-Site: none\r\n\r\n"
                             b"GET /?q=solved%201 HTTP/1.1\r\nHost: x\r\nSec-Fetch-Site: cross-site\r\n\r\n")
        self.assertEqual(out.count(b"HTTP/1.1 200"), 1)
        self.assertEqual(len(self.seen), 1)
        self.assertNotIn("solved", self.seen[0])

    async def test_bad_requests(self):
        out = await self.raw(b"NONSENSE\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"))
        out = await self.raw(b"GET / HTTP/1.1\r\nX: " + b"a" * 40_000 + b"\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 431"))
        out = await self.raw(b"GET http://evil.example/?q=x HTTP/1.1\r\nHost: x\r\n\r\n")
        self.assertTrue(out.startswith(b"HTTP/1.1 400"))  # absolute form would skip the path checks
        self.assertEqual(self.seen, [])


class UnitTest(unittest.TestCase):
    def test_unit_is_sandboxed_and_local(self):
        text = (ROOT / "systemd" / "julz-webproxy.service").read_text()
        for line in ("NoNewPrivileges=yes", "ProtectSystem=strict", "PrivateTmp=yes",
                     "TemporaryFileSystem=%h:ro", "CapabilityBoundingSet=", "MemoryMax="):
            self.assertIn(line, text, line)
        settings = "\n".join(l for l in text.splitlines() if not l.startswith("#"))
        self.assertNotIn(".config", settings)  # needs no secrets at all
        self.assertNotIn("Documents", settings)
        self.assertEqual(proxy.LISTEN, ("127.0.0.1", 3101))
        self.assertEqual(proxy.BACKEND, ("127.0.0.1", 3100))


if __name__ == "__main__":
    unittest.main()
