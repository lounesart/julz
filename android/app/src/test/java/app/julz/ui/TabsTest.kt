package app.julz.ui

import androidx.compose.animation.core.VectorConverter
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TabsTest {
    // Frames of a slide from 0 to [to], every 8 ms (120 Hz), from rest
    private fun frames(spec: androidx.compose.animation.core.AnimationSpec<Float>, to: Float): List<Float> {
        val a = androidx.compose.animation.core.TargetBasedAnimation(spec, Float.VectorConverter, 0f, to, 0f)
        return (0..a.durationNanos step 8_000_000L).map { a.getValueFromNanos(it) } + to
    }

    // The primary level is firm (258, my idea 26 Oct): the light never runs past the tab it goes
    // to by a visible amount, a tenth of a pixel on a 300 px jump, and never comes back
    @Test fun theSlideLandsWithoutWobble() {
        val f = frames(Tabs.slide, 4f)
        assertTrue("overshoot ${f.max() - 4f} tabs", f.max() - 4f < 0.1f / 75f)
        assertTrue("no way back", f.zipWithNext().all { (a, b) -> b >= a - 0.1f / 75f })
    }

    // Heavier than the wheels, still quick: a jump across the bar settles in a fifth to a half of a
    // second, a step to the next tab no slower than that
    @Test fun theSlideIsQuickButNotASnap() {
        val far = frames(Tabs.slide, 4f).size * 8
        val near = frames(Tabs.slide, 1f).size * 8
        assertTrue("far $far ms", far in 200..500)
        assertTrue("near $near ms, far $far ms", near <= far)
    }

    // Material 3's standard scheme for the primary level (stiffness 700), its expressive bounce left
    // to the wheels; damped fully, as its 0.9 left half a pixel past a far tab on the outline light
    @Test fun theTabsSpringIsFirmerThanTheWheelsPop() {
        val tab = Tabs.slide as androidx.compose.animation.core.SpringSpec<Float>
        val pop = Wheel.pop as androidx.compose.animation.core.SpringSpec<Float>
        assertTrue(tab.dampingRatio > pop.dampingRatio)
        assertEquals(1f, tab.dampingRatio, 0f)
        assertEquals(700f, tab.stiffness, 0f)
    }

    // A press sinks the light a few percent, never so far it looks like a different control
    @Test fun aPressSinksALittle() {
        assertTrue(Tabs.PRESS in 0.94f..0.98f)
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

    // Two cells share the ink: as much leaves one as reaches the next, so the light never looks
    // like two
    @Test fun inkIsShared() {
        listOf(0.1f, 0.4f, 0.75f).forEach { t -> assertEquals(1f, Tabs.ink(t, 0) + Tabs.ink(t, 1), 1e-4f) }
    }

    // A landing ticks once, firmer than the wheel's soft tick and not a Confirm: a tab moves
    // between choices and completes nothing (Android's SEGMENT_TICK)
    @Test fun aLandingTicksFirmerThanTheWheel() {
        assertEquals(HapticFeedbackType.SegmentTick, Tabs.tick)
        assertNotEquals(HapticFeedbackType.SegmentFrequentTick, Tabs.tick)
        assertNotEquals(HapticFeedbackType.Confirm, Tabs.tick)
    }
}
