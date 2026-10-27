package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import androidx.compose.ui.graphics.toArgb

class PaletteTest {
    @Test fun accentTextIsReadableOnEveryThemeWithEveryAccent() {
        // WCAG 1.4.3: text at least 4.5:1, the signing warning included
        for (p in Palette.presets) for ((name, a) in Palette.accents + (p.name to p.accent)) {
            val t = Palette.readable(a, p.bg)
            assertTrue("$name on ${p.name}: ${Palette.contrast(t, p.bg)}", Palette.contrast(t, p.bg) >= 4.5)
        }
    }

    @Test fun anAccentThatIsAlreadyReadableStaysAsItIs() {
        val bg = Palette.presets.first().bg
        for (a in listOf(0xFFB8FF3C.toInt(), 0xFF7FE3F0.toInt(), 0xFFF7D58B.toInt())) assertEquals(a, Palette.readable(a, bg))
    }

    /** A big solid shape in the accent (267): between 3 and 8 to 1 on the background, so a neon
     *  accent stops glaring on near black (Acid was 16.5, as bright as the text) and Red Stone
     *  clears WCAG 1.4.11 (it was 2.9); its ink reads at 4.5 or more (1.4.3) */
    @Test fun aFilledShapeSitsInItsBandOnEveryThemeWithEveryAccent() {
        for (p in Palette.presets) for ((name, a) in Palette.accents + (p.name to p.accent)) {
            val f = Palette.fill(a, p.bg)
            val c = Palette.contrast(f, p.bg)
            assertTrue("$name on ${p.name}: $c", c >= 3.0 && c <= 8.0)
            assertTrue("ink on $name: ${Palette.contrast(Palette.onFill(f), f)}", Palette.contrast(Palette.onFill(f), f) >= 4.5)
        }
    }

    // The default keeps its white ink: Magenta darkens a hair rather than flip to a dark icon
    @Test fun magentaKeepsWhiteInk() {
        val p = Palette.presets.first()
        assertEquals(0xFFFFFFFF.toInt(), Palette.onFill(Palette.fill(p.accent, p.bg)))
    }

    @Test fun aFillAlreadyInItsBandStaysAsItIs() {
        val bg = Palette.presets.first().bg
        val orange = 0xFFFF7A3D.toInt()
        assertEquals(orange, Palette.fill(orange, bg))
    }

    @Test fun contrastMatchesKnownValues() {
        assertEquals(21.0, Palette.contrast(0xFFFFFFFF.toInt(), 0xFF000000.toInt()), 0.01)
        assertEquals(1.0, Palette.contrast(0xFF777777.toInt(), 0xFF777777.toInt()), 0.01)
    }

    /** Every theme against every colour a screen writes text in (22d integrity): History's tags
     *  write a kind's colour on a faint tint of itself, grey text sits on the page */
    @Test fun everyThemeKeepsItsTextReadable() {
        fun mix(a: Int, b: Int, t: Double): Int {
            fun ch(s: Int) = ((a shr s and 0xFF) * (1 - t) + (b shr s and 0xFF) * t).toInt() shl s
            return (0xFF shl 24) or ch(16) or ch(8) or ch(0)
        }
        for (p in Palette.presets) {
            for (k in app.julz.feed.Kind.entries) {
                val tint = J.tint(k).toArgb()
                val under = mix(p.bg, tint, 0.16)  // the tag's own background
                assertTrue("${k.name} tag on ${p.name}: ${Palette.contrast(tint, under)}", Palette.contrast(tint, under) >= 4.5)
            }
            // Code colours on the code box, raise (8% white) over the page (204)
            val box = mix(p.bg, 0xFFFFFFFF.toInt(), 0x14 / 255.0)
            for (t in app.julz.feed.Tok.entries) {
                val ink = J.code(t).toArgb()
                assertTrue("${t.name} code on ${p.name}: ${Palette.contrast(ink, box)}", Palette.contrast(ink, box) >= 4.5)
            }
            assertTrue("grey text on ${p.name}", Palette.contrast(0xFFABA4AC.toInt(), p.bg) >= 4.5)
            assertTrue("faint text on ${p.name}: ${Palette.contrast(0xFF7E777F.toInt(), p.bg)}", Palette.contrast(0xFF7E777F.toInt(), p.bg) >= 3.0)
        }
    }
}
