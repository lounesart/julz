package app.julz.ui

import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import org.junit.Rule
import org.junit.Test

/** Screenshots of the main screens against goldens in src/test/snapshots (184, threat 150).
 *  The regressions of 19 Oct (126, 127) were layout ones no unit test could see. */
class ScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_5)

    @Test
    fun firstRun() = paparazzi.snapshot {
        FirstRun("The server refused the token. Enter the new one.") { _, _, _ -> null }
    }
}
