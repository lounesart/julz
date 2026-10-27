package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Test
import java.io.File

/** Big solid shapes take the accent's fill tone (267); the accent itself fills small marks only.
 *  A new background(J.acc) must be one of these, or use J.accFill */
class AccentFillTest {
    private val marks = mapOf(
        "App.kt" to 1,           // the tab badge, 16 dp
        "GoalsTab.kt" to 1,      // a goal's thin bar
        "MarkdownView.kt" to 1,  // a chart's thin bar
        "NativeChat.kt" to 2,    // the thinking dot and my message's 3 dp line
    )

    @Test fun onlySmallMarksFillWithTheAccent() {
        val solid = Regex("""background\(J\.acc\)""")
        val found = File("src/main/java/app/julz").walk().filter { it.extension == "kt" }
            .associate { it.name to solid.findAll(it.readText()).count() }.filterValues { it > 0 }
        assertEquals(marks, found.toSortedMap())
    }
}
