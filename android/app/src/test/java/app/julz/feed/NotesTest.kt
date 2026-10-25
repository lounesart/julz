package app.julz.feed

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threats 118 and 148: the notes browser's folders and notes from the approver, read
 *  only. The list has no text; one note's text comes by its id when it is opened (206). */
class NotesTest {
    private val dnsId = "c6f1b3".padEnd(64, '0')

    private fun note(note: String = "study/network-plus/dns.md", modified: String = "2026-10-16", id: String = dnsId,
                     name: String = note.substringAfterLast('/').removeSuffix(".md")) =
        JSONObject().put("name", name).put("note", note).put("modified", modified).put("size", 30).put("id", id)

    private fun one(note: String = "study/network-plus/dns.md", text: String = "# DNS\nNames to addresses.\n") =
        JSONObject().put("note", note).put("text", text).toString()

    private fun folder(name: String, vararg notes: JSONObject) =
        JSONObject().put("folder", name).put("notes", JSONArray(notes.toList()))

    private fun all(vararg folders: JSONObject) = JSONObject().put("folders", JSONArray(folders.toList())).toString()

    @Test fun foldersAndNotesParse() {
        val f = VaultNotes.parse(all(folder("study/network-plus", note()), folder("daily", note("daily/week.md"))))!!
        assertEquals(listOf("study/network-plus", "daily"), f.map { it.folder })
        assertEquals("dns", f[0].notes[0].name)
        assertEquals(dnsId, f[0].notes[0].id)
        assertEquals(emptyList<VaultFolder>(), VaultNotes.parse(all()))
    }

    @Test fun countsPerFolder() {
        val f = VaultNotes.parse(all(folder("daily", note("daily/a.md"), note("daily/b.md")), folder("study", note("study/c.md"))))!!
        assertEquals(mapOf("daily" to 2, "study" to 1), VaultNotes.counts(f))
    }

    @Test fun anythingOffShapeIsNull() {
        for (bad in listOf("", "{", all(folder("Templates", note("Templates/t.md"))),
                all(folder("study/..", note("study/../x.md"))), all(folder("study", note("daily/x.md"))),
                all(folder("study", note("study/x.md", name = "a\u202Eb"))),
                all(folder("study", note("study/x.md", id = "A".repeat(64)))),
                all(folder("study", note("study/x.md", id = "a".repeat(63)))),
                all(folder("study", note("study/x.md", id = "../x"))),
                all(folder("study", note("study/x.md", modified = "16 Oct"))),
                all(folder("study", *Array(301) { note("study/n$it.md") }))))
            assertNull(bad, VaultNotes.parse(bad))
    }

    @Test fun oneNoteGivesItsText() {
        assertEquals("# DNS\nNames to addresses.\n", VaultNotes.one(one(), "study/network-plus/dns.md"))
        assertEquals("", VaultNotes.one(one(text = ""), "study/network-plus/dns.md"))
    }

    @Test fun oneNoteOffShapeIsNull() {
        val asked = "study/network-plus/dns.md"
        // A reply for another note than the one asked for is refused, as is planted or long text
        for (bad in listOf("", "{", "[]", one(note = "daily/week.md"), one(text = "a\u202Eb"), one(text = "y".repeat(4001)),
                JSONObject().put("note", asked).toString(), JSONObject().put("note", asked).put("text", 5).toString(), JSONObject(one()).put("x", 1).toString()))
            assertNull(bad, VaultNotes.one(bad, asked))
    }
}
