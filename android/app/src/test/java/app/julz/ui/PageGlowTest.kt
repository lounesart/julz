package app.julz.ui

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Test

class PageGlowTest {
    /** The page's lower glow is the design's (257, my note 26 Oct: the bottom lacked the colours of
     *  the top): read from tokens.css, so the app cannot drift from it again */
    @Test fun lowerGlowIsTheDesigns() {
        val css = File("../../docs/design/tokens.css").readText()
        val m = Regex("""radial-gradient\((\d+)% (\d+)% at (\d+)% (\d+)%,#7FE3F0([0-9A-F]{2}) 0%,#7FE3F000 (\d+)%\)""").find(css)!!
        val (w, h, x, y, alpha, stop) = m.destructured
        val e = PageGlow.lower(1000f, 2000f)
        assertEquals(x.toFloat() / 100 * 1000f, e.cx, 0.5f)
        assertEquals(y.toFloat() / 100 * 2000f, e.cy, 0.5f)
        // CSS sizes the ellipse by its radii in percent; the colour is gone at the stop
        assertEquals(w.toFloat() / 100 * stop.toFloat() / 100 * 1000f, e.rx, 0.5f)
        assertEquals(h.toFloat() / 100 * stop.toFloat() / 100 * 2000f, e.ry, 0.5f)
        assertEquals(alpha.toInt(16) / 255f, PageGlow.LOWER_ALPHA, 0.001f)
    }
}
