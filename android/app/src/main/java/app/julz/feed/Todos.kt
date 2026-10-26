package app.julz.feed

import org.json.JSONArray
import org.json.JSONObject

data class TodoList(val name: String, val done: Int, val total: Int, val open: List<String>,
                    val doneItems: List<String> = emptyList(), val doing: List<String> = emptyList())

/** The tasks the laptop sends as one todo notice (SECURITY.md threats 100, 113, 127). v3: a head
 *  `v3\u241F<snapshot id>`, then records `name\u241Fdone\u241Ftotal\u241Fopen count\u241Fin progress
 *  count\u241Fopen\u2026\u241Fin progress\u2026\u241Fdone\u2026` joined by \u241E. v2, without the in progress
 *  count, still reads (older notices). Anything off shape drops the whole snapshot. */
object TodoSnapshot {
    private const val LISTS = "\u241E"
    private const val FIELDS = "\u241F"
    private const val MAX_TASK = 80  // the words; the tags Goals reads apart do not count (113b)
    private const val MAX_LINE = 160
    const val MAX_PICKS = 20
    private val NAME = Regex("\\w[\\w .-]{0,39}")
    private val ID = Regex("[0-9a-f]{64}")
    private val VERSIONS = setOf("v2", "v3")

    /** A task as the laptop lets it travel: words to 80 without the tags, the line to 160 (100, 113b) */
    fun task(s: String) = s.isNotBlank() && s.length <= MAX_LINE && GoalsData.shownText(s).length <= MAX_TASK

    /** The snapshot id the laptop signs a tick against, or null. */
    /** A list's file name as words for the screen (126b): get_job reads Get job. */
    fun listLabel(name: String): String =
        name.replace('_', ' ').replace('-', ' ').split(' ').filter { it.isNotEmpty() }.joinToString(" ")
            .replaceFirstChar { it.uppercase() }

    fun id(message: String): String? {
        val head = message.substringBefore(LISTS).split(FIELDS)
        return head.getOrNull(1)?.takeIf { head.size == 2 && head[0] in VERSIONS && ID.matches(it) && parse(message) != null }
    }

    fun parse(message: String): List<TodoList>? {
        if (message == "none") return emptyList()
        val records = message.split(LISTS)
        val head = records[0].split(FIELDS)
        if (records.size < 2 || head.size != 2 || head[0] !in VERSIONS || !ID.matches(head[1])) return null
        val v3 = head[0] == "v3"
        val first = if (v3) 5 else 4  // where the tasks begin
        return records.drop(1).map { record ->
            val f = record.split(FIELDS)
            if (f.size < first + 1) return null
            val name = f[0]
            val (done, total, count) = Triple(f[1].toIntOrNull(), f[2].toIntOrNull(), f[3].toIntOrNull())
            val doingCount = if (v3) f[4].toIntOrNull() else 0
            if (!NAME.matches(name) || done == null || total == null || count == null || doingCount == null ||
                done < 0 || done > total || count < 0 || doingCount < 0 || count + doingCount < 1 ||
                first + count + doingCount > f.size) return null
            val tasks = f.drop(first)
            if (tasks.any { !task(it) }) return null
            val open = tasks.take(count)
            val doing = tasks.drop(count).take(doingCount)
            val doneItems = tasks.drop(count + doingCount)
            if (doneItems.size > done) return null
            TodoList(name, done, total, open, doneItems, doing)
        }
    }

    /** The snapshot as words for the feed: one line per list. Off shape gives nothing, never the
     *  raw record. */
    fun summary(message: String): String {
        val lists = parse(message) ?: return ""
        if (lists.isEmpty()) return "No open todos"
        return lists.joinToString("\n") { l ->
            "${listLabel(l.name)} ${l.done}/${l.total}: " + (l.open + l.doing.map { "$it (in progress)" }).joinToString(", ")
        }
    }

    /** What the app sends to begin a tick, or a start (127): the snapshot id it saw and (list,
     *  task) pairs, never a path or other text. The laptop builds the text to sign from its own
     *  snapshot (113). */
    fun tickBody(id: String, picks: List<Pair<String, String>>, action: String = "tick"): JSONObject? {
        if (action !in setOf("tick", "start") || !ID.matches(id) || picks.isEmpty() || picks.size > MAX_PICKS) return null
        val pick = JSONArray()
        for ((list, item) in picks) pick.put(JSONObject().put("list", list).put("item", item))
        return JSONObject().put("action", action).put("sha256", id).put("pick", pick).put("via", "device")
    }
}

/** A notice's text as the screens show it: a todo snapshot as words, anything else as it came. */
val Notice.shown: String get() = if (kind == Kind.TODO) TodoSnapshot.summary(message) else message

data class DoneDay(val date: String, val items: List<Pair<String, String>>)

/** The Done tab (SECURITY.md 114): a week of ticked tasks from the approver's /api/done, checked
 *  again here. Off shape gives null, never part of a week. */
object DoneWeek {
    private const val MAX_DAYS = 7
    private const val MAX_ITEMS = 60
    private val DATE = Regex("\\d{4}-\\d{2}-\\d{2}")
    private val HIDDEN = Regex("[\\p{Cc}\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}]")

    private fun plain(s: String) = TodoSnapshot.task(s) && !HIDDEN.containsMatchIn(s)

    fun parse(raw: String): List<DoneDay>? {
        val days = try { JSONObject(raw).getJSONArray("days") } catch (e: Exception) { return null }
        if (days.length() > MAX_DAYS) return null
        var count = 0
        return (0 until days.length()).map { i ->
            val d = days.optJSONObject(i) ?: return null
            val date = d.optString("date"); val items = d.optJSONArray("items") ?: return null
            if (!DATE.matches(date)) return null
            DoneDay(date, (0 until items.length()).map { j ->
                val it = items.optJSONObject(j) ?: return null
                val list = it.optString("list"); val item = it.optString("item")
                if (!plain(list) || !plain(item) || ++count > MAX_ITEMS) return null
                list to item
            })
        }
    }

    /** Today, Yesterday, else a short date like "Thu 15 Oct". */
    fun label(date: String, today: java.time.LocalDate): String {
        val d = runCatching { java.time.LocalDate.parse(date) }.getOrNull() ?: return date
        return when (d) {
            today -> "Today"
            today.minusDays(1) -> "Yesterday"
            else -> d.format(java.time.format.DateTimeFormatter.ofPattern("EEE d MMM", java.util.Locale.ENGLISH))
        }
    }
}
