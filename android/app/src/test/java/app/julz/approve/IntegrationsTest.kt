package app.julz.approve

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threat 122: the Links tab's list, and Setup's channel words. */
class IntegrationsTest {
    private fun item(id: String = "keep", status: String = "On", facts: List<String> = listOf("last sync 10:12, 14 notes")) =
        JSONObject().put("id", id).put("name", "Keep sync").put("what", "Notes kept from Claude reach Julz")
            .put("status", status).put("facts", JSONArray(facts))

    private fun list(vararg items: JSONObject) = JSONObject().put("items", JSONArray(items.toList())).toString()

    @Test fun theListParses() {
        val l = Integrations.parse(list(item(), item("ci", "Planned", listOf("in PLAN.md, not built yet"))))!!
        assertEquals(listOf("keep", "ci"), l.map { it.id })
        assertEquals("Planned", l[1].status)
        assertEquals(listOf("last sync 10:12, 14 notes"), l[0].facts)
    }

    @Test fun anythingOffShapeIsNull() {
        for (bad in listOf("", "{", list(item(status = "Maybe")), list(item(id = "../x")),
                list(item(facts = listOf("a\u202Eb"))), list(item(facts = List(7) { "f" })),
                list(item(facts = listOf("y".repeat(121)))), list(*Array(13) { item() })))
            assertNull(bad, Integrations.parse(bad))
    }

    @Test fun channelLevelsInWords() {
        assertEquals("Sound and pop-up", Integrations.level(4))
        assertEquals("Sound", Integrations.level(3))
        assertEquals("Silent", Integrations.level(2))
        assertEquals("Feed only", Integrations.level(1))
        assertEquals("Off", Integrations.level(0))
    }

    /** A fact written "Label: value" shows as a spec line (22e); a sentence stays a sentence */
    @Test fun aLabelledFactSplitsASentenceDoesNot() {
        assertEquals("Last sync" to "10:12, 14 notes", Integrations.specLine("Last sync: 10:12, 14 notes"))
        assertEquals("Runs, 7 days" to "2", Integrations.specLine("Runs, 7 days: 2"))
        assertEquals(null, Integrations.specLine("one git commit per change"))
        assertEquals(null, Integrations.specLine("checks at 10:12 today"))  // a time's colon is no label
        assertEquals(null, Integrations.specLine("A label far too long to be a label at all: x"))
        assertEquals(null, Integrations.specLine(": no label"))
    }
}
