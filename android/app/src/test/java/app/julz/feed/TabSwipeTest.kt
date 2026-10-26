package app.julz.feed

import org.junit.Assert.assertEquals
import org.junit.Test

class TabSwipeTest {
    @Test fun swipeLeftGoesToTheNextTab() { assertEquals(1, TabSwipe.next(0, 3, -200f, 100f)) }
    @Test fun swipeRightGoesToThePreviousTab() { assertEquals(0, TabSwipe.next(1, 3, 200f, 100f)) }
    @Test fun shortSwipeStays() { assertEquals(1, TabSwipe.next(1, 3, -99f, 100f)) }
    @Test fun thresholdExactlyMoves() { assertEquals(2, TabSwipe.next(1, 3, -100f, 100f)) }
    @Test fun firstTabStopsAtTheEdge() { assertEquals(0, TabSwipe.next(0, 3, 500f, 100f)) }
    @Test fun lastTabStopsAtTheEdge() { assertEquals(2, TabSwipe.next(2, 3, -500f, 100f)) }
    @Test fun moveIsOneTabNeverTwo() { assertEquals(1, TabSwipe.next(0, 3, -900f, 100f)) }
}
