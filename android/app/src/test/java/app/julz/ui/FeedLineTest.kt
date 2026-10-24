package app.julz.ui

import app.julz.feed.Kind
import app.julz.feed.Notice
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class FeedLineTest {
    private fun n(id: String, kind: Kind = Kind.RUN) = Notice(id, 100, kind, "t", "m")
    private val a = n("aaaaaaaa1"); private val b = n("aaaaaaaa2"); private val c = n("aaaaaaaa3", Kind.APPROVAL)

    @Test fun nowSaysHowManyAreUnreadOrNothing() {
        assertEquals("1 unread", FeedLine.now(listOf(a, b), ReadState(emptyList()).read(b.id))?.text)
        assertEquals("2 unread", FeedLine.now(listOf(a, b), ReadState(emptyList()))?.text)
        assertNull(FeedLine.now(listOf(a, b), ReadState(emptyList()).read(a.id).read(b.id)))
    }

    @Test fun messagesCountsAndReadsOnlyWhatIsShown() {
        // the filter shows one approval: the line counts it alone, Read all reads it alone
        val line = FeedLine.messages(listOf(c), ReadState(emptyList()))!!
        assertEquals("1 unread", line.text)
        assertEquals(listOf(c), line.unread)
    }

    @Test fun readAllOnlyWhileSomethingIsUnreadClearWhileSomethingIsShown() {
        val allRead = FeedLine.messages(listOf(a), ReadState(emptyList()).read(a.id))!!
        assertTrue(allRead.unread.isEmpty())
        assertTrue(allRead.clear)
        assertEquals("All read", allRead.text)
        val some = FeedLine.messages(listOf(a, b), ReadState(emptyList()).read(a.id))!!
        assertEquals(listOf(b), some.unread)
    }

    @Test fun anEmptyListHasNoLine() {
        assertNull(FeedLine.messages(emptyList(), ReadState(emptyList())))
        assertNull(FeedLine.now(emptyList(), ReadState(emptyList())))
    }

    @Test fun nowNeverOffersClear() {
        assertFalse(FeedLine.now(listOf(a), ReadState(emptyList()))!!.clear)
    }
}
