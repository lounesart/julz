package app.julz.ui

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threats 102 and 103: what may load in the chat, and what our theme may contain. */
class ChatTest {
    private val o = Origins.from("https://laptop.tail1234.ts.net:8444")!!

    @Test fun onlyTheChatOriginLoadsInside() {
        assertTrue(ChatRules.inside(o, "https://laptop.tail1234.ts.net/"))
        assertTrue(ChatRules.inside(o, "https://laptop.tail1234.ts.net/c/abc?q=x"))
        for (bad in listOf(
            "https://laptop.tail1234.ts.net:8443/",  // the approver stays out (33)
            "https://laptop.tail1234.ts.net:8444/",
            "http://laptop.tail1234.ts.net/",
            "https://evil.example/",
            "https://laptop.tail1234.ts.net.evil.example/",
            "https://user@laptop.tail1234.ts.net/",
            "javascript:alert(1)",
            "file:///sdcard/x.html",
            "intent://x#Intent;end",
            "",
        )) assertFalse(bad, ChatRules.inside(o, bad))
    }

    @Test fun theScriptOnlyInsertsTheStylesheet() {
        val look = LookPrefs()
        val script = ChatTheme.script(look)
        val quoted = org.json.JSONObject.quote(ChatTheme.css(look))
        assertTrue(script.startsWith("(function(){var s=document.getElementById('julz-theme');"))
        assertTrue(script.endsWith("s.textContent=$quoted;})()"))  // the CSS only as a JSON string
        assertFalse(script.replace(quoted, "").contains("eval"))
    }

    @Test fun theThemeCannotFetchOrCarryCode() {
        for (preset in Palette.presets) for ((_, accent) in Palette.accents) {
            val css = ChatTheme.css(LookPrefs(preset.id, accent))
            for (bad in listOf("url(", "@import", "expression", "\"", "'", "<", ">", "\\"))
                assertFalse("$bad in ${preset.id}", css.contains(bad, ignoreCase = true))
            val colours = Regex("#[0-9A-Fa-f]+").findAll(css).map { it.value }.toList()
            assertTrue(colours.isNotEmpty())
            assertTrue(colours.all { it.length == 7 })
        }
    }
}
