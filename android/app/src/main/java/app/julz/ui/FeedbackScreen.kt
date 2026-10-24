package app.julz.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardCapitalization
import androidx.compose.ui.unit.dp
import app.julz.approve.ApproverApi
import app.julz.approve.Begun
import app.julz.feed.FeedbackItem
import app.julz.feed.FeedbackList
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** Feedback (PLAN.md E, SECURITY.md 120): I write it here, one fingerprint saves it as a note in
 *  feedback/, and Claude Code sorts it into BACKLOG.md, writing back its state and place. The
 *  list shows what happened to each. The draft lives at app level, so leaving keeps it. */
@Composable
fun FeedbackScreen(origins: Origins, draft: String, setDraft: (String) -> Unit, kind: Int, setKind: (Int) -> Unit,
                   back: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var items by remember { mutableStateOf<List<FeedbackItem>?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    var reloads by remember { mutableIntStateOf(0) }
    var signing by remember { mutableStateOf<Begun?>(null) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(reloads) {
        val reply = withContext(Dispatchers.IO) {
            try { ApproverApi.call(origins, ApproverApi.FEEDBACK) } catch (e: Exception) { 0 to "" }
        }
        val parsed = if (reply.first == 200) FeedbackList.parse(reply.second) else null
        if (parsed != null) { items = parsed; problem = null }
        else problem = if (reply.first == 0) "The approver is not reachable. Is the laptop on and Tailscale up?"
                       else "The laptop answered oddly"
    }
    fun send() {
        val body = FeedbackList.body(FeedbackList.KINDS[kind], draft.trim()) ?: run { status = "Write a few plain words first"; return }
        busy = true; status = null
        signWithDevice(context, scope, origins, "feedback", body, "Send feedback", { signing = it }) { word, why ->
            busy = false
            if (word != null) {
                setDraft("")
                status = "Sent. It shows below in a few seconds; Claude sorts it next session."
                scope.launch { delay(4000); reloads++ }  // julz-vault saves it, then writes a new list
            } else status = why
        }
    }
    val colors = fieldColors()

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader("Feedback", "read by Claude, sorted into the backlog", back, "Back to feed") {
            RoundButton(Icons.reload, "Reload") { status = null; reloads++ }
        }
        Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
            Segmented(listOf("Bug", "Idea", "Change"), kind) { if (!busy) setKind(it) }
            OutlinedTextField(draft, { if (it.length <= FeedbackList.MAX_TEXT) setDraft(it) }, Modifier.fillMaxWidth(),
                label = { Text("What should change?") }, minLines = 3, maxLines = 10, colors = colors, shape = fieldShape(oneLine = false), textStyle = J.bodyText,
                enabled = !busy, keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.Sentences),
                supportingText = { Text("Plain words, no links · ${draft.length} / ${FeedbackList.MAX_TEXT}") })
            signing?.let {
                // Plain text only (34): the exact note the laptop built for this nonce (109)
                Column(Modifier.fillMaxWidth().glass(J.rM).padding(J.sp4), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
                    Text(it.text.trimEnd(), style = J.sec.copy(fontFamily = J.mono, color = J.text))
                    Text("You are signing exactly this.", style = J.cap.copy(color = J.accText, fontWeight = FontWeight(700)))
                }
            }
            status?.let { Text(it, style = J.sec.copy(color = J.text)) }
            GlowButton(if (busy) "Waiting for your fingerprint" else "Send with fingerprint") { if (!busy) send() }
        }
        val list = items
        when {
            problem != null -> Text(problem!!, style = J.sec)
            list == null -> Text("Asking the laptop", style = J.sec)
            list.isEmpty() -> Text("No feedback yet.", style = J.sec)
            else -> {
                val open = list.filter { !it.done }
                val done = list.filter { it.done }
                if (open.isNotEmpty()) { SectionTitle("Open"); for (f in open) FeedbackCard(f) }
                if (done.isNotEmpty()) { SectionTitle("Done"); for (f in done) FeedbackCard(f) }
            }
        }
    }
}

@Composable
private fun FeedbackCard(f: FeedbackItem) {
    Column(Modifier.fillMaxWidth().glass(J.rM).padding(J.sp4), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
            // State as a word, never by colour alone: new, planned, later, rejected, done
            Tag(f.state, if (f.done) J.muted else J.text)
            if (f.kind.isNotEmpty()) Text(f.kind, style = J.cap)
            Box(Modifier.weight(1f))
            Text(f.created, style = J.monoCap)
        }
        Text(f.text, style = J.bodyText.copy(color = if (f.done) J.muted else J.text), maxLines = 4)  // plain text (120)
        if (f.where.isNotEmpty()) Text(f.where, style = J.monoCap)
    }
}
