package app.julz.ui

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.background
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import app.julz.approve.ApproverApi
import app.julz.feed.VaultFolder
import app.julz.feed.VaultNote
import app.julz.feed.VaultNotes
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** The notes browser (SECURITY.md 118), read only: folders, the notes in one, a note's text.
 *  Back goes up a level, then leaves. The text lives only in memory while this screen is open. */
@Composable
fun NotesScreen(origins: Origins, start: String?, back: () -> Unit) {
    var all by remember { mutableStateOf<List<VaultFolder>?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    var reloads by remember { mutableIntStateOf(0) }
    var folder by remember { mutableStateOf(start) }
    var note by remember { mutableStateOf<VaultNote?>(null) }
    LaunchedEffect(reloads) {
        val reply = withContext(Dispatchers.IO) {
            try { ApproverApi.call(origins, ApproverApi.NOTES) } catch (e: Exception) { 0 to "" }
        }
        val parsed = if (reply.first == 200) VaultNotes.parse(reply.second) else null
        if (parsed != null) { all = parsed; problem = null }
        else problem = if (reply.first == 0) "The approver is not reachable. Is the laptop on and Tailscale up?"
                       else "The laptop answered oddly"
    }
    // Up one level: a note to its folder, a folder to the one around it, then the overview
    fun up() {
        val f = folder
        when {
            note != null -> note = null
            f != null && f != start -> folder = if ('/' in f) f.substringBeforeLast('/') else null
            else -> back()
        }
    }
    BackHandler { up() }
    val f = all?.firstOrNull { it.folder == folder }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader(note?.name ?: folder?.substringAfterLast('/') ?: "Notes",
            note?.let { "${it.note} · ${it.modified}" } ?: folder ?: "your vault, read only", ::up,
            action = if (note == null) ({ RoundButton(Icons.reload, "Reload") { reloads++ } }) else null)
        val n = note
        when {
            problem != null -> Text(problem!!, style = J.sec)
            all == null -> Text("Asking the laptop", style = J.sec)
            n != null -> {
                // Obsidian formatting in the app's style, nothing fetched (119); a wikilink opens a note
                // that is in the snapshot, by its name or its path
                val notes = all!!.flatMap { it.notes }
                fun find(target: String) = notes.firstOrNull { it.name.equals(target, true) }
                    ?: notes.firstOrNull { it.note.removeSuffix(".md").endsWith(target, true) }
                Column(Modifier.fillMaxWidth().glass().padding(J.inset)) {
                    MarkdownView(remember(n) { app.julz.feed.ObsidianMd.parse(n.text) }) { target ->
                        find(target)?.let { x -> { note = x; folder = x.note.substringBeforeLast('/') } }
                    }
                }
                // Cut only at the 4000 character limit; size is in bytes, and Cyrillic takes two a letter
                if (n.text.length >= 4000) Text("The rest is in Obsidian: only the first 4000 characters travel.",
                    style = J.cap.copy(color = J.muted))
            }
            folder != null -> {
                // A folder shows the folders inside it, then its own notes
                val inside = all!!.filter { it.folder.startsWith("$folder/") }
                if (inside.isNotEmpty()) Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
                    for (g in inside) ListRow(g.folder.removePrefix("$folder/"),
                        if (g.notes.size == 1) "1 note" else "${g.notes.size} notes", onClick = { folder = g.folder })
                }
                if (f != null) Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
                    for (x in f.notes) ListRow(x.name, x.modified, onClick = { note = x }) {
                        Text("${x.size} B", style = J.monoCap)
                    }
                }
                if (f == null && inside.isEmpty()) Text("No notes in $folder yet.", style = J.bodyText)
            }
            all!!.isEmpty() -> Text("No notes yet.", style = J.bodyText)
            else -> {
                // Grouped by the top folder: study, daily, Inbox, Claude, Outbox, feedback
                val order = listOf("study", "daily", "Inbox", "Claude", "Outbox", "feedback")
                for ((top, group) in all!!.groupBy { it.folder.substringBefore('/') }.toList()
                        .sortedBy { order.indexOf(it.first) }) {
                    // With Coloured folders, a dot in the top folder's colour beside its name (22b)
                    val c = Folders.argb(top)?.takeIf { Look.prefs.colorFolders }
                    if (c == null) SectionTitle(top)
                    else Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                        Box(Modifier.padding(start = J.sp1).size(10.dp).background(androidx.compose.ui.graphics.Color(c),
                            androidx.compose.foundation.shape.CircleShape))
                        SectionTitle(top)
                    }
                    Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
                        for (g in group) ListRow(if (g.folder == top) "$top (top)" else g.folder.substringAfter('/'),
                            if (g.notes.size == 1) "1 note" else "${g.notes.size} notes", onClick = { folder = g.folder })
                    }
                }
            }
        }
    }
}
