package app.julz.ui

import java.net.SocketTimeoutException
import java.net.URI
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threat 104: which links the app asks about, and what an answer means. */
class LinkCheckTest {
    @Test fun onlyMissingPagesAndMissingSitesCountAsBroken() {
        assertEquals(LinkCheck.Verdict.BROKEN, LinkCheck.verdict(404, null))
        assertEquals(LinkCheck.Verdict.BROKEN, LinkCheck.verdict(410, null))
        assertEquals(LinkCheck.Verdict.NO_SITE, LinkCheck.verdict(null, UnknownHostException("x")))
        for (code in listOf(200, 204, 301, 302, 400, 401, 403, 405, 429, 500, 503))
            assertEquals("$code", LinkCheck.Verdict.OPEN, LinkCheck.verdict(code, null))
        // Cannot tell: open as before, never block
        assertEquals(LinkCheck.Verdict.OPEN, LinkCheck.verdict(null, SocketTimeoutException()))
        assertEquals(LinkCheck.Verdict.OPEN, LinkCheck.verdict(null, SSLHandshakeException("x")))
        assertEquals(LinkCheck.Verdict.OPEN, LinkCheck.verdict(null, null))
    }

    @Test fun publicSitesAreChecked() {
        for (ok in listOf("https://www.bbc.com/weather/3088171", "https://en.wikipedia.org/wiki/Pozna%C5%84",
                          "https://bbc.co.uk/", "https://www.bbc.com:443/x"))
            assertTrue(ok, LinkCheck.worthChecking(URI(ok)))
    }

    @Test fun myOwnNetworkIsNeverRequestedByTheApp() {
        for (inside in listOf(
            "http://www.bbc.com/",  // https only
            "https://192.168.1.1/admin", "https://10.0.0.1/", "https://100.64.0.1/", "https://127.0.0.1:8090/",
            "https://[::1]/", "https://[fd7a:115c:a1e0::1]/", "https://0x7f000001/", "https://2130706433/",
            "https://localhost/", "https://router/", "https://printer.local/", "https://nas.lan/",
            "https://x.internal/", "https://box.home.arpa/", "https://laptop.tail1234.ts.net:8443/",
            "https://LAPTOP.TAIL1234.TS.NET./", "https://user@www.bbc.com/", "https://www.bbc.com:8080/",
            "not a url",
        )) assertFalse(inside, LinkCheck.worthChecking(runCatching { URI(inside) }.getOrNull()))
    }

    @Test fun aPublicNameThatPointsInsideIsNotRequestedEither() {
        fun ip(s: String) = java.net.InetAddress.getByName(s)  // literals only, no lookup
        for (inside in listOf("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.0.10", "169.254.1.1",
                              "100.64.0.1", "100.127.255.254", "0.0.0.0", "::1", "fe80::1", "fd7a:115c:a1e0::1",
                              "fc00::1", "::ffff:127.0.0.1", "224.0.0.1"))
            assertFalse(inside, LinkCheck.public(listOf(ip("151.101.0.81"), ip(inside))))
        assertTrue(LinkCheck.public(listOf(ip("151.101.0.81"), ip("2a04:4e42::81"), ip("100.128.0.1"))))
        assertFalse(LinkCheck.public(emptyList()))
    }
}
