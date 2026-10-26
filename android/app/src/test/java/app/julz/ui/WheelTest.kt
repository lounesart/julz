package app.julz.ui

import app.julz.chat.ChatApi
import app.julz.feed.Kind
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class WheelTest {
    // The word nearest the strip's middle is the one picked
    @Test fun nearestPicksTheClosestCentre() { assertEquals(2, Wheel.nearest(listOf(1 to 40f, 2 to 170f, 3 to 300f), 180f)) }
    @Test fun nearestWorksLeftOfTheMiddle() { assertEquals(1, Wheel.nearest(listOf(1 to 160f, 2 to 260f), 180f)) }
    @Test fun nearestOfNothingIsNull() { assertNull(Wheel.nearest(emptyList(), 180f)) }

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
    @Test fun oneWordDoesNotLoop() { assertEquals(1, Wheel.slots(1)); assertEquals(3 * Wheel.LOOP, Wheel.slots(3)) }

    // The chat wheel: one swipe, one step, round the loop; a short one stays (no precise swipe needed)
    @Test fun swipeUpStepsToTheNext() { assertEquals(1, Wheel.step(0, 3, -60f, 40f)) }
    @Test fun swipeDownStepsBack() { assertEquals(0, Wheel.step(1, 3, 60f, 40f)) }
    @Test fun stepWrapsAtTheEnd() { assertEquals(0, Wheel.step(2, 3, -60f, 40f)) }
    @Test fun stepWrapsAtTheStart() { assertEquals(2, Wheel.step(0, 3, 60f, 40f)) }
    @Test fun shortSwipeStays() { assertEquals(1, Wheel.step(1, 3, -39f, 40f)) }
    @Test fun longSwipeIsStillOneStep() { assertEquals(2, Wheel.step(1, 3, -900f, 40f)) }

    // A short flick that leaves the word near the middle still steps one, in its direction
    @Test fun settleStepsOnAfterAShortFlickLeft() { assertEquals(11, Wheel.settle(10, 10, -40f, 30f)) }
    @Test fun settleStepsBackAfterAShortFlickRight() { assertEquals(9, Wheel.settle(10, 10, 40f, 30f)) }
    @Test fun settleKeepsATinyNudge() { assertEquals(10, Wheel.settle(10, 10, 20f, 30f)) }
    @Test fun settleTakesTheNearestAfterARoll() { assertEquals(14, Wheel.settle(10, 14, -5f, 30f)) }
}
