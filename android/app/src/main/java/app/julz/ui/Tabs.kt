package app.julz.ui

import androidx.compose.animation.core.Animatable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.geometry.center
import androidx.compose.ui.graphics.drawscope.scale
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import kotlinx.coroutines.launch

/** The primary level's motion (258): the tabs (Segmented) and the tab bar. One motion language
 *  with the wheels, the other weight: the wheels stretch, magnify and pop, a destination moves as
 *  something heavy (my pick 26 Oct, weight and impact, after the firm spring looked too static).
 *  The light leans back a hair, travels and arrives still moving, hits its tab and squashes
 *  against it, then settles with no bounce; the arriving word punches in, and a press sinks it. */
object Tabs {
    /** The way there: sets off from rest, speeds up and arrives still moving (twice the mean speed),
     *  so the stop reads as a hit; no overshoot, the squash takes the speed (Tabs.squash) */
    val travel = androidx.compose.animation.core.CubicBezierEasing(0.45f, 0f, 0.75f, 0.5f)

    /** How long the way takes over [cells] tabs: longer the farther, as a heavier thing would */
    fun travelMs(cells: Float) = (170 + 45 * kotlin.math.abs(cells)).toInt().coerceAtMost(380)

    /** The lean before the way, in cells: a hair against it, as a weight gathers itself. Tab [last]
     *  is the row's end: past an end it leans only END_LEAN, inside the bar's padding */
    const val LEAN_MS = 70
    const val END_LEAN = 0.03f
    fun lean(from: Float, to: Float, last: Int, give: Float = 1f) =
        (from - kotlin.math.sign(to - from) * 0.06f * give).coerceIn(-END_LEAN, last + END_LEAN) - from

    /** The hit: in fast, out on a fully damped spring, so it settles without a bounce */
    const val HIT_MS = 45
    val recover = androidx.compose.animation.core.spring<Float>(dampingRatio = 1f, stiffness = 700f)

    /** The light's scale (along the way, across it) at [impact], 0 at rest, 1 at the hit: shorter
     *  along, a little fuller across, so it keeps its volume roughly */
    fun squash(impact: Float, give: Float = 1f) = (1f - 0.09f * impact * give) to (1f + 0.045f * impact * give)

    /** How much of the squash, the lean and the punch a row gives, from its cell's width along the
     *  way and [ref], about a tab bar cell (Tabs.REF): all of it up to that width, less on wider
     *  cells, so they move about as many pixels (my note 26 Oct: Todos' wide tabs looked liquid) */
    val REF get() = J.row  // a tab bar cell is a little under a row's height
    fun give(cellPx: Float, refPx: Float) = (refPx / cellPx).coerceAtMost(1f)

    /** The arriving word or icon starts this much smaller and grows to its size as the light lands */
    const val PUNCH = 0.9f
    fun punch(give: Float) = 1f - (1f - PUNCH) * give

    /** How far the light sinks while a finger is on a tab, the spring there and back (Material 3's
     *  fast effects spring, no bounce), and the least time it stays sunk, so a quick tap shows it */
    const val PRESS = 0.92f
    val press = androidx.compose.animation.core.spring<Float>(dampingRatio = 1f, stiffness = 3800f)
    const val MIN_PRESS_MS = 110L
    fun holdLeft(elapsedMs: Long) = (MIN_PRESS_MS - elapsedMs).coerceAtLeast(0L)

    /** How much of cell [i] the light covers with the light at [at] (in cells), 0 to 1: a word
     *  takes the light's ink as much as it is under it, so the colour moves with the light */
    fun ink(at: Float, i: Int) = (1f - kotlin.math.abs(at - i)).coerceIn(0f, 1f)

    /** The tab the light came to rest on at [at], if it is not [last], the one it rested on before:
     *  a swipe's landing, which hits as a tap's does */
    fun landed(last: Int, at: Float): Int? {
        val k = kotlin.math.round(at).toInt()
        return if (k != last && kotlin.math.abs(at - k) < 0.005f) k else null
    }

    /** The pick moved to [now] with a tap to [pending] on its way, or none: (tick?, what is still
     *  pending). A tap ticks itself at once, so its way and its end stay quiet; a change with nothing
     *  pending is a swipe crossing into a page, and ticks */
    fun change(pending: Int?, now: Int): Pair<Boolean, Int?> = when (pending) {
        null -> true to null
        now -> false to null
        else -> false to pending
    }

    /** One tick per change: between choices, so not a Confirm (Android's SEGMENT_TICK), the same
     *  as the wheel's (Wheel.tickType) */
    val tick = HapticFeedbackType.SegmentTick
}

/** The light of a row of tabs as it moves (Tabs): where it is in cells, the hit's squash and which
 *  way it came, the arriving cell's punch and the press's sink. Read while drawing */
internal class TabLight(start: Float) {
    val pos = Animatable(start)
    val impact = Animatable(0f)
    val arrival = Animatable(1f)
    val sink = Animatable(1f)
    var dir by mutableFloatStateOf(1f)
    var arriving by mutableIntStateOf(-1)
    /** The row's give (Tabs.give), set where it is drawn */
    var give = 1f

    /** The arriving cell's scale: [i] punches in, the rest stand at their size */
    fun scaleOf(i: Int) = if (i == arriving) arrival.value else 1f

    /** Lean, travel, hit, settle, in a row whose last tab is [last]. A new pick mid way carries on from where the light is, no lean */
    suspend fun go(to: Int, last: Int, still: Boolean) {
        val from = pos.value
        if (still) { pos.snapTo(to.toFloat()); return }
        if (kotlin.math.abs(to - from) < 0.001f) return
        dir = kotlin.math.sign(to - from)
        impact.snapTo(0f)
        arrival.snapTo(1f)
        if (kotlin.math.abs(from - kotlin.math.round(from)) < 0.01f)
            pos.animateTo(from + Tabs.lean(from, to.toFloat(), last, give), androidx.compose.animation.core.tween(Tabs.LEAN_MS,
                easing = androidx.compose.animation.core.FastOutSlowInEasing))
        pos.animateTo(to.toFloat(), androidx.compose.animation.core.tween(Tabs.travelMs(to - pos.value), easing = Tabs.travel))
        hit(to, dir)
    }

    /** The landing on [to], coming the way [way] (+1 along, -1 back): the squash and the punch.
     *  A tap's travel ends in it; over a pager, the page's landing calls it alone */
    suspend fun hit(to: Int, way: Float) {
        dir = way
        arriving = to
        kotlinx.coroutines.coroutineScope {
            launch {
                impact.animateTo(1f, androidx.compose.animation.core.tween(Tabs.HIT_MS))
                impact.animateTo(0f, Tabs.recover)
            }
            launch {
                arrival.snapTo(Tabs.punch(give))
                arrival.animateTo(1f, Tabs.recover)
            }
        }
    }

    /** Sinks while [held], and stays sunk at least Tabs.MIN_PRESS_MS after the press began */
    private var downAt = 0L
    suspend fun press(held: Boolean, still: Boolean) {
        if (still) return
        if (held) { downAt = System.currentTimeMillis(); sink.animateTo(Tabs.PRESS, Tabs.press) }
        else {
            kotlinx.coroutines.delay(Tabs.holdLeft(System.currentTimeMillis() - downAt))
            sink.animateTo(1f, Tabs.press)
        }
    }

    /** The hit's scale (x, y): shorter along the way it came, fuller across */
    fun squash(vertical: Boolean): Pair<Float, Float> {
        val (along, across) = Tabs.squash(impact.value, give)
        return if (vertical) across to along else along to across
    }
}

/** A row's tab light, kept across recompositions, started on [start] */
@androidx.compose.runtime.Composable
internal fun rememberTabLight(start: Int) = androidx.compose.runtime.remember { TabLight(start.toFloat()) }

/** Draws [light]'s shape at the light's place: [cell] is one tab's size, [step] the distance from
 *  one tab to the next, along x or, [vertical], along y. The hit squashes it against its leading
 *  edge, the press about its middle */
internal fun androidx.compose.ui.graphics.drawscope.DrawScope.drawTabLight(
    light: TabLight, at: Float, cell: androidx.compose.ui.geometry.Size, step: Float, vertical: Boolean,
    shape: androidx.compose.ui.graphics.Shape, draw: androidx.compose.ui.graphics.drawscope.DrawScope.(androidx.compose.ui.graphics.Outline) -> Unit) {
    light.give = Tabs.give(if (vertical) cell.height else cell.width, Tabs.REF.toPx())
    val (sx, sy) = light.squash(vertical)
    // The hit pivots at the edge that hit, so the far edge catches up; the press at the middle
    val lead = if (light.dir > 0) 1f else 0f
    val pivot = if (vertical) androidx.compose.ui.geometry.Offset(cell.width / 2, cell.height * lead)
        else androidx.compose.ui.geometry.Offset(cell.width * lead, cell.height / 2)
    translate(if (vertical) 0f else step * at, if (vertical) step * at else 0f) {
        scale(light.sink.value, cell.center) {
            scale(sx, sy, pivot) { draw(shape.createOutline(cell, layoutDirection, this)) }
        }
    }
}
