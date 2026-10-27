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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.julz.feed.FeedStore
import app.julz.feed.shown
import app.julz.feed.Kind
import app.julz.feed.Notice

/** What History shows for one day (22d, asked 18 Oct): every stored day, not a week; a time
 *  only when the minute changes; the day's last todo snapshot with the earlier ones behind it. */
object HistoryDay {
    /** As long as the feed keeps notices: 23 of 30 days were stored but out of reach */
    val DAYS = (FeedStore.KEEP_SECONDS / 86_400).toInt()

    data class Entry(val notice: Notice, val showTime: Boolean, val earlier: List<Notice>)

    /** Notices per day, index = days ago */
    fun counts(notices: List<Notice>, now: Long, zone: java.time.ZoneId = java.time.ZoneId.systemDefault()): IntArray {
        val out = IntArray(DAYS)
        for (n in notices) Days.ago(n.time, now, zone).takeIf { it < DAYS }?.let { out[it]++ }
        return out
    }

    fun entries(notices: List<Notice>, daysBack: Int, now: Long,
                zone: java.time.ZoneId = java.time.ZoneId.systemDefault()): List<Entry> {
        val day = notices.filter { Days.ago(it.time, now, zone) == daysBack }.sortedByDescending { it.time }
        val todos = day.filter { it.kind == Kind.TODO }
        val last = todos.firstOrNull()
        var minute = Long.MIN_VALUE
        return day.filter { it.kind != Kind.TODO || it === last }.map { n ->
            val m = n.time / 60
            Entry(n, m != minute, if (n === last) todos.drop(1) else emptyList()).also { minute = m }
        }
    }
}

private const val DAY = 86_400L

@Composable
internal fun History(notices: List<Notice>, open: (Notice) -> Unit, daysBack: Int, pick: (Int) -> Unit) {
    val now = System.currentTimeMillis() / 1000
    // Worked out again when the date changes too: open past midnight, today stayed yesterday (22d)
    val today = Days.ago(0, now)
    val counts = remember(notices, today) { HistoryDay.counts(notices, now) }
    // Today at the right end, older days to the left, as far back as notices are kept
    val strip = rememberLazyListState()
    // The strip moves only when the chosen day is out of view: tapping Saturday pushed today away
    LaunchedEffect(daysBack) {
        val seen = strip.layoutInfo.visibleItemsInfo
        val inView = seen.any { it.index == daysBack && it.offset >= 0 && it.offset + it.size <= strip.layoutInfo.viewportEndOffset }
        if (!inView) strip.animateScrollToItem(daysBack)
    }
    LazyRow(Modifier.fillMaxWidth().nestedScroll(KeepSideways).padding(bottom = J.sp4), state = strip, reverseLayout = true,
        horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
        items(HistoryDay.DAYS) { d ->
            val on = d == daysBack
            val t = now - d * DAY
            val count = counts[d]
            val ink = if (on) J.onAccFill else if (count == 0) J.faint else J.muted
            // The other days in the cards' family: glass and a hairline; the chosen one in the accent's fill (267)
            Column(Modifier.width(64.dp).heightIn(min = if (on) 100.dp else 84.dp).clip(J.pill)
                .then(if (on) Modifier.background(J.accFill) else Modifier.background(J.surface).border(1.dp, J.line, J.pill))
                .clickable(role = Role.Tab, onClickLabel = "$count notices") { pick(d) },
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
                val c = java.util.Calendar.getInstance().apply { timeInMillis = t * 1000 }
                Text(c.get(java.util.Calendar.DAY_OF_MONTH).toString(), style = J.ts.copy(fontFamily = J.display, color = ink))
                Text(java.text.SimpleDateFormat("EEE").format(java.util.Date(t * 1000)), style = J.cap.copy(color = ink))
                // How much happened that day, so a quiet day reads as quiet before the tap
                Text(if (count == 0) "·" else count.toString(), style = J.monoCap.copy(color = ink))
            }
        }
    }
    val entries = remember(notices, daysBack, today) { HistoryDay.entries(notices, daysBack, now) }
    // Which days' earlier snapshots are open; kept when rows scroll away and back
    var unfolded by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(listOf<String>()) }
    LazyColumn(verticalArrangement = Arrangement.spacedBy(J.gap),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(bottom = J.end)) {
        for (e in entries) {
            item(key = e.notice.id) {
                HistoryRow(if (e.showTime) Words.time(e.notice.time) else "") {
                    HistoryCard(e.notice, open)
                    if (e.earlier.isNotEmpty()) {
                        val shown = e.notice.id in unfolded
                        Text(if (shown) "Hide earlier" else "+${e.earlier.size} earlier",
                            style = J.sec.copy(color = J.accText, fontWeight = FontWeight(600)),
                            modifier = Modifier.heightIn(min = J.tap).clickable(role = Role.Button) {
                                unfolded = if (shown) unfolded - e.notice.id else unfolded + e.notice.id
                            }.padding(horizontal = J.sp2, vertical = J.sp3))
                    }
                }
            }
            // Open, the earlier snapshots are rows like any other, in the list's own time column
            // (22d integrity: they sat nested in the card's column, with their own time style)
            if (e.notice.id in unfolded) items(e.earlier, key = { it.id }) { n ->
                HistoryRow(Words.time(n.time)) { HistoryCard(n, open) }
            }
        }
        if (entries.isEmpty()) item { Text("Nothing on this day.", style = J.sec) }
    }
}

/** One row of History: the time column and what it holds, the same for every row, earlier
 *  snapshots included (22d integrity: they had their own font, colour and indent). At big
 *  text the time stands above, so the card keeps the width (22f). */
@Composable
private fun HistoryRow(time: String, content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) {
    androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(J.sp3),
        maxItemsInEachRow = if (J.big) 1 else 2) {
        // In line with the card's first row; a time is never broken: "11:3 / 2" at 200 percent (22d)
        Text(time, style = J.time, maxLines = 1, softWrap = false, modifier = Modifier.widthIn(min = 56.dp).padding(top = J.sp3))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(J.sp2), content = content)
    }
}

/** One notice, all in one family (22d, Saturday's look, asked 18 Oct): dark glass with a line
 *  and a glow in its kind's colour. A warning or an approval is the same card, stronger: a
 *  brighter line, a wider glow, tinted glass, so what needs me stands out (Von Restorff)
 *  without a full block of colour. Look and feel's "History as bright cards" colours them all. */
@Composable
private fun HistoryCard(n: Notice, open: (Notice) -> Unit) {
    val (title, id) = Words.shortTitle(n.title)
    val tint = J.tint(n.kind)
    val loud = Look.prefs.brightHistory
    val strong = n.kind == Kind.WARNING || n.kind == Kind.APPROVAL
    val ink = if (loud) J.onPastel else J.text
    val card = if (loud) Modifier.clip(J.rL).background(tint) else Modifier.kindCard(tint, strong)
    // Compact (asked 2026-10-18): the kind is a small pill inside the card, on the line with the
    // short id; the card is sized to what it says
    Column(Modifier.fillMaxWidth().then(card).clickable(role = Role.Button) { open(n) }
        .padding(horizontal = J.sp4, vertical = J.sp3), verticalArrangement = Arrangement.spacedBy(J.sp1)) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
            Tag(Words.status(n.kind), if (loud) J.onPastel else tint)
            Box(Modifier.weight(1f))
            if (Look.prefs.showIds) id?.let { Text(it, style = J.monoCap.copy(color = if (loud) J.onPastelFaint else J.faint), maxLines = 1, softWrap = false) }
        }
        // Tighter lines than body text: a history card is read at a glance
        Text(title, style = J.cardTitle.copy(color = ink))
        Text(n.shown, style = J.cardText.copy(color = if (loud) J.onPastelSoft else J.muted), maxLines = 2)
    }
}
