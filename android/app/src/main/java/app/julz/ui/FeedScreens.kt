package app.julz.ui

import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import app.julz.feed.shown
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.julz.feed.Kind
import app.julz.feed.Notice

private const val DAY = 86_400L

/** Calendar days in the phone's zone, the same for the week strip and History. */
object Days {
    fun ago(time: Long, now: Long, zone: java.time.ZoneId = java.time.ZoneId.systemDefault()): Int {
        fun day(t: Long) = java.time.Instant.ofEpochSecond(t).atZone(zone).toLocalDate()
        return java.time.temporal.ChronoUnit.DAYS.between(day(time), day(now)).toInt().coerceAtLeast(0)
    }

    /** A day's bar as a part of its full height: the busiest day of the week is full, a quiet
     *  week (at most 3 a day) never fills one, and a single notice stays visible. */
    fun bar(count: Int, week: List<Int>): Float {
        if (count <= 0) return 0f
        return (count.toFloat() / maxOf(3, week.maxOrNull() ?: 0)).coerceIn(0.15f, 1f)
    }
}

/** The quiet line above the notices (22c): what is unread among what I see, and the actions for
 *  exactly those, so Read all and Clear always act on the same notices, filter or not. */
object FeedLine {
    data class Line(val text: String, val unread: List<Notice>, val clear: Boolean)

    /** Now lists no notices: it says how many wait and leads to Messages */
    fun now(notices: List<Notice>, read: ReadState): Line? {
        val unread = notices.filter { !read.isRead(it.id) }
        return if (unread.isEmpty()) null else Line("${unread.size} unread", unread, clear = false)
    }

    fun messages(shown: List<Notice>, read: ReadState): Line? {
        if (shown.isEmpty()) return null
        val unread = shown.filter { !read.isRead(it.id) }
        return Line(if (unread.isEmpty()) "All read" else "${unread.size} unread", unread, clear = true)
    }
}

/** On a row that scrolls sideways inside the pager (History's days, Messages' filters): what
 *  the row could not scroll stays with it, so a drag that starts on the row never turns the
 *  page; up and down still go to the page. */
object KeepSideways : androidx.compose.ui.input.nestedscroll.NestedScrollConnection {
    override fun onPostScroll(consumed: androidx.compose.ui.geometry.Offset, available: androidx.compose.ui.geometry.Offset,
                              source: androidx.compose.ui.input.nestedscroll.NestedScrollSource) = available.copy(y = 0f)

    override suspend fun onPostFling(consumed: androidx.compose.ui.unit.Velocity, available: androidx.compose.ui.unit.Velocity) =
        available.copy(y = 0f)
}

/** Feed: Now, Messages, History. Everything shown comes from the checked feed store. */
@Composable
fun FeedScreen(notices: List<Notice>, read: ReadState, lastContact: Long, tab: Int, onTab: (Int) -> Unit, inboxCount: Int?,
               filter: Kind?, setFilter: (Kind?) -> Unit,
               open: (Notice) -> Unit, markRead: (List<Notice>) -> Unit, approve: (Notice) -> Unit,
               todos: () -> Unit, inbox: () -> Unit, feedback: () -> Unit, cleared: ReadState, setCleared: (ReadState) -> Unit) {
    var historyDay by remember { mutableIntStateOf(0) }
    // Messages: what the last Clear hid, for Undo (the filter lives in App, so a tap can set it)
    var undo by remember { mutableStateOf<Pair<ReadState, Int>?>(null) }
    val kept = notices.filter { !cleared.isRead(it.id) }
    val shown = kept.filter { filter == null || it.kind == filter }
    // A swipe pages the three tabs (22c); tab stays the one truth, so a notification tap still
    // opens Messages, and the pager follows it, jumping when the phone's animations are off
    val pager = androidx.compose.foundation.pager.rememberPagerState(initialPage = tab) { 3 }
    val still = stillMotion()
    androidx.compose.runtime.LaunchedEffect(tab) {
        if (pager.currentPage != tab) { if (still) pager.scrollToPage(tab) else pager.animateScrollToPage(tab) }
    }
    val current by androidx.compose.runtime.rememberUpdatedState(tab)
    val setTab by androidx.compose.runtime.rememberUpdatedState(onTab)
    androidx.compose.runtime.LaunchedEffect(pager) {
        androidx.compose.runtime.snapshotFlow { pager.settledPage }.collect { if (it != current) setTab(it) }
    }
    Column(Modifier.fillMaxSize()) {
      Column(Modifier.padding(horizontal = J.gutter)) {
        // In landscape the title, the tabs and Feedback share one line, so the notices keep the height (22d)
        val wide = J.rail
        val tabs = @Composable { m: Modifier ->
            Segmented(listOf("Now", "Messages", "History"), pager.currentPage,
                { pager.currentPage + pager.currentPageOffsetFraction }, m, onTab)
        }
        // Who and how it is going, and Feedback: nothing here changes its job (22c)
        Row(Modifier.fillMaxWidth().padding(top = if (wide) J.sp3 else J.sp6, bottom = if (wide) J.sp3 else J.sp4),
            verticalAlignment = Alignment.CenterVertically) {
            Column(if (wide) Modifier else Modifier.weight(1f)) {
                Text("Julz", style = J.tl)
                val ago = System.currentTimeMillis() / 1000 - lastContact
                Text(when {
                    lastContact == 0L -> "not connected yet"
                    ago < 15 * 60 -> "live · laptop"
                    else -> "laptop not reachable since " + Words.time(lastContact)
                }, style = J.monoCap)
            }
            if (wide) { Spacer(Modifier.width(J.sp6)); tabs(Modifier.weight(1f)); Spacer(Modifier.width(J.sp4)) }
            // Feedback, one tap from the Feed (E, 120)
            RoundButton(Icons.feedback, "Feedback", feedback)
        }
        if (!wide) { tabs(Modifier); Spacer(Modifier.height(J.sp4)) }
      }
        // Pages are built as they come: building the neighbours ahead was measured worse, 6 janky
        // frames of 644 over ten swipes instead of 3 (18 Oct)
        androidx.compose.foundation.pager.HorizontalPager(pager, Modifier.weight(1f),
            verticalAlignment = Alignment.Top) { page ->
            Column(Modifier.fillMaxSize().padding(horizontal = J.gutter)) {
                when (page) {
                    // See them shows every unread one: a filter left by a notification tap hid them (22d)
                    0 -> Now(notices, read, open, approve, todos, inbox, inboxCount, { setFilter(null); onTab(1) }) { d -> historyDay = d; onTab(2) }
                    1 -> Messages(kept, shown, read, open, filter, setFilter, markRead, clear = {
                            undo = cleared to shown.size
                            markRead(shown)
                            setCleared(cleared.with(shown.map { it.id }))
                        }, undo?.let { it.second }) { undo?.let { setCleared(it.first) }; undo = null }
                    else -> History(notices, open, historyDay) { historyDay = it }
                }
            }
        }
    }
}

/** One quiet line above a list: what is there, and the actions for exactly that (22c). */
@Composable
private fun QuietLine(text: String, actions: @Composable () -> Unit) {
    Row(Modifier.fillMaxWidth().heightIn(min = J.tap), verticalAlignment = Alignment.CenterVertically) {
        Text(text, style = J.monoCap, modifier = Modifier.weight(1f))
        actions()
    }
}

@Composable
private fun TextAction(label: String, onClick: () -> Unit) {
    Box(Modifier.heightIn(min = J.tap).clip(J.rS).clickable(role = Role.Button, onClick = onClick)
        .padding(horizontal = J.sp3), contentAlignment = Alignment.Center) {
        Text(label, style = J.sec.copy(color = J.accText, fontWeight = FontWeight(700)))
    }
}

@Composable
private fun Now(notices: List<Notice>, read: ReadState, open: (Notice) -> Unit, approve: (Notice) -> Unit,
                todos: () -> Unit, inbox: () -> Unit, inboxCount: Int?, messages: () -> Unit, showDay: (Int) -> Unit) {
    val now = System.currentTimeMillis() / 1000
    val week = notices.filter { Days.ago(it.time, now) < 7 }
    val waiting = notices.firstOrNull { it.kind == Kind.APPROVAL && !read.isRead(it.id) }
    Column(Modifier.verticalScroll(rememberScrollState()).padding(bottom = J.end),
        verticalArrangement = Arrangement.spacedBy(J.gap)) {
        // How many wait, one tap from the list that shows them
        FeedLine.now(notices, read)?.let { QuietLine(it.text) { TextAction("See them", messages) } }
        if (waiting != null) {
            Column(Modifier.fillMaxWidth().assemble(key = "now-hero").clip(J.rL).background(J.heroBrush).padding(J.inset),
                verticalArrangement = Arrangement.spacedBy(J.sp4)) {
                Text("needs you · since " + Words.time(waiting.time), style = J.monoCap.copy(color = J.onAcc))
                Text(waiting.title, style = J.tm.copy(color = J.onAcc))
                GlowButton("Review and approve") { approve(waiting) }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
            Tile(Modifier.weight(1f).clickable(role = Role.Button, onClickLabel = "Open History") { showDay(0) },
                week.size.toString(), "This week", "notices from the laptop")
            val lists = notices.firstOrNull { it.kind == Kind.TODO }?.let { app.julz.feed.TodoSnapshot.parse(it.message) }
            Tile(Modifier.weight(1f).clickable(role = Role.Button, onClickLabel = "Open todos", onClick = todos),
                (lists?.sumOf { it.open.size + it.doing.size } ?: 0).toString(), "Todos open",
                lists?.joinToString(" · ") { "${app.julz.feed.TodoSnapshot.listLabel(it.name)} ${it.done}/${it.total}" }?.ifEmpty { "all done" } ?: "no snapshot yet")
        }
        Column(Modifier.fillMaxWidth().assemble(key = "now-week").glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp4)) {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                val counts = (6 downTo 0).map { d -> week.count { Days.ago(it.time, now) == d } }
                for ((i, d) in (6 downTo 0).withIndex()) {
                    val date = java.util.Date((now - d * DAY) * 1000)
                    val count = counts[i]
                    // The whole column is the tap target; TalkBack says the day and the count
                    Column(Modifier.weight(1f).clip(J.rS)
                        .clickable(role = Role.Button, onClickLabel = "Open this day in History") { showDay(d) }
                        .semantics(mergeDescendants = true) {
                            contentDescription = java.text.SimpleDateFormat("EEEE").format(date) +
                                ", " + if (count == 1) "1 notice" else "$count notices"
                        }.padding(vertical = J.sp2),
                        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(J.sp2)) {
                        Box(Modifier.width(10.dp).height(56.dp).clip(RoundedCornerShape(5.dp)).background(J.raise),
                            contentAlignment = Alignment.BottomCenter) {
                            val part = Days.bar(count, counts)
                            if (part > 0f) Box(Modifier.fillMaxWidth().fillMaxHeight(part).clip(RoundedCornerShape(5.dp))
                                .background(if (d == 0) J.acc else J.text))
                        }
                        Text(java.text.SimpleDateFormat("EEEEE").format(date),
                            style = J.cap.copy(color = if (d == 0) J.accText else J.muted))
                    }
                }
            }
            Text("Your week", style = J.item)
        }
        // Always there: opens the Inbox screen (D) and says how many notes wait there now
        Row(Modifier.fillMaxWidth().assemble(key = "now-inbox").glass().clickable(role = Role.Button, onClickLabel = "Open Inbox") {
                inbox()
            }.padding(J.inset),
            verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
            KindIcon(Kind.INBOX)
            Column(Modifier.weight(1f)) {
                Text("Inbox", style = J.item)
                Text(app.julz.feed.InboxSnapshot.line(inboxCount), style = J.sec)
            }
        }
        if (notices.isEmpty()) Text("Nothing yet. Julz will tell you when something comes up.", style = J.sec)
    }
}

@Composable
private fun Tile(modifier: Modifier, number: String, title: String, sub: String) {
    Column(modifier.assemble(key = "tile-$title").glass().heightIn(min = 150.dp).padding(J.inset), verticalArrangement = Arrangement.SpaceBetween) {
        Text(number, style = J.hero)
        Spacer(Modifier.height(J.sp4))
        Text(title, style = J.item)
        Text(sub, style = J.sec)
    }
}

@Composable
private fun Messages(kept: List<Notice>, shown: List<Notice>, read: ReadState, open: (Notice) -> Unit,
                     filter: Kind?, setFilter: (Kind?) -> Unit, markRead: (List<Notice>) -> Unit, clear: () -> Unit,
                     clearedCount: Int?, undo: () -> Unit) {
    // One wheel for the filters (251): All and only the kinds that have notices, each with its
    // count; the chosen one stays in the middle, so a tap on a warning shows Warnings there (22d)
    val kinds = Wheel.kinds(kept.map { it.kind }.toSet(), filter)
    WheelPicker(kinds.map { if (it == null) "All" else Words.label(it) }, kinds.indexOf(filter).coerceAtLeast(0),
        // Narrower than the tabs above, centred: a filter, not a second tab bar (my note 26 Oct)
        Modifier.padding(bottom = J.sp3).fillMaxWidth().wrapContentWidth().widthIn(max = 280.dp), counts = kinds.map { k -> kept.count { k == null || it.kind == k } }) { setFilter(kinds[it]) }
    // Read all and Clear act on what the filter shows; Clear hides, History keeps them
    FeedLine.messages(shown, read)?.let { line ->
        QuietLine(line.text) {
            if (line.unread.isNotEmpty()) TextAction("Read all") { markRead(line.unread) }
            TextAction("Clear", clear)
        }
    }
    clearedCount?.let { count ->
        Row(Modifier.fillMaxWidth().glass(J.rM).padding(start = J.sp5).heightIn(min = 56.dp),
            verticalAlignment = Alignment.CenterVertically) {
            Text("Cleared $count. They stay in History.", style = J.sec.copy(color = J.text), modifier = Modifier.weight(1f))
            Text("Undo", style = J.bodyText.copy(color = J.accText, fontWeight = FontWeight(700)),
                modifier = Modifier.heightIn(min = 48.dp).clickable(role = Role.Button, onClick = undo)
                    .padding(horizontal = J.sp5, vertical = J.sp3))
        }
        Spacer(Modifier.height(J.sp3))
    }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(J.rowGap), contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = J.end)) {
        var lastDay = ""
        for (n in shown) {
            val day = Words.day(n.time)
            if (day != lastDay) {
                lastDay = day
                item(key = "day-$day") { Box(Modifier.padding(top = J.sp4, bottom = J.sp1)) { SectionTitle(day) } }
            }
            item(key = n.id) {
                val unread = !read.isRead(n.id)
                // A sideways swipe pages the tabs (22c): a notice is read by opening it, or Read all
                Row(Modifier.fillMaxWidth().background(J.bg, J.rM).glass(J.rM, if (unread) J.acc.copy(alpha = 0.4f) else J.line)
                    .clickable(role = Role.Button) { open(n) }.heightIn(min = J.row).padding(J.sp3),
                    verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
                    // At big text the badge steps aside: the title needs the width (22f, as in Tools)
                    if (!J.big) KindIcon(n.kind)
                    Column(Modifier.weight(1f)) {
                        // The short title as History says it, the id under the time (22d integrity)
                        val (title, id) = Words.shortTitle(n.title)
                        Row(verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
                            // plain text, never a link (91); one title style, heavier only when unread
                            Text(title, style = if (unread) J.itemUnread else J.item, modifier = Modifier.weight(1f))
                            Text(Words.time(n.time), style = J.monoCap, modifier = Modifier.padding(top = 2.dp))
                        }
                        Text(n.shown, style = J.sec, maxLines = 2)
                        // The id on its own quiet line, not bundled with the time (22d)
                        if (Look.prefs.showIds) id?.let { Text(it, style = J.monoCap.copy(color = J.faint), maxLines = 1, softWrap = false,
                            modifier = Modifier.padding(top = J.sp1)) }
                    }
                }
            }
        }
        if (shown.isEmpty()) item {
            Text(if (filter == null) "All clear. Older notices are in History." else "Nothing in this channel.", style = J.sec)
        }
    }
}
