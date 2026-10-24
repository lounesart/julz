package app.julz.feed

import java.io.File
import java.nio.file.Files
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threats 89, 90 and 92: the feed on the phone, the stream address, the text that
 *  reaches the notification shade. */
class FeedTest {
    private val day = 86_400L
    private val now = 1_800_000_000L
    private fun n(id: String, ageDays: Long = 0, kind: Kind = Kind.RUN, title: String = "Julz: run done") =
        Notice(id, now - ageDays * day, kind, title, "Report is in Outbox.")

    private fun store(): Pair<FeedStore, File> {
        val f = Files.createTempFile("feed", ".jsonl").toFile()
        return FeedStore(f) { now } to f
    }

    @Test fun duplicatesAreDroppedAndNewestComesFirst() {
        val (s, _) = store()
        assertTrue(s.add(n("aaaaaaaa1", 2)))
        assertTrue(s.add(n("aaaaaaaa2", 1)))
        assertFalse(s.add(n("aaaaaaaa1", 2)))  // catch up can send the same notice again
        assertEquals(listOf("aaaaaaaa2", "aaaaaaaa1"), s.all().map { it.id })
        assertEquals("aaaaaaaa2", s.lastId())
    }

    @Test fun noticesOfTheSameSecondStayNewestFirst() {
        val (s, f) = store()
        s.add(n("aaaaaaaa1")); s.add(n("aaaaaaaa2")); s.add(n("aaaaaaaa3"))  // all the same time
        assertEquals(listOf("aaaaaaaa3", "aaaaaaaa2", "aaaaaaaa1"), s.all().map { it.id })
        assertEquals(listOf("aaaaaaaa3", "aaaaaaaa2", "aaaaaaaa1"), FeedStore(f) { now }.all().map { it.id })
        assertEquals("aaaaaaaa3", s.lastId())  // catch up starts after the last one that arrived
    }

    @Test fun itSurvivesARestart() {
        val (s, f) = store()
        s.add(n("aaaaaaaa1"))
        assertEquals(listOf("aaaaaaaa1"), FeedStore(f) { now }.all().map { it.id })
    }

    @Test fun olderThan30DaysIsPurged() {
        val (s, f) = store()
        s.add(n("aaaaaaaa1", 31))
        s.add(n("aaaaaaaa2", 29))
        assertEquals(1, s.purge())
        assertEquals(listOf("aaaaaaaa2"), FeedStore(f) { now }.all().map { it.id })
    }

    @Test fun aChangedFileIsCheckedLikeTheStream() {
        val (s, f) = store()
        s.add(n("aaaaaaaa1"))
        f.appendText("{\"id\":\"../x\",\"time\":1,\"kind\":\"RUN\",\"title\":\"t\",\"message\":\"m\"}\n")
        f.appendText("{\"id\":\"bbbbbbbb1\",\"time\":5,\"kind\":\"EVIL\",\"title\":\"t\",\"message\":\"m\"}\n")
        f.appendText("{\"id\":\"bbbbbbbb2\",\"time\":5,\"kind\":\"RUN\",\"title\":\"a\u202Eb\",\"message\":\"m\"}\n")
        f.appendText("not json\n")
        assertEquals(listOf("aaaaaaaa1"), FeedStore(f) { now }.all().map { it.id })
    }

    @Test fun aFileWithTheSameNoticeTwiceLoadsItOnce() {
        val (s, f) = store()
        s.add(n("aaaaaaaa1"))
        f.appendText(f.readText())
        assertEquals(listOf("aaaaaaaa1"), FeedStore(f) { now }.all().map { it.id })
    }

    @Test fun theFeedHasACap() {
        val (s, _) = store()
        for (i in 0 until FeedStore.MAX_ENTRIES + 5) s.add(n("id%08d".format(i)))
        assertEquals(FeedStore.MAX_ENTRIES, s.all().size)
        assertEquals("id%08d".format(FeedStore.MAX_ENTRIES + 4), s.all().first().id)  // order kept after the cap
        s.add(n("zzzzzzzz1"))
        assertEquals("zzzzzzzz1", s.all().first().id)
    }

    @Test fun wipeEmptiesIt() {
        val (s, f) = store()
        s.add(n("aaaaaaaa1"))
        s.wipe()
        assertTrue(s.all().isEmpty())
        assertFalse(f.exists())
    }

    @Test fun unreadCountsPerKind() {
        val (s, _) = store()
        s.add(n("aaaaaaaa1", kind = Kind.APPROVAL))
        s.add(n("aaaaaaaa2", kind = Kind.RUN))
        s.add(n("aaaaaaaa3", ageDays = 3, kind = Kind.RUN))
        assertEquals(mapOf(Kind.APPROVAL to 1, Kind.RUN to 1), s.unreadSince(now - day))
    }

    /** A notice the open screen kept out of the tray was seen there: a later notice of
     *  another kind must not bring it back (found on the phone 18 Oct). */
    @Test fun aKindSeenOnScreenStaysSeen() {
        val (s, _) = store()
        s.add(n("aaaaaaaa1", kind = Kind.INBOX))
        s.add(n("aaaaaaaa2", kind = Kind.CHANGE))
        assertEquals(mapOf(Kind.CHANGE to 1), s.unreadSince(now - day, mapOf(Kind.INBOX to now)))
        // seen for one kind only
        assertEquals(mapOf(Kind.INBOX to 1, Kind.CHANGE to 1), s.unreadSince(now - day, mapOf(Kind.RUN to now)))
    }

    @Test fun streamAddressFromCheckedPartsOnly() {
        val server = "https://laptop.tail1234.ts.net:8444"
        val topic = "julz-" + "a".repeat(32)
        assertEquals("$server/$topic/json?since=48h", Stream.url(server, topic, null))
        assertEquals("$server/$topic/json?since=aaaaaaaa2", Stream.url(server, topic, "aaaaaaaa2"))
        assertNull(Stream.url(server, "julz-*", null))
        assertNull(Stream.url(server, topic, "x&poll=1"))
        assertNull(Stream.url("http://laptop.tail1234.ts.net:8444", topic, null))
    }

    @Test fun notificationTextIsKindAndCountOnly() {
        assertEquals("Julz · Approvals" to "1 new approval", Shade.text(Kind.APPROVAL, 1))
        assertEquals("Julz · Runs" to "3 new runs", Shade.text(Kind.RUN, 3))
        assertEquals("Julz · Warnings" to "2 new warnings", Shade.text(Kind.WARNING, 2))
        // the signature is the point: there is no way to hand it a title (threat 90)
        val params = Shade::class.java.declaredMethods.first { it.name == "text" }.parameterTypes
        assertEquals(listOf(Kind::class.java, Int::class.javaPrimitiveType), params.toList())
    }
}
