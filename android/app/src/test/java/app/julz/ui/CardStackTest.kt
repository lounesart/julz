package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** One rhythm inside a card (D1): the Todos list title sat 8 dp over its tasks, the Goals title
 *  12 dp over its goals. Every inset card on these tabs spaces its rows by J.stack. */
class CardStackTest {
    @Test fun todosAndGoalsCardsUseTheStackGap() {
        for (name in listOf("TodosScreen.kt", "GoalsTab.kt")) {
            val lines = File("src/main/java/app/julz/ui/$name").readLines()
            val cards = lines.indices.filter { ".glass().padding(J.inset)" in lines[it] }
            assertTrue(name, cards.isNotEmpty())
            for (i in cards) {
                val head = lines[i] + lines.getOrElse(i + 1) { "" }
                assertTrue("$name:${i + 1}", "spacedBy(J.stack)" in head)
            }
        }
    }

    @Test fun stackIsTwelveAndEightAtBigText() {
        val was = J.scale
        try {
            J.scale = 1f; assertEquals(12f, J.stack.value)
            J.scale = 1.6f; assertEquals(8f, J.stack.value)
        } finally { J.scale = was }
    }
}
