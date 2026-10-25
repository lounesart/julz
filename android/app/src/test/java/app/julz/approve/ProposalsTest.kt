package app.julz.approve

import java.security.MessageDigest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threat 156: changes Julz asks for in the native chat, signed here (208). */
class ProposalsTest {
    private fun sha(s: String) = MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    private fun card(id: String = "1760000000-00000001.json", text: String = "Julz asks to add to daily/week.md:\n\n- [ ] bread\n",
                     hash: String = sha(text)) = JSONObject().put("id", id).put("text", text).put("sha256", hash)

    private fun list(vararg cards: JSONObject) = JSONObject().put("proposals", JSONArray(cards.toList())).toString()

    @Test fun theListParses() {
        val l = Proposals.parse(list(card(), card("1760000001-0000000a.json", "Julz asks to delete Inbox/x.md\n\ngit keeps a copy on the laptop.\n")))!!
        assertEquals(listOf("1760000000-00000001.json", "1760000001-0000000a.json"), l.map { it.id })
        assertEquals("Julz asks to add to daily/week.md:\n\n- [ ] bread\n", l[0].text)
        assertEquals(emptyList<Proposal>(), Proposals.parse(list()))
    }

    @Test fun anOffShapeListIsNull() {
        for (bad in listOf("", "{", "{\"proposals\": 5}", list(card(id = "../x.json")), list(card(id = "1760000000-0000000G.json")),
                list(card(text = "")), list(card(text = "a\u202Eb")), list(card(text = "a\u200Bb")), list(card(text = "a\u0007b")),
                list(card(text = "y".repeat(ApproverState.MAX_TEXT + 1))), list(card(hash = sha("other"))),
                list(card(hash = "A".repeat(64))), list(card().put("extra", 1)), list(*Array(Proposals.MAX + 1) { card() })))
            assertNull(bad.take(60), Proposals.parse(bad))
    }

    @Test fun signingAndDroppingNameTheCardAndItsHash() {
        val p = Proposals.parse(list(card()))!![0]
        for (action in listOf("change", "drop")) {
            val body = Proposals.body(p, action)
            assertEquals(setOf("action", "id", "sha256", "via"), body.keys().asSequence().toSet())
            assertEquals(action, body.getString("action"))
            assertEquals(p.id, body.getString("id"))
            assertEquals(sha(p.text), body.getString("sha256"))
            assertEquals("device", body.getString("via"))
        }
    }

    @Test(expected = IllegalArgumentException::class)
    fun noOtherAction() { Proposals.body(Proposals.parse(list(card()))!![0], "approve") }

    @Test fun theUrlIsAllowed() {
        assertEquals("https://h/api/proposals", ApproverApi.urlOrNull(app.julz.ui.Origins("https://c", "https://h"), ApproverApi.PROPOSALS))
    }
}
