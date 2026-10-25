package app.julz.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Icon
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.semantics.semantics
import app.julz.feed.MdChart
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.withLink
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.julz.feed.MdBlock
import app.julz.feed.MdCallout
import app.julz.feed.MdCode
import app.julz.feed.MdEmbed
import app.julz.feed.MdHeading
import app.julz.feed.MdItem
import app.julz.feed.MdPara
import app.julz.feed.MdProps
import app.julz.feed.MdQuote
import app.julz.feed.MdRule
import app.julz.feed.MdTable
import app.julz.feed.Span
import app.julz.feed.Highlight
import app.julz.feed.Piece
import app.julz.feed.Tok

private val CODE_BG get() = J.raise

/** A note drawn in the app's own styles (SECURITY.md 119). Nothing here loads anything: the
 *  blocks come from ObsidianMd, a wikilink is tappable only when `opens` knows the note, a
 *  #tag only when `tags` knows it (212). [link] is for chat answers only (138): a checked https address goes to it on a tap, for 104. */
@Composable
fun MarkdownView(blocks: List<MdBlock>, opens: ((String) -> (() -> Unit)?)? = null,
                 tags: ((String) -> (() -> Unit)?)? = null, link: ((String) -> Unit)? = null) {
    // Reading rhythm (26e, from Practical Typography, Material 3 and how Claude sets answers): body
    // at a line height of 1.5; a heading sits closer to what it opens than to what came before;
    // list items closer to each other than to the paragraphs around them
    val read = J.bodyText.copy(lineHeight = J.bodyText.fontSize * 1.53f)
    Column {
        blocks.forEachIndexed { i, b ->
            val prev = blocks.getOrNull(i - 1)
            val gap = when {
                i == 0 -> 0.dp
                b is MdHeading -> if (b.level <= 2) J.sp6 else J.sp5
                prev is MdHeading -> J.sp2
                b is MdItem && prev is MdItem -> J.sp2
                else -> J.sp4
            }
            Box(Modifier.padding(top = gap)) { Block(b, read, opens, link, tags) }
        }
    }
}

@Composable
private fun Block(b: MdBlock, read: androidx.compose.ui.text.TextStyle, opens: ((String) -> (() -> Unit)?)?, link: ((String) -> Unit)?,
                  tags: ((String) -> (() -> Unit)?)?) {
    when (b) {
        is MdProps -> Props(b, tags)
        // H1 and H2 in the display font, the app's own voice; smaller ones bold body text
        is MdHeading -> Text(spans(b.spans, opens, link, tags), style = when (b.level) {
            1 -> J.tm; 2 -> J.ts.copy(fontFamily = J.display); else -> read.copy(fontWeight = FontWeight(700))
        })
        is MdPara -> Text(spans(b.spans, opens, link, tags), style = read)
        is MdItem -> Item(b, opens, link, tags, read)
        is MdQuote -> Bar(J.line) { Text(spans(b.spans, opens, link, tags), style = read.copy(color = J.muted)) }
        is MdCallout -> Callout(b, read, opens, link, tags)
        is MdCode -> Column(Modifier.fillMaxWidth().clip(J.rS).background(CODE_BG).outline(1.dp, J.line, J.rS)
            .padding(J.sp4), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            // Its own Copy (26b): a command out of an answer without the words around it
            val clipboard = androidx.compose.ui.platform.LocalClipboardManager.current
            val pieces = androidx.compose.runtime.remember(b) { Highlight.pieces(b.lang, b.text) }
            val system = Highlight.system(b.lang)
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                Text(b.lang, style = J.monoCap)
                // Where it runs (204), so a PowerShell line never passes for bash
                if (system != null) Text(system, style = J.cap.copy(color = J.muted), modifier = Modifier.clip(J.rS)
                    .outline(1.dp, J.line, J.rS).padding(horizontal = J.sp2))
                Box(Modifier.weight(1f))
                Text("Copy", style = J.cap.copy(color = J.accText, fontWeight = FontWeight(700)),
                    modifier = Modifier.clip(J.pill).clickable(role = androidx.compose.ui.semantics.Role.Button,
                        onClickLabel = "Copy the code") { clipboard.setText(AnnotatedString(b.text)) }
                        .padding(horizontal = J.sp3, vertical = J.sp2))
            }
            val scroll = rememberScrollState()
            Text(if (pieces == null) AnnotatedString(b.text) else coloured(pieces), style = J.monoCap.copy(color = J.text),
                softWrap = false, modifier = Modifier.edgeFade(scroll).horizontalScroll(scroll))
        }
        is MdTable -> Table(b, opens, link, tags)
        is MdChart -> Chart(b)
        MdRule -> Box(Modifier.fillMaxWidth().height(1.dp).background(J.line))
        is MdEmbed -> Row(Modifier.clip(J.rS).background(J.raise).padding(horizontal = J.sp4, vertical = J.sp2)) {
            // Never loaded: an image could tell a server that I read this note (119)
            Text("Image not shown: ${b.name}", style = J.cap)
        }
    }
}

/** A callout in its kind's colour and icon, as Obsidian draws them (26e): a tip green, a note
 *  blue, a warning amber, a danger red, a question in the accent. "-" starts it folded; its
 *  title opens it. Before, every kind was the same accent bar, so a warning read as a tip. */
@Composable
private fun Callout(b: MdCallout, read: androidx.compose.ui.text.TextStyle, opens: ((String) -> (() -> Unit)?)?, link: ((String) -> Unit)?,
                  tags: ((String) -> (() -> Unit)?)?) {
    val (tint, icon) = when (b.kind) {
        "tip", "hint", "success", "check", "done" -> J.good to Icons.check
        "warning", "caution", "attention", "important" -> J.caution to Icons.alert
        "danger", "error", "bug", "failure", "fail", "missing" -> J.warn to Icons.alert
        "question", "help", "faq" -> J.accText to Icons.question
        else -> J.info to Icons.info
    }
    var open by androidx.compose.runtime.saveable.rememberSaveable(b) { androidx.compose.runtime.mutableStateOf(!b.folded) }
    val folds = b.folded && b.spans.isNotEmpty()
    Column(Modifier.fillMaxWidth().clip(J.rM).background(tint.copy(alpha = 0.10f)).outline(1.dp, tint.copy(alpha = 0.35f), J.rM)
        .padding(J.sp4), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
        Row(Modifier.fillMaxWidth().then(if (folds) Modifier.clickable(role = androidx.compose.ui.semantics.Role.Button,
                onClickLabel = if (open) "Fold" else "Open") { open = !open } else Modifier),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
            Icon(icon, null, tint = tint, modifier = Modifier.size(20.dp))
            Text(b.title, style = read.copy(fontWeight = FontWeight(700), color = tint), modifier = Modifier.weight(1f))
            if (folds) Icon(Icons.down, null, tint = tint, modifier = Modifier.size(20.dp)
                .graphicsLayer { rotationZ = if (open) 180f else 0f })
        }
        if (open && b.spans.isNotEmpty()) Text(spans(b.spans, opens, link, tags), style = read)
    }
}

/** A chart block as bars (26e): each bar in the accent against a track, its value at the end;
 *  scaled to the largest, or to 100 for percentages. TalkBack reads label and value. */
@Composable
private fun Chart(c: MdChart) {
    val top = if (c.unit == "%") maxOf(100.0, c.bars.maxOf { it.second }) else c.bars.maxOf { it.second }.coerceAtLeast(1e-9)
    Column(Modifier.fillMaxWidth().clip(J.rM).background(J.raise).padding(J.sp4), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
        if (c.title != null) Text(c.title, style = J.item)
        for ((label, v) in c.bars) {
            val shown = (if (v % 1.0 == 0.0) v.toLong().toString() else v.toString()) + c.unit
            Column(Modifier.semantics(mergeDescendants = true) {}, verticalArrangement = Arrangement.spacedBy(J.sp1)) {
                Row(Modifier.fillMaxWidth()) {
                    Text(label, style = J.sec.copy(color = J.text), modifier = Modifier.weight(1f))
                    Text(shown, style = J.monoCap.copy(color = J.text))
                }
                Box(Modifier.fillMaxWidth().height(8.dp).clip(J.pill).background(J.line)) {
                    Box(Modifier.fillMaxWidth((v / top).toFloat().coerceIn(0f, 1f)).fillMaxHeight().clip(J.pill).background(J.acc))
                }
            }
        }
    }
}

/** Code in its colours (204); the text is the pieces joined, exactly the block */
private fun coloured(pieces: List<Piece>): AnnotatedString = buildAnnotatedString {
    for (p in pieces) withStyle(SpanStyle(color = J.code(p.tok),
        fontStyle = if (p.tok == Tok.COMMENT) FontStyle.Italic else FontStyle.Normal)) { append(p.text) }
}

/** Spans as styled text; only a wikilink to a known note gets a tap. */
private fun spans(list: List<Span>, opens: ((String) -> (() -> Unit)?)?, link: ((String) -> Unit)? = null,
                  tags: ((String) -> (() -> Unit)?)? = null): AnnotatedString = buildAnnotatedString {
    for (s in list) {
        var style = SpanStyle()
        if (s.bold) style = style.merge(SpanStyle(fontWeight = FontWeight(700)))
        if (s.italic) style = style.merge(SpanStyle(fontStyle = FontStyle.Italic))
        if (s.strike) style = style.merge(SpanStyle(textDecoration = TextDecoration.LineThrough))
        if (s.mark) style = style.merge(SpanStyle(background = J.acc.copy(alpha = 0.33f)))
        // Inline code as cyan mono text, no block behind it: a span that wraps or two spans side by
        // side then read as one (asked 2026-10-18); code blocks keep their box
        if (s.code) style = style.merge(SpanStyle(fontFamily = J.mono, fontSize = J.sec.fontSize, color = J.tint(app.julz.feed.Kind.RUN)))
        if (s.tag) style = style.merge(SpanStyle(color = J.accText))
        // An inline field as a quiet chip: mono, muted, on a raised background (22d)
        if (s.field) style = style.merge(SpanStyle(fontFamily = J.mono, fontSize = J.cap.fontSize, color = J.muted, background = J.raise))
        val open = s.wiki?.let { opens?.invoke(it) }
        val tap = if (s.tag) tags?.invoke(s.text) else null
        val web = s.link
        when {
            web != null && link != null -> withLink(LinkAnnotation.Clickable(web, TextLinkStyles(SpanStyle(color = J.accText,
                textDecoration = TextDecoration.Underline))) { link(web) }) { withStyle(style) { append(s.text) } }
            open != null -> withLink(LinkAnnotation.Clickable(s.wiki, TextLinkStyles(SpanStyle(color = J.accText,
                textDecoration = TextDecoration.Underline))) { open() }) { withStyle(style) { append(s.text) } }
            s.wiki != null -> withStyle(style.merge(SpanStyle(color = J.muted))) { append(s.text) }  // no such note
            tap != null -> withLink(LinkAnnotation.Clickable(s.text, TextLinkStyles(style)) { tap() }) { append(s.text) }
            else -> withStyle(style) { append(s.text) }
        }
    }
}

@Composable
private fun Item(b: MdItem, opens: ((String) -> (() -> Unit)?)?, link: ((String) -> Unit)?, tags: ((String) -> (() -> Unit)?)?,
                 read: androidx.compose.ui.text.TextStyle = J.bodyText) {
    Row(Modifier.padding(start = J.sp4 * b.depth), horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
        when (b.marker) {
            "[/]" -> {
                // In progress: the box in the accent, half filled, as the stage circle on Todos (22d)
                Box(Modifier.padding(top = 2.dp).size(20.dp).clip(RoundedCorner6).outline(1.5.dp, J.acc, RoundedCorner6)) {
                    Box(Modifier.fillMaxHeight().fillMaxWidth(0.5f).background(J.acc.copy(alpha = 0.6f)))
                }
                Text(spans(b.spans, opens, link, tags), style = read, modifier = Modifier.weight(1f))
            }
            "[ ]", "[x]" -> {
                val done = b.marker == "[x]"
                // Drawn, not tappable: ticking stays on Todos, signed (113)
                Box(Modifier.padding(top = 2.dp).size(20.dp).clip(RoundedCorner6).background(if (done) J.acc else Color.Transparent)
                    .outline(1.5.dp, if (done) J.acc else J.muted, RoundedCorner6), contentAlignment = Alignment.Center) {
                    if (done) Icon(Icons.check, null, tint = J.onAcc, modifier = Modifier.size(14.dp))
                }
                Text(spans(b.spans, opens, link, tags), style = read.copy(color = if (done) J.muted else J.text), modifier = Modifier.weight(1f))
            }
            else -> {
                Text(b.marker, style = read.copy(color = J.muted), modifier = Modifier.widthIn(min = 16.dp))
                Text(spans(b.spans, opens, link, tags), style = read, modifier = Modifier.weight(1f))
            }
        }
    }
}

private val RoundedCorner6 = androidx.compose.foundation.shape.RoundedCornerShape(6.dp)

@Composable
private fun Bar(color: Color, content: @Composable () -> Unit) {
    Row(Modifier.height(IntrinsicSize.Min), horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
        Box(Modifier.width(3.dp).fillMaxHeight().clip(RoundedCorner6).background(color))
        content()
    }
}

@Composable
private fun Props(p: MdProps, tags: ((String) -> (() -> Unit)?)?) {
    Column(Modifier.fillMaxWidth().clip(J.rS).background(J.raise).padding(J.sp4), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
        for ((k, v) in p.props) Row(horizontalArrangement = Arrangement.spacedBy(J.sp3), verticalAlignment = Alignment.CenterVertically) {
            Text(k, style = J.monoCap)
            Text(v, style = J.sec.copy(color = J.text))
        }
        // Tags wrap onto the next line, never cut off at the edge
        if (p.tags.isNotEmpty()) androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(J.sp2),
            verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            for (t in p.tags) {
                // A chip the browser knows opens its tag view (212). Compose widens its touch area
                // to 48 dp without moving the layout, the closest chip wins (asked: no big gaps)
                val go = tags?.invoke(t)
                val chip = Modifier.clip(J.rS).outline(1.dp, J.line, J.rS)
                Text("#$t", style = J.cap.copy(color = J.accText), modifier = (if (go != null)
                    chip.clickable(role = androidx.compose.ui.semantics.Role.Button, onClick = go) else chip)
                    .padding(horizontal = J.sp3, vertical = J.sp1))
            }
        }
    }
}

/** A table (26e): each column as wide as its longest cell, so a one digit column stays narrow;
 *  a table that fits fills the width, a wider one scrolls with a fade at the edge that says so
 *  (every column was 132 dp, and "Broadcast" was cut with no hint, found 19 Oct). */
@Composable
private fun Table(t: MdTable, opens: ((String) -> (() -> Unit)?)?, link: ((String) -> Unit)?,
                  tags: ((String) -> (() -> Unit)?)?) = androidx.compose.foundation.layout.BoxWithConstraints {
    val cols = (t.rows.maxOfOrNull { it.size } ?: 0).coerceAtLeast(1)
    // Each cell measured in its own style (a guess per character broke bold headers mid word);
    // a column at most 240 dp, so one long cell wraps instead of pushing the rest away
    val measurer = androidx.compose.ui.text.rememberTextMeasurer()
    val density = androidx.compose.ui.platform.LocalDensity.current
    val head = J.sec.copy(fontWeight = FontWeight(700))
    val natural = (0 until cols).map { c ->
        val px = t.rows.withIndex().maxOf { (r, row) ->
            val text = row.getOrNull(c)?.joinToString("") { it.text }.orEmpty()
            measurer.measure(text, if (r == 0) head else J.sec, maxLines = 1).size.width
        }
        minOf(with(density) { px.toDp() } + J.sp2 * 2 + 2.dp, 240.dp)
    }
    val total = natural.fold(0.dp) { a, w -> a + w }
    val widths = if (total <= maxWidth) natural.map { it * (maxWidth / total) } else natural
    val scroll = rememberScrollState()
    Box(Modifier.fillMaxWidth().clip(J.rS).outline(1.dp, J.line, J.rS)) {
        Column(Modifier.edgeFade(scroll).horizontalScroll(scroll)) {
            t.rows.forEachIndexed { r, row ->
                Row(Modifier.background(if (r == 0) J.raise else Color.Transparent)) {
                    for (c in 0 until cols) {
                        val cell = row.getOrNull(c).orEmpty()
                        Text(spans(cell, opens, link, tags), style = (if (r == 0) J.sec.copy(fontWeight = FontWeight(700)) else J.sec).copy(color = J.text),
                            modifier = Modifier.width(widths[c]).padding(horizontal = J.sp2, vertical = J.sp2))
                    }
                }
                if (r < t.rows.size - 1) Box(Modifier.width(widths.fold(0.dp) { a, w -> a + w }).height(1.dp).background(J.line))
            }
        }
    }
}

/** Fades the edges of a sideways scroll (26e, 217): the right while more is hidden there, the left
 *  once scrolled. The usual sign that a box scrolls. A mask on the content's own alpha, not a painted
 *  colour, so it matches whatever is behind (a painted fade showed a dark band over the chat's glow) */
private fun Modifier.edgeFade(scroll: androidx.compose.foundation.ScrollState): Modifier =
    graphicsLayer { compositingStrategy = androidx.compose.ui.graphics.CompositingStrategy.Offscreen }
        .drawWithContent {
            drawContent()
            val w = J.sp8.toPx()
            if (scroll.canScrollBackward) drawRect(androidx.compose.ui.graphics.Brush.horizontalGradient(
                listOf(Color.Transparent, Color.Black), startX = 0f, endX = w),
                size = androidx.compose.ui.geometry.Size(w, size.height), blendMode = androidx.compose.ui.graphics.BlendMode.DstIn)
            if (scroll.canScrollForward) drawRect(androidx.compose.ui.graphics.Brush.horizontalGradient(
                listOf(Color.Black, Color.Transparent), startX = size.width - w, endX = size.width),
                topLeft = androidx.compose.ui.geometry.Offset(size.width - w, 0f),
                size = androidx.compose.ui.geometry.Size(w, size.height), blendMode = androidx.compose.ui.graphics.BlendMode.DstIn)
        }
