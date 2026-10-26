package app.julz.feed

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threats 116 and 117: the Inbox from the approver, and what the app sends to act. */
class InboxTest {
    private val ID = "c".repeat(64)

    private fun note(name: String = "draft", note: String = "Inbox/$name.md", sha: String = "a".repeat(64),
                     preview: String = "# Draft\nA thought.\n", modified: String = "2026-10-17") =
        JSONObject().put("name", name).put("note", note).put("sha256", sha).put("size", 30)
            .put("modified", modified).put("preview", preview)

    private fun snap(notes: List<JSONObject> = listOf(note()), folders: List<String> = listOf("daily", "study/network-plus"),
                     id: String = ID) =
        JSONObject().put("id", id).put("notes", JSONArray(notes)).put("folders", JSONArray(folders)).toString()

    @Test fun anInboxParses() {
        val s = InboxSnapshot.parse(snap(listOf(note(), note("shop list"))))!!
        assertEquals(ID, s.id)
        assertEquals(listOf("draft", "shop list"), s.notes.map { it.name })
        assertEquals("Inbox/shop list.md", s.notes[1].note)
        assertEquals("# Draft\nA thought.\n", s.notes[0].preview)
        assertEquals(listOf("daily", "study/network-plus"), s.folders)
    }

    @Test fun anEmptyInboxIsEmpty() {
        val s = InboxSnapshot.parse(JSONObject().put("id", "").put("notes", JSONArray()).put("folders", JSONArray()).toString())!!
        assertEquals(emptyList<InboxNote>(), s.notes)
    }

    @Test fun anythingOffShapeIsNull() {
        for (bad in listOf("", "{", snap(id = "short"), snap(listOf(note(note = "study/x.md"))),
                snap(listOf(note(sha = "x"))), snap(listOf(note(preview = "y".repeat(2001)))),
                snap(listOf(note(preview = "a\u202Eb"))), snap(listOf(note(modified = "17 Oct"))),
                snap(folders = listOf("../x")), snap(folders = listOf("Claude")), snap(List(21) { note("n$it") })))
            assertNull(bad, InboxSnapshot.parse(bad))
    }

    @Test fun actingSendsOnlyTheSnapshotIdAndThePicks() {
        val body = InboxSnapshot.body(ID, listOf(InboxPick("Inbox/draft.md", "delete"),
            InboxPick("Inbox/shop.md", "move", "daily")))!!
        assertEquals(setOf("action", "sha256", "pick", "via"), body.keys().asSequence().toSet())
        assertEquals("inbox", body.getString("action"))
        assertEquals(ID, body.getString("sha256"))
        val pick = body.getJSONArray("pick")
        assertEquals(setOf("note", "do"), pick.getJSONObject(0).keys().asSequence().toSet())  // a delete has no folder
        assertEquals("daily", pick.getJSONObject(1).getString("to"))
        assertNull(InboxSnapshot.body(ID, emptyList()))
        assertNull(InboxSnapshot.body("short", listOf(InboxPick("Inbox/draft.md", "delete"))))
        assertNull(InboxSnapshot.body(ID, listOf(InboxPick("Inbox/draft.md", "move"))))  // a move needs a folder
        assertNull(InboxSnapshot.body(ID, listOf(InboxPick("Inbox/draft.md", "edit"))))
        assertNull(InboxSnapshot.body(ID, List(21) { InboxPick("Inbox/n$it.md", "delete") }))
    }

    @Test fun aPickTravelsAsOneSavableString() {
        val p = InboxPick("Inbox/shop list.md", "move", "study/network-plus")
        assertEquals(p, InboxPick.from(p.key))
        assertEquals(InboxPick("Inbox/draft.md", "delete"), InboxPick.from(InboxPick("Inbox/draft.md", "delete").key))
    }

    /** The Now card counts what the laptop has, never an old notice title (found 18 Oct). */
    @Test fun theCardSaysTheLiveCount() {
        assertEquals("Notes waiting to be sorted", InboxSnapshot.line(null))
        assertEquals("Empty, nothing to sort", InboxSnapshot.line(0))
        assertEquals("1 note waiting to be sorted", InboxSnapshot.line(1))
        assertEquals("2 notes waiting to be sorted", InboxSnapshot.line(2))
        // the laptop sends at most MAX_NOTES, so a full list may hide more
        assertEquals("20 or more notes waiting to be sorted", InboxSnapshot.line(InboxSnapshot.MAX_NOTES))
    }

    /** Back on the feed right after a move or delete, the laptop may still have the old Inbox:
     *  its id is the one I signed, so the card reads again (13c). */
    @Test fun theCountWaitsForTheChangeISigned() {
        val old = InboxSnapshot.parse(snap())!!
        val new = InboxSnapshot.parse(snap(emptyList(), id = ""))!!
        assertEquals(true, InboxSnapshot.settled(old, null, last = false))
        assertEquals(false, InboxSnapshot.settled(old, ID, last = false))
        assertEquals(true, InboxSnapshot.settled(new, ID, last = false))
        // a refused change leaves the Inbox as it was, so the last read is the true count
        assertEquals(true, InboxSnapshot.settled(old, ID, last = true))
    }
}
