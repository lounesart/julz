package app.julz.feed

import app.julz.feed.Tok.COMMENT
import app.julz.feed.Tok.KEYWORD
import app.julz.feed.Tok.NUMBER
import app.julz.feed.Tok.PROMPT
import app.julz.feed.Tok.STRING
import app.julz.feed.Tok.VARIABLE
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Code colours (204, SECURITY.md 119): our own tokenizer, one forward pass, and the coloured
 *  pieces are always exactly the code, so colour can never hide or add a part of a command. */
class HighlightTest {
    /** The coloured pieces only, as (kind, text) */
    private fun marks(lang: String, code: String) =
        Highlight.pieces(lang, code)!!.filter { it.tok != Tok.PLAIN }.map { it.tok to it.text }

    @Test fun unknownOrNoLanguageStaysPlain() {
        assertNull(Highlight.pieces("", "ls -la"))
        assertNull(Highlight.pieces("brainfuck", "+++"))
        assertNull(Highlight.pieces("chart", "a: 1"))
    }

    @Test fun theFenceNamesTheLanguage() {
        assertEquals("bash", Highlight.lang("Bash title=\"x\""))
        assertEquals("ps1", Highlight.lang("PS1"))
        assertEquals("", Highlight.lang(""))
        assertEquals("", Highlight.lang("{.bash}"))
        assertEquals(listOf(KEYWORD to "def"), marks("Py", "def"))
        assertEquals(listOf(KEYWORD to "if"), marks("Bash title=x", "if"))
    }

    @Test fun piecesAlwaysJoinBackToTheCode() {
        val samples = listOf(
            "\$ sudo nft list ruleset # show it\nif [ -f \"\$F\" ]; then echo 'x'; fi",
            "echo \"unclosed\nls", "\${", "\$", "'", "\"\\", "#", "<#", "/*", "PS C:\\> ", "C:\\>", ">>> ",
            "\"\"\"never closed", "x = '''a\nb''' # c", "SELECT 1 -- n\n/* x", "\t\u202e\u0000 é ж 😀 \"\\\"",
        )
        for (lang in listOf("bash", "powershell", "cmd", "python", "c", "js", "kotlin", "json", "yaml", "ini", "sql", "console"))
            for (s in samples) assertEquals("$lang: $s", s, Highlight.pieces(lang, s)!!.joinToString("") { it.text })
        // And on noise: every printable and control character in random order
        val rnd = java.util.Random(204)
        repeat(200) {
            val s = String(CharArray(rnd.nextInt(80)) { "\$#'\"\\{}<>/*-;:%!@ \n\taZ09.PSC>".let { a -> a[rnd.nextInt(a.length)] } })
            for (lang in listOf("bash", "powershell", "cmd", "python", "c", "sql", "console"))
                assertEquals(s, Highlight.pieces(lang, s)!!.joinToString("") { it.text })
        }
    }

    @Test fun shellKeywordsStringsVariablesAndComments() {
        assertEquals(listOf(PROMPT to "\$ ", COMMENT to "# list"), marks("bash", "\$ nft list ruleset # list"))
        assertEquals(listOf(KEYWORD to "if", STRING to "\"\$HOME\"", KEYWORD to "then", KEYWORD to "fi"),
            marks("sh", "if [ -d \"\$HOME\" ]; then ls; fi"))
        assertEquals(listOf(VARIABLE to "\$USER", VARIABLE to "\${#arr}", VARIABLE to "\$?"), marks("bash", "echo \$USER \${#arr} \$?"))
        // A # inside a word is not a comment, a number inside a word is not a number
        assertEquals(listOf(NUMBER to "443"), marks("bash", "curl host#frag v2 --port 443"))
        // Part of a path or a flag is not a keyword
        assertEquals(emptyList<Pair<Tok, String>>(), marks("bash", "ls /tmp/for --if"))
        // An apostrophe that never closes ends at the line, so the next line keeps its colours
        assertEquals(listOf(STRING to "'t", KEYWORD to "fi"), marks("bash", "echo don't\nfi"))
    }

    @Test fun consoleColoursOnlyTheCommandsNotTheirOutput() {
        assertEquals(listOf(PROMPT to "\$ ", KEYWORD to "export"), marks("console", "\$ export A=b\nif this is output"))
    }

    @Test fun powershellIgnoresCaseAndKnowsItsPrompt() {
        assertEquals(listOf(PROMPT to "PS C:\\Users\\me> ", KEYWORD to "ForEach", VARIABLE to "\$env:PATH"),
            marks("powershell", "PS C:\\Users\\me> ForEach (\$env:PATH)"))
        assertEquals(listOf(COMMENT to "<# a\nb #>", KEYWORD to "return"), marks("pwsh", "<# a\nb #> return"))
    }

    @Test fun cmdComments() {
        assertEquals(listOf(PROMPT to "C:\\> ", KEYWORD to "dir"), marks("cmd", "C:\\> dir"))
        assertEquals(listOf(COMMENT to "rem note", COMMENT to ":: too"), marks("bat", "rem note\n:: too"))
        assertEquals(listOf(VARIABLE to "%PATH%"), marks("cmd", "path %PATH%"))
    }

    @Test fun pythonCAndSql() {
        assertEquals(listOf(PROMPT to ">>> ", KEYWORD to "def", STRING to "\"\"\"a\nb\"\"\"", COMMENT to "# c"),
            marks("python", ">>> def f(): \"\"\"a\nb\"\"\" # c"))
        assertEquals(listOf(KEYWORD to "#include", STRING to "<stdio.h>", KEYWORD to "int", NUMBER to "0", COMMENT to "// ok"),
            marks("c", "#include <stdio.h>\nint x = 0; // ok"))
        assertEquals(listOf(KEYWORD to "select", NUMBER to "1", COMMENT to "-- n"), marks("sql", "select 1 -- n"))
        assertEquals(listOf(STRING to "\"k\"", KEYWORD to "true"), marks("json", "{\"k\": true}"))
    }

    @Test fun theSystemComesFromTheLanguage() {
        assertEquals("Windows", Highlight.system("powershell"))
        assertEquals("Windows", Highlight.system("cmd"))
        assertEquals("Linux, macOS", Highlight.system("bash"))
        assertNull(Highlight.system("python"))
        assertNull(Highlight.system(""))
    }

    @Test fun lookaheadsStopAtTheirWindow() {
        // A closing } or > further than the window is not looked for: plain, not a variable or prompt
        val far = "a".repeat(100)
        assertEquals(emptyList<Pair<Tok, String>>(), marks("bash", "\${$far}"))
        assertEquals(emptyList<Pair<Tok, String>>(), marks("powershell", "PS $far> x"))
        assertEquals(listOf(VARIABLE to "\${${"a".repeat(40)}}"), marks("bash", "\${${"a".repeat(40)}}"))
    }

    @Test fun aLongBlockStaysPlainACraftedOneHighlightsInTime() {
        assertNull(Highlight.pieces("bash", "a".repeat(Highlight.MAX + 1)))
        for (unit in listOf("\${", "\"\\", "PS ", "<#", "'", "\$", "#", "C:\\")) {
            val s = unit.repeat(Highlight.MAX / unit.length)
            val start = System.nanoTime()
            for (lang in listOf("bash", "powershell", "cmd", "python")) Highlight.pieces(lang, s)
            assertTrue(unit, (System.nanoTime() - start) / 1_000_000 < 500)
        }
    }
}
