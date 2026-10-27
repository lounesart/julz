package app.julz.ui

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The web switch's icon (264): a globe off, an eye opened in it on, so on is a shape and not a
 *  colour only (WCAG 1.4.1); cut with Industrial, round otherwise, as the corners are. */
class WebIconTest {
    @After fun reset() { Look.prefs = LookPrefs() }

    @Test fun offIsTheGlobeOnIsTheEyeInEachLook() {
        for ((industrial, off, on) in listOf(Triple(false, "globe", "webOn"), Triple(true, "globeCut", "webOnCut"))) {
            Look.prefs = LookPrefs(industrial = industrial)
            assertEquals(off, Icons.web(false).name)
            assertEquals(on, Icons.web(true).name)
            // A page's row in Sources is a globe in the same look
            assertEquals(off, Icons.globe.name)
        }
    }

    @Test fun theSwitchDrawsItsStateWithTheIcon() {
        val src = File("src/main/java/app/julz/ui/NativeChat.kt").readText()
        val switch = src.substringAfter("private fun WebSwitch(").substringBefore("\n}\n")
        assertTrue("WebSwitch must draw Icons.web(on)", switch.contains("Icons.web("))
    }
}
