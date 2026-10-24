package app.julz

import android.content.pm.ApplicationInfo
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threat 105: debug tools only in debug builds, and a log that keeps no secrets. */
class DebugTest {
    @Test fun debugOnlyFollowsTheDebuggableFlag() {
        assertTrue(DebugOnly.enabled(ApplicationInfo.FLAG_DEBUGGABLE))
        assertTrue(DebugOnly.enabled(ApplicationInfo.FLAG_DEBUGGABLE or ApplicationInfo.FLAG_HAS_CODE))
        assertFalse(DebugOnly.enabled(0))
        assertFalse(DebugOnly.enabled(ApplicationInfo.FLAG_HAS_CODE or ApplicationInfo.FLAG_ALLOW_BACKUP))
    }

    @Test fun theLogKeepsTheLast200Lines() {
        val log = AppLog.Ring(200)
        for (i in 1..250) log.add(i.toLong(), "line $i")
        val lines = log.lines()
        assertEquals(200, lines.size)
        assertEquals("line 51", lines.first().text)
        assertEquals("line 250", lines.last().text)
    }

    @Test fun aLogLineIsOneShortLine() {
        val log = AppLog.Ring(10)
        log.add(1, "first\nsecond\r\nthird")
        log.add(2, "x".repeat(500))
        assertEquals("first second third", log.lines()[0].text)
        assertEquals(200, log.lines()[1].text.length)
    }

    @Test fun aChatAddressIsLoggedWithoutItsQuery() {
        assertEquals("/c/abc", AppLog.path("https://laptop.tail1234.ts.net/c/abc?q=done%3A%20Walk&submit=false"))
        assertEquals("/", AppLog.path("https://laptop.tail1234.ts.net/?q=secret#frag"))
        assertEquals("/", AppLog.path("https://laptop.tail1234.ts.net"))
        assertEquals("?", AppLog.path("not a url at all %%"))
    }
}
