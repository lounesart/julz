package app.julz.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/** The text I sign stays above the system's fingerprint sheet (219, SECURITY.md 109). */
class SignPanelTest {
    @Test
    fun waitsForTheFirstLayout() {
        // ScrollState says Int.MAX_VALUE until it is measured: never a decision on that
        assertNull(SignPanel.step(Int.MAX_VALUE))
    }

    @Test
    fun fitsGoesStraightToThePrompt() = assertEquals(SignPanel.Step.PROMPT, SignPanel.step(0))

    @Test
    fun anythingToScrollIsReadFirst() {
        // The sheet takes every touch while it is up: text I would have to scroll is read before
        for (px in listOf(1, 40, 5000)) assertEquals(SignPanel.Step.READ, SignPanel.step(px))
    }

    private val hash = "741af55b4ec085a58dfd86cafdc21e8cea5779638953e3d10ca753559857dd3b"

    @Test
    fun aHashShowsShort() {
        // 219b: nobody compares 64 hex by eye; the signature still covers it whole
        assertEquals("inbox: 741af55b4ec0…\ndelete: Inbox/cottage-pie-recipe.md\n",
            SignPanel.shown("inbox: $hash\ndelete: Inbox/cottage-pie-recipe.md\n"))
        assertEquals("a 741af55b4ec0… b 741af55b4ec0…", SignPanel.shown("a $hash b $hash"))
    }

    @Test
    fun onlyAWholeHashIsShortened() {
        // Anything else stays whole, so nothing can hide behind the rule
        for (t in listOf(hash.dropLast(1), hash + "0", hash.uppercase(), "x$hash", "${hash}x",
                         hash.replaceRange(30, 31, "g"), "move: Inbox/a.md -> study/a.md")) {
            assertEquals(t, SignPanel.shown(t))
        }
        assertEquals("tick: 741af55b4ec0…\n- Review nmap flags", SignPanel.shown("tick: $hash\n- Review nmap flags"))
    }

    @Test
    fun anOldSigningCannotTouchANewOne() {
        // A late callback of a finished signing must not close or cancel the one now shown
        var cancelled = 0
        val old = SignPanel.Ask("a", "old", {}) { cancelled++ }
        val now = SignPanel.Ask("b", "new", {}) { cancelled += 10 }
        try {
            SignPanel.ask = now
            SignPanel.close(old)
            SignPanel.cancel(old)
            assertEquals(now, SignPanel.ask)
            assertEquals(0, cancelled)
            SignPanel.cancel(now)
            assertEquals(10, cancelled)
            SignPanel.close(now)
            assertNull(SignPanel.ask)
        } finally { SignPanel.ask = null }
    }

    @Test
    fun panelStaysAboveTheSheet() {
        // Measured 25 Oct on the Redmi (uiautomator): the sheet starts at y 1262 of 2712, the
        // status bar ends at 110, 520 dpi. The panel sits under the status bar plus its margin
        val px = 2712; val status = 110; val margin = (12 * 3.25).toInt()
        assertTrue(status + margin + SignPanel.ABOVE * px < 1262 - 40)
    }

    @Test
    fun onlyThePanelSaysWhatIsSigned() {
        // Every signing screen once drew the text at its bottom, under the sheet. One place now
        val ui = File("src/main/java/app/julz")
        val offenders = ui.walk().filter { it.isFile && it.extension == "kt" && it.name != "SignPanel.kt" }
            .filter { f -> f.readText().let { "signing exactly this" in it || "BiometricPrompt.Builder" in it ||
                ".authenticate(" in it } }
            .map { it.name }.toList()
        assertEquals(emptyList<String>(), offenders)
        val panel = File(ui, "ui/SignPanel.kt").readText()
        assertTrue("Your fingerprint signs this, nothing else." in panel)
        assertTrue("Signs the text shown above" in panel)
    }

    @Test
    fun drawnOverEveryScreen() {
        // In App's root, after the sheets: over every screen, the tab bar and any open sheet
        val app = File("src/main/java/app/julz/ui/App.kt").readText()
        assertTrue(Regex("""SheetLayer\(sheets\)\s*\n\s*SignLayer\(\)""").containsMatchIn(app))
    }
}
