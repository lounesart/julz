package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test

/** BACKLOG 211: each view of the notes browser keeps its own scroll position. */
class NotesScrollTest {
    @Test fun backFromAScrolledNoteFindsTheFolderWhereItWas() {
        val s = NotesScroll()
        val folder = NotesScroll.key("study/net", null)
        assertEquals(0, s.at(folder))                       // a folder seen first opens at its header
        s.keep(folder, 120)
        val note = NotesScroll.key("study/net", "aa".repeat(32))
        assertEquals(0, s.at(note))                         // the note opens at its top
        s.keep(note, 3000)                                  // scrolled far down the note
        assertEquals(120, s.at(folder))                     // back: the list where I left it
        assertEquals(0, s.at(note))                         // the note again: at its top
    }

    @Test fun viewsDoNotShareAPosition() {
        val s = NotesScroll()
        s.keep(NotesScroll.key(null, null), 400)
        assertEquals(0, s.at(NotesScroll.key("daily", null)))
        assertEquals(400, s.at(NotesScroll.key(null, null)))
        assertNotEquals(NotesScroll.key(null, null), NotesScroll.key("daily", null))
        assertNotEquals(NotesScroll.key("a", null), NotesScroll.key("a", "aa".repeat(32)))
        assertNotEquals(NotesScroll.key("a", null), NotesScroll.key("a", null, "net"))  // a tag view, 212
    }

    @Test fun keepsAFixedNumberOfPlaces() {
        val s = NotesScroll()
        for (i in 0 until NotesScroll.MAX + 5) s.keep(NotesScroll.key("f$i", null), 10)
        assertEquals(0, s.at(NotesScroll.key("f0", null)))  // the oldest went
        assertEquals(10, s.at(NotesScroll.key("f${NotesScroll.MAX + 4}", null)))
        assertEquals(NotesScroll.MAX, s.size)
    }
}
