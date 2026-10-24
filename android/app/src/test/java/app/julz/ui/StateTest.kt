package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class StateTest {
    /** SECURITY.md threat 94: the app opens only two addresses, both from the checked server. */
    @Test fun originsComeOnlyFromTheServerSetting() {
        val o = Origins.from("https://laptop.tail1234.ts.net:8444")!!
        assertEquals("https://laptop.tail1234.ts.net/", o.chat)
        assertEquals("https://laptop.tail1234.ts.net:8443/", o.approver)
        assertNull(Origins.from("https://evil.example:8444"))
        assertNull(Origins.from("http://laptop.tail1234.ts.net:8444"))
        assertNull(Origins.from("https://laptop.tail1234.ts.net:8444/x"))
    }

    @Test fun clearingHidesWhatWasThereNotWhatComesLater() {
        val n = { id: String -> app.julz.feed.Notice(id, 100, app.julz.feed.Kind.RUN, "t", "m") }
        val before = listOf(n("aaaaaaaa1"), n("aaaaaaaa2"))
        val cleared = ReadState(emptySet()).with(before.map { it.id })
        val later = n("aaaaaaaa3")  // same second as the clear
        assertEquals(listOf(later), (listOf(later) + before).filter { !cleared.isRead(it.id) })
        assertEquals(cleared.ids, ReadState(emptySet()).with(before.map { it.id } + "bad id!").ids)  // shape kept
    }

    @Test fun readStateRemembersAndHasACap() {
        val r = ReadState(emptySet())
        val r2 = r.read("aaaaaaaa1").read("aaaaaaaa2")
        assertTrue(r2.isRead("aaaaaaaa1"))
        assertFalse(r2.isRead("aaaaaaaa3"))
        var big = ReadState(emptySet())
        for (i in 0 until ReadState.MAX + 10) big = big.read("id%08d".format(i))
        assertEquals(ReadState.MAX, big.ids.size)
        assertTrue(big.isRead("id%08d".format(ReadState.MAX + 9)))  // the newest stays
    }

    @Test fun readStateOnlyKeepsIdsOfTheRightShape() {
        assertEquals(setOf("aaaaaaaa1"), ReadState.parse(setOf("aaaaaaaa1", "../x", "", "a b")).ids)
    }
}
