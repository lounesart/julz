package app.julz.ui

import androidx.compose.animation.core.animateFloat
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.drawWithCache
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
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.gestures.detectVerticalDragGestures
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
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.draw.drawWithContent
import androidx.compose.ui.node.invalidateDraw
import kotlinx.coroutines.flow.collectLatest
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selectableGroup
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.gestures.animateScrollBy
import androidx.compose.foundation.gestures.scrollBy
import kotlinx.coroutines.flow.first
import androidx.compose.animation.core.calculateTargetValue
import androidx.compose.animation.core.animateTo
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
        .outline(1.dp, tint?.copy(alpha = 0.7f) ?: J.line, J.pill), contentAlignment = Alignment.Center) {
        Icon(icon, contentDescription = null, tint = tint ?: J.muted, modifier = Modifier.size(22.dp))
    }
}

/** border() drawn as a stroke. Compose draws a cut corner border (Industrial) through a bitmap
 *  the size of the element, and a 3060 line code block asked for 210 MB: the app died (25 Oct).
 *  Inset by half the width, as border() is, so a clip to the same shape keeps all of it. */
fun Modifier.outline(width: androidx.compose.ui.unit.Dp, color: Color, shape: androidx.compose.ui.graphics.Shape) =
    drawWithCache {
        val w = width.toPx()
        val inner = shape.createOutline(androidx.compose.ui.geometry.Size(size.width - w, size.height - w), layoutDirection, this)
        onDrawWithContent {
            drawContent()
            translate(w / 2, w / 2) { drawOutline(inner, color, style = androidx.compose.ui.graphics.drawscope.Stroke(w)) }
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
 *  swipe; it is read while drawing, so a swipe redraws the pill and nothing else. A tap moves it
 *  as the tab bar does, with weight (258, Tabs): it leans, travels, hits its tab and squashes, the
 *  word punches in, a finger sinks it; each word takes its ink as the light covers it. A tap ticks
 *  at once, a swipe as it crosses into a page. It jumps with animations off. */
@Composable
fun Segmented(options: List<String>, selected: Int, position: (() -> Float)? = null, modifier: Modifier = Modifier,
              onSelect: (Int) -> Unit) {
    androidx.compose.foundation.layout.BoxWithConstraints(modifier.fillMaxWidth()) {
    val labelStyle = J.sec.copy(fontWeight = J.ts.fontWeight)
    val pillShape = J.pill
    val textSize = rememberRowSize(options, labelStyle, (maxWidth - J.sp1 * (options.size + 1)) / options.size - J.sp1 * 2)
    val still = stillMotion()
    val light = rememberTabLight(selected)
    val scope = androidx.compose.runtime.rememberCoroutineScope()
    val haptic = androidx.compose.ui.platform.LocalHapticFeedback.current
    val pending = remember { arrayOfNulls<Int>(1) }
    val glide = remember { arrayOfNulls<kotlinx.coroutines.Job>(1) }
    val first = remember { booleanArrayOf(true) }
    LaunchedEffect(selected) {
        if (first[0]) { first[0] = false; return@LaunchedEffect }
        // A swipe ticks as it crosses into a page; a tap ticked at once and its way stays quiet
        val (tick, left) = Tabs.change(pending[0], selected)
        pending[0] = left
        if (tick && position != null) haptic.performHapticFeedback(Tabs.tick)
        if (position == null) light.go(selected, options.size - 1, still)
    }
    val at = { if (position != null && !light.gliding) position() else light.pos.value }
    val presses = remember(options.size) { List(options.size) { androidx.compose.foundation.interaction.MutableInteractionSource() } }
    val held = presses.map { it.collectIsPressedAsState().value }.any { it }
    LaunchedEffect(held) { light.press(held, still) }
    val tap = { i: Int ->
        if (i != selected) {
            haptic.performHapticFeedback(Tabs.tick)
            pending[0] = i
            // Over a pager the tap's glide draws the light while the pages slide on the same timing
            if (position != null) {
                glide[0]?.cancel()
                glide[0] = scope.launch {
                    light.pos.snapTo(position())
                    light.gliding = true
                    try { light.go(i, options.size - 1, still) } finally { light.gliding = false }
                }
            }
        }
        onSelect(i)
    }
    Row(Modifier.fillMaxWidth().glass(J.pill).padding(J.sp1).drawBehind {
            val gap = J.sp1.toPx()
            val w = (size.width - gap * (options.size - 1)) / options.size
            // The light in the pill token's own shape, round or cut (22d: it stayed round with
            // Industrial); outlined, a 1 dp accent line drawn inside the light's bounds
            drawTabLight(light, at(), androidx.compose.ui.geometry.Size(w, size.height), w + gap, false, pillShape) { o ->
                if (J.outline) drawOutline(o, J.acc, style = androidx.compose.ui.graphics.drawscope.Stroke(1.dp.toPx()))
                else drawOutline(o, J.text)
            }
        },
        horizontalArrangement = Arrangement.spacedBy(J.sp1)) {
        options.forEachIndexed { i, label ->
            val on = i == selected
            // The word takes the light's ink as the light covers it (Tabs.ink), read while drawing
            val ink = if (J.outline) J.accText else J.bg
            Box(Modifier.weight(1f).heightIn(min = J.tap).clip(J.pill)
                .clickable(presses[i], indication = androidx.compose.foundation.LocalIndication.current, role = Role.Tab) { tap(i) }
                .semantics { this.selected = on }, contentAlignment = Alignment.Center) {  // TalkBack says which is on (223b)
                androidx.compose.foundation.text.BasicText(label, style = labelStyle.copy(fontSize = textSize),
                    color = { androidx.compose.ui.graphics.lerp(J.muted, ink, Tabs.ink(at(), i)) },
                    maxLines = 1, softWrap = false, modifier = Modifier.padding(horizontal = J.sp1)
                        .graphicsLayer { light.scaleOf(i).let { scaleX = it; scaleY = it } })
            }
        }
    }
    }
}

/** The wheel picker (251): a secondary control, one level under the tabs (Material 3: secondary
 *  tabs separate content inside a destination), as tall as SmallPill (J.small), its touch area
 *  widened by Compose without a gap. No track, the picked word under the tabs' light (filled, or
 *  outlined with Look and feel's option) in 14 sp, its
 *  neighbours half hidden by the same fade on both sides. A roll that stops settles the nearest word in the middle
 *  and picks it; a flick lands on a word (centre snap) and each word passing the middle ticks, as
 *  a real picker does. A tap on a word rolls it in, the visible way beside the swipe. [vertical] is
 *  one word in the light for a tight spot (the chat box, my note 26 Oct: no neighbours there): a
 *  swipe up or down steps one, a tap steps to the next; the caller gives its size. Inside the Feed's
 *  pager the drag stays with the strip (KeepSideways). [counts], if given, stand beside the words. */
@Composable
fun WheelPicker(words: List<String>, selected: Int, modifier: Modifier = Modifier, counts: List<Int?>? = null,
                vertical: Boolean = false, onSelect: (Int) -> Unit) {
    val n = words.size
    if (n == 0) return
    // A fixed row with ends; only the chat's one word wheel loops, started in its middle
    val slots = Wheel.slots(n, vertical)
    val loop = slots > n
    val state = remember(n) { androidx.compose.foundation.lazy.LazyListState(if (loop) Wheel.LOOP / 2 * n + selected else 0) }
    val still = stillMotion()
    val pick by androidx.compose.runtime.rememberUpdatedState(onSelect)
    val now by androidx.compose.runtime.rememberUpdatedState(selected)
    // The word in the middle while it rolls, so the colours follow the finger
    val middle by remember { androidx.compose.runtime.derivedStateOf { wheelMiddle(state) } }
    val rolling = remember { booleanArrayOf(false) }
    // A pick from outside (a tap, a notification's filter) rolls to it; the first one jumps
    val first = remember { booleanArrayOf(true) }
    // A tick each time a new word reaches the middle, not on the first placing (Wheel.tick)
    val haptic = androidx.compose.ui.platform.LocalHapticFeedback.current
    val ticked = remember { arrayOfNulls<Int>(1) }
    LaunchedEffect(middle) {
        if (Wheel.tick(ticked[0], middle, first[0])) haptic.performHapticFeedback(androidx.compose.ui.hapticfeedback.HapticFeedbackType.SegmentFrequentTick)
        if (!first[0] && middle != null) ticked[0] = middle
    }
    val pop = remember { androidx.compose.animation.core.Animatable(1f) }
    LaunchedEffect(selected, state) {
        androidx.compose.runtime.snapshotFlow { state.layoutInfo.totalItemsCount }.first { it > 0 }
        // Cleared in finally: a flick that cut a roll short left them set, and the wheel never
        // centred or picked again (found flicking back and forth, my note 26 Oct)
        rolling[0] = true
        val placing = first[0]
        try {
            val to = if (!loop) selected else Wheel.closest(wheelMiddle(state) ?: state.firstVisibleItemIndex, selected, n)
            wheelRoll(state, to, still || first[0])
        } finally {
            if (first[0]) ticked[0] = wheelMiddle(state)
            first[0] = false; rolling[0] = false
        }
        // The pick has landed: the light swells and springs back, so it reads as made (Wheel.POP)
        if (!placing && !still) {
            pop.animateTo(Wheel.POP, androidx.compose.animation.core.tween(90, easing = J.ease))
            pop.animateTo(1f, Wheel.pop)
        }
    }
    // A roll by hand: the fling lands on a word in one motion (WheelFling), then that word is picked
    LaunchedEffect(state) {
        androidx.compose.runtime.snapshotFlow { state.isScrollInProgress }.collect { moving ->
            if (moving || rolling[0] || first[0]) return@collect
            val slot = wheelMiddle(state) ?: return@collect
            val i = Wheel.real(slot, n)
            if (i != now) pick(i) else if (kotlin.math.abs(wheelOffset(state, slot) ?: 0f) > 1f) {
                // A flick that cuts this roll short cancels the scroll, not this loop: let it through
                // and the loop ended, so the wheel never picked again (found flicking, 26 Oct)
                rolling[0] = true
                try { wheelRoll(state, slot, still) }
                catch (e: kotlinx.coroutines.CancellationException) { if (!kotlinx.coroutines.currentCoroutineContext().isActive) throw e }
                finally { rolling[0] = false }
            }
        }
    }
    val context = androidx.compose.ui.platform.LocalContext.current
    val density = androidx.compose.ui.platform.LocalDensity.current
    val pillShape = J.pill
    // Counted after the touch slop, so 12 dp more is a short flick, not a precise one
    val reach = with(androidx.compose.ui.platform.LocalDensity.current) { J.sp3.toPx() }
    // Quiet ticks past each end, so a side never looks empty, a word's room away from the end word;
    // those at a pulled end spread with the pull, as a stretched spring (Wheel.spread)
    val ticks: androidx.compose.ui.graphics.drawscope.DrawScope.(Float, Float) -> Unit = { pull, limit ->
        val info = state.layoutInfo
        val seen = info.visibleItemsInfo
        val r = J.sp1.toPx() / 2; val gap = J.sp3.toPx()
        val off = J.sp1.toPx() + J.sp3.toPx() + gap + r
        fun dots(cx: Float, side: Float) {
            val g = gap * if (pull * side < 0f) Wheel.spread(pull, limit) else 1f
            for (k in -1..1) drawCircle(J.faint, r, androidx.compose.ui.geometry.Offset(cx + side * (k + 1) * g - side * gap, size.height / 2))
        }
        seen.firstOrNull { it.index == 0 }?.let { dots(it.offset - info.viewportStartOffset - off, -1f) }
        seen.firstOrNull { it.index == info.totalItemsCount - 1 }?.let { dots(it.offset + it.size - info.viewportStartOffset + off, 1f) }
    }
    val ends = remember(state, still) { WheelEnds(state, still, ticks) }
    val endsScope = androidx.compose.runtime.rememberCoroutineScope()
    androidx.compose.runtime.SideEffect { ends.scope = endsScope }
    val fling = remember(state, density, n) {
        WheelFling(state, density, android.view.ViewConfiguration.get(context).scaledMinimumFlingVelocity * 4f, n) { ends.kick(it) }
    }
    // Where the light should be, from where the words are: [left, right, how big the middle word
    // draws, the light's width gathered on the nearest word]. Between the two words round the middle
    // its edges go by Wheel.edges, so it stretches across and gathers; each word's extent as it
    // draws (Wheel.magnify); past an end it leans toward the pull, the edge on that side with the
    // word, the other lagging, never over the ticks (Liquid Glass; my notes 26 Oct)
    val clear = with(density) { (J.sp1 + J.sp3 - J.sp2).toPx() }
    val speed = remember { androidx.compose.runtime.mutableFloatStateOf(0f) }
    fun lightTarget(): FloatArray? {
        val info = state.layoutInfo
        val mid = (info.viewportStartOffset + info.viewportEndOffset) / 2f
        val seen = info.visibleItemsInfo
        val a = seen.lastOrNull { it.offset + it.size / 2f <= mid } ?: seen.firstOrNull() ?: return null
        val b = seen.firstOrNull { it.index == a.index + 1 } ?: a
        val ca = a.offset + a.size / 2f; val cb = b.offset + b.size / 2f
        val t = if (b === a) 0f else ((mid - ca) / (cb - ca)).coerceIn(0f, 1f)
        // Elastic on a slow move, straight across on a fast one (Wheel.calm)
        val s = speed.floatValue
        val calm = if (still) 0f else Wheel.calm(s)
        val el = Wheel.edges(t)
        val e = (t + (el.first - t) * calm) to (t + (el.second - t) * calm)
        val step = (cb - ca).takeIf { it > 0f } ?: a.size.toFloat()
        val ma = Wheel.magnify((ca - mid) / step); val mb = Wheel.magnify((cb - mid) / step)
        val start = info.viewportStartOffset
        var left = (ca - a.size / 2f * ma) + ((cb - b.size / 2f * mb) - (ca - a.size / 2f * ma)) * e.first - start
        var right = (ca + a.size / 2f * ma) + ((cb + b.size / 2f * mb) - (ca + a.size / 2f * ma)) * e.second - start
        // Fast, it streaks along the motion, mostly ahead: later words come from the right
        // The light's own width, blended from word to word: switched at halfway, the streak jumped
        val rest = a.size * ma + (b.size * mb - a.size * ma) * t
        val streak = if (still) 0f else Wheel.streak(s) * rest
        if (s > 0f) { right += streak * 0.7f; left -= streak * 0.3f } else if (s < 0f) { left -= streak * 0.7f; right += streak * 0.3f }
        // The lean only at the end being pulled: a pull still settling after a flick back into the
        // list leaned against the wrong word and squeezed the light to a dot (found on video). Away
        // from an end the light just goes with the words while the pull settles
        val p = ends.now
        if (p < 0f && a.index == info.totalItemsCount - 1) { left += p; right = minOf(right + p * 0.3f, a.offset + a.size - start + p + clear) }
        else if (p > 0f && a.index == 0 && t == 0f) { right += p; left = maxOf(left + p * 0.3f, a.offset - start + p - clear) }
        else { left += p; right += p }
        return floatArrayOf(left, right, ma + (mb - ma) * (e.first + e.second) / 2, rest)
    }
    // How fast the strip goes, in words a second, smoothed over about 80 ms: measured each frame
    // only while it moves, back to 0 once still. Slow, the light is elastic; fast, it streaks
    if (!vertical && n > 1) LaunchedEffect(state) {
        var lastF = Float.NaN
        var lastT = 0L
        while (true) {
            androidx.compose.runtime.withFrameNanos { now ->
                val f = wheelPlace(state)
                if (f != null && !lastF.isNaN() && lastT != 0L) {
                    val dt = ((now - lastT) / 1e9f).coerceIn(0.001f, 0.1f)
                    val k = 1f - kotlin.math.exp(-dt / 0.08f)
                    speed.floatValue += ((f - lastF) / dt - speed.floatValue) * k
                }
                lastF = f ?: Float.NaN; lastT = now
            }
            if (!state.isScrollInProgress && kotlin.math.abs(speed.floatValue) < 0.05f) {
                speed.floatValue = 0f
                androidx.compose.runtime.snapshotFlow { state.isScrollInProgress }.first { it }
                lastF = Float.NaN; lastT = 0L
            }
        }
    }
    // A pull left by a touch that never became a drag springs back once the strip is still; a new
    // drag cancels the spring
    if (!vertical) LaunchedEffect(ends) {
        androidx.compose.runtime.snapshotFlow { state.isScrollInProgress || !ends.pulled }.collectLatest { busy ->
            if (!busy && !ends.bouncing) ends.settle(0f)
        }
    }
    androidx.compose.foundation.layout.BoxWithConstraints(modifier.then(if (vertical) Modifier else Modifier.fillMaxWidth())
        // One word, one step a swipe: no precise swipe needed (my note 26 Oct)
        .then(if (!vertical) Modifier else Modifier.pointerInput(n) {
            var moved = 0f
            detectVerticalDragGestures(onDragStart = { moved = 0f },
                onDragEnd = { Wheel.step(now, n, moved, reach).let { if (it != now) pick(it) } }) { _, dy -> moved += dy }
        })
        // Room for the light to swell: at the bottom of a screen the tab bar's band covered its lower edge
        .then(if (vertical) Modifier else Modifier.padding(vertical = J.sp1))
        .drawBehind {
            // The light where its edges are (lightTarget, followed by springs), thinner while
            // stretched (Wheel.squash), as big as the word it holds, and swelling for a moment when a
            // pick lands (pop). Still motion: a plain slide
            val tall = this.size.height
            var mag = 1f
            var stretch = 0f
            val box = if (vertical || n == 1) {
                val c = state.layoutInfo.visibleItemsInfo.firstOrNull() ?: return@drawBehind
                val w = if (vertical) this.size.width else c.size.toFloat()
                (this.size.width - w) / 2 to w
            } else {
                // Drawn straight from where the words are, so it never lags them
                val tg = lightTarget() ?: return@drawBehind
                mag = tg[2]
                stretch = (tg[1] - tg[0]) / tg[3].coerceAtLeast(1f) - 1f
                tg[0] to tg[1] - tg[0]
            }
            val grow = pop.value
            val size = androidx.compose.ui.geometry.Size(box.second * grow, tall * mag * Wheel.squash(stretch) * grow)
            translate(left = box.first - (size.width - box.second) / 2, top = (tall - size.height) / 2) {
                // In the chat box the mode is a tile like the send button beside it, not a picked tab
                if (vertical) drawOutline(pillShape.createOutline(size, layoutDirection, this), J.raise)
                else if (J.outline) {
                    // The line inside the light's own box, so no half of it falls outside
                    val w = 1.dp.toPx()
                    translate(w / 2, w / 2) {
                        drawOutline(pillShape.createOutline(androidx.compose.ui.geometry.Size(size.width - w, size.height - w), layoutDirection, this),
                            J.acc, style = androidx.compose.ui.graphics.drawscope.Stroke(w))
                    }
                }
                else drawOutline(pillShape.createOutline(size, layoutDirection, this), J.text)
            }
            // One word in view: a column of dots says where it stands and that more are there, as a
            // pager's indicator does, so the tile reads as a wheel to swipe, not a button (my note 26 Oct)
            if (vertical) {
                val dot = J.sp1.toPx()
                val on = Wheel.real(middle ?: selected, n)
                val top = (this.size.height - dot * (2 * n - 1)) / 2
                for (k in 0 until n) drawCircle(if (k == on) J.accText else J.faint, dot / 2,
                    androidx.compose.ui.geometry.Offset(J.sp2.toPx() + dot / 2, top + dot / 2 + k * dot * 2))
            }
        }) {
        val mask = Modifier
            .graphicsLayer { compositingStrategy = androidx.compose.ui.graphics.CompositingStrategy.Offscreen }
            .drawWithContent {
                drawContent()
                // Symmetric, from the words' own sizes: the middle one whole, the fade ends at the
                // middle of each neighbour, so their outer halves are gone at any strip size
                val seen = state.layoutInfo.visibleItemsInfo
                val c = seen.firstOrNull { it.index == middle } ?: return@drawWithContent
                val near = seen.filter { kotlin.math.abs(it.index - c.index) == 1 }.map { it.size }
                val whole = c.size / 2f + if (vertical) 0f else J.sp1.toPx()
                val fade = (near.ifEmpty { listOf(c.size) }.average().toFloat() / 2f).coerceAtLeast(1f)
                val w = if (vertical) size.height else size.width
                fun at(x: Float) = (x / w).coerceIn(0f, 1f)
                val stops = arrayOf(at(w / 2 - whole - fade) to Color.Transparent, at(w / 2 - whole) to Color.Black,
                    at(w / 2 + whole) to Color.Black, at(w / 2 + whole + fade) to Color.Transparent)
                drawRect(if (vertical) androidx.compose.ui.graphics.Brush.verticalGradient(*stops)
                         else androidx.compose.ui.graphics.Brush.horizontalGradient(*stops),
                    blendMode = androidx.compose.ui.graphics.BlendMode.DstIn)
            }.semantics { selectableGroup() }
        val word = @Composable { slot: Int ->
            val i = Wheel.real(slot, n)
            val lit = middle?.let { it == slot } ?: (i == selected)
            // The same words as Segmented: dark on the filled light, the readable accent on the outline
            val ink = if (!lit) J.muted else if (vertical || J.outline) J.accText else J.bg
            val style = J.cap
            Row(Modifier.then(if (vertical) Modifier.fillMaxWidth().height(maxHeight) else Modifier.height(J.small).graphicsLayer {
                    // The middle word a little bigger, by where it stands now (Wheel.magnify), no relayout
                    val info = state.layoutInfo
                    val item = info.visibleItemsInfo.firstOrNull { it.index == slot }
                    val m = if (item == null) 1f else Wheel.magnify((item.offset + item.size / 2f -
                        (info.viewportStartOffset + info.viewportEndOffset) / 2f) / (item.size + J.sp1.toPx()))
                    scaleX = m; scaleY = m
                })
                .clip(J.pill).clickable(role = Role.Tab) { pick(if (vertical) (i + 1) % n else i) }
                .clearAndSetSemantics {
                    contentDescription = Wheel.say(words[i] + (counts?.getOrNull(i)?.let { " $it" } ?: ""), i, words.size)
                    this.selected = i == selected; role = Role.Tab
                }.padding(start = if (vertical) J.sp5 else J.sp3, end = J.sp3),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
                Text(words[i], style = style.copy(color = ink, fontWeight = J.ts.fontWeight), maxLines = 1, softWrap = false)
                counts?.getOrNull(i)?.let {
                    Text(" $it", style = J.monoCap.copy(color = if (lit) ink else J.faint), maxLines = 1, softWrap = false)
                }
            }
        }
        if (vertical) androidx.compose.foundation.lazy.LazyColumn(Modifier.fillMaxSize().semantics { selectableGroup() },
            state = state, userScrollEnabled = false, horizontalAlignment = Alignment.CenterHorizontally) { items(slots) { word(it) } }
        else {
          val reachPx = with(density) { (maxWidth / 4).toPx() }
          androidx.compose.runtime.SideEffect { ends.limit = reachPx }
          androidx.compose.foundation.lazy.LazyRow(Modifier.fillMaxWidth().height(J.small).nestedScroll(KeepSideways).then(mask),
            state = state, contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = if (loop) 0.dp else maxWidth / 2),
            flingBehavior = fling, overscrollEffect = ends,
            horizontalArrangement = Arrangement.spacedBy(J.sp1), verticalAlignment = Alignment.CenterVertically) {
            items(slots) { word(it) }
          }
        }
    }
}

/** The wheel's ends (my note 26 Oct): a fixed row, not an endless loop, as iOS's picker is for what
 *  is not cyclic. A drag scrolls until an end word stands in the middle; past that the strip
 *  follows the finger less and less (Wheel.rubber) and springs back when let go, and a flick into
 *  an end bounces. The ticks past each end move with the strip. Still motion: no spring, it snaps */
private class WheelEnds(val state: androidx.compose.foundation.lazy.LazyListState, val still: Boolean,
                        val ticks: androidx.compose.ui.graphics.drawscope.DrawScope.(Float, Float) -> Unit) :
    androidx.compose.foundation.OverscrollEffect {
    /** How far a pull may go, a quarter of the strip; set by the wheel once it is measured */
    var limit = 1f
    private val pullState = androidx.compose.runtime.mutableFloatStateOf(0f)
    /** The pull now, read by the light, which stretches toward it */
    val now get() = pullState.floatValue
    private var pull: Float
        get() = pullState.floatValue
        set(v) { pullState.floatValue = v; if (node.isAttached) node.invalidateDraw() }
    override val isInProgress get() = pull != 0f
    val pulled get() = pull != 0f

    /** How far the strip may scroll by [dx] before an end word stands in the middle */
    private fun room(dx: Float): Float {
        val info = state.layoutInfo
        val mid = (info.viewportStartOffset + info.viewportEndOffset) / 2f
        val seen = info.visibleItemsInfo
        fun centre(i: androidx.compose.foundation.lazy.LazyListItemInfo) = i.offset + i.size / 2f
        val end = if (dx > 0) seen.firstOrNull { it.index == 0 }?.let { mid - centre(it) }
                  else seen.firstOrNull { it.index == info.totalItemsCount - 1 }?.let { centre(it) - mid }
        return end?.coerceAtLeast(0f) ?: Float.MAX_VALUE
    }

    override fun applyToScroll(delta: androidx.compose.ui.geometry.Offset,
                               source: androidx.compose.ui.input.nestedscroll.NestedScrollSource,
                               performScroll: (androidx.compose.ui.geometry.Offset) -> androidx.compose.ui.geometry.Offset): androidx.compose.ui.geometry.Offset {
        var rest = delta.x
        var used = 0f
        // Back toward rest first: a pull is undone before the strip scrolls again
        if (pull != 0f && rest * pull < 0f) {
            val take = if (kotlin.math.abs(rest) >= kotlin.math.abs(pull)) -pull else rest
            pull += take; rest -= take; used += take
        }
        if (rest != 0f) {
            val can = room(rest)
            val done = performScroll(androidx.compose.ui.geometry.Offset(rest.coerceIn(-can, can), 0f)).x
            rest -= done; used += done
        }
        if (rest != 0f && source == androidx.compose.ui.input.nestedscroll.NestedScrollSource.UserInput) {
            pull = Wheel.rubber(pull, rest, limit); used += rest
        }
        return androidx.compose.ui.geometry.Offset(used, 0f)
    }

    override suspend fun applyToFling(velocity: androidx.compose.ui.unit.Velocity,
                                      performFling: suspend (androidx.compose.ui.unit.Velocity) -> androidx.compose.ui.unit.Velocity) {
        // A pull under a pixel, left by a settle a touch cut short, is none: it made the next fling
        // spend all its speed on a bounce mid-list (found on video, 26 Oct)
        if (kotlin.math.abs(pull) < 1f) pull = 0f
        if (pull != 0f) {
            // Let go past an end: spring back, with a quarter of the speed if it goes into the end
            // (all of it threw the strip to the limit), as the fling's bounce; a flick away from the
            // end springs back and flings at once
            if (velocity.x * pull > 0f) { settle(velocity.x / 4); return }
            kotlinx.coroutines.coroutineScope {
                launch { settle(0f) }
                performFling(velocity)
            }
            return
        }
        // performFling answers what was used, not what is left; the wheel's own fling bounces at an
        // end (kick), since KeepSideways takes what is left so the pager does not page
        val left = velocity.x - performFling(velocity).x
        if (kotlin.math.abs(left) > 1f) settle(left)
    }

    /** A flick into an end: the bounce runs on its own, so the fling ends and picks at once */
    var scope: kotlinx.coroutines.CoroutineScope? = null
    private var bounce: kotlinx.coroutines.Job? = null
    val bouncing get() = bounce?.isActive == true
    fun kick(v: Float) { bounce?.cancel(); bounce = scope?.launch { settle(v) } }

    suspend fun settle(v: Float) {
        if (still) { pull = 0f; return }
        androidx.compose.animation.core.animate(pull, 0f, v,
            androidx.compose.animation.core.spring(stiffness = androidx.compose.animation.core.Spring.StiffnessMediumLow)) { value, _ ->
            pull = value.coerceIn(-limit, limit)
        }
    }

    inner class Shift : Modifier.Node(), androidx.compose.ui.node.DrawModifierNode {
        override fun androidx.compose.ui.graphics.drawscope.ContentDrawScope.draw() {
            val scope = this
            translate(left = pull) { scope.drawContent(); ticks(pull, limit) }
        }
    }
    override val node: Shift = Shift()
}

private fun wheelMiddle(state: androidx.compose.foundation.lazy.LazyListState): Int? {
    val info = state.layoutInfo
    return Wheel.nearest(info.visibleItemsInfo.map { it.index to it.offset + it.size / 2f },
        (info.viewportStartOffset + info.viewportEndOffset) / 2f)
}

/** Where the middle stands in words, between two while the strip rolls; null when empty */
private fun wheelPlace(state: androidx.compose.foundation.lazy.LazyListState): Float? {
    val info = state.layoutInfo
    val mid = (info.viewportStartOffset + info.viewportEndOffset) / 2f
    val seen = info.visibleItemsInfo
    fun centre(i: androidx.compose.foundation.lazy.LazyListItemInfo) = i.offset + i.size / 2f
    val a = seen.lastOrNull { centre(it) <= mid } ?: return seen.firstOrNull()?.index?.toFloat()
    val b = seen.firstOrNull { it.index == a.index + 1 } ?: return a.index.toFloat()
    return a.index + (mid - centre(a)) / (centre(b) - centre(a))
}

/** How far slot [i]'s centre sits from the middle, negative before it; null when out of view */
private fun wheelOffset(state: androidx.compose.foundation.lazy.LazyListState, i: Int): Float? {
    val info = state.layoutInfo
    val item = info.visibleItemsInfo.firstOrNull { it.index == i } ?: return null
    return item.offset + item.size / 2f - (info.viewportStartOffset + info.viewportEndOffset) / 2f
}

/** One flick, one motion: a free decay says how far the flick would carry, Wheel.landing turns
 *  that into a word (at least one for a real flick), and one spring takes the strip there from the
 *  finger's own speed, as Compose's snap fling does; no stop and second glide. It lands on a word
 *  in view, so the distance is exact */
private class WheelFling(val state: androidx.compose.foundation.lazy.LazyListState,
                         val density: androidx.compose.ui.unit.Density, val minVelocity: Float, val count: Int,
                         val bounce: (Float) -> Unit) :
    androidx.compose.foundation.gestures.FlingBehavior {
    override suspend fun androidx.compose.foundation.gestures.ScrollScope.performFling(initialVelocity: Float): Float {
        val info = state.layoutInfo
        val seen = info.visibleItemsInfo
        if (seen.isEmpty()) return initialVelocity
        val mid = (info.viewportStartOffset + info.viewportEndOffset) / 2f
        fun centre(i: androidx.compose.foundation.lazy.LazyListItemInfo) = i.offset + i.size / 2f
        val near = seen.minBy { kotlin.math.abs(centre(it) - mid) }
        val step = if (seen.size > 1) (centre(seen.last()) - centre(seen.first())) / (seen.size - 1) else near.size.toFloat()
        val travel = androidx.compose.animation.splineBasedDecay<Float>(density).calculateTargetValue(0f, initialVelocity)
        val want = Wheel.landing(near.index, travel - (centre(near) - mid), step, initialVelocity, minVelocity, count)
        val to = want.coerceIn(seen.first().index, seen.last().index)
        val delta = centre(seen.first { it.index == to }) - mid
        var done = 0f
        androidx.compose.animation.core.AnimationState(0f, Wheel.landingSpeed(initialVelocity, delta)).animateTo(delta, Wheel.settle) {
            scrollBy(value - done); done = value
        }
        // Flung into an end: it bounces with a quarter of the speed (half swung 275 px), the strip moving the other way to the
        // scroll. Only at a real end: a hard fling mid-list wants past the words in view too
        val end = (want < 0 && to == 0) || (want > info.totalItemsCount - 1 && to == info.totalItemsCount - 1)
        if (end) bounce(-initialVelocity / 4)
        return 0f
    }
}

private suspend fun wheelRoll(state: androidx.compose.foundation.lazy.LazyListState, i: Int, jump: Boolean) {
    if (i !in 0 until state.layoutInfo.totalItemsCount) return
    if (state.layoutInfo.visibleItemsInfo.none { it.index == i }) state.scrollToItem(i)
    val info = state.layoutInfo
    val item = info.visibleItemsInfo.firstOrNull { it.index == i } ?: return
    val delta = item.offset + item.size / 2f - (info.viewportStartOffset + info.viewportEndOffset) / 2f
    if (jump) state.scrollBy(delta)
    else state.animateScrollBy(delta, androidx.compose.animation.core.tween(240, easing = J.ease))
}

/** The app's switch (F1, D1): every colour from the theme, so no Material lavender shows. It
 *  only shows the state; the row around it is the one TalkBack stop and takes the tap. */
@Composable
fun JulzSwitch(on: Boolean) {
    androidx.compose.material3.Switch(checked = on, onCheckedChange = null,
        colors = androidx.compose.material3.SwitchDefaults.colors(
            checkedThumbColor = J.onAcc, checkedTrackColor = J.acc, checkedBorderColor = J.acc,
            // Off: the thumb in muted grey, 3:1 and more on every theme, on a faint glass track
            uncheckedThumbColor = J.muted, uncheckedTrackColor = J.raise, uncheckedBorderColor = J.faint))
}

/** The app's slider (F1, D1): the accent for the part chosen, a hairline for the rest, no tick dots. */
@Composable
fun JulzSlider(value: Float, onChange: (Float) -> Unit, range: ClosedFloatingPointRange<Float>, steps: Int,
               onDone: () -> Unit) {
    androidx.compose.material3.Slider(value = value, onValueChange = onChange, onValueChangeFinished = onDone,
        valueRange = range, steps = steps, modifier = Modifier.heightIn(min = J.tap),
        colors = androidx.compose.material3.SliderDefaults.colors(thumbColor = J.acc, activeTrackColor = J.acc,
            inactiveTrackColor = J.lineStrong, activeTickColor = Color.Transparent, inactiveTickColor = Color.Transparent))
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

/** A ghost row at the end of a list that turns into a field in place (223c; Trello's + Add a
 *  card, Things' New To-Do): shaped like the list's rows, a + and the label; tapped, a focused
 *  field with Add. Enter adds and stays open for the next one; an empty field closes when it
 *  loses focus or on Back. The draft is the caller's, so it outlives a tab switch and reopens. */
@Composable
fun InlineAdd(label: String, draft: String, onDraft: (String) -> Unit, enabled: Boolean, max: Int = 120,
              onAdd: (String) -> Unit) {
    var open by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(draft.isNotEmpty()) }
    if (draft.isNotEmpty()) open = true
    fun add() { draft.trim().takeIf { it.isNotEmpty() }?.let { onAdd(it); onDraft("") } }
    if (!open) {
        Row(Modifier.fillMaxWidth().heightIn(min = J.tap).clip(J.rM).border(1.dp, J.line, J.rM)
            .clickable(role = Role.Button, enabled = enabled) { open = true }.padding(horizontal = J.sp3),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
            Text("+", style = J.sec.copy(color = J.accText, fontWeight = androidx.compose.ui.text.font.FontWeight(600)), modifier = Modifier.clearAndSetSemantics { })  // TalkBack: just the label
            Text(label, style = J.sec.copy(color = J.muted))
        }
        return
    }
    val focus = remember { androidx.compose.ui.focus.FocusRequester() }
    var focused by remember { mutableStateOf(false) }
    androidx.activity.compose.BackHandler(enabled = draft.isBlank()) { open = false }
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
        androidx.compose.material3.OutlinedTextField(draft, { if (it.length <= max) onDraft(it) },
            Modifier.weight(1f).keepsKeyboard().focusRequester(focus).onFocusChanged {
                if (focused && !it.isFocused && draft.isBlank()) open = false
                focused = it.isFocused
            },
            label = { Text(label) }, singleLine = true, enabled = enabled, colors = fieldColors(), shape = fieldShape(oneLine = true),
            textStyle = J.bodyText,
            keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Done,
                capitalization = androidx.compose.ui.text.input.KeyboardCapitalization.Sentences),
            keyboardActions = androidx.compose.foundation.text.KeyboardActions(onDone = { add() }))
        Box(Modifier.keepsKeyboard()) { Pill("Add", false, enabled && draft.isNotBlank()) { add() } }  // the next one follows (228)
    }
    LaunchedEffect(Unit) { if (draft.isEmpty()) focus.requestFocus() }
}

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
 *  slides away instead of stopping at a hard edge (found 2026-10-18 on Goals). The page itself,
 *  glows and all: into flat J.bg it was a dark strip across the cyan glow (257) */
@Composable
fun androidx.compose.foundation.layout.BoxScope.FadeBottom() {
    Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(28.dp).pageBackdrop(fade = true))
}
