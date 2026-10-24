package app.julz.ui

import app.julz.feed.Kind
import app.julz.feed.Notice
import java.time.ZoneOffset
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class HistoryTest {
    private val utc = ZoneOffset.UTC
    private val now = 1_760_000_000L - 1_760_000_000L % 86_400 + 12 * 3600  // a day at 12:00 UTC
    private var seq = 0
    private fun n(kind: Kind, ago: Long) = Notice("aaaaaaaa${seq++}", now - ago, kind, "t", "m")

    @Test fun everyStoredDayIsReachableNotJustAWeek() {
        assertEquals(30, HistoryDay.DAYS)  // as long as the feed keeps notices
        val counts = HistoryDay.counts(listOf(n(Kind.RUN, 0), n(Kind.RUN, 60), n(Kind.CHANGE, 20 * 86_400L)), now, utc)
        assertEquals(30, counts.size)
        assertEquals(2, counts[0]); assertEquals(1, counts[20]); assertEquals(0, counts[7])
    }

    @Test fun aTimeShowsOnlyWhenTheMinuteChanges() {
        val day = listOf(n(Kind.RUN, 10), n(Kind.CHANGE, 20), n(Kind.WARNING, 30), n(Kind.CHANGE, 300))
        val e = HistoryDay.entries(day, 0, now, utc)
        // newest first: three in the same minute show one time, the fourth its own
        assertEquals(listOf(true, false, false, true), e.map { it.showTime })
    }

    @Test fun aDayKeepsItsLastTodoSnapshotWithTheEarlierOnesBehindIt() {
        val last = n(Kind.TODO, 60); val mid = n(Kind.TODO, 600); val first = n(Kind.TODO, 3600); val run = n(Kind.RUN, 120)
        val e = HistoryDay.entries(listOf(first, run, last, mid), 0, now, utc)
        assertEquals(listOf(last, run), e.map { it.notice })
        assertEquals(listOf(mid, first), e[0].earlier)
        assertTrue(e[1].earlier.isEmpty())
    }

    @Test fun onlyTheChosenDay() {
        val e = HistoryDay.entries(listOf(n(Kind.RUN, 0), n(Kind.RUN, 86_400L)), 1, now, utc)
        assertEquals(1, e.size)
    }

    @Test fun cardWordsMatchTheFilters() {
        for (k in Kind.entries) assertTrue(k.name, Words.label(k).startsWith(Words.status(k)))
    }
}
