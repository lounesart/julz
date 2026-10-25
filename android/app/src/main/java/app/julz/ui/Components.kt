package app.julz.ui

import androidx.compose.animation.core.animateFloat
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.shadow
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.indication
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.runtime.setValue
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.foundation.layout.offset
import androidx.compose.ui.graphics.drawscope.clipRect
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.width
import app.julz.feed.Kind
import java.text.DateFormat
import java.util.Calendar
import java.util.Date

/** Words the app owns for each kind. A notice never decides what I am told about it (86). */
object Words {
    fun label(kind: Kind) = when (kind) {
        Kind.APPROVAL -> "Approvals"; Kind.TODO -> "Todos"; Kind.INBOX -> "Inbox"; Kind.RUN -> "Runs"
        Kind.REVIEW -> "Review"; Kind.CHANGE -> "Changes"; Kind.WARNING -> "Warnings"
    }

    private val SHORT_ID = Regex("\\s([0-9a-f]{8})$")

    /** A notice title for History: without "Julz: " in front, capitalised, and its short id (the
     *  first 8 of a hash) apart, so the title fits one line. */
    fun shortTitle(title: String): Pair<String, String?> {
        val bare = title.removePrefix("Julz:").trim().ifEmpty { return title to null }
        val id = SHORT_ID.find(bare)?.groupValues?.get(1)
        val text = (if (id != null) bare.removeSuffix(id).trim() else bare).replaceFirstChar { it.uppercase() }
        return text to id
    }

    /** A card's kind in one word, the same words as the Messages filters (22d: History said
     *  Check where Messages said Warnings) */
    fun status(kind: Kind) = when (kind) {
        Kind.APPROVAL -> "Approval"; Kind.TODO -> "Todo"; Kind.INBOX -> "Inbox"; Kind.RUN -> "Run"
        Kind.REVIEW -> "Review"; Kind.CHANGE -> "Change"; Kind.WARNING -> "Warning"
    }

    fun meaning(kind: Kind) = when (kind) {
        // As Julz works now (22d integrity: it said passkey and keep; the fingerprint signs, Inbox
        // moves or deletes); these words also go into Ask Julz's question
        Kind.APPROVAL -> "Something waits for your decision on Approve: a spec Julz wrote for Claude Code, or a " +
            "question from a run. Nothing runs until you read it there and sign with your fingerprint."
        Kind.TODO -> "One of your todo lists changed. Tick tasks on Todos with your fingerprint."
        Kind.INBOX -> "Notes wait in Inbox to be sorted: move each one to its folder or delete it. One " +
            "fingerprint applies your picks."
        Kind.RUN -> "A Claude Code run finished. The report is in Outbox and its Keep card is on Approve; ask " +
            "Julz about it."
        Kind.REVIEW -> "Some of your notes are due for review. Say \"quiz me\" to Julz."
        Kind.CHANGE -> "Something happened on the laptop that does not need you: a note changed, a request was " +
            "refused, or a step you signed was carried out. The notice says which."
        Kind.WARNING -> "Something needs a look on the laptop. runner.log there says what."
    }

    fun time(seconds: Long): String =
        DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(seconds * 1000))

    fun day(seconds: Long, now: Long = System.currentTimeMillis() / 1000): String {
        val c = Calendar.getInstance().apply { timeInMillis = seconds * 1000 }
        val today = Calendar.getInstance().apply { timeInMillis = now * 1000 }
        val days = today.get(Calendar.DAY_OF_YEAR) - c.get(Calendar.DAY_OF_YEAR) +
            365 * (today.get(Calendar.YEAR) - c.get(Calendar.YEAR))
        return when (days) {
            0 -> "Today"; 1 -> "Yesterday"
            else -> DateFormat.getDateInstance(DateFormat.MEDIUM).format(Date(seconds * 1000))
        }
    }
}

@Composable
fun KindIcon(kind: Kind) = IconBadge(Icons.kind(kind), J.tint(kind))

/** An icon in a circle, one look everywhere (22d integrity: Messages had filled pastel circles,
 *  Tools grey ones, Move to its own): History's family, glass with a line and the icon in
 *  [tint]; neutral without one. */
@Composable
fun IconBadge(icon: ImageVector, tint: Color? = null) {
    // The theme's button shape, cut on Industrial (asked 18 Oct: the circles stayed round there)
    Box(Modifier.size(44.dp).background(tint?.copy(alpha = 0.12f) ?: J.raise, J.pill)
        .border(1.dp, tint?.copy(alpha = 0.7f) ?: J.line, J.pill), contentAlignment = Alignment.Center) {
        Icon(icon, contentDescription = null, tint = tint ?: J.muted, modifier = Modifier.size(22.dp))
    }
}

/** A notice's card in one family (22d integrity): dark glass with a line and a glow in its
 *  kind's colour; [strong] (a warning, an approval) a brighter line, a wider glow, tinted glass.
 *  History's cards and the notice's own card in Details use it, so they cannot drift apart. */
fun Modifier.kindCard(tint: Color, strong: Boolean, shape: androidx.compose.ui.graphics.Shape = J.rL) =
    this.shadow(if (strong) 18.dp else 10.dp, shape, ambientColor = tint, spotColor = tint).clip(shape).background(J.bg)
        .background(tint.copy(alpha = if (strong) 0.16f else 0.06f))
        .border(if (strong) 1.5.dp else 1.dp, tint.copy(alpha = if (strong) 0.95f else 0.55f), shape)

/** A status in one word, one look everywhere (22d integrity: four hand made versions): the word
 *  in [tint] on a faint tint of it. Never colour alone, the word says it. */
@Composable
fun Tag(text: String, tint: Color) {
    Text(text, style = J.tag.copy(color = tint), maxLines = 1,
        modifier = Modifier.clip(J.pill).background(tint.copy(alpha = 0.16f)).padding(horizontal = 10.dp, vertical = 2.dp))
}

@Composable
fun RoundButton(icon: ImageVector, description: String, onClick: () -> Unit) =
    IconButton(icon, description, J.raise, J.text, onClick = onClick)

/** Every icon button the same (asked 19 Oct, the sizes did not match): a 40 dp shape in the
 *  theme's button form (a circle, cut on Industrial) inside a 48 dp touch target, as Material 3
 *  has it. The press ripple stays inside the shape. Header buttons were 48 dp shapes, send a
 *  40 dp shape with a 40 dp target, under Android's 48 dp minimum. */
@Composable
fun IconButton(icon: ImageVector, description: String?, fill: Color, tint: Color, enabled: Boolean = true,
               line: Boolean = true, onClick: () -> Unit) {
    val press = remember { androidx.compose.foundation.interaction.MutableInteractionSource() }
    Box(Modifier.size(J.tap).clickable(press, null, enabled = enabled, role = Role.Button, onClickLabel = description, onClick = onClick),
        contentAlignment = Alignment.Center) {
        Box(Modifier.size(J.iconButton).clip(J.pill).background(fill)
            .then(if (line) Modifier.border(1.dp, J.line, J.pill) else Modifier)
            .indication(press, androidx.compose.material3.ripple()), contentAlignment = Alignment.Center) {
            Icon(icon, contentDescription = description, tint = tint, modifier = Modifier.size(22.dp))
        }
    }
}

/** Tabs in a pill. With [position] (a pager's page plus its offset) the light slides along with a
 *  swipe; it is read while drawing, so a swipe redraws the pill and nothing else. */
@Composable
fun Segmented(options: List<String>, selected: Int, position: (() -> Float)? = null, modifier: Modifier = Modifier,
              onSelect: (Int) -> Unit) {
    androidx.compose.foundation.layout.BoxWithConstraints(modifier.fillMaxWidth()) {
    val labelStyle = J.sec.copy(fontWeight = J.ts.fontWeight)
    val pillShape = J.pill
    val textSize = rememberRowSize(options, labelStyle, (maxWidth - J.sp1 * (options.size + 1)) / options.size - J.sp1 * 2)
    Row(Modifier.fillMaxWidth().glass(J.pill).padding(J.sp1).drawBehind {
            if (position == null) return@drawBehind
            val gap = J.sp1.toPx()
            val w = (size.width - gap * (options.size - 1)) / options.size
            val stroke = 1.dp.toPx()
            // Outlined: a 1 dp accent line, drawn inside the light's bounds
            // The light in the pill token's own shape, round or cut (22d: it stayed round with Industrial)
            val light = androidx.compose.ui.geometry.Size(w, size.height)
            translate(left = (w + gap) * position()) {
                val o = pillShape.createOutline(light, layoutDirection, this)
                if (J.outline) drawOutline(o, J.acc, style = androidx.compose.ui.graphics.drawscope.Stroke(stroke))
                else drawOutline(o, J.text)
            }
        },
        horizontalArrangement = Arrangement.spacedBy(J.sp1)) {
        options.forEachIndexed { i, label ->
            val on = i == selected
            Box(Modifier.weight(1f).heightIn(min = J.tap).clip(J.pill)
                .background(if (on && position == null && !J.outline) J.text else Color.Transparent)
                .border(1.dp, if (on && position == null && J.outline) J.acc else Color.Transparent, J.pill)
                .clickable(role = Role.Tab) { onSelect(i) }, contentAlignment = Alignment.Center) {
                Text(label, style = labelStyle.copy(color = if (!on) J.muted else if (J.outline) J.accText else J.bg,
                    fontSize = textSize), maxLines = 1, softWrap = false, modifier = Modifier.padding(horizontal = J.sp1))
            }
        }
    }
    }
}

/** A spec line, as on a data sheet (22e, from the planets reference): the label muted, the value
 *  mono in the readable accent. Plain text only. */
@Composable
fun SpecLine(label: String, value: String) {
    val valueStyle = J.sec.copy(fontFamily = J.mono, color = J.accText)
    // One label column, each value right beside its label (22d integrity: a value pushed to the
    // far end sat away from what it belongs to); stacked only at big text
    if (J.big) Column(Modifier.fillMaxWidth()) {
        Text(label, style = J.sec)
        Text(value, style = valueStyle)
    }
    else Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(J.sp3), verticalAlignment = Alignment.Top) {
        Text(label, style = J.sec, modifier = Modifier.width(120.dp))
        Text(value, style = valueStyle, modifier = Modifier.weight(1f))
    }
}

/** A real id as a code (22c, from the spec sheet reference): its kind in spaced caps, the id
 *  exactly as it is, so it matches what Julz says in the chat (39b). Never a made-up code. */
@Composable
fun Code(label: String, id: String) {
    Text(androidx.compose.ui.text.buildAnnotatedString {
        pushStyle(androidx.compose.ui.text.SpanStyle(letterSpacing = 2.sp, color = J.muted))
        append(label.uppercase()); pop()
        append("  ")
        pushStyle(androidx.compose.ui.text.SpanStyle(color = J.accText)); append(id); pop()
    }, style = J.monoCap)
}

/** One text size for a row of labels (22d): the size the widest one fits at, for all of them, so
 *  a row never mixes sizes ("Messages" alone got smaller at 200 percent), never under [least].
 *  [widths] in px measured at [base] sp; [avail] the px each label has. */
fun rowSize(widths: List<Int>, avail: Float, base: Float, least: Float): Float {
    val widest = widths.maxOrNull()?.takeIf { it > 0 } ?: return base
    return (base * minOf(1f, avail / widest)).coerceIn(minOf(least, base), base)
}

/** [rowSize] for labels in [style], each with [itemWidth]; on one line, never broken inside a
 *  word ("Appr / ove" at 200 percent). The least is 11 sp as it is at 100 percent. */
@Composable
fun rememberRowSize(labels: List<String>, style: androidx.compose.ui.text.TextStyle, itemWidth: androidx.compose.ui.unit.Dp):
        androidx.compose.ui.unit.TextUnit {
    val measurer = androidx.compose.ui.text.rememberTextMeasurer()
    val d = androidx.compose.ui.platform.LocalDensity.current
    val widths = labels.map { measurer.measure(it, style, maxLines = 1, softWrap = false).size.width }
    // room to spare: text does not shrink exactly in step with its size, 3 percent still clipped
    return rowSize(widths, with(d) { itemWidth.toPx() } * 0.9f, style.fontSize.value, 11f / d.fontScale).sp
}

/** Text fields in Julz's own shape (22d: the stock ones were near square, and their outline was
 *  brighter than the cards' hairline, so an empty field was the loudest line on a screen). One
 *  line is a pill like the buttons beside it, more lines a card like the rows. */
fun fieldShape(oneLine: Boolean) = if (oneLine) J.pill else J.rM

/** Quiet when empty: the cards' hairline over glass. The accent only while I type, the warning
 *  colour on an error. */
@Composable
fun fieldColors() = androidx.compose.material3.OutlinedTextFieldDefaults.colors(
    focusedBorderColor = J.acc, unfocusedBorderColor = J.line, disabledBorderColor = J.line.copy(alpha = 0.05f),
    errorBorderColor = J.warn, focusedContainerColor = J.surface, unfocusedContainerColor = J.surface,
    disabledContainerColor = J.surface, errorContainerColor = J.surface,
    focusedTextColor = J.text, unfocusedTextColor = J.text, disabledTextColor = J.muted,
    focusedLabelColor = J.accText, unfocusedLabelColor = J.muted, disabledLabelColor = J.faint, cursorColor = J.acc)

/** Every screen's header (22f): back, the title, a line under it, one action. One title size;
 *  the buttons line up with the title's first line however many lines the words take (at 200
 *  percent Tools' Reload sat in the middle of two lines); the same spacing everywhere. */
@Composable
fun ScreenHeader(title: String, sub: String? = null, back: (() -> Unit)? = null, backLabel: String = "Back",
                 mono: Boolean = true, content: Boolean = false, action: (@Composable () -> Unit)? = null) {
    // The line of the style actually drawn, so a small title centres on the buttons too
    val line = with(androidx.compose.ui.platform.LocalDensity.current) { (if (content) J.ts else J.tl).lineHeight.toDp() }
    // a 48 dp button against the title's first line: whichever is shorter moves down to centre
    val buttonTop = ((line - J.tap) / 2).coerceAtLeast(0.dp)
    val titleTop = ((J.tap - line) / 2).coerceAtLeast(0.dp)
    Row(Modifier.fillMaxWidth().padding(top = if (J.big) J.sp4 else J.sp6, bottom = J.sp2), verticalAlignment = Alignment.Top) {
        if (back != null) {
            Box(Modifier.padding(top = buttonTop)) { RoundButton(Icons.back, backLabel, back) }
            Spacer(Modifier.width(J.sp4))
        }
        androidx.compose.foundation.layout.BoxWithConstraints(Modifier.weight(1f).padding(top = titleTop)) {
        val room = maxWidth
        Column {
            // It may wrap between words, never inside one: at 200 percent Approve lost its e to
            // the next line. Its longest word sets the size, as a row of labels does (22f)
            // [content]: the title is something of mine (a chat's name), not the screen's: one
            // line in the section title size, cut with an ellipsis (26b, found 18 Oct)
            if (content) Text(title, style = J.ts, maxLines = 1, overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
            else {
                val size = rememberRowSize(title.split(' '), J.tl, room)
                Text(title, style = J.tl.copy(fontSize = size, lineHeight = size * 1.125f))
            }
            if (sub != null) Text(sub, style = if (mono) J.monoCap else J.sec)
        }
        }
        if (action != null) {
            Spacer(Modifier.width(J.sp3))
            Box(Modifier.padding(top = buttonTop)) { action() }
        }
    }
}

/** Arrives assembled, never popped (22f, after Arwes: things should not just appear): an accent
 *  hairline traces the frame, then the content fades up, 450 ms on the HyDE curve. Still when
 *  the phone asks for less motion. For what arrives with a screen, not rows while scrolling. */
/** What has arrived this session. A card with a key assembles the first time only: swiping
 *  back to Now rebuilt its cards and they assembled again mid swipe, which cost frames
 *  (0.46 to 0.9 percent janky over ten swipes, 18 Oct) and is not an arrival anyway */
object Arrived {
    private val seen = java.util.Collections.synchronizedSet(HashSet<String>())
    fun first(key: String): Boolean = seen.add(key)
}

@Composable
fun Modifier.assemble(shape: androidx.compose.ui.graphics.Shape = J.rL, key: String? = null): Modifier {
    if (stillMotion()) return this
    val arriving = remember(key) { key == null || Arrived.first(key) }
    if (!arriving) return this
    val p = remember { androidx.compose.animation.core.Animatable(0f) }
    androidx.compose.runtime.LaunchedEffect(Unit) { p.animateTo(1f, androidx.compose.animation.core.tween(450, easing = J.ease)) }
    return this.drawWithContent {
        drawContent()
        val v = p.value
        if (v < 1f) {
            val stroke = 1.dp.toPx()
            // the frame runs round first, then fades as the content lands
            // the element's own outline, round or cut, traced from the left
            clipRect(right = size.width * (v * 1.6f).coerceAtMost(1f)) {
                drawOutline(shape.createOutline(size, layoutDirection, this), J.acc.copy(alpha = 0.7f * (1f - v)),
                    style = androidx.compose.ui.graphics.drawscope.Stroke(stroke))
            }
        }
    }.graphicsLayer { alpha = ((p.value - 0.25f) / 0.75f).coerceIn(0f, 1f) }
}

/** True when the phone's animations are off: motion then jumps or stands still. */
@Composable
fun stillMotion(): Boolean {
    val context = androidx.compose.ui.platform.LocalContext.current
    return remember {
        android.provider.Settings.Global.getFloat(context.contentResolver,
            android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
    }
}

/** The one glowing action of a screen, as in the design system: a border of magenta that turns
 *  and a halo that breathes. Both stand still when the phone's animations are off. */
@Composable
fun GlowButton(label: String, onClick: () -> Unit) {
    val still = stillMotion()
    val glow = androidx.compose.animation.core.rememberInfiniteTransition(label = "glow")
    val angle = if (still) remember { androidx.compose.runtime.mutableFloatStateOf(0f) } else
        glow.animateFloat(0f, 360f, androidx.compose.animation.core.infiniteRepeatable(
            androidx.compose.animation.core.tween(4000, easing = androidx.compose.animation.core.LinearEasing)), label = "spin")
    val halo = if (still) remember { androidx.compose.runtime.mutableFloatStateOf(12f) } else
        glow.animateFloat(6f, 20f, androidx.compose.animation.core.infiniteRepeatable(
            androidx.compose.animation.core.tween(1300), androidx.compose.animation.core.RepeatMode.Reverse), label = "halo")
    val shape = J.pill
    // From the accent (22d integrity: the ring was magenta's pink and wine on every theme)
    val ring = androidx.compose.ui.graphics.Brush.sweepGradient(listOf(J.acc,
        androidx.compose.ui.graphics.lerp(J.acc, Color.White, 0.55f), J.accDeep, J.acc))
    Row(Modifier.fillMaxWidth().heightIn(min = J.tapL)
        .shadow(halo.value.dp, shape, ambientColor = J.acc, spotColor = J.acc)
        .clip(shape)
        .drawBehind { rotate(angle.value) { drawCircle(ring, radius = size.maxDimension) } }
        .padding(2.dp)
        .background(J.bg, J.pill)
        // Room around the words at big text, as at 100 percent (22d: they filled the button)
        .clickable(role = Role.Button, onClick = onClick).padding(horizontal = J.sp5, vertical = J.sp3),
        horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = J.bodyText.copy(fontWeight = J.ts.fontWeight, textAlign = androidx.compose.ui.text.style.TextAlign.Center),
            modifier = Modifier.weight(1f, fill = false))
        Icon(Icons.arrow, null, tint = J.text, modifier = Modifier.padding(start = J.sp2).size(20.dp))
    }
}

@Composable
fun PlainButton(label: String, color: Color = J.text, border: Color = J.lineStrong,
                modifier: Modifier = Modifier.fillMaxWidth(), onClick: () -> Unit) {
    Box(modifier.heightIn(min = J.tapL).clip(J.pill)
        .border(1.dp, border, J.pill).clickable(role = Role.Button, onClick = onClick),
        contentAlignment = Alignment.Center) {
        Text(label, style = J.bodyText.copy(color = color, fontWeight = J.ts.fontWeight,
            textAlign = androidx.compose.ui.text.style.TextAlign.Center),
            modifier = Modifier.padding(horizontal = J.sp5, vertical = J.sp3))
    }
}

@Composable
fun SectionTitle(text: String) {
    // Industrial: spaced capitals, as the spec sheet's labels (22b)
    if (Look.prefs.industrial) Text(text.uppercase(), style = J.cap.copy(fontWeight = J.ts.fontWeight, letterSpacing = 1.5.sp),
        modifier = Modifier.padding(horizontal = J.sp1))
    else Text(text, style = J.sec.copy(fontWeight = J.ts.fontWeight), modifier = Modifier.padding(horizontal = J.sp1))
}

@Composable
fun ListRow(title: String, sub: String? = null, onClick: (() -> Unit)? = null, trailing: @Composable () -> Unit = {}) {
    val base = Modifier.fillMaxWidth().heightIn(min = J.row)
    Row((if (onClick != null) base.clickable(role = Role.Button, onClick = onClick) else base)
        .padding(vertical = J.sp3), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
        Column(Modifier.weight(1f)) {
            Text(title, style = J.item)
            if (sub != null) Text(sub, style = J.sec)
        }
        trailing()
    }
}

/** Where a sheet draws: inside the app's own window, over every screen and the tab bar, so it
 *  looks as the design system draws it. A sheet in a window of its own (ModalBottomSheet) let the
 *  screen show through and got a light navigation bar (found 2026-10-18 on the phone). */
class SheetHost {
    var content by androidx.compose.runtime.mutableStateOf<(@Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit)?>(null)
    var dismiss by androidx.compose.runtime.mutableStateOf<(() -> Unit)?>(null)
}

val LocalSheetHost = androidx.compose.runtime.staticCompositionLocalOf<SheetHost?> { null }

/** A bottom sheet as the design system draws it (mockups Todos, Approve). Shown while this is
 *  in the composition; onDismiss runs on Back, on a tap on the dimmed screen, and from Cancel. */
@Composable
fun JulzSheet(onDismiss: () -> Unit, content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    val host = LocalSheetHost.current ?: return
    val body by androidx.compose.runtime.rememberUpdatedState(content)
    val close by androidx.compose.runtime.rememberUpdatedState(onDismiss)
    // The sheet draws over the screen but focus stayed in the box under it, so the keyboard
    // stayed up, even over a chat picked from My chats (216). A draft lives outside its field
    val focus = androidx.compose.ui.platform.LocalFocusManager.current
    val keyboard = androidx.compose.ui.platform.LocalSoftwareKeyboardController.current
    androidx.compose.runtime.DisposableEffect(host) {
        focus.clearFocus(); keyboard?.hide()
        host.content = { body(this) }
        host.dismiss = { close() }
        onDispose { host.content = null; host.dismiss = null }
    }
}

/** The dimmed screen and the sheet itself: solid (no blur on the phone, so not see through),
 *  28 top corners, a 40 by 4 handle, content that scrolls if it is long, reaching under the
 *  navigation buttons. Drawn last in the app's root. */
@Composable
fun SheetLayer(host: SheetHost) {
    val body = host.content ?: return
    androidx.activity.compose.BackHandler { host.dismiss?.invoke() }
    // Pulled down from its top it follows the finger and closes past a third of a screen or on
    // a quick flick, as every bottom sheet does (asked 18 Oct: only Back or the dim closed it).
    // The list inside scrolls first; only the pull past its top moves the sheet
    val pull = remember { androidx.compose.runtime.mutableFloatStateOf(0f) }
    val close = 300f * androidx.compose.ui.platform.LocalDensity.current.density
    val pulling = remember(host) {
        object : androidx.compose.ui.input.nestedscroll.NestedScrollConnection {
            override fun onPreScroll(available: androidx.compose.ui.geometry.Offset,
                                     source: androidx.compose.ui.input.nestedscroll.NestedScrollSource): androidx.compose.ui.geometry.Offset {
                if (available.y < 0 && pull.floatValue > 0) {
                    val used = maxOf(available.y, -pull.floatValue)
                    pull.floatValue += used
                    return androidx.compose.ui.geometry.Offset(0f, used)
                }
                return androidx.compose.ui.geometry.Offset.Zero
            }
            override fun onPostScroll(consumed: androidx.compose.ui.geometry.Offset, available: androidx.compose.ui.geometry.Offset,
                                      source: androidx.compose.ui.input.nestedscroll.NestedScrollSource): androidx.compose.ui.geometry.Offset {
                if (available.y > 0 && source == androidx.compose.ui.input.nestedscroll.NestedScrollSource.UserInput) {
                    pull.floatValue += available.y
                    return androidx.compose.ui.geometry.Offset(0f, available.y)
                }
                return androidx.compose.ui.geometry.Offset.Zero
            }
            override suspend fun onPreFling(available: androidx.compose.ui.unit.Velocity): androidx.compose.ui.unit.Velocity {
                if (pull.floatValue <= 0f) return androidx.compose.ui.unit.Velocity.Zero
                if (pull.floatValue > close || available.y > 2500f) host.dismiss?.invoke()
                else androidx.compose.animation.core.animate(pull.floatValue, 0f) { v, _ -> pull.floatValue = v }
                return available
            }
        }
    }
    Box(Modifier.fillMaxSize().background(J.scrim)
        .clickable(interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
            indication = null, onClickLabel = "Close") { host.dismiss?.invoke() }) {
        Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth()
            .offset { androidx.compose.ui.unit.IntOffset(0, pull.floatValue.toInt()) }.assemble()
            .clip(J.sheetTop).background(J.sheet)
            // The accent's glow, at the top of the sheet as on the page behind it
            .background(androidx.compose.ui.graphics.Brush.radialGradient(listOf(J.acc.copy(alpha = 0.22f), Color.Transparent),
                center = androidx.compose.ui.geometry.Offset(540f, 0f), radius = 900f))
            .border(1.dp, J.line, J.sheetTop)
            .clickable(interactionSource = remember { androidx.compose.foundation.interaction.MutableInteractionSource() },
                indication = null, onClick = {})  // a tap on the sheet is not a tap on the dimmed screen
            .navigationBarsPadding()
            .nestedScroll(pulling)
            .verticalScroll(androidx.compose.foundation.rememberScrollState())
            .padding(start = J.gutter, end = J.gutter, top = J.sp3, bottom = J.sp6),
            verticalArrangement = Arrangement.spacedBy(J.sp4)) {
            Box(Modifier.align(Alignment.CenterHorizontally).size(width = 40.dp, height = 4.dp)
                .clip(RoundedCornerShape(2.dp)).background(J.lineStrong))
            body()
        }
    }
}

/** The list's own pixels fade out over its last [height], so it blends into whatever is behind:
 *  FadeBottom paints J.bg, which showed as a black band where the page's glow is lighter (the
 *  chat in landscape, found 24 Oct). An offscreen layer and a DstIn mask, as Compose shows it */
fun Modifier.fadeOutBottom(height: androidx.compose.ui.unit.Dp): Modifier =
    graphicsLayer { compositingStrategy = androidx.compose.ui.graphics.CompositingStrategy.Offscreen }
        .drawWithContent {
            drawContent()
            val h = height.toPx()
            drawRect(androidx.compose.ui.graphics.Brush.verticalGradient(listOf(Color.Black, Color.Transparent),
                startY = size.height - h, endY = size.height), blendMode = androidx.compose.ui.graphics.BlendMode.DstIn)
        }

/** The end of a list that scrolls under a pinned bar: a short fade into the page, so content
 *  slides away instead of stopping at a hard edge (found 2026-10-18 on Goals). */
@Composable
fun androidx.compose.foundation.layout.BoxScope.FadeBottom() {
    Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(28.dp)
        .background(androidx.compose.ui.graphics.Brush.verticalGradient(listOf(Color.Transparent, J.bg))))
}
