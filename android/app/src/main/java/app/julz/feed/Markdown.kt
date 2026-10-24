package app.julz.feed

/** A piece of text and how it looks. In a note a span names a note (wiki), nothing outside the
 *  vault (SECURITY.md 119); [link], a checked https address, is set only for chat answers (138). */
data class Span(val text: String, val bold: Boolean = false, val italic: Boolean = false,
                val strike: Boolean = false, val mark: Boolean = false, val code: Boolean = false,
                val tag: Boolean = false, val wiki: String? = null, val field: Boolean = false,
                val link: String? = null)

sealed interface MdBlock
data class MdProps(val props: List<Pair<String, String>>, val tags: List<String>) : MdBlock
data class MdHeading(val level: Int, val spans: List<Span>) : MdBlock
data class MdPara(val spans: List<Span>) : MdBlock
data class MdItem(val depth: Int, val marker: String, val spans: List<Span>) : MdBlock
data class MdQuote(val spans: List<Span>) : MdBlock
data class MdCallout(val kind: String, val title: String, val spans: List<Span>, val folded: Boolean = false) : MdBlock
/** A ```chart block: "Label: number" lines drawn as bars (26e). Numbers only, at most 12 bars,
 *  nothing fetched; anything else stays a code block. */
data class MdChart(val title: String?, val bars: List<Pair<String, Double>>, val unit: String) : MdBlock
data class MdCode(val lang: String, val text: String) : MdBlock
data class MdTable(val rows: List<List<List<Span>>>) : MdBlock
data object MdRule : MdBlock
data class MdEmbed(val name: String) : MdBlock

/** Obsidian formatting, parsed by our own code line by line (SECURITY.md 119): no HTML, nothing
 *  fetched, images and embeds become placeholders, web links stay text. Regexes only ever see one
 *  line, and every search moves forward, so a crafted note cannot freeze it. */
object ObsidianMd {
    /** "[key:: value]" starting at [i], or null. Looked for in a bounded window only (a key of
     *  up to 20 and a value of up to 40 characters, on one line), so a long line full of "["
     *  cannot slow it (119): lowercase key, ":: ", a value, "]" */
    private fun fieldAt(s: String, i: Int): Triple<String, String, Int>? {
        var sep = -1
        for (j in i + 2..minOf(i + 21, s.length - 3)) if (s[j] == ':' && s[j + 1] == ':' && s[j + 2] == ' ') { sep = j; break }
        if (sep < 0) return null
        val key = s.substring(i + 1, sep)
        if (key[0] !in 'a'..'z' || !key.all { it in 'a'..'z' || it in '0'..'9' || it == '_' || it == '-' }) return null
        var end = -1
        for (j in sep + 4..minOf(sep + 43, s.length - 1)) {
            if (s[j] == ']') { end = j; break }
            if (s[j] == '[' || s[j] == '\n') return null
        }
        if (end < 0) return null
        val value = s.substring(sep + 3, end).trim()
        return if (value.isEmpty()) null else Triple(key, value, end)
    }

    private val HEADING = Regex("^(#{1,6})\\s+(.*)$")
    private val RULE = Regex("^(-{3,}|\\*{3,}|_{3,})$")
    private val EMBED = Regex("^!\\[\\[([^\\]]+)\\]\\]$")
    private val IMAGE = Regex("^!\\[([^\\]]*)\\]\\([^)]*\\)$")
    private val ITEM = Regex("^([ \\t]*)([-*+]|\\d{1,3}[.)])\\s+(.*)$")
    // [/] is in progress, the Obsidian Tasks mark Julz writes when I start a task (127, 22d)
    private val TASK = Regex("^\\[([ xX/])\\]\\s+(.*)$")
    private val CALLOUT = Regex("^\\[!(\\w+)\\]([+-]?)\\s*(.*)$")
    private val BAR = Regex("^(.{1,40}):\\s*([0-9]{1,9}(?:\\.[0-9]{1,3})?)\\s*(%|h|min)?$")
    private const val MAX_BARS = 12

    /** The bars of a chart block, or null when any line is not "Label: number": a first line
     *  without a colon is the title; one unit at most, from %, h or min. */
    private fun chart(body: List<String>): MdChart? {
        val lines = body.map { it.trim() }.filter { it.isNotEmpty() }
        if (lines.isEmpty()) return null
        val title = lines.first().takeIf { ':' !in it && it.length <= 60 }
        val rows = if (title != null) lines.drop(1) else lines
        if (rows.isEmpty() || rows.size > MAX_BARS) return null
        var unit = ""
        val bars = rows.map { r ->
            val m = BAR.matchEntire(r) ?: return null
            val u = m.groupValues[3]
            if (u.isNotEmpty()) { if (unit.isNotEmpty() && unit != u) return null; unit = u }
            m.groupValues[1].trim() to m.groupValues[2].toDouble()
        }
        return MdChart(title, bars, unit)
    }
    private val SEPARATOR = Regex("^\\|?\\s*:?-+:?\\s*(\\|\\s*:?-+:?\\s*)*\\|?$")
    private val COMMENT = Regex("%%.*?%%")
    private const val BULLET = "•"

    /** [links]: a chat answer (138), whose https addresses may be tapped; never for a note (119). */
    fun parse(source: String, links: Boolean = false): List<MdBlock> {
        fun inline(t: String) = this.inline(t, links)
        val lines = source.replace("\r", "").split("\n")
        val out = mutableListOf<MdBlock>()
        var i = 0
        if (lines.firstOrNull()?.trim() == "---") {
            val end = (1 until lines.size).firstOrNull { lines[it].trim() == "---" }
            if (end != null) { out += props(lines.subList(1, end)); i = end + 1 }
        }
        val para = mutableListOf<String>()
        fun flush() { if (para.isNotEmpty()) { out += MdPara(inline(para.joinToString("\n"))); para.clear() } }
        var inComment = false
        while (i < lines.size) {
            var line = lines[i]
            if (inComment) { if ("%%" in line) inComment = false; i++; continue }
            line = line.replace(COMMENT, "")
            if (line.trim().startsWith("%%")) { inComment = true; i++; continue }
            val t = line.trim()
            when {
                t.isEmpty() -> flush()
                t.startsWith("```") || t.startsWith("~~~") -> {
                    flush()
                    val fence = t.take(3)
                    val body = mutableListOf<String>()
                    i++
                    while (i < lines.size && !lines[i].trim().startsWith(fence)) { body += lines[i]; i++ }
                    val lang = t.drop(3).trim()
                    out += (if (lang == "chart") chart(body) else null) ?: MdCode(lang, body.joinToString("\n"))
                }
                HEADING.matches(t) -> {
                    flush()
                    val m = HEADING.find(t)!!
                    out += MdHeading(m.groupValues[1].length, inline(m.groupValues[2].trimEnd('#').trim()))
                }
                RULE.matches(t) -> { flush(); out += MdRule }
                EMBED.matches(t) -> { flush(); out += MdEmbed(EMBED.find(t)!!.groupValues[1].substringBefore('|')) }
                IMAGE.matches(t) -> { flush(); out += MdEmbed(IMAGE.find(t)!!.groupValues[1].ifBlank { "image" }) }
                t.startsWith(">") -> {
                    flush()
                    val quoted = mutableListOf<String>()
                    while (i < lines.size && lines[i].trim().startsWith(">")) {
                        quoted += lines[i].trim().removePrefix(">").removePrefix(" "); i++
                    }
                    i--
                    val c = CALLOUT.find(quoted.first())
                    out += if (c != null) MdCallout(c.groupValues[1].lowercase(),
                        c.groupValues[3].ifBlank { c.groupValues[1].replaceFirstChar { it.uppercase() } },
                        inline(quoted.drop(1).joinToString("\n")), folded = c.groupValues[2] == "-")
                    else MdQuote(inline(quoted.joinToString("\n")))
                }
                t.startsWith("|") -> {
                    flush()
                    val rows = mutableListOf<List<List<Span>>>()
                    while (i < lines.size && lines[i].trim().startsWith("|")) {
                        val r = lines[i].trim()
                        if (!SEPARATOR.matches(r)) rows += r.trim('|').split("|").map { inline(it.trim()) }
                        i++
                    }
                    i--
                    out += MdTable(rows)
                }
                ITEM.matches(line) -> {
                    flush()
                    val m = ITEM.find(line)!!
                    val indent = m.groupValues[1].sumOf { if (it == '\t') 4 else 1 as Int }
                    val raw = m.groupValues[2]
                    var rest = m.groupValues[3]
                    var marker = if (raw[0].isDigit()) raw.dropLast(1) + "." else BULLET
                    TASK.find(rest)?.let {
                        marker = when (it.groupValues[1]) { " " -> "[ ]"; "/" -> "[/]"; else -> "[x]" }
                        rest = it.groupValues[2]
                    }
                    out += MdItem((indent / 2).coerceAtMost(6), marker, inline(rest))
                }
                else -> para += t
            }
            i++
        }
        flush()
        return out
    }

    private fun props(lines: List<String>): MdProps {
        val props = mutableListOf<Pair<String, String>>()
        val tags = mutableListOf<String>()
        var key: String? = null
        for (l in lines) {
            val t = l.trim()
            if (t.startsWith("- ") && key != null) {
                val v = t.drop(2).trim()
                if (key == "tags") tags += v else props += key to v
                continue
            }
            val k = t.substringBefore(':', "").trim()
            if (k.isEmpty()) continue
            key = k
            val v = t.substringAfter(':').trim()
            val list = if (v.startsWith("[") && v.endsWith("]")) v.drop(1).dropLast(1).split(',').map { it.trim() }.filter { it.isNotEmpty() } else null
            when {
                k == "tags" -> tags += list ?: listOfNotNull(v.ifEmpty { null })
                v.isNotEmpty() -> props += k to (list?.joinToString(", ") ?: v)
            }
        }
        return MdProps(props, tags)
    }

    /** One line or paragraph into spans. Every search goes forward from where it is; an opening
     *  mark without its closing one is plain text. */
    /** An address a tap may open, through the link check (104): https, a dotted host name (a
     *  single name could be a machine at home, which 104 does not check), no user part, no space
     *  or control character, as written (HTTPS:// is not it). Null for anything else. */
    fun webLink(url: String): String? {
        if (url.length > 2_000 || !url.startsWith("https://") || url.any { it.isWhitespace() || it.isISOControl() }) return null
        val u = try { java.net.URI(url) } catch (e: Exception) { return null }
        val host = u.host ?: return null
        return url.takeIf { u.scheme == "https" && '.' in host.trim('.') && u.rawUserInfo == null }
    }

    private const val URL_END = " \t\n<>\"'()[]{}`"
    private const val TRAILING = ".,;:!?"

    fun inline(s: String, links: Boolean = false): List<Span> {
        val out = mutableListOf<Span>()
        val buf = StringBuilder()
        fun text() { if (buf.isNotEmpty()) { out += Span(buf.toString()); buf.clear() } }
        fun closing(mark: String, from: Int): Int {
            val end = s.indexOf(mark, from)
            return if (end > from && !s[from].isWhitespace() && !s[end - 1].isWhitespace()) end else -1
        }
        var i = 0
        while (i < s.length) {
            val c = s[i]
            val prev = if (i > 0) s[i - 1] else ' '
            when {
                c == '`' && s.indexOf('`', i + 1) > i -> {
                    val end = s.indexOf('`', i + 1); text(); out += Span(s.substring(i + 1, end), code = true); i = end + 1; continue
                }
                s.startsWith("![[", i) && s.indexOf("]]", i + 3) > 0 -> {
                    val end = s.indexOf("]]", i + 3); text(); out += Span("[image: ${s.substring(i + 3, end).substringBefore('|')}]"); i = end + 2; continue
                }
                s.startsWith("![", i) -> {
                    val mid = s.indexOf("](", i + 2); val end = if (mid > 0) s.indexOf(')', mid + 2) else -1
                    if (mid > 0 && end > 0 && '\n' !in s.substring(i, end)) {
                        text(); out += Span("[image: ${s.substring(i + 2, mid).ifBlank { "image" }}]"); i = end + 1; continue
                    }
                }
                s.startsWith("[[", i) && s.indexOf("]]", i + 2) > 0 -> {
                    val end = s.indexOf("]]", i + 2)
                    val inner = s.substring(i + 2, end)
                    val target = inner.substringBefore('|').substringBefore('#').trim()
                    val label = if ('|' in inner) inner.substringAfter('|').trim() else target
                    text(); out += Span(label, wiki = target.ifEmpty { null }); i = end + 2; continue
                }
                // An inline field, as my goals note uses them: a quiet chip, not raw brackets (22d)
                c == '[' && fieldAt(s, i) != null -> {
                    val (key, value, end) = fieldAt(s, i)!!
                    text(); out += Span("$key $value", field = true); i = end + 1; continue
                }
                c == '[' -> {
                    val mid = s.indexOf("](", i + 1); val end = if (mid > 0) s.indexOf(')', mid + 2) else -1
                    if (mid > 0 && end > 0 && ']' !in s.substring(i + 1, mid) && '\n' !in s.substring(i, end)) {
                        // A web link stays text with its address in view, never a target (119);
                        // in an answer that address may be tapped, and the label never hides it (138)
                        val url = s.substring(mid + 2, end)
                        text(); out += Span("${s.substring(i + 1, mid)} ($url)", link = if (links) webLink(url) else null); i = end + 1; continue
                    }
                }
                // A bare address in an answer, without the full stop after it (138)
                links && s.startsWith("https://", i) && !prev.isLetterOrDigit() -> {
                    var end = i + 8
                    while (end < s.length && s[end] !in URL_END) end++
                    while (end > i + 8 && s[end - 1] in TRAILING) end--
                    val url = s.substring(i, end)
                    val ok = webLink(url)
                    if (ok != null) { text(); out += Span(url, link = ok); i = end; continue }
                }
                else -> {}
            }
            val pair = listOf("**" to "b", "__" to "b", "~~" to "s", "==" to "m").firstOrNull { s.startsWith(it.first, i) }
            if (pair != null) {
                val end = closing(pair.first, i + 2)
                if (end > 0) {
                    val inner = s.substring(i + 2, end)
                    text(); out += when (pair.second) {
                        "b" -> Span(inner, bold = true); "s" -> Span(inner, strike = true); else -> Span(inner, mark = true)
                    }
                    i = end + 2; continue
                }
            }
            if ((c == '*' || (c == '_' && !prev.isLetterOrDigit())) && i + 1 < s.length) {
                val end = closing(c.toString(), i + 1)
                if (end > 0 && (c == '*' || end + 1 >= s.length || !s[end + 1].isLetterOrDigit())) {
                    text(); out += Span(s.substring(i + 1, end), italic = true); i = end + 1; continue
                }
            }
            if (c == '#' && prev.isWhitespace() && i + 1 < s.length && s[i + 1].isLetter()) {
                var end = i + 1
                while (end < s.length && (s[end].isLetterOrDigit() || s[end] in "/_-")) end++
                text(); out += Span(s.substring(i, end), tag = true); i = end; continue
            }
            buf.append(c); i++
        }
        text()
        return out
    }

    /** The first lines as plain words, for a short preview; null when there is nothing to show. */
    fun plain(source: String, maxLines: Int): String? {
        val lines = parse(source).flatMap { b ->
            when (b) {
                is MdProps, MdRule -> emptyList()
                is MdHeading -> listOf(b.spans.joinToString("") { it.text })
                is MdPara -> b.spans.joinToString("") { it.text }.split("\n")
                is MdItem -> listOf("${b.marker} " + b.spans.joinToString("") { it.text })
                is MdQuote -> b.spans.joinToString("") { it.text }.split("\n")
                is MdCallout -> listOf(b.title)
                is MdCode -> b.text.split("\n")
                is MdTable -> b.rows.map { r -> r.joinToString(" | ") { c -> c.joinToString("") { it.text } } }
                is MdEmbed -> listOf("[image: ${b.name}]")
                is MdChart -> listOfNotNull(b.title) + b.bars.map { (l, v) -> "$l ${v.toString().removeSuffix(".0")}${b.unit}" }
            }
        }.filter { it.isNotBlank() }.take(maxLines)
        return lines.joinToString("\n").ifEmpty { null }
    }
}
