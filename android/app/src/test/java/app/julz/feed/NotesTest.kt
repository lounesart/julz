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
                     name: String = note.substringAfterLast('/').removeSuffix(".md"), tags: List<Any> = emptyList()) =
        JSONObject().put("name", name).put("note", note).put("modified", modified).put("size", 30).put("id", id)
            .put("tags", JSONArray(tags))

    private fun one(note: String = "study/network-plus/dns.md", text: String = "# DNS\nNames to addresses.\n") =
        JSONObject().put("note", note).put("text", text).toString()

    private fun folder(name: String, vararg notes: JSONObject) =
        JSONObject().put("folder", name).put("notes", JSONArray(notes.toList()))

    private fun all(vararg folders: JSONObject, tags: List<Any> = emptyList()) =
        JSONObject().put("folders", JSONArray(folders.toList())).put("tags", JSONArray(tags)).toString()

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

    /** 212, threat 149: the tag table and each note's indexes into it. */
    @Test fun tagsResolveToTheirNames() {
        val f = VaultNotes.parse(all(folder("study", note("study/a.md", tags = listOf(1, 0))),
            folder("daily", note("daily/b.md", tags = listOf(0)), note("daily/c.md")), tags = listOf("net", "сеть")))!!
        assertEquals(listOf("сеть", "net"), f[0].notes[0].tags)
        assertEquals(emptyList<String>(), f[1].notes[1].tags)
        // A tag view lists its notes across folders
        assertEquals(listOf("study/a.md", "daily/b.md"), VaultNotes.withTag(f, "net").map { it.note })
        assertEquals(emptyList<VaultNote>(), VaultNotes.withTag(f, "dns"))
    }

    @Test fun tagsOffShapeAreNull() {
        val n = { t: List<Any> -> folder("study", note("study/a.md", tags = t)) }
        val table = listOf("net", "dns")
        val cases = mapOf(
            "out of range" to all(n(listOf(2)), tags = table), "negative" to all(n(listOf(-1)), tags = table),
            "duplicate index" to all(n(listOf(0, 0)), tags = table), "a string index" to all(n(listOf("0")), tags = table),
            "eleven" to all(n(List(11) { it }), tags = List(11) { "t$it" }),
            "upper case" to all(n(listOf(0)), tags = listOf("Net")), "space" to all(n(listOf(0)), tags = listOf("a b")),
            "hidden" to all(n(listOf(0)), tags = listOf("a\u202Eb")), "number first" to all(n(listOf(0)), tags = listOf("2026")),
            "too long" to all(n(listOf(0)), tags = listOf("l".repeat(41))), "not a string" to all(n(listOf(0)), tags = listOf(5)),
            "duplicate tag" to all(n(listOf(0)), tags = listOf("net", "net")),
            "201 tags" to all(n(listOf(0)), tags = List(201) { "t$it" }),
            "no table" to JSONObject().put("folders", JSONArray(listOf(n(listOf())))).toString(),
            "no tags on a note" to all(folder("study", JSONObject(note("study/a.md").toString()).apply { remove("tags") })))
        for ((name, bad) in cases) assertNull(name, VaultNotes.parse(bad))
    }

    @Test fun aTappedTagIsLookedUpByItsKey() {
        assertEquals("net", VaultNotes.tagKey("#Net"))
        assertEquals("lab", VaultNotes.tagKey("'#lab'"))
        assertEquals("сеть/ip", VaultNotes.tagKey("Сеть/IP"))
        for (bad in listOf("", "#", "a b", "#2026", "x:y", "a\u202Eb", "l".repeat(41))) assertNull(bad, VaultNotes.tagKey(bad))
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
