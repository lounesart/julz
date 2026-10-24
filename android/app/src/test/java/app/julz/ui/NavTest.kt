package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NavTest {
    private val feed = Nav("feed")

    @Test fun backGoesOneLevelUpToWhereICameFrom() {
        val look = feed.tab("settings").open("look")
        assertEquals("look", look.here)
        assertEquals("settings", look.back().here)
        assertEquals("feed", look.back().back().here)
    }

    @Test fun enrollFromApproveReturnsToApprove() {
        assertEquals("approve", feed.tab("approve").open("enroll").back().here)
        assertEquals("settings", feed.tab("settings").open("enroll").back().here)
    }

    @Test fun atTheFeedBackIsAndroidsOwn() {
        assertFalse(feed.canGoBack)
        assertEquals(feed, feed.back())
        assertTrue(feed.tab("chat").canGoBack)
    }

    @Test fun aTabStartsFromTheFeedAndRetappingGoesToItsTop() {
        val deep = feed.tab("settings").open("look")
        assertEquals(listOf("feed", "approve"), deep.tab("approve").path)
        assertEquals(listOf("feed", "settings"), deep.tab("settings").path)
        assertEquals(listOf("feed"), deep.tab("feed").path)
    }

    @Test fun aPlaceOnThePathIsGoneBackToNeverStackedTwice() {
        val loop = feed.tab("approve").open("enroll").open("approve").open("enroll").open("approve")
        assertEquals(listOf("feed", "approve"), loop.path)
        assertEquals(feed, feed.open("feed"))
    }

    @Test fun theLitTabIsWhereThePathStarted() {
        assertEquals("feed", feed.section)
        assertEquals("approve", feed.tab("approve").open("enroll").section)
        assertEquals("todos", feed.open("todos").section)
        assertEquals("inbox", feed.open("inbox").open("notes").section)
    }
}
