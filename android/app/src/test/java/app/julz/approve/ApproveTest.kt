package app.julz.approve

import app.julz.ui.Origins
import java.util.Base64
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threats 107 to 111: the app half of the Julz device key. The vectors come from
 *  julz_devicekey.py, so both sides build the same bytes. */
class ApproveTest {
    private val o = Origins.from("https://laptop.tail1234.ts.net:8444")!!

    @Test fun thePayloadMatchesTheLaptop() {
        val p = DevicePayload.build("approve", "goal: x\nnote: use port 8080\n", "11".repeat(32))
        assertEquals("anVsei1kZXZpY2UtdjEA1gEnaZYKiDqe7Ctv/ETgwNVYDSSyPUJnaWx/++f7p7EREREREREREREREREREREREREREREREREREREREREREQ==",
            Base64.getEncoder().encodeToString(p))
        assertNull(runCatching { DevicePayload.build("approve", "x", "not hex") }.getOrNull())
        assertNull(runCatching { DevicePayload.build("approve", "x", "ab") }.getOrNull())  // hex, too short
    }

    @Test fun theFingerprintMatchesTheLaptop() {
        val der = ByteArray(91) { it.toByte() }
        assertEquals("58d2-9459-b213-0a2e", DevicePayload.fingerprint(der))
    }

    @Test fun onlyTheApproverOriginAndItsOwnPaths() {
        assertEquals("https://laptop.tail1234.ts.net:8443", ApproverApi.origin(o))
        assertEquals("https://laptop.tail1234.ts.net:8443/api/state", ApproverApi.url(o, ApproverApi.STATE))
        for (bad in listOf("/api/state?x=1", "//evil.example/", "https://evil.example/api/state", "/api/../x", "api/state"))
            assertNull(bad, ApproverApi.urlOrNull(o, bad))
    }

    private fun spec(name: String = "fix-readme.md", sha: String = "a".repeat(64), text: String = "goal: x\n",
                     project: String = "julz-sandbox") =
        JSONObject().put("name", name).put("sha256", sha).put("text", text).put("project", project)

    @Test fun stateKeepsOnlyWellFormedSpecs() {
        val json = JSONObject()
            .put("enrolled", true).put("device", "58d2-9459-b213-0a2e")
            .put("specs", JSONArray().put(spec())
                .put(spec(name = "../x.md")).put(spec(sha = "zz")).put(spec(text = "y".repeat(4097)))
                .put(spec(project = "Bad Name")).put("not an object"))
            .put("needs", JSONArray().put(JSONObject())).put("queued", JSONArray()).put("keeps", JSONArray())
            .put("running", JSONObject.NULL)
        val s = ApproverState.parse(json.toString())!!
        assertEquals(listOf("fix-readme.md"), s.specs.map { it.name })
        assertEquals("58d2-9459-b213-0a2e", s.device)
        assertEquals(1, s.elsewhere)  // the need waits on the approver page for now
        assertEquals(listOf("Question from Claude" to "1 task waits for your answer"), s.onThePage())
        assertNull(ApproverState.parse("[]"))
        assertNull(ApproverState.parse("not json"))
        assertNull(ApproverState.parse("x".repeat(ApproverState.MAX_BYTES + 1)))
        val big = JSONObject(json.toString()).put("pad", "p".repeat(ApproverState.MAX_BYTES)).toString()
        assertNull(ApproverState.parse(big))  // valid JSON, too big
        assertNull(ApproverState.parse(json.put("device", "<script>").toString())!!.device)
    }

    @Test fun onlyWhatReallyWaitsIsListed() {
        fun state(needs: Int, queued: Int, keeps: Int, running: Boolean) = ApproverState.parse(JSONObject()
            .put("specs", JSONArray())
            .put("needs", JSONArray().apply { repeat(needs) { put(JSONObject()) } })
            .put("queued", JSONArray().apply { repeat(queued) { put(JSONObject()) } })
            .put("keeps", JSONArray().apply { repeat(keeps) { put(JSONObject()) } })
            .put("running", if (running) JSONObject() else JSONObject.NULL).toString())!!
        assertEquals(listOf("Keep" to "1 finished task: choose notes to keep"), state(0, 0, 1, false).onThePage())
        assertEquals(emptyList<Pair<String, String>>(), state(0, 0, 0, false).onThePage())
        assertEquals(listOf("Questions from Claude" to "2 tasks wait for your answer", "Running now" to "Claude is working",
            "Waiting to run" to "3 approved, in line", "Keep" to "2 finished tasks: choose notes to keep"),
            state(2, 3, 2, true).onThePage())
    }

    @Test fun aBeginAnswerMustBeForThisAction() {
        val good = JSONObject().put("nonce", "ab".repeat(32)).put("action", "approve").put("text", "goal: x\n").toString()
        assertEquals("goal: x\n", Begun.parse(good, "approve")!!.text)
        assertNull(Begun.parse(good, "reject"))
        assertNull(Begun.parse(JSONObject(good).put("nonce", "zz").toString(), "approve"))
        assertNull(Begun.parse(JSONObject(good).put("text", "y".repeat(4097)).toString(), "approve"))
        assertNull(Begun.parse("{}", "approve"))
        assertTrue(Begun.parse(good, "approve")!!.nonce.length == 64)
    }

    @Test fun theSignedTextMustCarryTheNoteITyped() {
        val spec = "goal: x\nproject: julz-sandbox\ndone_when: y\n"
        val noted = Begun("ab".repeat(32), "approve", spec + "note: use port 8080\n")
        val plain = Begun("ab".repeat(32), "approve", spec)
        assertTrue(noted.carries("  use port 8080 "))
        assertTrue(plain.carries(""))
        assertTrue(!plain.carries("use port 8080"))  // typed but not in the text: stop
        assertTrue(!noted.carries(""))  // a note I did not type: stop
        assertTrue(!noted.carries("use port 9090"))
        assertTrue(Begun("ab".repeat(32), "reject", spec).carries("ignored on a deny"))
    }

    @Test fun theNoteFollowsTheGateRules() {
        assertNull(Note.problem(""))
        assertNull(Note.problem("use port 8080"))
        for (bad in listOf("a\nb", "see https://x.example", "www.example.com", "<<<x", "y".repeat(281), "ghp_abcdefghijklmnop"))
            assertTrue(bad, Note.problem(bad) != null)
    }
}
