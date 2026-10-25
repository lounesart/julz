package app.julz.ui

import androidx.compose.runtime.Composable
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import app.julz.feed.Kind
import app.julz.feed.Notice
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.util.Locale
import java.util.TimeZone

/** Screenshots of the main screens against goldens in src/test/snapshots (184, threat 150).
 *  The regressions of 19 Oct (126, 127) were layout ones no unit test could see: rows and the
 *  pinned button under the floating tab bar. So screens are drawn in the real Shell. */
class ScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_5)

    // Times on screen follow the zone and locale: fixed, so a golden is the same on any machine
    private val zone = TimeZone.getDefault()
    private val locale = Locale.getDefault()

    @Before fun fix() { TimeZone.setDefault(TimeZone.getTimeZone("UTC")); Locale.setDefault(Locale.US) }
    @After fun restore() { TimeZone.setDefault(zone); Locale.setDefault(locale) }

    private val origins = Origins.from("https://laptop.tail1234.ts.net:8444")!!

    @Composable
    private fun shell(section: Screen, content: @Composable () -> Unit) =
        Shell(wide = false, bar = { TabBar(section, 2, it, {}, {}, {}, {}, {}) }, content = content)

    private val todos = run {
        val l = "␞"; val f = "␟"
        Notice("t1", 1761400800, Kind.TODO, "Todos",
            "v3${f}${"c".repeat(64)}" +
                "${l}cpts${f}2${f}7${f}4${f}1${f}Finish the SQL injection module${f}Write up the AD lab" +
                "${f}Review nmap flags${f}Redo the pivoting box${f}Read the Kerberos chapter" +
                "${f}Set up the lab VM${f}Take notes on Responder" +
                "${l}get_job${f}1${f}4${f}3${f}0${f}Update the CV${f}Apply to two helpdesk roles" +
                "${f}Practise the A+ questions${f}Send the cover letter" +
                "${l}week${f}0${f}3${f}3${f}0${f}Physio on Tuesday${f}Call the bank${f}Buy a USB hub")
    }

    @Test
    fun firstRun() = paparazzi.snapshot {
        FirstRun("The server refused the token. Enter the new one.") { _, _, _ -> null }
    }

    // A picked task brings the pinned Apply bar: it must sit above the tab bar (126)
    @Test
    fun todosPicked() = paparazzi.snapshot {
        shell(Screen.TODOS) {
            TodosScreen(listOf(todos), origins, listOf(pickKey("cpts", "Review nmap flags")), {}) {}
        }
    }

    @Test
    fun todosUnpicked() = paparazzi.snapshot {
        shell(Screen.TODOS) { TodosScreen(listOf(todos), origins, emptyList(), {}) {} }
    }
}
