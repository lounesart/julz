package app.julz.feed

import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threat 120: feedback from the app, and the list of it from the approver. */
class FeedbackTest {
    private fun item(name: String = "2026-10-17 tabs", done: Boolean = false, kind: String = "idea",
                     state: String = "planned", where: String = "BACKLOG 41", text: String = "Tabs for messages.",
                     created: String = "2026-10-17") =
        JSONObject().put("name", name).put("done", done).put("created", created).put("kind", kind)
            .put("state", state).put("where", where).put("text", text)

    private fun list(vararg items: JSONObject) = JSONObject().put("items", JSONArray(items.toList())).toString()

    @Test fun theListParses() {
        val l = FeedbackList.parse(list(item(), item("2026-10-15 old", done = true, kind = "", state = "done", where = "")))!!
        assertEquals(listOf(false, true), l.map { it.done })
        assertEquals("planned", l[0].state)
        assertEquals("BACKLOG 41", l[0].where)
        assertEquals(emptyList<FeedbackItem>(), FeedbackList.parse(list()))
    }

    @Test fun anOffShapeListIsNull() {
        for (bad in listOf("", "{", list(item(kind = "rant")), list(item(text = "a\u202Eb")),
                list(item(text = "y".repeat(601))), list(item(name = "../x")), list(item(created = "17 Oct")),
                list(*Array(71) { item() })))
            assertNull(bad, FeedbackList.parse(bad))
    }

    @Test fun sendingCarriesTheKindTheWordsAndTheirHash() {
        val body = FeedbackList.body("bug", "Logs title wraps.")!!
        assertEquals(setOf("action", "kind", "text", "sha256", "via"), body.keys().asSequence().toSet())
        assertEquals("feedback", body.getString("action"))
        val sha = MessageDigest.getInstance("SHA-256").digest("Logs title wraps.".toByteArray())
            .joinToString("") { "%02x".format(it) }
        assertEquals(sha, body.getString("sha256"))
        assertNull(FeedbackList.body("rant", "x"))
        assertNull(FeedbackList.body("idea", "   "))
        assertNull(FeedbackList.body("idea", "y".repeat(2001)))
    }
}
