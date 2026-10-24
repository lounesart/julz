package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class A11yTest {
    @Test fun textScaleStaysInItsRange() {
        assertEquals(0.85f, A11yPrefs.clampScale(0.1f), 0.001f)
        assertEquals(2.0f, A11yPrefs.clampScale(9f), 0.001f)
        assertEquals(1.3f, A11yPrefs.clampScale(1.3f), 0.001f)
        assertEquals(1.0f, A11yPrefs.clampScale(Float.NaN), 0.001f)
    }

    @Test fun storedValuesRoundTrip() {
        val a = A11yPrefs(scale = 1.6f, bold = true, contrast = false, solid = true, labels = true)
        assertEquals(a, A11yPrefs.decode(a.encode()))
    }

    @Test fun anythingOddFallsBackToDefaults() {
        assertEquals(A11yPrefs(), A11yPrefs.decode("garbage"))
        assertEquals(A11yPrefs(), A11yPrefs.decode(""))
        val d = A11yPrefs.decode("scale=7;bold=yes")
        assertEquals(2.0f, d.scale, 0.001f)  // clamped
        assertFalse(d.bold)  // only "true" counts
    }

    @Test fun guidesShowUntilIHideThem() {
        assertTrue(A11yPrefs().guides)
        assertTrue(A11yPrefs.decode("scale=1.0;bold=false").guides)  // stored before guides existed
        assertTrue(A11yPrefs.decode("guides=no").guides)  // only "false" hides them
        assertFalse(A11yPrefs.decode(A11yPrefs(guides = false).encode()).guides)
    }

    @Test fun bigTextShowsTabNames() {
        assertFalse(A11yPrefs(scale = 1.0f).showLabels)
        assertTrue(A11yPrefs(scale = 1.6f).showLabels)
        assertTrue(A11yPrefs(labels = true).showLabels)
    }
}
