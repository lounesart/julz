package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/** The chat box on the 4 dp grid (266): a typed dp in the composer, its web switch and its wheel
 *  is 0, a 1 dp line, or a multiple of 4. The controls sat 6 dp from the box (2 inset + 4) until
 *  this was measured against Claude's 8 */
class ComposerGridTest {
    @Test fun theComposerSpacesInStepsOfFour() {
        val src = File("src/main/java/app/julz/ui/NativeChat.kt").readText()
        val box = src.substringAfter("/** Pinned at the bottom (26b").substringBefore("/** The modes, at most one on")
        val off = Regex("""(?<![\w.])(\d+(?:\.\d+)?)\.dp\b""").findAll(box).map { it.groupValues[1].toDouble() }
            .filter { it != 0.0 && it != 1.0 && it % 4 != 0.0 }.toList()
        assertEquals("dp off the 4 grid in the chat box", emptyList<Double>(), off)
    }
}
