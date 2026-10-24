package app.julz.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp

/** The words of every guide, in one voice and one place (22c). Fixed text in the app, never
 *  data from the laptop, so nothing outside can put words into a guide. */
object Guides {
    // Each at most 120 characters, about three lines on a 375 dp phone (GuidesTest)
    const val APPROVE = "Approve signs a job for Claude Code with your fingerprint. It runs in a copy; Keep brings " +
        "the result into your notes."
    const val TODOS = "Tap a circle to start a task, Tick when it is done. One fingerprint applies your picks; git " +
        "can undo any change."
    const val GOALS = "Tap a goal for a target, a due date or its todos. A todo tagged #goal/<id> counts toward it. " +
        "One fingerprint applies it."
    const val INBOX = "Pick changes, one fingerprint applies them. A note changed since you saw it is left alone; " +
        "git can undo any change."
    const val TOOLS = "What Julz can do and how each part is doing. You watch them here and switch them on the laptop."

    val all = listOf(APPROVE, TODOS, GOALS, INBOX, TOOLS)
}

/** A guide under a screen's title: the same quiet card everywhere, a dashed hairline, no
 *  colour. Hide hides every guide; Show guides in Accessibility brings them back. */
@Composable
fun Guide(text: String) {
    if (!A11y.prefs.guides) return
    val context = LocalContext.current
    val frame = J.rM
    Column(Modifier.fillMaxWidth().drawBehind {
            // The row token's own outline, round or cut (22d)
            drawOutline(frame.createOutline(size, layoutDirection, this), J.line,
                style = Stroke(1.dp.toPx(), pathEffect = PathEffect.dashPathEffect(floatArrayOf(6.dp.toPx(), 4.dp.toPx()))))
        }.padding(start = J.sp4, end = J.sp1, top = J.sp3)) {
        Text(text, style = J.sec, modifier = Modifier.padding(end = J.sp3))
        Box(Modifier.align(Alignment.End).heightIn(min = J.tap).clip(J.rS)
            .clickable(role = Role.Button, onClickLabel = "Hide all guides") { A11y.set(context, A11y.prefs.copy(guides = false)) }
            .padding(horizontal = J.sp3), contentAlignment = Alignment.Center) {
            Text("Hide", style = J.sec.copy(color = J.text, fontWeight = FontWeight(600)))
        }
    }
}
