package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SizeClassTest {
    @Test fun heightClassesFollowAndroidsBreakpoints() {
        assertEquals(SizeClass.COMPACT, SizeClass.ofHeight(360))   // a phone on its side
        assertEquals(SizeClass.COMPACT, SizeClass.ofHeight(479))
        assertEquals(SizeClass.MEDIUM, SizeClass.ofHeight(480))
        assertEquals(SizeClass.MEDIUM, SizeClass.ofHeight(899))
        assertEquals(SizeClass.EXPANDED, SizeClass.ofHeight(900))  // a phone upright
    }

    @Test fun theRailIsForCompactHeightNotForWideScreens() {
        assertTrue(SizeClass.rail(widthDp = 834, heightDp = 375))   // landscape phone
        assertFalse(SizeClass.rail(widthDp = 375, heightDp = 834))  // upright phone
        // split screen, upper half: wider than tall, but tall enough for the bottom bar
        assertFalse(SizeClass.rail(widthDp = 600, heightDp = 520))
    }
}
