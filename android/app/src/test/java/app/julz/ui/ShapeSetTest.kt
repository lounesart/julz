package app.julz.ui

import androidx.compose.foundation.shape.CutCornerShape
import androidx.compose.foundation.shape.RoundedCornerShape
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ShapeSetTest {
    @Test fun roundByDefaultCutWhenIndustrial() {
        for (cut in listOf(false, true)) {
            val s = ShapeSet(cut)
            for (shape in listOf(s.small, s.row, s.card, s.pill, s.sheetTop))
                assertTrue(shape.toString(), if (cut) shape is CutCornerShape else shape is RoundedCornerShape)
        }
    }

    @Test fun industrialIsAnOptionOffUnlessStored() {
        assertFalse(LookPrefs().industrial)
        assertEquals(LookPrefs(industrial = true), LookPrefs.decode(LookPrefs(industrial = true).encode()))
        assertFalse(LookPrefs.decode("theme=magenta;accent=;cut=yes").industrial)
    }

    @Test fun theSpecSheetPresetIsNavyWithAKnownAccent() {
        val p = Palette.presets.first { it.id == "specsheet" }
        assertTrue(Palette.accents.any { it.second == p.accent })  // so the icon alias exists (135)
        assertTrue(Palette.contrast(Palette.readable(p.accent, p.bg), p.bg) >= 4.5)
    }
}
