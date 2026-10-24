package app.julz.feed

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threat 118: the notes browser's folders and notes from the approver, read only. */
class NotesTest {
    private fun note(note: String = "study/network-plus/dns.md", text: String = "# DNS\nNames to addresses.\n",
                     modified: String = "2026-10-16") =
        JSONObject().put("name", note.substringAfterLast('/').removeSuffix(".md")).put("note", note)
            .put("modified", modified).put("size", 30).put("text", text)

    private fun folder(name: String, vararg notes: JSONObject) =
        JSONObject().put("folder", name).put("notes", JSONArray(notes.toList()))

    private fun all(vararg folders: JSONObject) = JSONObject().put("folders", JSONArray(folders.toList())).toString()

    @Test fun foldersAndNotesParse() {
        val f = VaultNotes.parse(all(folder("study/network-plus", note()), folder("daily", note("daily/week.md"))))!!
        assertEquals(listOf("study/network-plus", "daily"), f.map { it.folder })
        assertEquals("dns", f[0].notes[0].name)
        assertEquals("# DNS\nNames to addresses.\n", f[0].notes[0].text)
        assertEquals(emptyList<VaultFolder>(), VaultNotes.parse(all()))
    }

    @Test fun countsPerFolder() {
        val f = VaultNotes.parse(all(folder("daily", note("daily/a.md"), note("daily/b.md")), folder("study", note("study/c.md"))))!!
        assertEquals(mapOf("daily" to 2, "study" to 1), VaultNotes.counts(f))
    }

    @Test fun anythingOffShapeIsNull() {
        for (bad in listOf("", "{", all(folder("Templates", note("Templates/t.md"))),
                all(folder("study/..", note("study/../x.md"))), all(folder("study", note("daily/x.md"))),
                all(folder("study", note("study/x.md", text = "a\u202Eb"))),
                all(folder("study", note("study/x.md", text = "y".repeat(4001)))),
                all(folder("study", note("study/x.md", modified = "16 Oct"))),
                all(folder("study", *Array(301) { note("study/n$it.md") }))))
            assertNull(bad, VaultNotes.parse(bad))
    }
}
