package app.julz.ui

import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TabsTest {
    private fun slope(f: (Float) -> Float, x: Float, h: Float = 1e-3f) =
        (f((x + h).coerceAtMost(1f)) - f((x - h).coerceAtLeast(0f))) / ((x + h).coerceAtMost(1f) - (x - h).coerceAtLeast(0f))

    // Weight and impact (258, my pick 26 Oct: the firm spring looked too static): the light sets
    // off from rest and is still moving when it reaches its tab, so the stop reads as a hit
    @Test fun theTravelArrivesMoving() {
        val f = { x: Float -> Tabs.travel.transform(x) }
        assertTrue("sets off slow: ${slope(f, 0f)}", slope(f, 0f) < 0.5f)
        assertTrue("arrives fast: ${slope(f, 1f)}", slope(f, 1f) >= 1.5f)
    }

    // Heavy, never elastic: no overshoot, never back, on the way
    @Test fun theTravelNeverOvershoots() {
        val ys = (0..1000).map { Tabs.travel.transform(it / 1000f) }
        assertTrue(ys.all { it in -1e-4f..1.0001f })
        assertTrue(ys.zipWithNext().all { (a, b) -> b >= a - 1e-5f })
    }

    // A longer way takes longer, as a heavier thing would, but never drags
    @Test fun aFartherTabTakesLongerWithinBounds() {
        val ms = (1..4).map { Tabs.travelMs(it.toFloat()) }
        assertTrue(ms.zipWithNext().all { (a, b) -> b > a })
        assertTrue("$ms", ms.first() >= 180 && ms.last() <= 380)
    }

    // The lean before the way is a hair, against the way, and none for no way
    @Test fun theLeanGoesBackALittle() {
        assertTrue(Tabs.lean(2f, 4f, 4) < 0f && Tabs.lean(2f, 0f, 4) > 0f)
        assertTrue(kotlin.math.abs(Tabs.lean(2f, 4f, 4)) <= 0.1f)
        assertEquals(0f, Tabs.lean(2f, 2f, 4), 0f)
    }

    // An end tab leans less, inside the bar's padding: the light poked past the bar's border on
    // the video
    @Test fun anEndTabLeansInsideTheBar() {
        assertTrue(Tabs.lean(0f, 3f, 4) < 0f)
        assertTrue(Tabs.lean(0f, 3f, 4) >= -Tabs.END_LEAN - 1e-4f)
        assertTrue(Tabs.lean(4f, 1f, 4) <= Tabs.END_LEAN + 1e-4f)
        assertTrue(kotlin.math.abs(Tabs.lean(0f, 3f, 4)) < kotlin.math.abs(Tabs.lean(2f, 4f, 4)))
    }

    // The hit squashes the light along the way only: a bulge across pushed its corners out of
    // the track and back (my note 27 Oct: the corner bounced); nothing at rest
    @Test fun theHitSquashesAlongTheWayOnly() {
        assertEquals(1f, Tabs.squash(0f), 0f)
        assertTrue("along ${Tabs.squash(1f)}", Tabs.squash(1f) in 0.88f..0.95f)
    }

    // Squashed, the light keeps the edge that hit and its height; it is drawn shorter, not
    // stretched, so a cut corner keeps its size
    @Test fun aSquashedLightKeepsItsLeadingEdge() {
        val (left, width) = Tabs.squashed(100f, 0.9f, way = 1f)
        assertEquals(10f, left, 1e-4f); assertEquals(90f, width, 1e-4f)
        val (left2, _) = Tabs.squashed(100f, 0.9f, way = -1f)
        assertEquals(0f, left2, 0f)
    }

    // The arriving word punches in from a little smaller, a visible step, not a pop from nothing
    @Test fun theArrivalPunchesIn() { assertTrue(Tabs.PUNCH in 0.85f..0.95f) }

    // A press sinks the light far enough to see, and a quick tap still shows it for a moment
    @Test fun aPressSinksVisibly() {
        assertTrue(Tabs.PRESS in 0.9f..0.94f)
        assertEquals(Tabs.MIN_PRESS_MS, Tabs.holdLeft(0))
        assertEquals(40L, Tabs.holdLeft(Tabs.MIN_PRESS_MS - 40))
        assertEquals(0L, Tabs.holdLeft(500))
        val s = Tabs.press as androidx.compose.animation.core.SpringSpec<Float>
        assertEquals(1f, s.dampingRatio, 0f)  // an effect, no bounce
    }

    // The word fills with the light's ink as the light covers its cell: none apart, all on it,
    // half when half covered, either side
    @Test fun inkFollowsTheLight() {
        assertEquals(1f, Tabs.ink(2f, 2), 0f)
        assertEquals(0f, Tabs.ink(0f, 2), 0f)
        assertEquals(0f, Tabs.ink(1f, 2), 0f)
        assertEquals(0.5f, Tabs.ink(1.5f, 2), 1e-4f)
        assertEquals(0.5f, Tabs.ink(2.5f, 2), 1e-4f)
        assertEquals(Tabs.ink(1.7f, 2), Tabs.ink(2.3f, 2), 1e-4f)
    }

    // Two cells share the ink: as much leaves one as reaches the next
    @Test fun inkIsShared() {
        listOf(0.1f, 0.4f, 0.75f).forEach { t -> assertEquals(1f, Tabs.ink(t, 0) + Tabs.ink(t, 1), 1e-4f) }
    }

    // One tick per change, at the moment it is made (my note 26 Oct: the count of vibrations
    // varied and the tick came late): a tap ticks at once, the tabs it glides past on the way
    // stay quiet, and a swipe ticks as it crosses into a page
    @Test fun aTapTicksOnceAndItsWayIsQuiet() {
        var pending: Int? = 2  // tapped History from Now
        val (passMessages, p1) = Tabs.change(pending, 1); pending = p1
        assertFalse(passMessages); assertEquals(2, pending)
        val (land, p2) = Tabs.change(pending, 2)
        assertFalse(land); assertEquals(null, p2)
    }
    @Test fun aSwipeTicksAsItCrosses() { assertEquals(true to null, Tabs.change(null, 1)) }

    // A tab moves between choices and completes nothing, so not a Confirm (Android's
    // SEGMENT_TICK); the wheel ticks the same since its soft tick could not be felt (my yes 26 Oct)
    @Test fun aTabTicksAsAChoice() {
        assertEquals(HapticFeedbackType.SegmentTick, Tabs.tick)
        assertNotEquals(HapticFeedbackType.Confirm, Tabs.tick)
        assertEquals(Tabs.tick, Wheel.tickType)
    }


    // The give is sized by a real width, not by the cell (my note 26 Oct: Todos' tabs looked too
    // liquid): a cell as wide as the tab bar's gives all of it, one twice as wide half, so the
    // squash, the lean and the punch move about as many pixels on every row
    @Test fun wideTabsGiveLess() {
        assertEquals(1f, Tabs.give(60f, 60f), 0f)
        assertEquals(1f, Tabs.give(40f, 60f), 0f)
        assertEquals(0.5f, Tabs.give(120f, 60f), 1e-4f)
        val wide = Tabs.squash(1f, 0.5f)
        val bar = Tabs.squash(1f, 1f)
        assertEquals(1f - wide, (1f - bar) / 2, 1e-4f)
        assertEquals(1f, Tabs.punch(0f), 0f)
        assertTrue(Tabs.punch(0.5f) > Tabs.punch(1f))
    }

}
