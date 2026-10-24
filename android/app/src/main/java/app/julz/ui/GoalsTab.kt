package app.julz.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateListOf
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import app.julz.approve.ApproverApi
import app.julz.approve.Begun
import app.julz.feed.GoalItem
import app.julz.feed.GoalPick
import app.julz.feed.GoalsData
import app.julz.feed.GoalsSnapshot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/** What the Goals tab and the Todos screen's bottom bar share: the picks, the signing and the
 *  result, so Apply sits at the bottom as on Todos and Inbox (asked 2026-10-18). */
class GoalsUi {
    var snap by mutableStateOf<GoalsSnapshot?>(null)
    var problem by mutableStateOf<String?>(null)
    var reloads by mutableIntStateOf(0)
    val picks = mutableStateListOf<GoalPick>()
    val drafts = mutableStateMapOf<String, String>()
    var signing by mutableStateOf<Begun?>(null)
    var busy by mutableStateOf(false)
    var status by mutableStateOf<String?>(null)
    var open by mutableStateOf<String?>(null)       // the goal shown whole, by period and text
    val targets = mutableStateMapOf<String, String>()  // target numbers being typed, by goal
    var addTo by mutableStateOf<String?>(null)      // the period the one Add form adds to (126b)
    val active get() = status != null || signing != null || picks.isNotEmpty()
}

/** The Goals tab's part of the pinned bar: the result, the exact text while signing, Apply. */
@Composable
fun GoalsBar(origins: Origins, ui: GoalsUi) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    fun apply() {
        val body = ui.snap?.let { GoalsData.body(it.id, ui.picks.toList()) } ?: return
        ui.busy = true; ui.status = null
        signWithDevice(context, scope, origins, "goal", body, "Change goals", { ui.signing = it }) { word, why ->
            ui.busy = false
            if (word != null) {
                ui.picks.clear()
                ui.status = word.replaceFirstChar { it.uppercase() } + ". Goals update in a few seconds."
                scope.launch { delay(4000); ui.reloads++ }
            } else ui.status = why
        }
    }
    ui.status?.let { Text(it, style = J.sec.copy(color = J.text)) }
    ui.signing?.let {
        Column(Modifier.fillMaxWidth().glass(J.rM).padding(J.sp4), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            Text(it.text.trimEnd(), style = J.sec.copy(fontFamily = J.mono, color = J.text))
            Text("You are signing exactly this.", style = J.cap.copy(color = J.accText, fontWeight = FontWeight(700)))
        }
    }
    if (ui.picks.isNotEmpty()) GlowButton(if (ui.busy) "Waiting for your fingerprint" else
        if (ui.picks.size == 1) "Apply 1 change with fingerprint" else "Apply ${ui.picks.size} changes with fingerprint") { if (!ui.busy) apply() }
}

/** Goals next to todos (base 7, SECURITY.md 123): a card per period, a bar per goal from its own
 *  count or its linked todos, pick to tick, +1, add; one fingerprint applies the picks. */
@Composable
fun GoalsTab(origins: Origins, ui: GoalsUi, todos: List<app.julz.feed.TodoList>) {
    val picks = ui.picks
    val drafts = ui.drafts
    val busy = ui.busy
    LaunchedEffect(ui.reloads) {
        val reply = withContext(Dispatchers.IO) { try { ApproverApi.call(origins, ApproverApi.GOALS) } catch (e: Exception) { 0 to "" } }
        val parsed = if (reply.first == 200) GoalsData.parse(reply.second) else null
        if (parsed != null) { ui.snap = parsed; ui.problem = null }
        else ui.problem = if (reply.first == 0) "The approver is not reachable. Is the laptop on and Tailscale up?" else "The laptop answered oddly"
    }
    fun toggle(p: GoalPick) { if (p in picks) picks.remove(p) else if (picks.size < 20) picks.add(p) }
    val colors = fieldColors()

    Column(verticalArrangement = Arrangement.spacedBy(J.sp3)) {
        val s = ui.snap
        val today = java.time.LocalDate.now()
        // One Add form with the period as a choice, this week first; a field in all four cards
        // filled the screen (126b)
        if (ui.problem == null && s != null && s.periods.isNotEmpty()) {
            val to = ui.addTo?.takeIf { k -> s.periods.any { it.key == k } } ?: s.periods.getOrElse(1) { s.periods[0] }.key
            Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                    OutlinedTextField(drafts["new"].orEmpty(), { if (it.length <= 120) drafts["new"] = it }, Modifier.weight(1f),
                        label = { Text("Add a goal") }, singleLine = true, enabled = !busy, colors = colors, shape = fieldShape(oneLine = true), textStyle = J.bodyText)
                    Pill("Add", false, !busy && !drafts["new"].isNullOrBlank()) {
                        drafts["new"]?.trim()?.takeIf { it.isNotEmpty() }?.let { toggle(GoalPick("add", to, it)); drafts["new"] = "" }
                    }
                }
                ActionRow("For") { for (p in s.periods) SmallPill(p.label, p.key == to, !busy) { ui.addTo = p.key } }
            }
        }
        // Milestones first: open goals with a date from any period, soonest first (126)
        if (ui.problem == null && s != null && s.milestones.isNotEmpty())
            Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                Text("Milestones", style = J.ts)
                for (m in s.milestones) Column(verticalArrangement = Arrangement.spacedBy(J.sp1)) {
                    Text(GoalsData.shownText(m.text), style = J.bodyText)  // plain text (126)
                    Bar(m.rollup ?: 0, 100, listOfNotNull(m.rollup?.let { "$it%" }, GoalsData.dueLabel(m.due, today)).joinToString(" \u00b7 "))
                }
            }
        when {
            ui.problem != null -> Text(ui.problem!!, style = J.sec)
            s == null -> Text("Asking the laptop", style = J.sec)
            else -> for (p in s.periods) Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(p.label, style = J.ts, modifier = Modifier.weight(1f))
                    Text(p.key, style = J.monoCap)
                }
                if (p.goals.isEmpty()) Text("No goals yet.", style = J.sec)
                for (g in p.goals) GoalRow(p.key, g, ui, todos, ::toggle)
                for (a in picks.filter { it.action == "add" && it.period == p.key }) Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Will add: ${a.value}", style = J.sec.copy(color = J.accText), modifier = Modifier.weight(1f))
                    Pill("Undo", false, !busy) { picks.remove(a) }
                }
            }
        }
    }
}

/** A goal: its words, one bar and its place in the tree; tapped, it opens a short set of
 *  actions (trimmed 2026-10-18: too much text under a goal). */
@Composable
private fun GoalRow(period: String, g: GoalItem, ui: GoalsUi, todos: List<app.julz.feed.TodoList>, toggle: (GoalPick) -> Unit) {
    val key = "$period\u0000${g.text}"
    val open = ui.open == key
    val busy = ui.busy
    var linking by remember(key) { mutableStateOf(false) }
    var dating by remember(key) { mutableStateOf(false) }
    var estimating by remember(key) { mutableStateOf(false) }
    fun picked(action: String, extra: String = "") = ui.picks.any { it.action == action && it.period == period && it.value == g.text && it.extra == extra }
    Column(Modifier.fillMaxWidth().clip(J.rM).border(1.dp, if (picked("tick")) J.acc else if (open) J.acc.copy(alpha = 0.5f) else J.line, J.rM)
        .clickable(role = Role.Button, onClickLabel = if (open) "Close goal" else "Open goal") { ui.open = if (open) null else key }
        .padding(J.sp3), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
            Text(GoalsData.title(g), style = J.bodyText.copy(color = if (g.done) J.muted else J.text,
                textDecoration = if (g.done) TextDecoration.LineThrough else null), modifier = Modifier.weight(1f))  // plain text (123)
            // The one big action: Tick finishes it, the same checkbox as a todo's (126b); the rest are grouped below (22d)
            if (!g.done) Box(Modifier.heightIn(min = J.tap).toggleable(picked("tick"), enabled = !busy, role = Role.Checkbox) {
                toggle(GoalPick("tick", period, g.text)) }.semantics { contentDescription = "Tick ${GoalsData.title(g)}" },
                contentAlignment = Alignment.Center) { CheckMark(picked("tick")) }
        }
        // One bar: the roll up of its parts, else its own count, else its linked todos; then its
        // parent and the days to its due date, counted here (126)
        val under = listOfNotNull(g.parent?.let { "in $it" }, g.due?.let { GoalsData.dueLabel(it, java.time.LocalDate.now()) },
            g.hours?.let { GoalsData.hoursLabel(it.first, it.second) })
            .joinToString("") { " \u00b7 $it" }
        when {
            g.rollup != null -> Bar(g.rollup, 100, "${g.rollup}%$under")
            g.progress != null -> Bar(g.progress.first, g.progress.second, "${g.progress.first}/${g.progress.second}$under")
            g.linked != null -> Bar(g.linked.first, g.linked.second, "${g.linked.first}/${g.linked.second} todos$under")
            !g.done -> Text("No progress yet$under", style = J.cap)
        }
        if (open && !g.done) {
            // Grouped by purpose, the labels in one column (22d, asked 18 Oct): what moves it on,
            // how it is planned, where it belongs; each field opens under its pill
            var targeting by remember(key) { mutableStateOf(false) }
            val p = g.progress
            val gid = g.goal
            val duePick = ui.picks.firstOrNull { it.action == "due" && it.period == period && it.value == g.text }
            val estPick = ui.picks.firstOrNull { it.action == "est" && it.period == period && it.value == g.text }
            val targetPick = ui.picks.firstOrNull { it.action == "target" && it.period == period && it.value == g.text }
            ActionRow("Progress") {
                if (p != null && p.first < p.second && !GoalsData.byHours(g))
                    SmallPill(if (picked("bump")) "+1 \u2713" else "+1", picked("bump"), !busy) { toggle(GoalPick("bump", period, g.text)) }
                // Log time: one amount per goal per Apply (129)
                for ((label, h) in listOf("+30m" to "0.5", "+1h" to "1", "+2h" to "2")) {
                    val on = picked("log", h)
                    SmallPill(if (on) "$label \u2713" else label, on, !busy) {
                        ui.picks.removeAll { it.action == "log" && it.period == period && it.value == g.text && it.extra != h }
                        toggle(GoalPick("log", period, g.text, h))
                    }
                }
            }
            ActionRow("Plan") {
                SmallPill(when {
                    duePick != null -> "Due ${shortDay(duePick.extra)} \u2713"
                    g.due != null -> "Due ${shortDay(g.due)}"
                    else -> "Due"
                }, duePick != null, !busy) { dating = true }
                if (p == null && !GoalsData.byHours(g)) SmallPill(if (targetPick != null) "Target ${targetPick.extra} \u2713" else "Target",
                    targetPick != null || targeting, !busy) { targeting = !targeting; estimating = false }
                SmallPill(if (estPick != null) "Estimate ${estPick.extra}h \u2713" else "Estimate", estPick != null || estimating, !busy) {
                    estimating = !estimating; targeting = false
                }
                if (gid != null) {
                    val linkPicks = ui.picks.count { (it.action == "link" || it.action == "unlink") && it.period == period && it.value == g.text }
                    SmallPill(if (linkPicks > 0) "Todos ($linkPicks)" else "Todos", linking, !busy) { linking = !linking }
                }
            }
            val parents = (ui.snap?.tree?.let { GoalsData.parentsFor(g.goal, it) } ?: emptySet()) - setOfNotNull(g.parent)
            if (parents.isNotEmpty()) ActionRow("Under") {
                for (u in parents.sorted().take(16)) {
                    val on = picked("nest", u)
                    SmallPill(if (on) "$u \u2713" else u, on, !busy) {
                        ui.picks.removeAll { it.action == "nest" && it.period == period && it.value == g.text && it.extra != u }
                        toggle(GoalPick("nest", period, g.text, u))
                    }
                }
            }
            if (targeting) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                OutlinedTextField(ui.targets[key].orEmpty(), { v -> if (v.length <= 4 && v.all { it.isDigit() }) ui.targets[key] = v },
                    Modifier.weight(1f), label = { Text("Target, like 10") }, singleLine = true, enabled = !busy, colors = fieldColors(),
                    shape = fieldShape(oneLine = true), textStyle = J.bodyText, keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Number))
                val n = ui.targets[key].orEmpty()
                Pill("Set", false, !busy && (n.toIntOrNull() ?: 0) in 1..9999) {
                    ui.picks.removeAll { it.action == "target" && it.period == period && it.value == g.text }
                    toggle(GoalPick("target", period, g.text, n)); targeting = false
                }
            }
            if (estimating) Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                val k = "est$key"
                OutlinedTextField(ui.targets[k].orEmpty(), { v -> if (v.length <= 6 && v.all { it.isDigit() || it == '.' }) ui.targets[k] = v },
                    Modifier.weight(1f), label = { Text("Hours, like 6 or 1.5") }, singleLine = true, enabled = !busy, colors = fieldColors(),
                    shape = fieldShape(oneLine = true), textStyle = J.bodyText, keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        keyboardType = androidx.compose.ui.text.input.KeyboardType.Decimal))
                val h = ui.targets[k].orEmpty()
                val ok = GoalsData.body("0".repeat(64), listOf(GoalPick("est", period, g.text, h))) != null
                Pill("Set", false, !busy && ok) {
                    ui.picks.removeAll { it.action == "est" && it.period == period && it.value == g.text }
                    toggle(GoalPick("est", period, g.text, h)); estimating = false
                }
            }
            if (dating) DueSheet(GoalsData.shownText(g.text), duePick?.extra ?: g.due,
                choose = { d ->
                    ui.picks.removeAll { it.action == "due" && it.period == period && it.value == g.text }
                    if (d != g.due) toggle(GoalPick("due", period, g.text, d))
                    dating = false
                }, cancel = { dating = false })
            if (gid != null) {
                // Linked ones first with a check, a tap picks them to unlink (128); the rest with +
                if (linking) for ((list, todo) in todos.flatMap { l -> (l.doing.filter { gid in GoalsData.goalsOf(it) } + l.open).map { l.name to it } }
                        .sortedByDescending { gid in GoalsData.goalsOf(it.second) }.take(16)) {
                    val linked = gid in GoalsData.goalsOf(todo)
                    val action = if (linked) "unlink" else "link"
                    val on = picked(action, todo)
                    Row(Modifier.fillMaxWidth().heightIn(min = J.tap)
                        .clickable(role = Role.Checkbox, enabled = !busy, onClickLabel = if (linked) "Unlink" else "Link") {
                            toggle(GoalPick(action, period, g.text, todo, list)) },
                        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                        val mark = when { linked && on -> "\u2212"; linked -> "\u2713"; on -> "\u2713"; else -> "+" }
                        Text(mark, style = J.bodyText.copy(color = if (linked != on) J.accText else J.muted), modifier = Modifier.widthIn(min = 20.dp))
                        Text(GoalsData.shownText(todo), style = J.sec.copy(color = if (linked && on) J.muted else J.text,
                            textDecoration = if (linked && on) TextDecoration.LineThrough else null), modifier = Modifier.weight(1f))
                        Text(if (linked && on) "unlink" else list, style = J.monoCap)
                    }
                }
            }
        }
    }
}

private fun shortDay(iso: String): String =
    GoalsData.day(iso)?.format(java.time.format.DateTimeFormatter.ofPattern("d MMM", java.util.Locale.ENGLISH)) ?: iso

/** A due date in the app's own sheet: today to ten years ahead, as the laptop checks (126). */
@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
private fun DueSheet(goal: String, current: String?, choose: (String) -> Unit, cancel: () -> Unit) {
    val utc = java.time.ZoneOffset.UTC
    val today = java.time.LocalDate.now()
    val last = today.plusDays(3653)
    val state = androidx.compose.material3.rememberDatePickerState(
        initialSelectedDateMillis = current?.let { GoalsData.day(it) }?.atStartOfDay(utc)?.toInstant()?.toEpochMilli(),
        yearRange = today.year..last.year,
        selectableDates = object : androidx.compose.material3.SelectableDates {
            override fun isSelectableDate(utcTimeMillis: Long): Boolean {
                val d = java.time.Instant.ofEpochMilli(utcTimeMillis).atZone(utc).toLocalDate()
                return !d.isBefore(today) && !d.isAfter(last)
            }
            override fun isSelectableYear(year: Int) = year in today.year..last.year
        })
    JulzSheet(onDismiss = cancel) {
        Column(verticalArrangement = Arrangement.spacedBy(J.sp1)) {
            Text("Due date", style = J.tm)
            Text(goal, style = J.sec)  // plain text (126)
        }
        val c = androidx.compose.material3.DatePickerDefaults.colors(containerColor = Color.Transparent,
            titleContentColor = J.muted, headlineContentColor = J.text, weekdayContentColor = J.muted,
            subheadContentColor = J.muted, navigationContentColor = J.text, yearContentColor = J.text,
            currentYearContentColor = J.acc, selectedYearContentColor = J.bg, selectedYearContainerColor = J.text,
            dayContentColor = J.text, disabledDayContentColor = J.muted.copy(alpha = 0.4f),
            selectedDayContentColor = J.bg, selectedDayContainerColor = J.text,
            todayContentColor = J.acc, todayDateBorderColor = J.acc, dividerColor = J.line)
        androidx.compose.material3.DatePicker(state, Modifier.bleed(J.gutter), title = null, headline = null,
            showModeToggle = false, colors = c)
        val picked = state.selectedDateMillis?.let { java.time.Instant.ofEpochMilli(it).atZone(utc).toLocalDate().toString() }
        if (picked != null) GlowButton("Due ${shortDay(picked)}") { choose(picked) }
        PlainButton("Cancel", color = J.muted, onClick = cancel)
    }
}

@Composable
private fun Bar(n: Int, m: Int, label: String) {
    val f = if (m > 0) (n.toFloat() / m).coerceIn(0f, 1f) else 0f
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
        Box(Modifier.weight(1f).height(6.dp).clip(RoundedCornerShape(3.dp)).background(J.raise)) {
            Box(Modifier.fillMaxWidth(f).fillMaxHeight().clip(RoundedCornerShape(3.dp)).background(J.acc))
        }
        Text(label, style = J.monoCap)
    }
}

/** One labelled group of a goal's actions (22d): a small caption over its pills, so the pills
 *  have the card's whole width and a group stays on one line (a label column left too little). */
@Composable
private fun ActionRow(label: String, content: @Composable () -> Unit) {
    Column(Modifier.fillMaxWidth()) {
        Text(label, style = J.cap, modifier = Modifier.padding(start = J.sp1))
        androidx.compose.foundation.layout.FlowRow(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(J.sp1),
            itemVerticalAlignment = Alignment.CenterVertically) { content() }
    }
}

/** A secondary action: looks 36 dp tall, still a 48 dp target to the finger (Material's
 *  minimum), so a goal's actions sit close without being harder to hit (22d). */
@Composable
private fun SmallPill(label: String, on: Boolean, enabled: Boolean, onClick: () -> Unit) {
    Box(Modifier.minimumInteractiveComponentSize().clickable(role = Role.Button, enabled = enabled, onClick = onClick)
        .heightIn(min = 36.dp).clip(J.pill)
        .background(if (on && !J.outline) J.text else J.raise)
        .border(1.dp, if (on && J.outline) J.acc else J.line, J.pill)
        .padding(horizontal = J.sp3), contentAlignment = Alignment.Center) {
        Text(label, style = J.cap.copy(color = if (!on) J.text else if (J.outline) J.accText else J.bg, fontWeight = FontWeight(600)),
            maxLines = 1)
    }
}

@Composable
internal fun Pill(label: String, on: Boolean, enabled: Boolean, onClick: () -> Unit) {
    Box(Modifier.heightIn(min = J.tap).widthIn(min = 64.dp).clip(J.pill)
        .background(if (on && !J.outline) J.text else J.raise)
        .border(1.dp, if (on && J.outline) J.acc else J.line, J.pill)
        .clickable(role = Role.Button, enabled = enabled, onClick = onClick).padding(horizontal = J.sp4),
        contentAlignment = Alignment.Center) {
        Text(label, style = J.sec.copy(color = if (!on) J.text else if (J.outline) J.accText else J.bg, fontWeight = FontWeight(600)))
    }
}
