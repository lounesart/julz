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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.isTraversalGroup
import androidx.compose.ui.semantics.traversalIndex
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.foundation.layout.height
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import app.julz.approve.ApproverApi
import app.julz.feed.DoneDay
import app.julz.feed.DoneWeek
import app.julz.feed.Kind
import app.julz.feed.Notice
import app.julz.feed.TabSwipe
import app.julz.feed.TodoSnapshot

/** A picked task, kept at app level so leaving the screen keeps my picks (HANDOFF gotcha). A
 *  pick to start a task (127) carries START in front: one Apply is all ticks or all starts. */
fun pickKey(list: String, item: String) = "$list\u0000$item"
private const val START = "start\u0000"

/** Todos (PLAN.md C, SECURITY.md 113): each list in its own card, Left and Done. A tap picks a
 *  task; one fingerprint ticks every pick. The app sends only the snapshot id and the picks;
 *  the laptop builds the text I sign, shown whole here while I sign. */
@Composable
fun TodosScreen(notices: List<Notice>, origins: Origins, picked: List<String>, setPicked: (List<String>) -> Unit,
                back: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val snap = notices.firstOrNull { it.kind == Kind.TODO }
    val lists = snap?.let { TodoSnapshot.parse(it.message) }
    val id = snap?.let { TodoSnapshot.id(it.message) }
    var busy by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    // Ticked and signed, waiting for the laptop's next snapshot: shown as Sent until it comes, so
    // the old list never invites a second tick (found 2026-10-18 on the phone)
    var sent by remember { mutableStateOf(emptyList<String>() to "") }
    val waiting = if (sent.second == id) sent.first.toSet() else emptySet()
    var tab by remember { mutableIntStateOf(0) }
    // The view on the wheel (251): the board, all lists, or one list by its name
    var view by remember { mutableStateOf(Wheel.ALL) }
    val goals = remember { GoalsUi() }
    // The Done tab (114): asked from the approver when shown, and again when the snapshot changes
    var week by remember { mutableStateOf<List<DoneDay>?>(null) }
    var weekProblem by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(tab, id) {
        if (tab != 1) return@LaunchedEffect
        weekProblem = null
        val reply = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            try { ApproverApi.call(origins, ApproverApi.DONE) } catch (e: Exception) { 0 to "" }
        }
        val parsed = if (reply.first == 200) DoneWeek.parse(reply.second) else null
        if (parsed != null) week = parsed
        else weekProblem = if (reply.first == 0) "The approver is not reachable. Is the laptop on and Tailscale up?"
                           else "The laptop answered oddly"
    }
    // Picks of tasks that are no longer open (ticked, started, or the list changed) drop by
    // themselves: a tick takes a task open or in progress, a start only an open one (127)
    val open = lists.orEmpty().flatMap { l -> l.open.map { pickKey(l.name, it) } }.toSet()
    val doing = lists.orEmpty().flatMap { l -> l.doing.map { pickKey(l.name, it) } }.toSet()
    val live = picked.filter { if (it.startsWith(START)) it.removePrefix(START) in open else it in open || it in doing }
    val starting = live.any { it.startsWith(START) }
    fun toggle(key: String) {
        val on = key in live
        // A tick and a start sign different texts: picking one kind drops the other
        val same = live.filter { it.startsWith(START) == key.startsWith(START) }
        setPicked(if (on) same - key else (same + key).take(TodoSnapshot.MAX_PICKS))
    }

    fun confirm() {
        val pairs = live.map { it.removePrefix(START) }.map { it.substringBefore('\u0000') to it.substringAfter('\u0000') }
        val action = if (starting) "start" else "tick"
        val body = id?.let { TodoSnapshot.tickBody(it, pairs, action) } ?: run { status = "Reload: no snapshot to tick against"; return }
        busy = true; status = null
        val verb = if (starting) "Start" else "Tick"
        signWithDevice(context, scope, origins, action, body,
            if (pairs.size == 1) "$verb 1 task" else "$verb ${pairs.size} tasks") { word, problem ->
            busy = false
            if (word != null) {
                sent = live to (id ?: "")
                setPicked(emptyList())
                status = word.replaceFirstChar { it.uppercase() } + ". The list updates in a few seconds."
            } else status = problem
        }
    }

    OwnsBarFade()
    Column(Modifier.fillMaxSize().padding(bottom = barClear())) {
    Box(Modifier.weight(1f)) {
    Column(Modifier.fillMaxSize()) {
    // The header and the tabs stay in view while the list scrolls: a tab scrolled away left a
    // goal's tick under my thumb (126b)
    Column(Modifier.padding(horizontal = J.gutter).padding(bottom = J.gap), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        // The time of the last change on the laptop, not of a fetch: say so (126b)
        ScreenHeader("Todos", if (snap == null) "no snapshot from the laptop yet" else "last change at " +
            Words.time(snap.time), back, "Back to feed")
        Segmented(listOf("Left", "Done", "Goals"), tab) { tab = it }
    }
    // The wheel floats at the list's bottom, under the thumb, as on Messages (257); only Left has one
    val names = lists.orEmpty().map { it.name }
    val views = Wheel.todoViews(names)
    val at = Wheel.todoIndex(view, names)
    fun left(name: String?) = lists.orEmpty().filter { name == null || it.name == name }.sumOf { it.open.size + it.doing.size }
    val wheel = tab == 0 && !lists.isNullOrEmpty()
    val density = androidx.compose.ui.platform.LocalDensity.current
    var band by remember { mutableStateOf(0.dp) }
    Box(Modifier.weight(1f).semantics { isTraversalGroup = true }) {
    // A swipe left or right moves one tab (250); the switch above stays as the visible way. It only
    // changes the view, never a pick or a tick: those stay behind the fingerprint
    val reach = with(androidx.compose.ui.platform.LocalDensity.current) { 80.dp.toPx() }
    Column(Modifier.fillMaxSize().pointerInput(tab) {
        var moved = 0f
        detectHorizontalDragGestures(onDragStart = { moved = 0f }, onDragCancel = { moved = 0f },
            onDragEnd = { tab = TabSwipe.next(tab, 3, moved, reach) }) { _, dx -> moved += dx }
    }.verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.sp6 + if (wheel) band else 0.dp), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        if (tab == 0) Guide(Guides.TODOS) else if (tab == 2) Guide(Guides.GOALS)
        if (tab == 2) GoalsTab(origins, goals, lists.orEmpty()) else if (tab == 1) DoneTab(week, weekProblem) else when {
            lists == null -> Text("Nothing here yet. Julz sends your tasks when they change.", style = J.sec)
            lists.isEmpty() -> Text("Every task is done.", style = J.bodyText)
            else -> {
                val board = at == 0
                @Composable fun task(list: String, t: String, inProgress: Boolean, showList: Boolean) =
                    TaskRow(list, t, inProgress, showList, live, waiting, busy, ::toggle)
                if (!board) for (l in lists.filter { at == 1 || it.name == views[at] }) Column(Modifier.fillMaxWidth().glass().padding(J.inset),
                    verticalArrangement = Arrangement.spacedBy(J.stack)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(TodoSnapshot.listLabel(l.name), style = J.ts, modifier = Modifier.weight(1f))
                        Text("${l.done}/${l.total}", style = J.monoCap)
                    }
                    if (l.doing.isNotEmpty()) {
                        Text("In progress", style = J.cap.copy(color = J.muted))
                        for (t in l.doing) task(l.name, t, true, false)
                    }
                    if (l.open.isNotEmpty()) {
                        // A caption only when it parts the list; alone it repeated the tab's name (126b)
                        if (l.doing.isNotEmpty() || l.doneItems.isNotEmpty()) Text("Left", style = J.cap.copy(color = J.muted))
                        for (t in l.open) task(l.name, t, false, false)
                    }
                    if (l.doneItems.isNotEmpty()) {
                        Text("Done", style = J.cap.copy(color = J.muted), modifier = Modifier.padding(top = J.sp2))
                        for (t in l.doneItems) Text("\u2713  " + app.julz.feed.GoalsData.shownText(t), style = J.sec.copy(textDecoration = TextDecoration.LineThrough),
                            modifier = Modifier.padding(start = J.sp4))
                    }
                } else {
                    // The board (planner.md 3): every list's tasks by stage, as HacknPlan and HTB
                    // Academy's module list show them: in progress, planned, done
                    for ((title, tasks) in listOf("In progress" to lists.flatMap { l -> l.doing.map { l.name to it } },
                                                  "Planned" to lists.flatMap { l -> l.open.map { l.name to it } })) {
                        Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.stack)) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(title, style = J.ts, modifier = Modifier.weight(1f))
                                Text("${tasks.size}", style = J.monoCap)
                            }
                            if (tasks.isEmpty()) Text(if (title == "Planned") "Nothing planned." else "Nothing started. Tap a task's circle to start it.", style = J.sec)
                            // The list's name only tells lists apart: with one list it was noise (126b)
                            for ((list, t) in tasks) task(list, t, title == "In progress", lists.size > 1)
                        }
                    }
                    val done = lists.flatMap { l -> l.doneItems.map { l.name to it } }
                    if (done.isNotEmpty()) Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.stack)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("Done", style = J.ts, modifier = Modifier.weight(1f))
                            Text("${lists.sumOf { it.done }}", style = J.monoCap)
                        }
                        for ((list, t) in done) Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("\u2713  " + app.julz.feed.GoalsData.shownText(t), style = J.sec.copy(textDecoration = TextDecoration.LineThrough),
                                modifier = Modifier.weight(1f).padding(start = J.sp4))
                            if (lists.size > 1) Text(TodoSnapshot.listLabel(list), style = J.monoCap)
                        }
                    }
                }
            }
        }
    }
    // On the page's own fade, as on Messages; TalkBack still reads the filter first
    if (wheel) Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth()
        .onSizeChanged { band = with(density) { it.height.toDp() } }.semantics { traversalIndex = -1f }) {
        Box(Modifier.fillMaxWidth().height(J.sp6).pageBackdrop(fade = true))
        Box(Modifier.fillMaxWidth().pageBackdrop()) {
            // Each view with what is left in it, so the wheel says where the work is
            WheelPicker(views.map { when (it) { Wheel.BOARD -> "Board"; Wheel.ALL -> "All lists"; else -> TodoSnapshot.listLabel(it) } }, at,
                counts = views.map { left(it.takeIf { v -> v != Wheel.BOARD && v != Wheel.ALL }) }) { view = views[it] }
        }
    } else FadeBottom()
    }
    }
    }
    // Pinned above the tab bar: what happened and the button, in view wherever the list is
    // scrolled (found 2026-10-18 on the phone). The text I sign is in the sign panel (219)
    if (tab == 2 && goals.active) Column(Modifier.fillMaxWidth().padding(horizontal = J.gutter, vertical = J.sp3),
        verticalArrangement = Arrangement.spacedBy(J.sp3)) { GoalsBar(origins, goals) }
    if (tab == 0 && (status != null || live.isNotEmpty())) Column(Modifier.fillMaxWidth()
        .padding(horizontal = J.gutter, vertical = J.sp3), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
        status?.let { Text(it, style = J.sec.copy(color = J.text)) }
        if (live.isNotEmpty()) GlowButton(when {
            busy -> "Waiting for your fingerprint"
            live.size == 1 -> "${if (starting) "Start" else "Tick"} 1 task with fingerprint"
            else -> "${if (starting) "Start" else "Tick"} ${live.size} tasks with fingerprint"
        }) { if (!busy) confirm() }
    }
    }
}

/** One task: its stage as a circle (empty planned, half in progress; a tap on an empty one picks
 *  it to start, 127), its words, Tick, and under them a quiet line with its list, goals and
 *  hours that uses the width beside Tick too, at most two lines (22c). */
@Composable
private fun TaskRow(list: String, t: String, inProgress: Boolean, showList: Boolean, live: List<String>,
                    waiting: Set<String>, busy: Boolean, toggle: (String) -> Unit) {
    val key = pickKey(list, t)
    val on = key in live
    val startOn = START + key in live
    val gone = key in waiting || START + key in waiting
    // A picked row is marked in the accent, so what the fingerprint will tick reads at a glance (126b)
    Column(Modifier.fillMaxWidth().heightIn(min = J.row).clip(J.rM).border(1.dp, if (on) J.acc else J.line, J.rM)
        .padding(end = J.sp2), verticalArrangement = Arrangement.Center) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(J.tap).clickable(role = Role.Button, enabled = !inProgress && !busy && !gone,
            onClickLabel = if (startOn) "Do not start $t" else "Start $t") { toggle(START + key) },
            contentAlignment = Alignment.Center) {
            StageCircle(if (inProgress) 1 else if (startOn) 2 else 0)
        }
        // The rest of the row is one checkbox, as Material's list with a trailing checkbox: the
        // words and the box pick it to tick. The big Tick pill outweighed the task (126b)
        Row(Modifier.weight(1f).heightIn(min = J.tap).toggleable(on, enabled = !busy && !gone, role = Role.Checkbox) { toggle(key) },
            verticalAlignment = Alignment.CenterVertically) {
            Text(app.julz.feed.GoalsData.shownText(t), style = J.bodyText,  // plain text (91)
                modifier = Modifier.weight(1f).padding(vertical = J.sp2, horizontal = J.sp1))
            CheckMark(on, gone)
        }
    }
    val goals = app.julz.feed.GoalsData.goalsOf(t)
    val quiet = listOfNotNull(TodoSnapshot.listLabel(list).takeIf { showList }, goals.takeIf { it.isNotEmpty() }?.let { "\u2192 " + it.joinToString(", ") },
        app.julz.feed.GoalsData.todoHours(t)?.let { app.julz.feed.GoalsData.hoursLabel(it.first, it.second) },
        "start picked".takeIf { startOn })
    // Lined up with the words above, under the circle's width
    if (quiet.isNotEmpty()) Text(quiet.joinToString(" \u00b7 "), style = J.monoCap, maxLines = 2,
        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
        modifier = Modifier.padding(start = J.tap + J.sp1, bottom = J.sp2))
    }
}

/** Tick as a checkbox, drawn like Keep's file checkbox (126b): an outline, filled in the accent
 *  with a check when picked, "Sent" until the laptop's next snapshot. Shared with Goals. */
@Composable
internal fun CheckMark(on: Boolean, gone: Boolean = false) {
    Box(Modifier.widthIn(min = J.tap), contentAlignment = Alignment.Center) {
        if (gone) Text("Sent", style = J.cap.copy(color = J.muted))
        else Box(Modifier.size(20.dp).clip(J.rS).background(if (on) J.acc else Color.Transparent)
            .border(1.5.dp, if (on) J.acc else J.muted, J.rS), contentAlignment = Alignment.Center) {
            if (on) androidx.compose.material3.Icon(Icons.check, null, tint = J.onAcc, modifier = Modifier.size(14.dp))
        }
    }
}

/** 0 planned: an empty ring. 1 in progress: the ring half filled in the accent. 2 picked to
 *  start: the ring in the accent, half filled, waiting for the fingerprint. */
@Composable
private fun StageCircle(stage: Int) {
    val ring = if (stage == 0) J.muted else J.acc
    val fill = if (stage == 2) J.acc.copy(alpha = 0.5f) else J.acc
    androidx.compose.foundation.Canvas(Modifier.size(20.dp)) {
        val stroke = 2.dp.toPx()
        drawCircle(ring, radius = size.minDimension / 2 - stroke / 2, style = androidx.compose.ui.graphics.drawscope.Stroke(stroke))
        if (stage > 0) drawArc(fill, startAngle = -90f, sweepAngle = 180f, useCenter = true,
            topLeft = androidx.compose.ui.geometry.Offset(stroke * 2, stroke * 2),
            size = androidx.compose.ui.geometry.Size(size.width - stroke * 4, size.height - stroke * 4))
    }
}

/** Everything ticked in the last 7 days, archived lists too, by day, newest first (114). */
@Composable
private fun DoneTab(week: List<DoneDay>?, problem: String?) {
    val today = java.time.LocalDate.now()
    when {
        problem != null -> Text(problem, style = J.sec)
        week == null -> Text("Asking the laptop", style = J.sec)
        week.isEmpty() -> Text("Nothing ticked in the last 7 days.", style = J.bodyText)
        else -> for (d in week) Column(Modifier.fillMaxWidth().glass().padding(J.inset),
            verticalArrangement = Arrangement.spacedBy(J.stack)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(DoneWeek.label(d.date, today), style = J.ts, modifier = Modifier.weight(1f))
                Text("${d.items.size}", style = J.monoCap)
            }
            // Same tile as TaskRow, and the accent box of Left and Goals for the done mark (246)
            for ((list, item) in d.items) Row(Modifier.fillMaxWidth().heightIn(min = J.row).clip(J.rM).border(1.dp, J.line, J.rM)
                .padding(end = J.sp2), verticalAlignment = Alignment.CenterVertically) {
                Box(Modifier.semantics { contentDescription = "done" }) { CheckMark(true) }  // read as "done", not "check mark"
                Column(Modifier.weight(1f).padding(vertical = J.sp2)) {
                    Text(app.julz.feed.GoalsData.shownText(item), style = J.bodyText)  // plain text (91)
                    Text(TodoSnapshot.listLabel(list), style = J.monoCap)
                }
            }
        }
    }
}
