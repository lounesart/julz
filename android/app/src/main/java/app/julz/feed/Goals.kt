package app.julz.feed

import org.json.JSONArray
import org.json.JSONObject

data class GoalItem(val text: String, val done: Boolean, val progress: Pair<Int, Int>?, val goal: String?, val linked: Pair<Int, Int>?,
                    val parent: String? = null, val rollup: Int? = null, val parts: Int = 0, val due: String? = null,
                    val est: Int? = null, val spent: Int? = null, val hours: Pair<Int, Int>? = null)
data class GoalPeriod(val key: String, val label: String, val goals: List<GoalItem>)
/** An open goal with a due date, from any note in goals/ (126). */
data class Milestone(val goal: String, val text: String, val due: String, val rollup: Int?)
data class GoalsSnapshot(val id: String, val periods: List<GoalPeriod>, val tree: Map<String, String?> = emptyMap(),
                         val milestones: List<Milestone> = emptyList())

/** One change I picked: add a goal, tick one, count one up, set its target (extra = the number),
 *  link a todo to it or unlink one (extra = the todo, list = its list), put it under a goal (extra = its id)
 *  give it a due date (extra = YYYY-MM-DD), an estimate or hours logged (extra = hours, 129). */
data class GoalPick(val action: String, val period: String, val value: String, val extra: String = "", val list: String = "")

/** One part of a goal on its page (227): a child goal or a linked todo, its words and, for a child
 *  goal, its own progress as shown on its bar. */
data class GoalPart(val text: String, val done: Boolean, val progress: String? = null)
/** A goal's page, HTB style (227): its words, percent, hours and due date, then what is done and
 *  what is left by name, and counts for parts the phone cannot name. Read only: nothing on it acts. */
data class GoalDetail(val title: String, val percent: Int?, val hours: Pair<Int, Int>?, val due: String?,
                      val done: List<GoalPart>, val left: List<GoalPart>, val unnamedDone: Int, val unnamedLeft: Int, val elsewhere: Int)

/** Goals from the approver's /api/goals (SECURITY.md 123), checked again here, and what the app
 *  sends to begin a signed change. */
object GoalsData {
    private val ID = Regex("[0-9a-f]{64}")
    private val KEY = Regex("\\d{4}(-\\d{2}|-W\\d{2})?")  // a year, month or week; never a day (159)
    private val GOAL_ID = Regex("[a-z0-9][a-z0-9-]{0,39}")
    private val TAG = Regex("\\s*(#goal/[a-z0-9-]+|\\[in:: [a-z0-9-]+\\]|\\[due:: [0-9-]+\\]|\\[(est|spent):: [0-9.]+h\\])")
    private val EST = Regex("\\[est:: (\\d{1,4}(?:\\.\\d{1,2})?)h\\]")
    private val SPENT = Regex("\\[spent:: (\\d{1,4}(?:\\.\\d{1,2})?)h\\]")
    private val HOURS_IN = Regex("\\d{1,3}(\\.(0|25|5|75))?")
    private const val MAX_MINUTES = 9999 * 60

    /** A period key's kind, from its shape: year, month or week; anything else null. */
    fun kindOf(key: String) = when {
        YEAR.matches(key) -> "year"
        MONTH.matches(key) -> "month"
        WEEK.matches(key) -> "week"
        else -> null
    }
    private val YEAR = Regex("\\d{4}")
    private val MONTH = Regex("\\d{4}-\\d{2}")
    private val WEEK = Regex("\\d{4}-W\\d{2}")

    /** Which of week and month the Goals tab shows under the year (223, threat 159): the phone
     *  keeps it for itself and never sends it; read back as month, else week. */
    fun viewOf(stored: String?) = if (stored == "month") "month" else "week"

    /** A card's key beside its label, only when it says something the label does not (223b). */
    fun keyShown(p: GoalPeriod) = p.key != p.label

    /** A goal's page from what the phone holds (227): child goals from the periods it knows (current
     *  and past) and the tree, linked todos from todos.json by their exact #goal/<id> tag. The
     *  laptop's linked n/m counts every tagged todo, also in finished lists the phone never gets,
     *  so the difference is shown as a count; a child goal in a note the phone has not is
     *  "elsewhere". Words go through shownText, as on the cards (123). */
    fun detail(g: GoalItem, periods: List<GoalPeriod>, tree: Map<String, String?>, todos: List<TodoList>): GoalDetail {
        fun pct(x: GoalItem): Int? = x.rollup ?: x.progress?.takeIf { it.second > 0 }?.let { it.first * 100 / it.second } ?: if (x.done) 100 else null
        val children = if (g.goal == null) emptyList() else periods.flatMap { it.goals }.filter { it.parent == g.goal }.distinct()
        val named = children.mapNotNull { it.goal }.toSet()
        val elsewhere = if (g.goal == null) 0 else tree.count { (id, parent) -> parent == g.goal && id !in named }
        val tag = g.goal?.let { Regex("(?<!\\S)#goal/${Regex.escape(it)}(?![a-z0-9-])") }
        fun tagged(items: List<String>) = if (tag == null) emptyList() else items.filter { tag.containsMatchIn(it) }
        val doneTodos = todos.flatMap { tagged(it.doneItems) }.map { GoalPart(shownText(it), true) }
        val leftTodos = todos.flatMap { tagged(it.open + it.doing) }.map { GoalPart(shownText(it), false) }
        val parts = children.map { c ->
            GoalPart(shownText(c.text).let { if (c.progress != null) it.replace(COUNT, "").trim() else it }, c.done,
                c.rollup?.let { "$it%" } ?: c.progress?.let { "${it.first}/${it.second}" })
        }
        val (linkedDone, linkedTotal) = g.linked ?: (0 to 0)
        return GoalDetail(title(g), pct(g), g.hours, g.due,
            parts.filter { it.done } + doneTodos, parts.filterNot { it.done } + leftTodos,
            maxOf(0, linkedDone - doneTodos.size), maxOf(0, linkedTotal - linkedDone - leftTodos.size), elsewhere)
    }

    /** The cards on the Goals tab: the year always, then the picked week or month. */
    fun shown(periods: List<GoalPeriod>, view: String) =
        periods.filter { kindOf(it.key) == "year" } + periods.filter { kindOf(it.key) == view }

    private val COUNT = Regex("\\s*\\(\\d{1,4}/\\d{1,4}\\)")

    /** An estimate makes hours logged the goal's measure, as the laptop's roll up does (126b). */
    fun byHours(g: GoalItem) = (g.hours?.second ?: 0) > 0

    /** A goal's words for the screen: no tags, and no (n/m) once hours are its measure (126b). */
    fun title(g: GoalItem) = shownText(g.text).let { if (byHours(g)) it.replace(COUNT, "").trim() else it }

    /** Minutes as short hours: 135 of 420 is "2.25/7h"; logged without an estimate "1.5h". */
    fun hoursLabel(spent: Int, est: Int): String {
        fun h(m: Int) = java.math.BigDecimal(m).divide(java.math.BigDecimal(60), 2, java.math.RoundingMode.HALF_UP).stripTrailingZeros().toPlainString()
        return if (est > 0) "${h(spent)}/${h(est)}h" else "${h(spent)}h"
    }

    /** A todo's own [spent:: ] and [est:: ] as minutes, for its quiet line, or null. */
    fun todoHours(text: String): Pair<Int, Int>? {
        fun m(r: Regex) = r.find(text)?.groupValues?.get(1)?.toDoubleOrNull()?.let { Math.round(it * 60).toInt() }?.takeIf { it in 1..MAX_MINUTES }
        val s = m(SPENT); val e = m(EST)
        return if (s == null && e == null) null else (s ?: 0) to (e ?: 0)
    }
    private val DAY = Regex("\\d{4}-\\d{2}-\\d{2}")

    /** A real calendar day in ISO form, or null. */
    fun day(s: String): java.time.LocalDate? = if (!DAY.matches(s)) null else
        try { java.time.LocalDate.parse(s) } catch (e: java.time.format.DateTimeParseException) { null }

    /** Days to a due date, short to sit by a bar, counted on the phone from today, never taken
     *  from the snapshot (126). */
    fun dueLabel(due: String, today: java.time.LocalDate): String {
        val d = day(due) ?: return ""
        val n = java.time.temporal.ChronoUnit.DAYS.between(today, d)
        return when {
            n == 0L -> "due today"
            n > 0 -> "${n}d left"
            else -> "${-n}d late"
        }
    }
    private val HIDDEN = Regex("[\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}\\p{Cc}]")

    private fun pair(a: JSONArray?): Pair<Int, Int>? = a?.takeIf { it.length() == 2 }?.let { it.optInt(0) to it.optInt(1) }

    fun parse(raw: String): GoalsSnapshot? {
        val j = try { JSONObject(raw) } catch (e: Exception) { return null }
        val id = j.optString("id"); val ps = j.optJSONArray("periods") ?: return null
        if (!(ID.matches(id) || (id.isEmpty() && ps.length() == 0)) || ps.length() > 3) return null
        val t = j.optJSONObject("tree") ?: JSONObject()
        if (t.length() > 500) return null
        val tree = t.keys().asSequence().associateWith { k -> if (t.isNull(k)) null else t.optString(k) }
        if (tree.any { (k, v) -> !GOAL_ID.matches(k) || (v != null && !GOAL_ID.matches(v)) }) return null
        val ms = j.optJSONArray("milestones") ?: JSONArray()
        if (ms.length() > 20) return null
        val milestones = (0 until ms.length()).map { i ->
            val m = ms.optJSONObject(i) ?: return null
            val goal = m.optString("goal"); val text = m.optString("text"); val due = m.optString("due")
            val rollup = if (m.isNull("rollup")) null else m.optInt("rollup", -1)
            if (!GOAL_ID.matches(goal) || text.isEmpty() || text.length > 180 || HIDDEN.containsMatchIn(text) || day(due) == null ||
                (rollup != null && rollup !in 0..100)) return null
            Milestone(goal, text, due, rollup)
        }
        return GoalsSnapshot(id, periodsOf(ps) ?: return null, tree, milestones)
    }

    /** Open goals from the periods just before the current ones, for a read only card (126b(3),
     *  SECURITY.md 157): only the periods key, the same checks per period and goal, none done. */
    fun parsePast(raw: String): List<GoalPeriod>? {
        val j = try { JSONObject(raw) } catch (e: Exception) { return null }
        if (j.keys().asSequence().toSet() != setOf("periods")) return null
        val ps = j.optJSONArray("periods") ?: return null
        if (ps.length() > 3) return null
        return periodsOf(ps)?.takeIf { l -> l.none { p -> p.goals.any { it.done } } }
    }

    private fun periodsOf(ps: JSONArray): List<GoalPeriod>? {
        return (0 until ps.length()).map { i ->
            val p = ps.optJSONObject(i) ?: return null
            val key = p.optString("key"); val gs = p.optJSONArray("goals") ?: return null
            if (!KEY.matches(key) || gs.length() > 20) return null
            GoalPeriod(key, p.optString("label").take(20), (0 until gs.length()).map { k ->
                val g = gs.optJSONObject(k) ?: return null
                val text = g.optString("text")
                val goal = if (g.isNull("goal")) null else g.optString("goal")
                val progress = if (g.isNull("progress")) null else pair(g.optJSONArray("progress")) ?: return null
                val linked = if (g.isNull("linked")) null else pair(g.optJSONArray("linked")) ?: return null
                val parent = if (g.isNull("parent")) null else g.optString("parent")
                val rollup = if (g.isNull("rollup")) null else g.optInt("rollup", -1)
                val due = if (g.isNull("due") || !g.has("due")) null else g.optString("due")
                val est = if (g.isNull("est") || !g.has("est")) null else g.optInt("est", -1)
                val spent = if (g.isNull("spent") || !g.has("spent")) null else g.optInt("spent", -1)
                val hours = if (g.isNull("hours") || !g.has("hours")) null else pair(g.optJSONArray("hours")) ?: return null
                if (listOfNotNull(est, spent).any { it !in 1..MAX_MINUTES } || (hours != null && (hours.first < 0 || hours.second < 0))) return null
                if (text.isEmpty() || text.length > 180 || HIDDEN.containsMatchIn(text) || (goal != null && !GOAL_ID.matches(goal)) ||
                    (parent != null && !GOAL_ID.matches(parent)) || (rollup != null && rollup !in 0..100) ||
                    (due != null && day(due) == null)) return null
                GoalItem(text, g.optBoolean("done"), progress, goal, linked, parent, rollup, g.optInt("parts"), due, est, spent, hours)
            })
        }
    }

    /** The goals a goal may go under: all in the tree but itself and its own parts (the laptop
     *  checks again, 125). A goal without an id may go under any. */
    fun parentsFor(goal: String?, tree: Map<String, String?>): Set<String> = tree.keys.filter { candidate ->
        var walk: String? = candidate; var steps = 0
        while (walk != null && steps <= 8) { if (walk == goal) return@filter false; walk = tree[walk]; steps++ }
        true
    }.toSet()

    private val TAG_ID = Regex("#goal/([a-z0-9][a-z0-9-]{0,39})")

    /** The goals a task line counts toward, by their tags; shown apart from its words. */
    fun goalsOf(text: String): List<String> = TAG_ID.findAll(text).map { it.groupValues[1] }.toList()

    /** A goal's or a task's words without its #goal tags and parent, which are shown apart. */
    fun shownText(text: String) = text.replace(TAG, "").trim()

    fun body(id: String, picks: List<GoalPick>): JSONObject? {
        if (!ID.matches(id) || picks.isEmpty() || picks.size > 20) return null
        val arr = JSONArray()
        for (p in picks) {
            val o = JSONObject().put("do", p.action).put("period", p.period).put(if (p.action == "add") "text" else "item", p.value)
            when (p.action) {
                "add", "tick", "bump" -> {}
                "target" -> { val n = p.extra.toIntOrNull(); if (n == null || n !in 1..9999 || !p.extra.all { it.isDigit() }) return null; o.put("target", p.extra) }
                "link", "unlink" -> { if (p.extra.isBlank() || p.list.isBlank()) return null; o.put("list", p.list).put("todo", p.extra) }
                "nest" -> { if (!GOAL_ID.matches(p.extra)) return null; o.put("under", p.extra) }
                "due" -> { if (day(p.extra) == null) return null; o.put("due", p.extra) }
                "est", "log" -> {
                    val m = p.extra.takeIf { HOURS_IN.matches(it) }?.toDouble()?.let { Math.round(it * 60).toInt() } ?: return null
                    if (m !in 15..(if (p.action == "est") 999 else 24) * 60) return null
                    o.put("hours", p.extra)
                }
                else -> return null
            }
            arr.put(o)
        }
        return JSONObject().put("action", "goal").put("sha256", id).put("pick", arr).put("via", "device")
    }
}
