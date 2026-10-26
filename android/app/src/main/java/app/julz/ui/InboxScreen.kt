package app.julz.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import app.julz.approve.ApproverApi
import app.julz.feed.InboxNote
import app.julz.feed.InboxPick
import app.julz.feed.InboxSnapshot
import app.julz.feed.InboxSnapshotData
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext


/** Inbox (PLAN.md D, SECURITY.md 116, 117): my Inbox notes, each in a card with a preview.
 *  Picks (delete, or move to a folder) are applied with one fingerprint; the laptop builds the
 *  text I sign, shown whole in the bar while I sign. */
@Composable
fun InboxScreen(origins: Origins, picked: List<String>, setPicked: (List<String>) -> Unit, browse: (String?) -> Unit,
                signed: (String) -> Unit, back: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var snap by remember { mutableStateOf<InboxSnapshotData?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    var reloads by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    var counts by remember { mutableStateOf<Map<String, Int>>(emptyMap()) }
    // A notice this screen keeps out of the tray reloads it at once
    val fresh by app.julz.JulzService.changes.collectAsState()
    val firstFresh = remember { fresh }
    LaunchedEffect(fresh) { if (fresh != firstFresh) reloads++ }
    LaunchedEffect(reloads) {
        // How full each folder is, for the Move panel (118); the Inbox works without it
        withContext(Dispatchers.IO) {
            try { ApproverApi.call(origins, ApproverApi.NOTES) } catch (e: Exception) { 0 to "" }
        }.let { (code, raw) -> if (code == 200) app.julz.feed.VaultNotes.parse(raw)?.let { counts = app.julz.feed.VaultNotes.counts(it) } }
        val reply = withContext(Dispatchers.IO) {
            try { ApproverApi.call(origins, ApproverApi.INBOX) } catch (e: Exception) { 0 to "" }
        }
        val parsed = if (reply.first == 200) InboxSnapshot.parse(reply.second) else null
        if (parsed != null) { snap = parsed; problem = null }
        else problem = if (reply.first == 0) "The approver is not reachable. Is the laptop on and Tailscale up?"
                       else "The laptop answered oddly"
    }
    // The id signed is that of the snapshot the picks were checked against, as drawn
    val s = snap
    fun apply(picks: List<InboxPick>) {
        val body = s?.let { InboxSnapshot.body(it.id, picks) } ?: run { status = "Reload: no Inbox to act on"; return }
        busy = true; status = null
        signWithDevice(context, scope, origins, "inbox", body,
            if (picks.size == 1) "Change 1 note" else "Change ${picks.size} notes") { word, why ->
            busy = false
            if (word != null) {
                setPicked(emptyList())
                signed(s.id)
                status = word.replaceFirstChar { it.uppercase() } + ". The Inbox updates in a few seconds."
                scope.launch { delay(InboxSnapshot.SETTLE_MS); reloads++ }  // julz-vault applies them, then writes a new Inbox
            } else status = why
        }
    }

    InboxContent(snap, problem, counts, picked, setPicked, busy, status,
        reload = { status = null; reloads++ }, apply = ::apply, browse = browse, back = back)
}

/** What the Inbox shows, from what InboxScreen fetched and signs: no network and no key here, so
 *  a screenshot test draws it from fixed data (184). */
@Composable
internal fun InboxContent(s: InboxSnapshotData?, problem: String?, counts: Map<String, Int>, picked: List<String>,
                          setPicked: (List<String>) -> Unit, busy: Boolean, status: String?,
                          reload: () -> Unit, apply: (List<InboxPick>) -> Unit, browse: (String?) -> Unit,
                          back: () -> Unit) {
    var open by remember { mutableStateOf<String?>(null) }   // the note shown whole
    var choosing by remember { mutableStateOf<String?>(null) }  // the note whose folders are shown
    // Picks of notes no longer in the Inbox (moved, deleted, changed) drop by themselves
    val notes = s?.notes.orEmpty().map { it.note }.toSet()
    val picks = picked.mapNotNull { InboxPick.from(it) }.filter { it.note in notes }
    fun pickFor(n: InboxNote) = picks.firstOrNull { it.note == n.note }
    fun set(n: InboxNote, p: InboxPick?) {
        setPicked(picks.filter { it.note != n.note }.map { it.key } + listOfNotNull(p?.key))
    }

    OwnsBarFade()
    Column(Modifier.fillMaxSize().padding(bottom = barClear())) {
    Box(Modifier.weight(1f)) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.sp6), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader("Inbox", when {
            s == null -> "asking the laptop"
            s.notes.size == 1 -> "1 note waiting to be sorted"
            else -> "${s.notes.size} notes waiting to be sorted"
        }, back, "Back to feed") { RoundButton(Icons.reload, "Reload", reload) }
        Guide(Guides.INBOX)
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            ListRow("Browse all notes", "every folder and what is in it, read only", onClick = { browse(null) }) {
                androidx.compose.material3.Icon(Icons.arrow, null, tint = J.muted)
            }
        }
        when {
            problem != null -> Text(problem, style = J.sec)
            s == null -> Text("Asking the laptop", style = J.sec)
            s.notes.isEmpty() -> Text("The Inbox is empty.", style = J.bodyText)
            else -> for (n in s.notes) {
                val p = pickFor(n)
                Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(n.name, style = J.ts, modifier = Modifier.weight(1f))
                        Text(n.modified, style = J.monoCap)
                    }
                    // Collapsed: the first lines without their marks; open: the note drawn with its
                    // Obsidian formatting, nothing fetched (119)
                    val whole = open == n.note
                    val lines = n.preview.trimEnd().lines()
                    val toggle = Modifier.fillMaxWidth().clickable(role = Role.Button,
                        onClickLabel = if (whole) "Show less" else "Show all") { open = if (whole) null else n.note }
                    if (whole) Box(toggle) { MarkdownView(remember(n.preview) { app.julz.feed.ObsidianMd.parse(n.preview) }) }
                    else Text(app.julz.feed.ObsidianMd.plain(n.preview, 4) ?: "(empty)", style = J.sec.copy(color = J.text), modifier = toggle)
                    // The preview is cut at 2000 characters (size is in bytes, not letters)
                    if (!whole && (lines.size > 4 || n.preview.length >= 2000))
                        Text("Tap to read more" + if (n.preview.length >= 2000) ", the rest in Obsidian" else "", style = J.cap.copy(color = J.muted))
                    if (p != null) Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(if (p.action == "delete") "Will be deleted" else "Will move to ${p.to}",
                            style = J.sec.copy(color = if (p.action == "delete") J.warn else J.acc, fontWeight = FontWeight(700)),
                            modifier = Modifier.weight(1f))
                        Chip("Undo", !busy) { set(n, null) }
                    } else Row(horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                        Chip("Move", !busy) { choosing = if (choosing == n.note) null else n.note }
                        Chip("Delete", !busy, J.warn) { set(n, InboxPick(n.note, "delete")); choosing = null }
                    }

                }
            }
        }
        // Move to: a sheet over the screen, as the design system draws choices (asked 2026-10-18)
        val moving = s?.notes?.firstOrNull { it.note == choosing }
        if (s != null && moving != null) MoveSheet(moving, s.folders, counts,
            choose = { f -> set(moving, InboxPick(moving.note, "move", f)); choosing = null },
            look = { choosing = null; browse(null) }, cancel = { choosing = null })
    }
    FadeBottom()
    }
    // Pinned above the tab bar, as on Todos: what happened and the button. The text I sign is in
    // the sign panel at the top, where the fingerprint sheet does not cover it (219)
    if (status != null || picks.isNotEmpty()) Column(Modifier.fillMaxWidth()
        .padding(horizontal = J.gutter, vertical = J.sp3), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
        status?.let { Text(it, style = J.sec.copy(color = J.text)) }
        if (picks.isNotEmpty()) GlowButton(when {
            busy -> "Waiting for your fingerprint"
            picks.size == 1 -> "Apply 1 change with fingerprint"
            else -> "Apply ${picks.size} changes with fingerprint"
        }) { if (!busy) apply(picks) }
    }
    }
}

@Composable
private fun Chip(label: String, enabled: Boolean, color: androidx.compose.ui.graphics.Color = J.text, onClick: () -> Unit) {
    Box(Modifier.heightIn(min = J.tap).clip(J.pill).border(1.dp, J.line, J.pill)
        .background(J.raise).clickable(role = Role.Button, enabled = enabled, onClick = onClick)
        .padding(horizontal = J.sp4), contentAlignment = Alignment.Center) {
        Text(label, style = J.sec.copy(color = color, fontWeight = FontWeight(600)))
    }
}

/** Where a note can go, in a sheet: each folder a row with what it holds, a tap picks it. */
@Composable
private fun MoveSheet(n: InboxNote, folders: List<String>, counts: Map<String, Int>,
                      choose: (String) -> Unit, look: () -> Unit, cancel: () -> Unit) {
    JulzSheet(onDismiss = cancel) {
        Column(verticalArrangement = Arrangement.spacedBy(J.sp1)) {
            Text("Move to", style = J.tm)
            Text("${n.note.substringAfter('/')} keeps its name", style = J.sec)
        }
        // Rows as in Messages: each on its own glass, a pastel circle with the icon, the count where
        // Messages shows the time, no arrows (asked 2026-10-18)
        Column(verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            for (f in folders) {
                val inside = counts.keys.count { it.startsWith("$f/") }
                val notes = counts[f] ?: 0
                Row(Modifier.fillMaxWidth().glass(J.rM).clickable(role = Role.Button, onClickLabel = "Move to $f") { choose(f) }
                    .heightIn(min = J.row).padding(J.sp3), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
                    // Neutral by default, no colour fill (asked 2026-10-18): a raised dot with a hairline and a
                    // muted icon; with Coloured folders its top folder's colour as a line, a tint and the icon (22b)
                    IconBadge(Icons.folder, Folders.argb(f)?.takeIf { Look.prefs.colorFolders }?.let { androidx.compose.ui.graphics.Color(it) })
                    Column(Modifier.weight(1f)) {
                        Text(f.substringAfterLast('/'), style = J.item)
                        val folders = if (inside == 1) "1 folder" else "$inside folders"
                        Text(if ('/' in f) "in ${f.substringBeforeLast('/')}" + (if (inside > 0) ", $folders" else "")
                             else if (inside > 0) "$folders inside" else "top of $f", style = J.sec)
                    }
                    Text(if (notes == 1) "1 note" else "$notes notes", style = J.monoCap)
                }
            }
        }
        PlainButton("Look inside the folders", onClick = look)
        PlainButton("Cancel", color = J.muted, onClick = cancel)
    }
}
