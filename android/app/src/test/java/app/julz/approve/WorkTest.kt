package app.julz.approve

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threat 121: Claude's questions, the running job, queued runs and Keep, natively. */
class WorkTest {
    private val A = "a".repeat(64); private val B = "b".repeat(64); private val C = "c".repeat(64)

    private fun need(stopped: Boolean = false, need: String = "run the tests on the laptop", sha: String = B) =
        JSONObject().put("root", A).put("step", 2).put("project", "julz-sandbox").put("goal", "add a usage line")
            .put("need", need).put("why", "the sandbox has no network").put("text", "continue: $A\nanswer: done\n")
            .put("sha256", sha).put("work", "/home/v/.local/share/julz/work/$A").put("stopped", stopped)

    private fun keep(files: List<Pair<String, Int>> = listOf("labs/01-osi.md" to 3400, "labs/02-tcp.md" to 4100)) =
        JSONObject().put("root", A).put("goal", "Network+ labs").put("project", "julz-sandbox")
            .put("files", JSONArray(files.map { JSONObject().put("path", it.first).put("size", it.second) }))
            .put("rejected", JSONArray(listOf(JSONObject().put("path", "x.sh").put("reason", "not a note"))))
            .put("rejected_count", 1).put("stopped", JSONObject.NULL).put("sha256", B)

    private fun state(needs: List<JSONObject> = listOf(need()), keeps: List<JSONObject> = listOf(keep()),
                      running: JSONObject? = JSONObject().put("sha256", C).put("project", "julz-sandbox").put("goal", "x")
                          .put("step", 1).put("started", 1).put("text", "halt: $C\n").put("text_sha256", B),
                      queued: List<JSONObject> = listOf(JSONObject().put("sha256", C).put("goal", "y").put("step", 1)
                          .put("kind", "spec").put("overridden", false).put("override", JSONObject().put("text", "override: $C\n").put("sha256", A)))) =
        JSONObject().put("specs", JSONArray()).put("needs", JSONArray(needs)).put("keeps", JSONArray(keeps))
            .put("running", running ?: JSONObject.NULL).put("queued", JSONArray(queued)).toString()

    // Found 18 Oct (9b): the web page offered my topics, the app did not
    @Test fun topicsAreTheServersListCheckedAgain() {
        val raw = JSONObject(state()).put("topics", JSONArray(listOf("daily", "network-plus", "Bad Topic", "../x",
            "a".repeat(41), "x\u202Ey"))).toString()
        assertEquals(listOf("daily", "network-plus"), WorkState.parse(raw)!!.topics)
        val many = JSONObject(state()).put("topics", JSONArray((1..30).map { "t$it" })).toString()
        assertEquals(20, WorkState.parse(many)!!.topics.size)
        assertEquals(emptyList<String>(), WorkState.parse(state())!!.topics)
    }

    // Found 18 Oct (9b): the page button showed with every card, so I used the page
    @Test fun pageButtonOnlyForCardsTheAppCouldNotShow() {
        val all = ApproverState(emptyList(), null, needs = 1, queued = 1, keeps = 1, running = true)
        assertEquals(0, hiddenCards(all, WorkState.parse(state())))
        assertEquals(1, hiddenCards(all, WorkState.parse(state(needs = listOf(need(sha = "short"))))))
        assertEquals(4, hiddenCards(all, null))
    }

    // Found 18 Oct (9b): the badge counted unread notices, so it stayed after I approved
    @Test fun badgeCountsWhatWaitsForMeNotWhatRuns() {
        val spec = SpecItem("a.md", "julz-sandbox", "x", A)
        assertEquals(3, ApproverState(listOf(spec), null, needs = 1, queued = 2, keeps = 1, running = true).waitingForMe)
        assertEquals(0, ApproverState(emptyList(), null, queued = 1, running = true).waitingForMe)
    }

    // Found 18 Oct (9b): a run took 5 to 14 s and the screen never reloaded, so Stop never showed
    @Test fun approveReloadsFastWhileSomethingMoves() {
        val busy = WorkState.parse(state())!!
        val idle = WorkState.parse(state(needs = emptyList(), keeps = emptyList(), running = null, queued = emptyList()))!!
        assertEquals(3_000L, reloadDelay(busy, now = 0L, fastUntil = 0L))
        assertEquals(15_000L, reloadDelay(idle, now = 0L, fastUntil = 0L))
        assertEquals(3_000L, reloadDelay(idle, now = 1_000L, fastUntil = 60_000L))
        assertEquals(15_000L, reloadDelay(idle, now = 61_000L, fastUntil = 60_000L))
        assertEquals(15_000L, reloadDelay(null, now = 0L, fastUntil = 0L))
    }

    @Test fun allFourKindsParse() {
        val w = WorkState.parse(state())!!
        assertEquals("run the tests on the laptop", w.needs.single().need)
        assertEquals(listOf("labs/01-osi.md", "labs/02-tcp.md"), w.keeps.single().files.map { it.path })
        assertEquals("not a note", w.keeps.single().rejected.single().second)
        assertEquals(C, w.running!!.sha256)
        assertEquals(A, w.queued.single().overrideSha)
    }

    @Test fun aBadCardIsDroppedNotTheRest() {
        val w = WorkState.parse(state(needs = listOf(need(sha = "short"), need(need = "a\u202Eb"), need(need = "y".repeat(501)), need())))!!
        assertEquals(1, w.needs.size)
        val k = WorkState.parse(state(keeps = listOf(keep(listOf("../etc/passwd" to 1)), keep(listOf("/abs.md" to 1)), keep())))!!
        assertEquals(1, k.keeps.size)
        assertNull(WorkState.parse("{"))
    }

    @Test fun needBodiesCarryOnlyTheIdTheHashAndTheAnswer() {
        val n = WorkState.parse(state())!!.needs.single()
        val go = WorkBodies.need(n, "")!!
        assertEquals(setOf("action", "root", "sha256", "via"), go.keys().asSequence().toSet())
        assertEquals("continue", go.getString("action"))
        val answer = WorkBodies.need(n, "use port 8080")!!
        assertEquals("answer", answer.getString("action"))
        assertEquals("use port 8080", answer.getString("answer"))
        assertNull(WorkBodies.need(n, "see https://evil.example"))
        assertNull(WorkBodies.need(n, "token ghp_" + "A1b2".repeat(10)))
        assertNull(WorkBodies.need(n, "y".repeat(301)))
        assertEquals("stop", WorkBodies.stop(n).getString("action"))
        val stopped = WorkState.parse(state(needs = listOf(need(stopped = true))))!!.needs.single()
        assertEquals("discard", WorkBodies.stop(stopped).getString("action"))
    }

    @Test fun haltOverrideAndKeepBodies() {
        val w = WorkState.parse(state())!!
        val halt = WorkBodies.halt(w.running!!)
        assertEquals(setOf("action", "run", "sha256", "via"), halt.keys().asSequence().toSet())
        assertEquals(B, halt.getString("sha256"))
        assertEquals(A, WorkBodies.override(w.queued.single())!!.getString("sha256"))
        val k = w.keeps.single()
        val body = WorkBodies.keep(k, "network-plus", listOf("labs/02-tcp.md", "labs/01-osi.md"))!!
        assertEquals(listOf("labs/01-osi.md", "labs/02-tcp.md"),  // in the card's order, never mine
            (0 until body.getJSONArray("pick").length()).map { body.getJSONArray("pick").getString(it) })
        assertNull(WorkBodies.keep(k, "Bad Topic", listOf("labs/01-osi.md")))
        assertNull(WorkBodies.keep(k, "network-plus", emptyList()))
        assertNull(WorkBodies.keep(k, "network-plus", listOf("labs/99-not-in-card.md")))
        assertTrue(body.keys().asSequence().toSet() == setOf("action", "root", "sha256", "topic", "pick", "via"))
    }

    /** Julz says the first 8 characters of the spec id; the card shows the same 8 (39b). */
    @Test fun aSpecHasTheShortIdJulzSays() {
        assertEquals(A.take(8), SpecItem("a.md", "julz-sandbox", "x", A).shortId)
    }
}
