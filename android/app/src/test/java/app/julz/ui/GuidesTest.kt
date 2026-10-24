package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class GuidesTest {
    @Test fun everyGuideIsShortPlainText() {
        assertEquals(5, Guides.all.size)
        for (g in Guides.all) {
            assertTrue(g, g.length <= 120)  // about three lines on a 375 dp phone; its own number, not MAX
            assertTrue(g, "://" !in g && "www." !in g)  // words, never a link (91)
            assertTrue(g, g.none { Character.isISOControl(it) })
        }
    }
}
