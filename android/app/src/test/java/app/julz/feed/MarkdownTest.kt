package app.julz.feed

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threat 119: Obsidian formatting parsed by our own code, nothing ever fetched. */
class MarkdownTest {
    private fun parse(s: String) = ObsidianMd.parse(s)
    private fun text(spans: List<Span>) = spans.joinToString("") { it.text }

    @Test fun frontmatterBecomesProperties() {
        val b = parse("---\ntags:\n  - network-plus\n  - dns\nstatus: learning\n---\n\n# DNS\n")
        val p = b[0] as MdProps
        assertEquals(listOf("status" to "learning"), p.props)
        assertEquals(listOf("network-plus", "dns"), p.tags)
        assertEquals(MdHeading(1, listOf(Span("DNS"))), b[1])
        assertEquals(listOf("a", "b"), (parse("---\ntags: [a, b]\n---\n")[0] as MdProps).tags)
    }

    @Test fun headingsListsAndTasks() {
        val b = parse("## Steps\n- one\n  - nested\n1. first\n- [ ] open\n- [x] done (done 2026-10-16)\n")
        assertEquals(2, (b[0] as MdHeading).level)
        assertEquals(MdItem(0, "\u2022", listOf(Span("one"))), b[1])
        assertEquals(1, (b[2] as MdItem).depth)
        assertEquals("1.", (b[3] as MdItem).marker)
        assertEquals("[ ]", (b[4] as MdItem).marker)
        assertEquals("[x]", (b[5] as MdItem).marker)
        assertEquals("done (done 2026-10-16)", text((b[5] as MdItem).spans))
    }

    @Test fun codeBlocksKeepTheirTextAsItIs() {
        val b = parse("```bash\nnft list ruleset **not bold**\n```\nafter")
        assertEquals(MdCode("bash", "nft list ruleset **not bold**"), b[0])
        assertEquals(MdPara(listOf(Span("after"))), b[1])
        assertEquals(MdCode("", "never closed"), parse("```\nnever closed")[0])
    }

    @Test fun tablesDropTheirSeparatorLine() {
        val t = parse("| Port | Use |\n|---|:---:|\n| 53 | DNS |\n")[0] as MdTable
        assertEquals(2, t.rows.size)
        assertEquals(listOf("Port", "Use"), t.rows[0].map { text(it) })
        assertEquals(listOf("53", "DNS"), t.rows[1].map { text(it) })
    }

    @Test fun inlineStyles() {
        val s = (parse("a **bold** and *it* and `x **y**` and ~~gone~~ and ==mark== #tag")[0] as MdPara).spans
        assertTrue(s.single { it.text == "bold" }.bold)
        assertTrue(s.single { it.text == "it" }.italic)
        assertTrue(s.single { it.text == "x **y**" }.code)  // nothing parsed inside code
        assertTrue(s.single { it.text == "gone" }.strike)
        assertTrue(s.single { it.text == "mark" }.mark)
        assertTrue(s.single { it.text == "#tag" }.tag)
    }

    @Test fun wikilinksNameANoteAndShowTheAlias() {
        val s = (parse("see [[dns-basics|DNS]] and [[osi#Layers]]")[0] as MdPara).spans
        assertEquals("dns-basics", s.single { it.text == "DNS" }.wiki)
        assertEquals("osi", s.single { it.text == "osi" }.wiki)
    }

    @Test fun webLinksShowTheirAddressAndCarryNoTarget() {
        val s = (parse("[click me](https://evil.example/x)")[0] as MdPara).spans
        assertEquals("click me (https://evil.example/x)", text(s))
        assertTrue(s.all { it.wiki == null })  // a Span has no field a click could use for a URL
    }

    // Chat answers only (138): an https link keeps its address in view and is the one thing tappable
    private fun answer(s: String) = ObsidianMd.parse(s, links = true)
    private fun links(blocks: List<MdBlock>) = blocks.flatMap { b ->
        when (b) {
            is MdPara -> b.spans; is MdHeading -> b.spans; is MdItem -> b.spans; is MdQuote -> b.spans
            is MdTable -> b.rows.flatten().flatten(); else -> emptyList()
        }
    }.mapNotNull { it.link }

    @Test fun answersGetHttpsLinksWithTheirAddressInView() {
        val s = (answer("see [the docs](https://example.com/a?b=1)")[0] as MdPara).spans
        assertEquals("see the docs (https://example.com/a?b=1)", text(s))
        assertEquals(listOf("https://example.com/a?b=1"), s.mapNotNull { it.link })
    }

    @Test fun aLabelNeverHidesWhereALinkGoes() {
        val s = (answer("[https://bank.example](https://evil.example/login)")[0] as MdPara).spans
        assertTrue(text(s).contains("(https://evil.example/login)"))
        assertEquals(listOf("https://evil.example/login"), s.mapNotNull { it.link })
    }

    @Test fun aBareAddressIsALinkWithoutTheFullStopAfterIt() {
        val s = (answer("Read https://example.com/x. Then (https://example.org/y), done")[0] as MdPara).spans
        assertEquals("Read https://example.com/x. Then (https://example.org/y), done", text(s))
        assertEquals(listOf("https://example.com/x", "https://example.org/y"), s.mapNotNull { it.link })
    }

    @Test fun onlyHttpsWithAHostBecomesALink() {
        for (url in listOf("javascript:alert(1)", "http://example.com", "file:///etc/passwd", "intent://x#Intent;end",
                "data:text/html,hi", "https://user@evil.example/", "https:///nohost", "HTTPS://example.com",
                "https://exa mple.com", "https://router/admin", "https://localhost/x", "content://app.julz/x", "https://example.com/\u0000")) {
            assertEquals(url, emptyList<String>(), links(answer("[x]($url)")))
            assertEquals(url, emptyList<String>(), links(answer("go $url now")))
        }
    }

    @Test fun anAddressGluedToAWordOrTooLongStaysText() {
        assertEquals(emptyList<String>(), links(answer("seehttps://example.com/x")))
        val long = "https://example.com/" + "a".repeat(2_000)
        assertEquals(emptyList<String>(), links(answer(long)))
        assertEquals(emptyList<String>(), links(answer("[x]($long)")))
    }

    @Test fun linksWorkInEveryBlockOfAnAnswer() {
        val l = links(answer("# See https://a.example\n- item https://b.example\n> quote https://c.example\n\n| a |\n|---|\n| https://d.example |"))
        assertEquals(listOf("https://a.example", "https://b.example", "https://c.example", "https://d.example"), l)
    }

    @Test fun codeKeepsAddressesAsCode() {
        assertEquals(emptyList<String>(), links(answer("run `curl https://example.com`")))
        assertTrue(answer("```\ncurl https://example.com\n```")[0] is MdCode)
    }

    @Test fun htmlInAnAnswerStaysText() {
        val src = "<script>alert(1)</script> <button>Approve</button>"
        assertEquals(src, text((answer(src)[0] as MdPara).spans))
        assertEquals(emptyList<String>(), links(answer(src)))
    }

    @Test fun notesNeverGetLinks() {
        assertEquals(emptyList<String>(), links(parse("[x](https://example.com) and https://example.org")))
    }

    @Test fun aLongLineOfAddressesStaysFast() {
        val line = "https://a.example/ ".repeat(5_000)
        val t = System.nanoTime()
        assertEquals(5_000, links(answer(line)).size)
        assertTrue((System.nanoTime() - t) < 2_000_000_000L)
    }

    // 26e, asked 19 Oct: a callout may start folded (Obsidian's "-"), and a chart block draws bars
    @Test fun aCalloutCanStartFolded() {
        val open = answer("> [!tip] Exam tip\n> Count the hosts.")[0] as MdCallout
        assertFalse(open.folded)
        assertEquals("tip", open.kind)
        val shut = answer("> [!warning]- Careful\n> Not on a production box.")[0] as MdCallout
        assertTrue(shut.folded)
        assertEquals("Careful", shut.title)
        assertFalse((answer("> [!note]+ Open\n> x")[0] as MdCallout).folded)
    }

    @Test fun aChartBlockBecomesBars() {
        val c = answer("```chart\nQuiz scores\nNetwork+: 80\nSecurity+: 62.5%\nA+: 0\n```")[0] as MdChart
        assertEquals("Quiz scores", c.title)
        assertEquals(listOf("Network+" to 80.0, "Security+" to 62.5, "A+" to 0.0), c.bars)
        assertEquals("%", c.unit)
    }

    @Test fun aChartThatDoesNotParseStaysCode() {
        for (bad in listOf("```chart\nx: lots\n```", "```chart\n```", "```chart\na: -5\n```", "```chart\na: 1e400\n```",
                "```chart\n" + (1..13).joinToString("\n") { "b$it: $it" } + "\n```", "```chart\n" + "x".repeat(41) + ": 1\n```"))
            assertTrue(bad.take(20), answer(bad)[0] is MdCode)
    }

    @Test fun mixedUnitsAndOtherBlocksStayCode() {
        assertTrue(answer("```chart\nNetwork+: 80%\nStudy: 3h\n```")[0] is MdCode)
        // Only a block marked chart: yaml or a config with "key: number" lines is code
        for (lang in listOf("yaml", "", "ini", "bash")) assertTrue(lang, answer("```$lang\nport: 22\nretries: 3\n```")[0] is MdCode)
    }

    @Test fun notesDrawChartsToo() {
        // A chart is data, not a link: notes may show one as well
        assertTrue(parse("```chart\nhours: 3\n```")[0] is MdChart)
    }

    @Test fun imagesAndEmbedsAreNeverFetched() {
        assertEquals(MdEmbed("diagram.png"), parse("![[diagram.png]]")[0])
        assertEquals(MdEmbed("pixel"), parse("![pixel](https://evil.example/p.png)")[0])
        val inline = text((parse("look ![x](https://evil.example/p.png) here")[0] as MdPara).spans)
        assertEquals("look [image: x] here", inline)
        assertFalse(parse("![pixel](https://evil.example/p.png)").toString().contains("evil.example"))
    }

    @Test fun htmlStaysText() {
        val p = parse("<img src=x onerror=alert(1)> <b>hi</b>")[0] as MdPara
        assertEquals("<img src=x onerror=alert(1)> <b>hi</b>", text(p.spans))
    }

    @Test fun quotesCalloutsCommentsAndRules() {
        val b = parse("> [!warning] Careful\n> do not run this\n\n> plain quote\n\n---\n\nkeep %%hidden%% this")
        assertEquals(MdCallout("warning", "Careful", listOf(Span("do not run this"))), b[0])
        assertEquals(MdQuote(listOf(Span("plain quote"))), b[1])
        assertEquals(MdRule, b[2])
        assertEquals("keep  this", text((b[3] as MdPara).spans))
    }

    @Test fun aCraftedLineParsesQuickly() {
        val evil = "*".repeat(2000) + "_".repeat(1000) + "[[".repeat(500)
        val start = System.nanoTime()
        parse(evil)
        assertTrue((System.nanoTime() - start) / 1_000_000 < 500)
    }

    @Test fun aPlainPreviewDropsTheMarks() {
        assertEquals("DNS\nNames to addresses. See dns-basics",
            ObsidianMd.plain("---\ntags: [a]\n---\n# DNS\nNames to **addresses**. See [[dns-basics]]\n", 3))
        assertNull(ObsidianMd.plain("---\ntags: [a]\n---\n", 3))
    }

    /** In progress, the Obsidian Tasks mark Julz writes when I start a task (127, 22d) */
    @Test fun anInProgressTaskIsItsOwnMark() {
        val b = parse("- [/] write the guide") .single() as MdItem
        assertEquals("[/]", b.marker)
        assertEquals("write the guide", text(b.spans))
    }

    /** Inline fields as my goals note uses them (22d): a quiet chip, not raw brackets */
    @Test fun anInlineFieldBecomesAFieldSpan() {
        val spans = (parse("Study 10 h [est:: 10h] [in:: pass-cpts]").single() as MdPara).spans
        val fields = spans.filter { it.field }
        assertEquals(listOf("est 10h", "in pass-cpts"), fields.map { it.text })
        assertEquals("Study 10 h est 10h in pass-cpts", text(spans).replace(Regex(" +"), " ").trim())
    }

    @Test fun onlyAWellFormedFieldIsAField() {
        for (src in listOf("[not a field]", "[a:: ]", "[a::    ]", "[est:: x[y]]", "[eSt:: 1h]", "[1a:: x]", "[-a:: x]", "[Est:: 1h]", "[est::1h]", "[est:: " + "x".repeat(41) + "]",
                           "[" + "k".repeat(21) + ":: v]", "[est:: 1h")) {
            val spans = (parse(src).single() as MdPara).spans
            assertTrue(src, spans.none { it.field })
            assertEquals(src, text(spans))
        }
    }
}
