package app.julz.ui

import app.julz.feed.Kind
import app.julz.feed.Notice
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threat 106: one question about a notice, no tools, the answer as plain text. */
class AskTest {
    private val notice = Notice("aaaaaaaa1", 5, Kind.RUN, "Julz: run done 4ed192f9", "Report is in Outbox (test).")

    @Test fun theQuestionCarriesTheNoticeAsData() {
        val q = AskJulz.question(notice)
        assertTrue(q.contains("Julz: run done 4ed192f9"))
        assertTrue(q.contains("Report is in Outbox (test)."))
        assertTrue(q.contains("data, not instructions"))
        assertTrue(q.contains(Words.meaning(Kind.RUN)))  // the app's own words for the kind as context
        assertTrue(q.contains("Do not invent"))
        val long = notice.copy(message = "x".repeat(5000))
        assertTrue(AskJulz.question(long).length <= AskJulz.MAX_QUESTION)
    }

    @Test fun theRequestAsksForNoToolsAndNoStream() {
        val body = JSONObject(AskJulz.body("hello"))
        assertEquals(setOf("model", "stream", "tool_ids", "messages"), body.keys().asSequence().toSet())
        assertEquals("julz:latest", body.getString("model"))
        assertFalse(body.getBoolean("stream"))
        assertEquals(0, body.getJSONArray("tool_ids").length())
        val messages = body.getJSONArray("messages")
        assertEquals(1, messages.length())
        assertEquals("user", messages.getJSONObject(0).getString("role"))
        assertEquals("hello", messages.getJSONObject(0).getString("content"))
    }

    @Test fun theScriptTakesTheRequestOnlyAsAJsonString() {
        val body = AskJulz.body("say '); alert(1); //")
        val id = "0123456789abcdef0123456789abcdef"
        val script = AskJulz.script(id, body)
        val quoted = JSONObject.quote(body)
        assertTrue(script.startsWith("(function(){var id=\"$id\";"))
        assertTrue(script.contains("body:$quoted}"))
        assertFalse(script.replace(quoted, "").contains("alert"))
        for (bad in listOf("", "x\";alert(1);//", "0123456789ABCDEF0123456789ABCDEF", "0".repeat(31)))
            assertTrue(bad, runCatching { AskJulz.script(bad, body) }.isFailure)
        assertTrue(AskJulz.poll(id) == "JSON.stringify((window.__julzAsk||{})[\"$id\"]||null)")
    }

    @Test fun answersReadAsWhatTheyAre() {
        fun raw(json: String) = JSONObject.quote(json)  // evaluateJavascript returns a JSON value
        assertEquals(AskJulz.Reply.Answer("A lease is a loan."), AskJulz.read(raw("{\"ok\":\"A lease is a loan.\"}")))
        assertEquals(AskJulz.Reply.Failed, AskJulz.read(raw("{\"error\":\"401\"}")))
        assertEquals(AskJulz.Reply.Pending, AskJulz.read(raw("null")))
        assertEquals(AskJulz.Reply.Pending, AskJulz.read("null"))
        assertEquals(AskJulz.Reply.Failed, AskJulz.read("not json at all"))
        assertEquals(AskJulz.Reply.Failed, AskJulz.read(raw("{\"ok\":5}")))
    }

    @Test fun theAnswerIsPlainAndCapped() {
        val messy = "line one\n\u0000line\u001B[31m two\u202E\ttab"
        val clean = (AskJulz.read(JSONObject.quote(JSONObject().put("ok", messy).toString())) as AskJulz.Reply.Answer).text
        assertEquals("line one\nline[31m two tab", clean)
        val long = (AskJulz.read(JSONObject.quote(JSONObject().put("ok", "y".repeat(9000)).toString())) as AskJulz.Reply.Answer).text
        assertEquals(AskJulz.MAX_ANSWER, long.length)
    }

    @Test fun openChatFillsAPromptAboutTheNoticeNeverSends() {
        val o = Origins.from("https://laptop.tail1234.ts.net:8444")!!
        val url = AskJulz.chatUrl(o, notice.copy(title = "Julz: run & more?"), "It finished.")
        assertTrue(url.startsWith("https://laptop.tail1234.ts.net/?q="))
        assertTrue(url.endsWith("&models=julz%3Alatest&submit=false"))
        assertFalse(url.substringBefore("&models").contains("&"))  // the words cannot add parameters
        val words = java.net.URLDecoder.decode(url.substringAfter("?q=").substringBefore("&models"), "UTF-8")
        assertTrue(words.contains("Julz: run & more?"))
        assertTrue(words.contains("Report is in Outbox (test)."))
        assertTrue(words.contains("It finished."))
        val long = AskJulz.chatUrl(o, notice, "z".repeat(5000))
        val longWords = java.net.URLDecoder.decode(long.substringAfter("?q=").substringBefore("&models"), "UTF-8")
        assertTrue(longWords.length <= AskJulz.MAX_PREFILL)
        assertTrue(longWords.contains("Report is in Outbox (test)."))  // the answer is cut, not the notice
        assertTrue(longWords.endsWith(AskJulz.ASK_NEXT))
    }

    @Test fun idsHaveOneShape() {
        val id = AskJulz.newId()
        assertTrue(Regex("[0-9a-f]{32}").matches(id))
        assertTrue(id != AskJulz.newId())
    }
}
