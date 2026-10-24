package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Test

class FoldersTest {
    @Test fun aFoldersColourComesFromItsTopFolder() {
        assertEquals(Folders.argb("study"), Folders.argb("study/network-plus"))
        assertEquals(Folders.argb("study"), Folders.argb("study/security-plus/ports"))
        assertNotEquals(Folders.argb("study"), Folders.argb("daily"))
    }

    @Test fun everyKnownTopFolderHasItsOwnColour() {
        val tops = listOf("study", "daily", "Inbox", "Claude", "Outbox", "feedback")
        assertEquals(tops.size, tops.map { Folders.argb(it) }.toSet().size)
    }

    @Test fun anUnknownFolderStaysNeutral() {
        assertNull(Folders.argb("misc/x"))
        assertNull(Folders.argb(""))
    }
}
