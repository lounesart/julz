package app.julz.ui

import java.time.LocalDateTime
import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Test

/** The week strip and History count the same calendar days, so a tap lands on the same notices. */
class DaysTest {
    private val warsaw = ZoneId.of("Europe/Warsaw")
    private fun at(y: Int, mo: Int, d: Int, h: Int, mi: Int = 0) =
        LocalDateTime.of(y, mo, d, h, mi).atZone(warsaw).toEpochSecond()

    @Test fun calendarDaysNotRollingHours() {
        val now = at(2026, 10, 17, 9)
        assertEquals(0, Days.ago(at(2026, 10, 17, 0, 1), now, warsaw))
        assertEquals(1, Days.ago(at(2026, 10, 16, 23, 59), now, warsaw))  // 9 hours ago, but yesterday
        assertEquals(1, Days.ago(at(2026, 10, 16, 10), now, warsaw))
        assertEquals(6, Days.ago(at(2026, 10, 11, 12), now, warsaw))
    }

    @Test fun acrossTheYearAndTheClockChange() {
        assertEquals(2, Days.ago(at(2026, 12, 31, 22), at(2027, 1, 2, 1), warsaw))
        assertEquals(1, Days.ago(at(2024, 12, 31, 12), at(2025, 1, 1, 12), warsaw))  // after a leap year
        // 25 October 2026: clocks go back, that day has 25 hours
        assertEquals(1, Days.ago(at(2026, 10, 25, 0, 30), at(2026, 10, 26, 0, 10), warsaw))
        assertEquals(0, Days.ago(at(2026, 10, 25, 0, 30), at(2026, 10, 25, 23, 50), warsaw))
    }

    @Test fun theFutureCountsAsToday() {
        val now = at(2026, 10, 17, 9)
        assertEquals(0, Days.ago(now + 60, now, warsaw))  // a laptop clock a little ahead
    }

    @Test fun barsShowHowBusyADayWasAgainstTheWeek() {
        assertEquals(0f, Days.bar(0, listOf(0, 0, 0)), 0f)
        assertEquals(1f, Days.bar(8, listOf(1, 4, 8)), 0f)  // the busiest day is full
        assertEquals(0.5f, Days.bar(4, listOf(1, 4, 8)), 0f)
        assertEquals(1f / 3, Days.bar(1, listOf(1, 0, 0)), 0.001f)  // a quiet week never fills a bar
        assertEquals(0.15f, Days.bar(1, listOf(1, 40)), 0f)  // one notice stays visible
    }
}
