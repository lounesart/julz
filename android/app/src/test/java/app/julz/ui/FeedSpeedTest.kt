package app.julz.ui

import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** A Feed tab change froze a frame (22g): FeedScreen built kept and shown again on every
 *  recomposition, new lists each time, so Messages could not skip and recomposed twice a tap,
 *  rows and wheel, about 50 ms of compose (measured 27 Oct). Remembered, it skips. */
class FeedSpeedTest {
    private val src = File("src/main/java/app/julz/ui/FeedScreens.kt").readText()

    @Test fun keptAndShownAreRemembered() {
        assertTrue(Regex("""val kept = remember\(notices, cleared\)""").containsMatchIn(src))
        assertTrue(Regex("""val shown = remember\(kept, filter\)""").containsMatchIn(src))
    }
}
