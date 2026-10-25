package app.julz.ui

import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.composed
import androidx.compose.ui.focus.FocusManager
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.layout.LayoutCoordinates
import androidx.compose.ui.layout.boundsInWindow
import androidx.compose.ui.layout.onGloballyPositioned

/** A tap outside the field ends editing and still acts (228, after 226): Android's and iOS's way,
 *  no dead first tap. The field itself and the buttons that go on with it (Add, Send) keep the
 *  keyboard; they say so with [keepsKeyboard]. */
object TapOut {
    /** A finished tap ends editing when it moved no more than the slop (a scroll is no tap) and
     *  lifted outside every area that keeps the keyboard. */
    fun endsEditing(down: Offset, up: Offset, slop: Float, keeps: Collection<Rect>): Boolean =
        (up - down).getDistance() <= slop && keeps.none { it.contains(up) }
}

/** Where the keyboard stays, in window coordinates, by the element that keeps it, and Shell's own
 *  place to turn a tap into window coordinates. Plain fields: layout writes them, a tap reads them. */
class KeyboardKeeps {
    val areas = mutableMapOf<Any, Rect>()
    var root: LayoutCoordinates? = null
}

val LocalKeyboardKeeps = staticCompositionLocalOf<KeyboardKeeps?> { null }

/** A text field, or a button that goes on with one, keeps the keyboard when tapped. */
fun Modifier.keepsKeyboard(): Modifier = composed {
    val keeps = LocalKeyboardKeeps.current
    val id = remember { Any() }
    DisposableEffect(keeps) { onDispose { keeps?.areas?.remove(id) } }
    onGloballyPositioned { keeps?.areas?.put(id, it.boundsInWindow()) }
}

/** Shell's observer: it reads every tap before the screen does (Initial pass) and consumes
 *  nothing, so whatever was tapped still acts; outside a keeping area it also clears focus,
 *  and the keyboard goes with the focus. */
fun Modifier.tapOutEndsEditing(keeps: KeyboardKeeps, focus: FocusManager): Modifier =
    pointerInput(keeps) {
        awaitEachGesture {
            val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
            var last = down.position
            while (true) {
                val change = awaitPointerEvent(PointerEventPass.Initial).changes.firstOrNull { it.id == down.id } ?: return@awaitEachGesture
                last = change.position
                if (!change.pressed) break
            }
            val box = keeps.root?.takeIf { it.isAttached } ?: return@awaitEachGesture
            if (TapOut.endsEditing(box.localToWindow(down.position), box.localToWindow(last), viewConfiguration.touchSlop, keeps.areas.values))
                focus.clearFocus()
        }
    }
