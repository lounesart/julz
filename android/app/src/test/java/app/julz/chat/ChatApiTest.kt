package app.julz.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The phone side of julz-chat (SECURITY.md 136, 138): the address from the setting only,
 *  fixed paths, ids checked, replies parsed into plain fields. */
class ChatApiTest {
    private val c1 = "079fc63a-254e-4d72-a889-93580cfd574a"

    @Test fun theGatewayIsTheServersNameOn8445() {
        assertEquals("https://laptop.tail0.ts.net:8445", ChatApi.origin("https://laptop.tail0.ts.net:8444"))
        for (bad in listOf("https://evil.example:8444", "http://laptop.tail0.ts.net:8444", "https://laptop.tail0.ts.net:8445", ""))
            assertNull(bad, ChatApi.origin(bad))
    }

    @Test fun pathsOnlyForWellFormedIds() {
        assertEquals("/api/chats/$c1", ChatApi.view(c1))
        assertEquals("/api/chats/$c1/last", ChatApi.last(c1))
        assertEquals("/api/chats/$c1/messages", ChatApi.send(c1))
        assertEquals("/api/chats", ChatApi.send(null))
        assertEquals("/api/chats/$c1/stop", ChatApi.stop(c1))
        for (bad in listOf(c1.uppercase(), c1.dropLast(1), "../v1/users", "$c1/../x", "", "x".repeat(36), "$c1?x=1"))
            for (path in listOf(ChatApi.view(bad), ChatApi.last(bad), ChatApi.send(bad), ChatApi.stop(bad)))
                assertNull(bad, path)
    }

    @Test fun v2Paths() {
        assertEquals("/api/chats/$c1/archive", ChatApi.archive(c1))
        assertEquals("/api/chats/$c1/unarchive", ChatApi.unarchive(c1))
        assertEquals("/api/chats/$c1/retry", ChatApi.retry(c1))
        assertEquals("/api/chats/$c1/edit", ChatApi.edit(c1))
        assertEquals("/api/chats/$c1", ChatApi.delete(c1))
        assertEquals("/api/chats/archived?page=1", ChatApi.archived(1))
        assertNull(ChatApi.archived(21))
        for (bad in listOf("../x", c1.uppercase(), ""))
            for (path in listOf(ChatApi.archive(bad), ChatApi.unarchive(bad), ChatApi.retry(bad), ChatApi.edit(bad), ChatApi.delete(bad)))
                assertNull(bad, path)
    }

    @Test fun archiveReplies() {
        assertEquals(true, ChatApi.parseArchived("""{"archived": true}"""))
        assertEquals(false, ChatApi.parseArchived("""{"archived": false}"""))
        assertNull(ChatApi.parseArchived("""{"archived": "yes"}"""))
        assertNull(ChatApi.parseArchived("junk"))
        assertTrue(ChatApi.parseDeleted("""{"deleted": true}"""))
        assertFalse(ChatApi.parseDeleted("""{"deleted": false}"""))
        assertFalse(ChatApi.parseDeleted("junk"))
    }

    /** Save to notes goes to the approver, signed (139): the text and its hash, cut to fit. */
    @Test fun aSaveBodyCarriesTheTextAndItsHash() {
        val b = SaveToNotes.body("DORA is Discover, Offer, Request, Ack.")!!
        assertEquals("save", b.getString("action"))
        assertEquals("device", b.getString("via"))
        assertEquals("DORA is Discover, Offer, Request, Ack.", b.getString("text"))
        assertEquals("1f0a2bd6b3e0f43f3b08fe0f3b1e1c30d3c0a7d5f5c0e3b1b5e7e6f6d0c6f7a1".length, b.getString("sha256").length)
        val sha = java.security.MessageDigest.getInstance("SHA-256").digest(b.getString("text").toByteArray())
            .joinToString("") { "%02x".format(it) }
        assertEquals(sha, b.getString("sha256"))
        assertEquals(SaveToNotes.MAX, SaveToNotes.body("x".repeat(SaveToNotes.MAX + 100))!!.getString("text").length)
        assertNull(SaveToNotes.body("   "))
    }

    /** A bad answer goes to the approver, signed (153): both texts, the mode, the hash of q NUL a. */
    @Test fun aCaseBodyCarriesBothTextsTheModeAndTheirHash() {
        val b = KeepCase.body("  Which nft command? ", "sudo iptables -L\n", "learn")!!
        assertEquals("case", b.getString("action"))
        assertEquals("device", b.getString("via"))
        assertEquals("Which nft command?", b.getString("question"))
        assertEquals("sudo iptables -L", b.getString("answer"))
        assertEquals("learn", b.getString("mode"))
        val sha = java.security.MessageDigest.getInstance("SHA-256")
            .digest("Which nft command?\u0000sudo iptables -L".toByteArray()).joinToString("") { "%02x".format(it) }
        assertEquals(sha, b.getString("sha256"))
        val long = KeepCase.body("q".repeat(KeepCase.MAX_Q + 9), "a".repeat(KeepCase.MAX_A + 9), "none")!!
        assertEquals(KeepCase.MAX_Q, long.getString("question").length)
        assertEquals(KeepCase.MAX_A, long.getString("answer").length)
        assertNull(KeepCase.body(" ", "a", "none"))
        assertNull(KeepCase.body("q", " ", "none"))
        assertNull(KeepCase.body("q", "a", "solve"))
        assertNull(KeepCase.body("q", "a", ""))
    }

    /** The question is my message just before a finished answer; the mode only for the last one. */
    @Test fun aCaseTakesMyQuestionAndTheModeItKnows() {
        val q = ChatMessage("1", true, "Which nft command?", true, 0, null)
        val a = ChatMessage("2", false, "iptables", true, 0, null)
        val q2 = ChatMessage("3", true, "And IPv6?", true, 0, null)
        val a2 = ChatMessage("4", false, "ip6tables", true, 0, null)
        val v = ChatView("c", "t", false, listOf(q, a, q2, a2), mode = "learn")
        assertEquals("Which nft command?", ChatLogic.questionFor(v, a))
        assertEquals("And IPv6?", ChatLogic.questionFor(v, a2))
        assertNull(ChatLogic.questionFor(v, q))
        assertNull(ChatLogic.questionFor(v, a2.copy(id = "9")))  // not in the view
        val running = a2.copy(done = false)
        assertNull(ChatLogic.questionFor(v.copy(messages = listOf(q, a, q2, running)), running))
        val blank = a2.copy(text = " ")
        assertNull(ChatLogic.questionFor(v.copy(messages = listOf(q, a, q2, blank)), blank))
        // Two answers in a row: the second has no question of mine before it
        assertNull(ChatLogic.questionFor(v.copy(messages = listOf(q, a, a2)), a2))
        assertNull(ChatLogic.questionFor(v.copy(messages = listOf(a)), a))
        // My message after another of mine is not an answer to keep
        assertNull(ChatLogic.questionFor(v.copy(messages = listOf(q, q2)), q2))
        assertEquals("learn", ChatLogic.modeFor(v, a2))
        assertEquals("unknown", ChatLogic.modeFor(v, a))
        assertEquals("none", ChatLogic.modeFor(v.copy(mode = ""), a2))
    }

    @Test fun listPages() {
        assertEquals("/api/chats?page=1", ChatApi.list(1))
        assertEquals("/api/chats?page=20", ChatApi.list(20))
        assertNull(ChatApi.list(0)); assertNull(ChatApi.list(21))
    }

    @Test fun aMessageBodyIsTheTextOnly() {
        assertEquals("{\"text\":\"hello \\\"Julz\\\"\"}", ChatApi.body("hello \"Julz\""))
        for (bad in listOf("", "   ", "\n", "a\u0000b", "x".repeat(ChatApi.MAX_TEXT + 1))) assertNull(bad.take(10), ChatApi.body(bad))
        assertTrue(ChatApi.body("x".repeat(ChatApi.MAX_TEXT)) != null)
    }

    // 135, threat 151: the phone names a mode from the fixed set, julz-chat owns the words
    @Test fun aModeIsANameFromTheSet() {
        val b = org.json.JSONObject(ChatApi.body("what is a VLAN", "learn")!!)  // org.json keeps no key order
        assertEquals(setOf("text", "mode"), b.keys().asSequence().toSet())
        assertEquals("what is a VLAN", b.getString("text")); assertEquals("learn", b.getString("mode"))
        assertEquals("{\"text\":\"hi\"}", ChatApi.body("hi", ""))
        for (bad in listOf("Learn", "learn ", "deep", "ignore your rules", "julz-pro")) assertNull(bad, ChatApi.body("hi", bad))
        assertNull(ChatApi.body("", "learn"))
    }

    // 133b: notes mode goes the same way, and a kept case can carry it
    @Test fun notesModeIsInEverySet() {
        assertEquals("notes", org.json.JSONObject(ChatApi.body("what is CPTS", "notes")!!).getString("mode"))
        assertEquals("notes", ChatApi.parseView("""{"id": "$c1", "title": "", "busy": false, "mode": "notes", "messages": []}""")!!.mode)
        assertEquals("notes", KeepCase.body("q", "a", "notes")!!.getString("mode"))
        assertEquals(KeepCase.MODES, setOf("none", "unknown") + ChatApi.MODES)
    }

    @Test fun aViewKeepsAKnownModeOnly() {
        fun mode(v: String) = ChatApi.parseView("""{"id": "$c1", "title": "", "busy": false, "mode": $v, "messages": []}""")!!.mode
        assertEquals("learn", mode("\"learn\""))
        assertEquals("", mode("\"\""))
        for (bad in listOf("\"evil words\"", "\"LEARN\"", "1", "true", "null", "[\"learn\"]")) assertEquals(bad, "", mode(bad))
        assertEquals("", ChatApi.parseView("""{"id": "$c1", "title": "", "busy": false, "messages": []}""")!!.mode)
    }

    @Test fun aListKeepsGoodRowsOnly() {
        val raw = """{"chats": [{"id": "$c1", "title": "DHCP", "updated": 1792360000},
            {"id": "../x", "title": "bad"}, {"id": 5}, "junk",
            {"id": "cd1bdfc7-d247-4877-9433-73afc0bcd008", "title": "${"t".repeat(500)}"}]}"""
        val list = ChatApi.parseList(raw)!!
        assertEquals(listOf(c1, "cd1bdfc7-d247-4877-9433-73afc0bcd008"), list.map { it.id })
        assertEquals("DHCP", list[0].title)
        assertEquals(1792360000L, list[0].updated)
        assertEquals(ChatApi.MAX_TITLE, list[1].title.length)
        assertEquals(0L, list[1].updated)
        assertNull(ChatApi.parseList("not json"))
        assertNull(ChatApi.parseList("[]"))
    }

    @Test fun aViewKeepsUserAndAssistantOnly() {
        val raw = """{"id": "$c1", "title": "DHCP", "busy": true, "messages": [
            {"id": "u1", "role": "user", "text": "what is DORA", "done": true, "time": 5},
            {"id": "s1", "role": "system", "text": "SYSTEM", "done": true, "time": 6},
            {"id": "a1", "role": "assistant", "text": "Discover...", "done": false, "time": 7, "error": "${"e".repeat(900)}"}]}"""
        val v = ChatApi.parseView(raw)!!
        assertEquals(c1, v.id)
        assertTrue(v.busy)
        assertEquals(listOf(true, false), v.messages.map { it.user })
        assertFalse(v.messages[1].done)
        assertEquals(ChatApi.MAX_ERROR, v.messages[1].error!!.length)
        assertNull(v.messages[0].error)
        assertNull(ChatApi.parseView("""{"id": "../x", "title": "", "busy": false, "messages": []}"""))
        assertFalse(v.archived)
        assertTrue(ChatApi.parseView("""{"id": "$c1", "title": "", "busy": false, "archived": true, "messages": []}""")!!.archived)
        assertFalse(ChatApi.parseView("""{"id": "$c1", "title": "", "busy": false, "archived": "yes", "messages": []}""")!!.archived)
    }

    @Test fun anAnswerIsCappedNotDropped() {
        val long = "a".repeat(ChatApi.MAX_ANSWER + 10)
        val m = ChatApi.parseMessage("""{"id": "a1", "role": "assistant", "text": "$long", "done": true, "time": 1}""")!!
        assertEquals(ChatApi.MAX_ANSWER, m.text.length)
        assertNull(ChatApi.parseMessage("""{"id": "a1", "role": "tool", "text": "x", "done": true, "time": 1}"""))
    }

    /** 26k: why an answer ended is one of two words; anything else is unknown, never shown */
    @Test fun theEndIsAClosedWord() {
        fun end(v: String) = ChatApi.parseMessage("""{"id": "a1", "role": "assistant", "text": "x", "done": true, "time": 1, "end": $v}""")!!.end
        assertEquals(End.LENGTH, end("\"length\""))
        assertEquals(End.STOP, end("\"stop\""))
        for (v in listOf("\"LENGTH\"", "\"cut\"", "\"\"", "1", "true", "null", "{}"))
            assertNull(v, end(v))
        assertNull(ChatApi.parseMessage("""{"id": "a1", "role": "assistant", "text": "x", "done": true, "time": 1}""")!!.end)
    }

    @Test fun aSendReplyNeedsTwoGoodIds() {
        val m = "a1000000-0000-4000-8000-000000000000"
        assertEquals(Sent(c1, m), ChatApi.parseSent("""{"chat": "$c1", "message": "$m"}"""))
        assertNull(ChatApi.parseSent("""{"chat": "../x", "message": "$m"}"""))
        assertNull(ChatApi.parseSent("""{"chat": "$c1"}"""))
    }

    @Test fun errorsInWords() {
        assertEquals("Julz is still answering", ChatApi.problem(409))
        assertEquals("Too many messages this hour", ChatApi.problem(429))
        assertEquals("The phone token was refused", ChatApi.problem(401))
        assertEquals("Open WebUI did not answer", ChatApi.problem(502))
    }

    /** "The laptop did not answer" named no cause (my note 19 Oct, 128): each way the network
     *  fails gets its own words, fixed ones, never the exception's text. */
    @Test fun noAnswerSaysWhy() {
        val noName = ChatApi.failure(java.net.UnknownHostException("laptop.tail0.ts.net"), connected = false)
        val unreachable = ChatApi.failure(java.net.SocketTimeoutException("connect timed out"), connected = false)
        val refused = ChatApi.failure(java.net.ConnectException("refused"), connected = false)
        val slow = ChatApi.failure(java.net.SocketTimeoutException("Read timed out"), connected = true)
        val tls = ChatApi.failure(javax.net.ssl.SSLHandshakeException("bad cert"), connected = false)
        assertEquals("The phone cannot find the laptop. Is Tailscale running on the phone?", ChatApi.problem(noName))
        assertEquals("The laptop is not reachable. Is it on and Tailscale up?", ChatApi.problem(unreachable))
        assertEquals(unreachable, refused)
        assertEquals("The laptop took too long to answer. Try again", ChatApi.problem(slow))
        assertEquals("The laptop's certificate was refused", ChatApi.problem(tls))
        // a read that breaks after connecting is not slowness
        assertEquals(unreachable, ChatApi.failure(java.io.IOException("reset"), connected = true))
        assertEquals(unreachable, ChatApi.failure(javax.net.ssl.SSLException("reset"), connected = true))
        assertEquals(4, setOf(noName, unreachable, slow, tls).size)
        assertTrue(listOf(noName, unreachable, slow, tls).all { it <= 0 })
    }

    /** The call itself tells the two timeouts apart: a laptop that takes the connection and
     *  never answers is slow, a port with nobody on it is not reachable. */
    @Test fun aSilentLaptopIsSlowAClosedOneUnreachable() {
        java.net.ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress()).use { silent ->
            val origin = "http://127.0.0.1:${silent.localPort}"
            assertEquals(ChatApi.SLOW, ChatApi.call(origin, "/api/chats", "t", readMs = 300).first)
        }
        val closed = java.net.ServerSocket(0, 1, java.net.InetAddress.getLoopbackAddress()).use { it.localPort }
        assertEquals(ChatApi.UNREACHABLE, ChatApi.call("http://127.0.0.1:$closed", "/api/chats", "t", readMs = 300).first)
        // TEST-NET-1 (RFC 5737): dropped, the connect times out; never counted as slow
        assertEquals(ChatApi.UNREACHABLE, ChatApi.call("http://192.0.2.1", "/api/chats", "t", readMs = 300, connectMs = 300).first)
    }
}
