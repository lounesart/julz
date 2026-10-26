package app.julz.ui

import androidx.compose.animation.core.VectorConverter
import app.julz.chat.ChatApi
import app.julz.feed.Kind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WheelTest {
    // A landing ends when the word looks still, not 0.01 px later: Messages' list waited about
    // 350 ms on an unseen tail before it changed (my note 26 Oct): about 600 ms today, 360 with the threshold. 300 px at 3000 px/s, a flick
    private fun settleMs(spec: androidx.compose.animation.core.AnimationSpec<Float>) =
        androidx.compose.animation.core.TargetBasedAnimation(spec, Float.VectorConverter,
            0f, 300f, 3000f).durationNanos / 1_000_000
    @Test fun aLandingEndsWhenTheWordLooksStill() {
        val ours = settleMs(Wheel.settle)
        val default = settleMs(androidx.compose.animation.core.spring(stiffness = androidx.compose.animation.core.Spring.StiffnessMediumLow))
        assertTrue("settles in $ours ms", ours < 400)
        // the threshold does it: the same spring at Compose's default runs well past
        assertTrue("default $default ms, ours $ours ms", default > ours + 150)
    }

    // The word nearest the strip's middle is the one picked
    @Test fun nearestPicksTheClosestCentre() { assertEquals(2, Wheel.nearest(listOf(1 to 40f, 2 to 170f, 3 to 300f), 180f)) }
    @Test fun nearestWorksLeftOfTheMiddle() { assertEquals(1, Wheel.nearest(listOf(1 to 160f, 2 to 260f), 180f)) }
    @Test fun nearestOfNothingIsNull() { assertNull(Wheel.nearest(emptyList(), 180f)) }

    // A fixed row with ends (my note 26 Oct), no copies: past an end the strip follows the finger
    // less and less and never further than the limit, either way
    @Test fun aPullPastAnEndGetsHarder() {
        var pull = 0f
        val steps = (1..60).map { val before = pull; pull = Wheel.rubber(pull, 10f, 200f); pull - before }
        assertTrue("first step ${steps.first()}", steps.first() in 4f..7f)
        assertTrue("later steps shrink", steps.zipWithNext().all { (a, b) -> b <= a })
        assertTrue("stays inside the limit: $pull", pull < 200f)
        assertEquals(-Wheel.rubber(0f, 10f, 200f), Wheel.rubber(0f, -10f, 200f), 0f)
    }
    @Test fun onlyTheChatWheelLoops() {
        assertEquals(8, Wheel.slots(8, vertical = false))
        assertTrue(Wheel.slots(3, vertical = true) > 3)
    }

    @Test fun talkBackHearsThePlaceInTheRow() { assertEquals("Todos, 3 of 8", Wheel.say("Todos", 2, 8)) }

    // Messages: All, then only the kinds that have notices, in the usual order
    @Test fun messagesShowOnlyKindsPresent() {
        assertEquals(listOf(null, Kind.TODO, Kind.WARNING), Wheel.kinds(setOf(Kind.WARNING, Kind.TODO), null))
    }
    // A filter left by a notification tap stays, so the pick never vanishes from under me
    @Test fun messagesKeepTheChosenKindWhenEmpty() {
        assertEquals(listOf(null, Kind.APPROVAL, Kind.TODO), Wheel.kinds(setOf(Kind.TODO), Kind.APPROVAL))
    }
    @Test fun messagesWithNoNoticesStillHaveAll() { assertEquals(listOf(null), Wheel.kinds(emptySet(), null)) }

    // Todos: Board, All lists, then each list; All lists is the default, the board one roll left
    @Test fun todoViewsAreBoardAllThenLists() {
        assertEquals(listOf(Wheel.BOARD, Wheel.ALL, "study", "home"), Wheel.todoViews(listOf("study", "home")))
    }
    @Test fun todoViewFindsAList() { assertEquals(3, Wheel.todoIndex("home", listOf("study", "home"))) }
    @Test fun todoViewOfAGoneListFallsBackToAll() { assertEquals(1, Wheel.todoIndex("old", listOf("study"))) }
    @Test fun aListNamedBoardIsStillAList() { assertEquals(2, Wheel.todoIndex("board", listOf("board", "home"))) }
    // One list: its own view would show the same card as All lists, so rolling looked dead (my note 26 Oct)
    @Test fun oneListOffersNoViewOfItsOwn() { assertEquals(listOf(Wheel.BOARD, Wheel.ALL), Wheel.todoViews(listOf("study"))) }
    @Test fun oneListPickFallsBackToAll() { assertEquals(1, Wheel.todoIndex("study", listOf("study"))) }

    // Chat modes: Chat first; every other key is one julz-chat accepts (CASE_MODES, threat 151)
    @Test fun chatModeIsFirstAndEmpty() { assertEquals("" to "Chat", Wheel.MODES.first()) }
    @Test fun everyModeKeyIsKnownToTheChat() {
        assertTrue(Wheel.MODES.drop(1).all { it.first in ChatApi.MODES })
        assertEquals(ChatApi.MODES, Wheel.MODES.drop(1).map { it.first }.toSet())
    }

    // The wheel loops (no empty side): a pick rolls to the nearest copy of the word, never far round
    @Test fun closestCopyAhead() { assertEquals(1002, Wheel.closest(1000, 2, 5)) }
    @Test fun closestCopyBehindAcrossTheSeam() { assertEquals(999, Wheel.closest(1000, 4, 5)) }
    @Test fun closestCopyIsItselfWhenThere() { assertEquals(1003, Wheel.closest(1003, 3, 5)) }
    @Test fun realIndexOfACopy() { assertEquals(4, Wheel.real(999, 5)) }
    @Test fun oneWordDoesNotLoop() { assertEquals(1, Wheel.slots(1, vertical = true)); assertEquals(3 * Wheel.LOOP, Wheel.slots(3, vertical = true)) }

    // The chat wheel: one swipe, one step, round the loop; a short one stays (no precise swipe needed)
    @Test fun swipeUpStepsToTheNext() { assertEquals(1, Wheel.step(0, 3, -60f, 40f)) }
    @Test fun swipeDownStepsBack() { assertEquals(0, Wheel.step(1, 3, 60f, 40f)) }
    @Test fun stepWrapsAtTheEnd() { assertEquals(0, Wheel.step(2, 3, -60f, 40f)) }
    @Test fun stepWrapsAtTheStart() { assertEquals(2, Wheel.step(0, 3, 60f, 40f)) }
    @Test fun shortSwipeStays() { assertEquals(1, Wheel.step(1, 3, -39f, 40f)) }
    @Test fun longSwipeIsStillOneStep() { assertEquals(2, Wheel.step(1, 3, -900f, 40f)) }


    // The light rides on a word, stretches across while the middle passes, then rides the next: a
    // pure function of the scroll, so it never jumps (my note 26 Oct: jumpy). Elastic (my note 26
    // Oct: the frame looked stale): the edge on the way runs ahead, the other catches up
    @Test fun edgesRideTheWords() {
        assertEquals(0f to 0f, Wheel.edges(0.15f))
        assertEquals(1f to 1f, Wheel.edges(0.85f))
    }
    @Test fun theLeadingEdgeRunsAhead() {
        for (k in 0..100) { val (trail, lead) = Wheel.edges(k / 100f); assertTrue(lead >= trail) }
        val (trail, lead) = Wheel.edges(0.5f)
        assertTrue("stretched across the gap: ${lead - trail}", lead - trail in 0.3f..0.6f)
    }
    @Test fun goingBackIsTheMirror() {
        for (k in 0..100) {
            val t = k / 100f
            val (trail, lead) = Wheel.edges(t); val (trailBack, leadBack) = Wheel.edges(1 - t)
            assertEquals(1 - lead, trailBack, 1e-5f); assertEquals(1 - trail, leadBack, 1e-5f)
        }
    }
    @Test fun edgesNeverGoBackNorStep() {
        var last = Wheel.edges(0f)
        for (k in 1..100) {
            val e = Wheel.edges(k / 100f)
            assertTrue(e.first >= last.first && e.second >= last.second)
            assertTrue(e.first - last.first < 0.06f && e.second - last.second < 0.06f)
            last = e
        }
    }
    // Squash with the stretch, so it keeps its volume; at rest it is its full height
    @Test fun aStretchedFrameIsAFewPercentThinner() {
        assertEquals(1f, Wheel.squash(0f to 0f), 0f)
        val (trail, lead) = Wheel.edges(0.5f)
        assertTrue(Wheel.squash(trail to lead) in 0.9f..0.97f)
    }

    // The middle word a little bigger, as a drum's middle row (my idea 26 Oct): neighbours keep
    // their 14 sp, so nothing goes under the design's smallest text
    @Test fun theMiddleWordIsALittleBigger() {
        assertEquals(Wheel.MAG, Wheel.magnify(0f), 0f)
        assertTrue(Wheel.MAG in 1.05f..1.15f)
        assertEquals(1f, Wheel.magnify(1f), 0f); assertEquals(1f, Wheel.magnify(-2.5f), 0f)
        var last = Wheel.magnify(0f)
        for (k in 1..20) { val m = Wheel.magnify(k / 20f); assertTrue(m <= last); last = m }
        assertEquals(Wheel.magnify(0.3f), Wheel.magnify(-0.3f), 0f)
    }
    // At an end the ticks spread as the pull grows, as a stretched spring, and close again
    @Test fun ticksSpreadWithThePull() {
        assertEquals(1f, Wheel.spread(0f, 200f), 0f)
        assertTrue(Wheel.spread(-100f, 200f) > 1.3f)
        assertEquals(Wheel.spread(100f, 200f), Wheel.spread(-100f, 200f), 0f)
        assertTrue(Wheel.spread(200f, 200f) <= 2.6f)
    }
    @Test fun anyStretchThinsTheFrameAFewPercentAtMost() {
        assertEquals(1f, Wheel.squash(0f), 0f)
        assertTrue(Wheel.squash(5f) >= 0.85f)
    }

    // One fling, one motion: where it lands, from the free decay's travel in word widths
    @Test fun flingLandsWhereTheDecayEnds() { assertEquals(13, Wheel.landing(10, 290f, 100f, 500f, 200f)) }
    @Test fun aShortFlickStillStepsOne() { assertEquals(11, Wheel.landing(10, 20f, 100f, 400f, 200f)) }
    @Test fun aShortFlickBackStepsBack() { assertEquals(9, Wheel.landing(10, -20f, 100f, -400f, 200f)) }
    @Test fun aLetGoWithoutSpeedStays() { assertEquals(10, Wheel.landing(10, 5f, 100f, 50f, 200f)) }
    // Two words: a hard fling went round to the same word and looked like nothing (my test 26 Oct)
    @Test fun aFlingNeverComesBackRound() {
        assertEquals(11, Wheel.landing(10, 290f, 100f, 3000f, 200f, count = 2))
        assertEquals(9, Wheel.landing(10, -290f, 100f, -3000f, 200f, count = 2))
        assertEquals(13, Wheel.landing(10, 290f, 100f, 3000f, 200f, count = 8))
    }
}
