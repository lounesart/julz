package app.julz.ui

import androidx.compose.ui.hapticfeedback.HapticFeedbackType

/** The primary level's motion (258): the tabs (Segmented) and the tab bar. One motion language
 *  with the wheels, the other weight (my idea 26 Oct: bigger, static, stronger): the wheels stretch,
 *  magnify and pop on Material 3's expressive side, a destination slides firm on its standard side.
 *  The light keeps its shape, sinks a little under the finger and lands without a bounce. */
object Tabs {
    /** The light's slide to a picked tab: Material 3's standard spatial spring (stiffness 700),
     *  damped fully, as its 0.9 left half a pixel past a far tab on the outline light. A spring, so
     *  a jump across the bar takes about as long as a step, and a pick mid slide carries on */
    val slide = androidx.compose.animation.core.spring<Float>(dampingRatio = 1f, stiffness = 700f)

    /** How far the light sinks while a finger is on its tab, and the spring there and back:
     *  Material 3's fast effects spring, an effect, so no bounce */
    const val PRESS = 0.96f
    val press = androidx.compose.animation.core.spring<Float>(dampingRatio = 1f, stiffness = 3800f)

    /** How much of cell [i] the light covers with the light at [at] (in cells), 0 to 1: a word
     *  takes the light's ink as much as it is under it, so the colour moves with the light, in a
     *  glide or a swipe, instead of flipping halfway */
    fun ink(at: Float, i: Int) = (1f - kotlin.math.abs(at - i)).coerceIn(0f, 1f)

    /** A landing ticks once: between choices, so not a Confirm, and firmer than the wheel's
     *  frequent tick (Android's SEGMENT_TICK) */
    val tick = HapticFeedbackType.SegmentTick
}
