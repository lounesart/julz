package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** One switch and one slider in the app's colours (F1, D1): the stock Material ones drew a
 *  lavender track and a grey thumb on the dark cards. Screens use JulzSwitch and JulzSlider. */
class ControlsTest {
    private val ui = File("src/main/java/app/julz")
    private val stock = Regex("""material3\.(Switch|Slider)\b""")

    @Test fun onlyComponentsTouchTheStockControls() {
        val users = ui.walk().filter { it.extension == "kt" && stock.containsMatchIn(it.readText()) }.map { it.name }.toList()
        assertEquals(listOf("Components.kt"), users)
    }

    // Every colour role set, so no Material default (lavender, lilac) can show through
    @Test fun theSwitchSetsEveryColour() {
        val src = File(ui, "ui/Components.kt").readText()
        for (role in listOf("checkedThumbColor", "checkedTrackColor", "checkedBorderColor",
                "uncheckedThumbColor", "uncheckedTrackColor", "uncheckedBorderColor"))
            assertTrue(role, src.contains("$role ="))
    }

    @Test fun theSliderSetsEveryColour() {
        val src = File(ui, "ui/Components.kt").readText()
        for (role in listOf("thumbColor", "activeTrackColor", "inactiveTrackColor", "activeTickColor", "inactiveTickColor"))
            assertTrue(role, src.contains("$role ="))
    }
}
