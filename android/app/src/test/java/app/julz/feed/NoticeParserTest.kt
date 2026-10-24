package app.julz.feed

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threat 91: a notice is untrusted data. Anything off shape is dropped. */
class NoticeParserTest {
    private fun line(
        title: String = "Julz: 2 specs waiting",
        message: String = "Open the approver to read it before you approve.",
        tags: String = "[\"k_approval\"]",
        extra: String = "",
        id: String = "a1B2c3D4e5F6",
        event: String = "message",
    ) = "{\"id\":\"$id\",\"time\":1792000000,\"event\":\"$event\",\"topic\":\"julz-x\"," +
        "\"title\":${quote(title)},\"message\":${quote(message)},\"tags\":$tags$extra}"

    private fun quote(s: String) = org.json.JSONObject.quote(s)

    @Test fun aGoodNoticeParses() {
        val n = NoticeParser.parse(line())
        assertNotNull(n)
        assertEquals("a1B2c3D4e5F6", n!!.id)
        assertEquals(1792000000L, n.time)
        assertEquals(Kind.APPROVAL, n.kind)
        assertEquals("Julz: 2 specs waiting", n.title)
    }

    @Test fun keepalivesAndOpenEventsAreNotNotices() {
        assertNull(NoticeParser.parse(line(event = "keepalive")))
        assertNull(NoticeParser.parse(line(event = "open")))
    }

    @Test fun theKindMustBeExactlyOneKnownTag() {
        assertNull(NoticeParser.parse(line(tags = "[]")))
        assertNull(NoticeParser.parse(line(tags = "[\"k_evil\"]")))
        assertNull(NoticeParser.parse(line(tags = "[\"k_run\",\"k_approval\"]")))
        assertEquals(Kind.RUN, NoticeParser.parse(line(tags = "[\"warning\",\"k_run\"]"))!!.kind)
    }

    @Test fun hiddenAndRightToLeftCharactersAreDropped() {
        assertNull(NoticeParser.parse(line(title = "Julz: ok\u202Eevil")))  // RTL override
        assertNull(NoticeParser.parse(line(title = "Julz:\u200Bok")))  // zero width space
        assertNull(NoticeParser.parse(line(message = "a\u0007b")))  // control character
        assertNull(NoticeParser.parse(line(title = "two\nlines")))
    }

    @Test fun tooLongIsDropped() {
        assertNotNull(NoticeParser.parse(line(title = "x".repeat(120))))
        assertNull(NoticeParser.parse(line(title = "x".repeat(121))))
        assertNull(NoticeParser.parse(line(message = "x".repeat(501))))
    }

    @Test fun markupStaysPlainText() {
        val n = NoticeParser.parse(line(title = "<b>Julz</b> https://evil.example"))
        assertEquals("<b>Julz</b> https://evil.example", n!!.title)  // shown as text, never a link
    }

    @Test fun linksButtonsAndAttachmentsAreIgnored() {
        // A Notice has no field that could hold them, so they can never reach the screen (86)
        val n = NoticeParser.parse(line(extra = ",\"click\":\"https://evil.example\"," +
            "\"actions\":[{\"action\":\"view\",\"label\":\"Approve\",\"url\":\"https://evil.example\"}]," +
            "\"attachment\":{\"url\":\"https://evil.example/x.apk\"},\"icon\":\"https://evil.example/i.png\""))
        assertNotNull(n)
        assertEquals(setOf("id", "time", "kind", "title", "message"),
            Notice::class.java.declaredFields.map { it.name }.filter { !it.startsWith("$") }.toSet())
    }

    @Test fun badIdsTimesAndJsonAreDropped() {
        assertNull(NoticeParser.parse(line(id = "../../x")))
        assertNull(NoticeParser.parse(line(id = "")))
        assertNull(NoticeParser.parse(line().replace("1792000000", "-5")))
        assertNull(NoticeParser.parse("not json"))
        assertNull(NoticeParser.parse(line().replace("\"title\":", "\"title\":5,\"x\":")))
        assertNull(NoticeParser.parse("x".repeat(10_000)))
        // valid JSON, but a line this long is refused before it is parsed (memory, threat 92)
        assertNull(NoticeParser.parse(line(extra = ",\"pad\":\"" + "y".repeat(5_000) + "\"")))
    }
}
