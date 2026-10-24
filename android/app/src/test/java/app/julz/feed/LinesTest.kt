package app.julz.feed

import java.io.StringReader
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threat 92: one endless line from the server must not fill the phone's memory. */
class LinesTest {
    @Test fun splitsOnNewlines() {
        val r = BoundedLines(StringReader("a\nbb\n\nccc"), 10)
        assertEquals("a", r.next())
        assertEquals("bb", r.next())
        assertEquals("", r.next())
        assertEquals("ccc", r.next())
        assertNull(r.next())
    }

    @Test fun anOverlongLineIsSkippedAndReadingGoesOn() {
        val r = BoundedLines(StringReader("ok\n" + "x".repeat(50) + "\nnext\n"), 10)
        assertEquals("ok", r.next())
        assertEquals("next", r.next())  // the long one is gone, the stream is still usable
        assertNull(r.next())
    }

    @Test fun anEndlessLineEndsAtEndOfStream() {
        val r = BoundedLines(StringReader("y".repeat(100_000)), 4_096)
        assertNull(r.next())
    }

    @Test fun carriageReturnIsDropped() {
        assertEquals("a", BoundedLines(StringReader("a\r\n"), 10).next())
    }
}
