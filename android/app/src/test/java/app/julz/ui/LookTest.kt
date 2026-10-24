package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Test

/** SECURITY.md threat 95: a theme is a preset name and an accent from a fixed list, nothing more. */
class LookTest {
    @Test fun roundTrip() {
        val l = LookPrefs("acid", 0xFFF7D58B.toInt())
        assertEquals(l, LookPrefs.decode(l.encode()))
    }

    @Test fun unknownPresetsAndAccentsFallBack() {
        assertEquals(LookPrefs(), LookPrefs.decode("theme=evil;accent=-1"))
        assertEquals(LookPrefs(), LookPrefs.decode("garbage"))
        assertEquals("redstone", LookPrefs.decode("theme=redstone;accent=12345").theme)
        assertEquals(null, LookPrefs.decode("theme=redstone;accent=12345").accent)  // not in the list
    }

    @Test fun lightAccentsGetDarkTextOnThem() {
        assertEquals(true, Palette.isLight(0xFFB8FF3C.toInt()))
        assertEquals(false, Palette.isLight(0xFFE3197A.toInt()))
    }
}
