package app.julz.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.julz.approve.KeepItem
import app.julz.approve.NeedItem
import app.julz.approve.QueuedItem
import app.julz.approve.RunItem
import app.julz.approve.WorkBodies
import app.julz.approve.WorkState
import org.json.JSONObject


/** The approver page's last jobs, native (SECURITY.md 121): Claude's questions, the running job,
 *  queued runs and Keep. Each action is signed with the device key through the same paths as
 *  the page; the exact text the laptop built is on screen while I sign (109). */
@Composable
fun WorkCards(origins: Origins, w: WorkState, busy: Boolean, setBusy: (Boolean) -> Unit, say: (String?) -> Unit,
              reload: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    fun sign(action: String, body: JSONObject?, title: String) {
        if (body == null || busy) return
        setBusy(true); say(null)
        signWithDevice(context, scope, origins, action, body, title) { word, why ->
            setBusy(false)
            say(word?.let { it.replaceFirstChar { c -> c.uppercase() } + "." } ?: why)
            if (word != null) reload()
        }
    }

    w.running?.let { r ->
        SectionTitle("Running now")
        Card {
            Text("${r.project}, step ${r.step}", style = J.ts)
            Text(r.goal, style = J.sec)  // plain text (121)
            Signed(r.text)
            Button("Stop the run", J.warn) { sign("halt", WorkBodies.halt(r), "Stop the run") }
        }
    }
    if (w.queued.isNotEmpty()) {
        SectionTitle("Waiting to run")
        for (q in w.queued) Card {
            Text(q.goal, style = J.bodyText)
            Text(if (q.overridden) "step ${q.step}, run now signed" else "step ${q.step}, in line", style = J.monoCap)
            if (!q.overridden && q.overrideSha != null) {
                Signed(q.overrideText ?: "")
                Button("Run now, past the cap", J.acc) { sign("override", WorkBodies.override(q), "Run now") }
            }
        }
    }
    if (w.needs.isNotEmpty()) {
        SectionTitle("Claude needs you")
        for (n in w.needs) NeedCard(n, busy, n.text,
            go = { a -> WorkBodies.need(n, a).also { if (it == null) say("Answer: plain words, at most ${WorkBodies.MAX_ANSWER}, no links or secrets") }
                ?.let { sign(it.getString("action"), it, if (a.isBlank()) "Continue" else "Send answer") } },
            stop = { sign(WorkBodies.stop(n).getString("action"), WorkBodies.stop(n), if (n.stopped) "Delete the work copy" else "Stop the task") })
    }
    if (w.keeps.isNotEmpty()) {
        SectionTitle("Keep notes from a run")
        for (k in w.keeps) KeepCard(k, w.topics, busy) { topic, picked ->
            WorkBodies.keep(k, topic, picked).also { if (it == null) say("Pick at least one file and a topic like network-plus") }
                ?.let { sign("keep", it, "Keep notes") }
        }
    }
}

@Composable
private fun Card(content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth().assemble().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp3)) { content() }
}

/** The text the action signs: plain, mono, whole. While I sign, the server's text is in the sign panel (219). */
@Composable
private fun Signed(text: String) {
    if (text.isBlank()) return
    Text(text.trimEnd(), style = J.sec.copy(fontFamily = J.mono, color = J.text), modifier = Modifier.fillMaxWidth().glass(J.rM).padding(J.sp4))
}

/** An action button: outlined in its colour. The one glowing button stays with the specs. */
@Composable
private fun Button(label: String, color: Color, onClick: () -> Unit) =
    PlainButton(label, color = color, border = color.copy(alpha = 0.5f), onClick = onClick)

@Composable
private fun NeedCard(n: NeedItem, busy: Boolean, text: String, go: (String) -> Unit, stop: () -> Unit) {
    var answer by remember(n.root) { mutableStateOf("") }
    Card {
        Text(if (n.stopped) "Stopped, ${n.project}, next step ${n.step}" else "${n.project}, step ${n.step}", style = J.ts)
        Text(n.goal, style = J.sec)
        // Claude's words as plain text, never a button or link (121)
        Text(if (n.stopped) n.need else "Need: ${n.need}", style = J.bodyText)
        Text(if (n.stopped) n.why else "Why: ${n.why}", style = J.sec)
        Text("/work on the laptop is ${n.work}", style = J.monoCap)
        if (!n.stopped) Text("Continue tells Claude it is done. If you cannot do it, answer, or stop the task: "
            + "the same question again ends it.", style = J.sec.copy(color = J.warn))
        Signed(text)
        val colors = fieldColors()
        OutlinedTextField(answer, { if (it.length <= WorkBodies.MAX_ANSWER) answer = it }, Modifier.fillMaxWidth(),
            label = { Text(if (n.stopped) "Tell Claude something, or leave empty" else "Answer, or leave empty for Continue") },
            singleLine = true, enabled = !busy, colors = colors, shape = fieldShape(oneLine = true), textStyle = J.bodyText,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text),
            supportingText = { Text("Never a password, token or key: Claude reads it.") })
        Button(if (answer.isBlank()) (if (n.stopped) "Continue" else "I did it, continue") else "Send answer", J.acc) { go(answer) }
        Button(if (n.stopped) "Delete the work copy" else "Stop the task", J.warn, stop)
    }
}

@Composable
private fun KeepCard(k: KeepItem, topics: List<String>, busy: Boolean, keep: (String, List<String>) -> Unit) {
    val ticked = remember(k.root) { mutableStateMapOf<String, Boolean>().apply { k.files.forEach { put(it.path, true) } } }
    var topic by remember(k.root) { mutableStateOf("") }
    val picked = k.files.map { it.path }.filter { ticked[it] == true }
    Card {
        Text(k.goal, style = J.ts)
        Text("${k.project} · ${k.root.take(8)}", style = J.monoCap)
        Text("Tick the files to keep:", style = J.sec)
        Column(Modifier.fillMaxWidth().glass(J.rM).padding(horizontal = J.sp4)) {
            for (f in k.files) Row(Modifier.fillMaxWidth().heightIn(min = J.tap)
                .clickable(role = Role.Checkbox, enabled = !busy) { ticked[f.path] = ticked[f.path] != true },
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
                val on = ticked[f.path] == true
                Box(Modifier.size(20.dp).clip(androidx.compose.foundation.shape.RoundedCornerShape(6.dp))
                    .background(if (on) J.acc else Color.Transparent)
                    .border(1.5.dp, if (on) J.acc else J.muted, androidx.compose.foundation.shape.RoundedCornerShape(6.dp)),
                    contentAlignment = Alignment.Center) { if (on) Icon(Icons.check, null, tint = J.onAcc, modifier = Modifier.size(14.dp)) }
                Text(f.path, style = J.sec.copy(color = J.text), modifier = Modifier.weight(1f))
                Text("${f.size} B", style = J.monoCap)
            }
        }
        if (k.rejected.isNotEmpty()) {
            Text("Refused by the checks, cannot be kept:", style = J.sec.copy(color = J.warn))
            for ((p, why) in k.rejected) Text("$p: $why", style = J.monoCap)
            if (k.rejectedCount > k.rejected.size) Text("and ${k.rejectedCount - k.rejected.size} more", style = J.monoCap)
        }
        k.stopped?.let { Text(it, style = J.sec.copy(color = J.warn)) }
        val colors = fieldColors()
        // My folders so far, one tap each; a new one is typed below (found 18 Oct, 9b)
        if (topics.isNotEmpty()) androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(J.sp2),
            verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            for (t in topics) Pill(if (t == topic) "$t \u2713" else t, t == topic, !busy) { topic = if (t == topic) "" else t }
        }
        OutlinedTextField(topic, { topic = it.lowercase().take(40) }, Modifier.fillMaxWidth(),
            label = { Text(if (topics.isEmpty()) "Topic, like network-plus" else "Or a new topic") },
            singleLine = true, enabled = !busy, colors = colors, shape = fieldShape(oneLine = true), textStyle = J.bodyText.copy(fontFamily = J.mono),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii, autoCorrectEnabled = false),
            supportingText = { Text("Files go to julz-mem/Claude/${topic.ifBlank { "<topic>" }}/${k.root.take(8)}/. One Keep per task.") })
        Button("Keep ${picked.size} of ${k.files.size}", J.acc) { keep(topic, picked) }
    }
}
