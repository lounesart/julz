package app.julz.chat

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** When the screen polls and how a polled answer joins what is shown. */
class ChatLogicTest {
    private val user = ChatMessage("u1", true, "hi", true, 1, null)
    private fun answer(text: String, done: Boolean, id: String = "a1") = ChatMessage(id, false, text, done, 2, null)
    private fun view(vararg m: ChatMessage, busy: Boolean = false) = ChatView("c", "t", busy, m.toList())

    /** The single line box (262): one row while the draft fits beside the controls, Claude's two rows
     *  once it would wrap or has a line break; decided by the draft's width, never the line count */
    @Test fun composerTwoRowsOnlyOnceTheDraftWouldWrap() {
        assertFalse(ChatLogic.composerTwoRows("What is a /26?", textWidth = 120, oneRowWidth = 180))
        assertFalse(ChatLogic.composerTwoRows("", textWidth = 0, oneRowWidth = 180))
        assertFalse(ChatLogic.composerTwoRows("exactly", textWidth = 180, oneRowWidth = 180))
        assertTrue(ChatLogic.composerTwoRows("a long message", textWidth = 181, oneRowWidth = 180))
        assertTrue(ChatLogic.composerTwoRows("one\ntwo", textWidth = 30, oneRowWidth = 180))
        // Not measured yet: one row, as before
        assertFalse(ChatLogic.composerTwoRows("a long message", textWidth = 900, oneRowWidth = 0))
    }

    /** The Sources sheet (238): Notes | Links, only the tabs with something in them, Links first after a web turn */
    @Test fun sourcesTabsShowOnlyWhatIsThere() {
        val notes = answer("x", true).copy(sources = listOf("study/a.md"))
        val web = answer("x", true).copy(links = listOf(WebLink("https://a.example/", "a.example", "A")))
        val both = notes.copy(links = web.links)
        val searchedOnly = answer("x", true).copy(searched = listOf("q"))
        assertEquals(emptyList<String>(), ChatLogic.sourceTabs(answer("x", true)))
        assertEquals(listOf("Notes"), ChatLogic.sourceTabs(notes))
        assertEquals(listOf("Links"), ChatLogic.sourceTabs(web))
        assertEquals(listOf("Links"), ChatLogic.sourceTabs(searchedOnly))
        assertEquals(listOf("Notes", "Links"), ChatLogic.sourceTabs(both))
        assertEquals(1, ChatLogic.firstSourceTab(both))
        assertEquals(0, ChatLogic.firstSourceTab(notes))
        assertEquals(0, ChatLogic.firstSourceTab(web))
        assertEquals(0, ChatLogic.firstSourceTab(answer("x", true)))
    }

    /** The web switch (26d): greyed with Notes, and Notes picked turns it off (julz-chat refuses the pair) */
    @Test fun webNeverWithNotes() {
        assertTrue(ChatLogic.webAllowed(""))
        assertTrue(ChatLogic.webAllowed("learn"))
        assertFalse(ChatLogic.webAllowed("notes"))
        assertTrue(ChatLogic.webWith(true, "learn"))
        assertFalse(ChatLogic.webWith(true, "notes"))
        assertFalse(ChatLogic.webWith(false, ""))
    }

    @Test fun warmsOnceAMinuteAtMost() {
        assertTrue(ChatLogic.warmDue(null, 0))
        assertFalse(ChatLogic.warmDue(1_000, 1_000))
        assertFalse(ChatLogic.warmDue(1_000, 60_999))
        assertTrue(ChatLogic.warmDue(1_000, 61_000))
        assertEquals("/api/warm", ChatApi.WARM)
    }

    @Test fun pollsFastWhileAnsweringThenSlower() {
        assertNull(ChatLogic.pollDelay(busy = false, sinceSendMs = 0))
        assertEquals(300L, ChatLogic.pollDelay(busy = true, sinceSendMs = 0))
        assertEquals(300L, ChatLogic.pollDelay(busy = true, sinceSendMs = 119_999))
        assertEquals(1_000L, ChatLogic.pollDelay(busy = true, sinceSendMs = 120_000))
    }

    @Test fun aPolledAnswerReplacesItsPlaceholder() {
        val v = ChatLogic.withLast(view(user, answer("", false), busy = true), answer("Hello", false))!!
        assertEquals("Hello", v.messages.last().text)
        assertTrue(v.busy)
        val done = ChatLogic.withLast(v, answer("Hello there", true))!!
        assertFalse(done.busy)
        assertEquals(2, done.messages.size)
    }

    @Test fun anotherMessageMeansReload() {
        assertNull(ChatLogic.withLast(view(user, answer("x", true)), answer("y", false, id = "a2")))
        assertNull(ChatLogic.withLast(view(), answer("y", false)))
    }

    @Test fun sendNeedsTextAndQuiet() {
        assertTrue(ChatLogic.canSend("hi", busy = false, sending = false))
        assertFalse(ChatLogic.canSend("  ", busy = false, sending = false))
        assertFalse(ChatLogic.canSend("hi", busy = true, sending = false))
        assertFalse(ChatLogic.canSend("hi", busy = false, sending = true))
        assertFalse(ChatLogic.canSend("x".repeat(ChatApi.MAX_TEXT + 1), busy = false, sending = false))
    }

    @Test fun thinkingOnlyBeforeTheFirstWords() {
        assertTrue(ChatLogic.thinking(view(user, answer("", false), busy = true)))
        assertFalse(ChatLogic.thinking(view(user, answer("Hi", false), busy = true)))
        assertFalse(ChatLogic.thinking(view(user, answer("", true))))
    }

    @Test fun retryOnlyTheLastFinishedAnswer() {
        assertTrue(ChatLogic.canRetry(view(user, answer("x", true)), answer("x", true)))
        assertFalse(ChatLogic.canRetry(view(user, answer("x", true), answer("y", true, id = "a2")), answer("x", true)))
        assertFalse(ChatLogic.canRetry(view(user, answer("x", false), busy = true), answer("x", false)))
        assertFalse(ChatLogic.canRetry(view(user), user))
        assertFalse(ChatLogic.canRetry(view(answer("x", true)), answer("x", true)))  // no message of mine before it
    }

    @Test fun editOnlyMyLastMessage() {
        val v = view(user, answer("x", true))
        assertTrue(ChatLogic.canEdit(v, user))
        assertFalse(ChatLogic.canEdit(v, answer("x", true)))
        val older = ChatMessage("u0", true, "old", true, 0, null)
        assertFalse(ChatLogic.canEdit(view(older, answer("a", true, id = "a0"), user, answer("x", true)), older))
    }

    /** 203: an edit while she answers stops that answer first (julz-chat does it) */
    @Test fun editWhileSheAnswersOnlyTheMessageSheAnswers() {
        assertTrue(ChatLogic.canEdit(view(user, answer("x", false), busy = true), user))
        assertTrue(ChatLogic.canEdit(view(user, answer("", false), busy = true), user))
        // busy, but her running answer does not follow my message right away
        val other = answer("y", false, id = "a2")
        assertFalse(ChatLogic.canEdit(view(user, answer("x", true), other, busy = true), user))
        assertFalse(ChatLogic.canEdit(view(user, busy = true), user))
    }

    @Test fun anEditSendsWhileSheAnswers() {
        assertTrue(ChatLogic.canSend("hi", busy = true, sending = false, editing = true))
        assertFalse(ChatLogic.canSend("hi", busy = true, sending = true, editing = true))
        assertFalse(ChatLogic.canSend(" ", busy = true, sending = false, editing = true))
    }

    /** 26k: a long chat cut an answer mid sentence and called it done; the screen marks it. */
    @Test fun anAnswerThatStopsMidSentenceIsMarked() {
        for (t in listOf("Wait, in the previous quiz I wrote option A as", "Sure.\nThe three layers are",
                "Here is how a resolver works, step by step, and then"))
            assertTrue(t, ChatLogic.cutOff(answer(t, true)))
        // A whole answer of a few words is a reply, not a cut: "OK" was marked (found 24 Oct)
        for (t in listOf("OK", "three", "I'm Julz", "Sure thing", "Привет, как дела"))
            assertFalse(t, ChatLogic.cutOff(answer(t, true)))
        for (t in listOf("Done.", "Really?", "Yes!", "See RFC 1034)", "```\nls -la\n```", "- one\n- two",
                "| a | b |", "Ready: ", "## Heading", "\"quoted.\"", "Okay…", "Hi :)", "Почему?", "1. step one\n2. step two"))
            assertFalse(t, ChatLogic.cutOff(answer(t, true)))
        assertFalse(ChatLogic.cutOff(answer("still going", false)))  // running, not cut
        assertFalse(ChatLogic.cutOff(user))
        assertFalse(ChatLogic.cutOff(answer("", true)))
    }

    /** 26k: julz-chat's end word is the sure sign; the punctuation guess only when it is unknown */
    @Test fun theEndWordBeatsTheGuess() {
        val cut = "Here is how a resolver works, step by step, and then"
        assertTrue(ChatLogic.cutOff(answer("Done.", true).copy(end = End.LENGTH)))
        assertFalse(ChatLogic.cutOff(answer(cut, true).copy(end = End.STOP)))
        assertTrue(ChatLogic.cutOff(answer(cut, true)))  // unknown: still guessed
        assertFalse(ChatLogic.cutOff(answer("Done.", false).copy(end = End.LENGTH)))  // running
    }

    @Test fun aChatTitleIsNeverEmpty() {
        assertEquals("New chat", ChatLogic.title(""))
        assertEquals("New chat", ChatLogic.title("New Chat"))
        assertEquals("DHCP", ChatLogic.title("DHCP"))
    }

    // 215: after julz-chat restarts it knows no chat until it lists them; open, send, retry and
    // edit all list again once on a 404 and repeat, never more
    private fun relisting(vararg codes: Int, listed: Boolean = true): Triple<Int, Int, Int> {
        var calls = 0; var lists = 0
        val code = kotlinx.coroutines.runBlocking {
            ChatLogic.relisting({ codes[calls++] to "" }, { lists++; listed }).first
        }
        return Triple(code, calls, lists)
    }

    @Test fun a404ListsAgainOnceAndRepeats() {
        assertEquals(Triple(200, 1, 0), relisting(200))
        assertEquals(Triple(429, 1, 0), relisting(429))
        assertEquals(Triple(200, 2, 1), relisting(404, 200))
        assertEquals(Triple(404, 2, 1), relisting(404, 404))
        assertEquals(Triple(404, 1, 1), relisting(404, 200, listed = false))
    }
}
