package app.julz.ui

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class LauncherIconTest {
    @Test fun offMeansMagentaWhateverTheAccent() {
        for ((_, a) in Palette.accents) assertEquals("IconMagenta", LauncherIcon.aliasFor(LookPrefs(accent = a)))
    }

    @Test fun onFollowsTheAccentAndTheThemesOwnAccent() {
        assertEquals("IconCyan", LauncherIcon.aliasFor(LookPrefs(accent = 0xFF7FE3F0.toInt(), icon = true)))
        assertEquals("IconRedStone", LauncherIcon.aliasFor(LookPrefs(theme = "redstone", icon = true)))
        assertEquals("IconMagenta", LauncherIcon.aliasFor(LookPrefs(accent = 0x12345678, icon = true)))  // not a known accent
    }

    @Test fun exactlyOneEnabledAndItComesFirst() {
        // the new icon on before the others off: Julz is never without a launcher entry
        for (name in LauncherIcon.names) {
            val steps = LauncherIcon.steps(name)
            assertEquals(name to true, steps.first())
            assertEquals(1, steps.count { it.second })
            // each name once: the chosen one is never switched off again after it went on
            assertEquals(LauncherIcon.names.size, steps.size)
            assertEquals(LauncherIcon.names.toSet(), steps.map { it.first }.toSet())
        }
    }

    @Test fun theNamesMatchCheckApkAndTheManifest() {
        val py = File("../check-apk.py").readText()
        val icons = Regex("""ICONS = \(([^)]*)\)""").find(py)!!.groupValues[1].split(",").map { it.trim().trim('"') }
        assertEquals(icons.map { "Icon$it" }, LauncherIcon.names)
        val manifest = File("src/main/AndroidManifest.xml").readText()
        for (name in LauncherIcon.names) {
            val alias = Regex("""<activity-alias[^>]*android:name="\.$name"[^>]*>""").find(manifest)?.value
            assertTrue("$name declared", alias != null)
            assertTrue("$name opens MainActivity", "android:targetActivity=\".MainActivity\"" in alias!!)
            assertEquals("$name enabled by default", name == "IconMagenta", "android:enabled=\"true\"" in alias)
        }
        assertFalse("MainActivity not exported", Regex("""android:name="\.MainActivity"\s+android:exported="true"""").containsMatchIn(manifest))
    }

    @Test fun lookOptionsAreOffUnlessStoredTrue() {
        assertFalse(LookPrefs().outline); assertFalse(LookPrefs().icon)
        assertEquals(LookPrefs(outline = true, icon = true), LookPrefs.decode(LookPrefs(outline = true, icon = true).encode()))
        val odd = LookPrefs.decode("theme=magenta;accent=;outline=yes;icon=1")
        assertFalse(odd.outline); assertFalse(odd.icon)  // only "true" counts
        assertFalse(LookPrefs.decode("theme=magenta;accent=").icon)  // stored before the options existed
    }

    /** Ids show unless I hide them (asked 18 Oct); only "false" hides, as guides */
    @Test fun idsShowUnlessHidden() {
        assertTrue(LookPrefs().showIds)
        assertTrue(LookPrefs.decode("theme=magenta;accent=").showIds)  // stored before the option
        assertTrue(LookPrefs.decode("theme=magenta;accent=;ids=no").showIds)
        assertFalse(LookPrefs.decode(LookPrefs(showIds = false).encode()).showIds)
    }
}
