package app.julz.feed

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Test

/** SECURITY.md threat 123: goals from the approver, and what the app sends to change them. */
class GoalsTest {
    private val ID = "c".repeat(64)
    private fun goal(text: String = "Study 10 h (3/10)", progress: List<Int>? = listOf(3, 10), goal: String? = null,
                     linked: List<Int>? = null, done: Boolean = false, parent: String? = null, rollup: Int? = null, parts: Int = 0,
                     due: String? = null, est: Int? = null, spent: Int? = null, hours: List<Int>? = null) =
        JSONObject().put("text", text).put("done", done).put("progress", progress?.let { JSONArray(it) } ?: JSONObject.NULL)
            .put("goal", goal ?: JSONObject.NULL).put("linked", linked?.let { JSONArray(it) } ?: JSONObject.NULL)
            .put("parent", parent ?: JSONObject.NULL).put("rollup", rollup ?: JSONObject.NULL).put("parts", parts)
            .put("due", due ?: JSONObject.NULL).put("est", est ?: JSONObject.NULL).put("spent", spent ?: JSONObject.NULL)
            .put("hours", hours?.let { JSONArray(it) } ?: JSONObject.NULL)

    private fun milestone(goal: String = "cpts", text: String = "Pass CPTS #goal/cpts [due:: 2027-03-01]", due: String = "2027-03-01", rollup: Int? = 50) =
        JSONObject().put("goal", goal).put("text", text).put("due", due).put("rollup", rollup ?: JSONObject.NULL)

    private fun snap(goals: List<JSONObject> = listOf(goal(), goal("Exam #goal/exam [in:: cpts]", null, "exam", listOf(1, 2), parent = "cpts", rollup = 50, parts = 2)),
                     key: String = "2026-W43", tree: JSONObject = JSONObject().put("exam", "cpts").put("cpts", JSONObject.NULL),
                     milestones: List<JSONObject> = listOf(milestone())) =
        JSONObject().put("id", ID).put("tree", tree).put("milestones", JSONArray(milestones)).put("periods", JSONArray(listOf(
            JSONObject().put("key", key).put("label", "This week").put("note", "goals/$key.md").put("goals", JSONArray(goals))))).toString()

    private fun past(vararg periods: Pair<String, List<JSONObject>>) = JSONObject().put("periods", JSONArray(periods.map { (key, goals) ->
        JSONObject().put("key", key).put("label", "Last week").put("note", "goals/$key.md").put("goals", JSONArray(goals)) })).toString()

    // Open goals from past periods, read only (126b(3), threat 157)
    @Test fun pastGoalsParse() {
        val l = GoalsData.parsePast(past("2026-W42" to listOf(goal("Study 10 h (2/10)", listOf(2, 10))), "2025" to emptyList()))!!
        assertEquals(listOf("2026-W42", "2025"), l.map { it.key })
        assertEquals("Last week", l[0].label)
        assertEquals("Study 10 h (2/10)", l[0].goals.single().text)
        assertEquals(emptyList<GoalPeriod>(), GoalsData.parsePast(JSONObject().put("periods", JSONArray()).toString()))
    }

    @Test fun pastGoalsUrlIsAllowed() {
        assertEquals("https://h/api/goals/past",
            app.julz.approve.ApproverApi.urlOrNull(app.julz.ui.Origins("https://c", "https://h"), app.julz.approve.ApproverApi.GOALS_PAST))
    }

    @Test fun pastGoalsOffShapeIsNull() {
        val ok = JSONObject(past("2026-W42" to listOf(goal())))
        for (bad in listOf("", "{", snap(), past("2026-W42" to listOf(goal(done = true))), past("../x" to listOf(goal())),
                past("2026-W42" to listOf(goal("a\u202Eb"))), past("2026-W42" to listOf(goal(rollup = 101))),
                past(*Array(4) { "2026-W42" to listOf(goal()) }), past("2026-W42" to List(21) { goal() }),
                past("2026-10-24" to emptyList()),  // a day is no period (223, threat 159)
                ok.put("extra", 1).toString()))
            assertNull(bad.take(60), GoalsData.parsePast(bad))
    }

    @Test fun goalsParse() {
        val s = GoalsData.parse(snap())!!
        val g = s.periods.single().goals
        assertEquals(3 to 10, g[0].progress)
        assertEquals("exam", g[1].goal)
        assertEquals(1 to 2, g[1].linked)
        assertEquals("Exam", GoalsData.shownText(g[1].text))  // the tag and the parent are shown apart
        assertEquals("cpts", g[1].parent)
        // A task linked to goals reads as its words; the goals are listed apart (found 18 Oct)
        assertEquals("Review session notes", GoalsData.shownText("Review session notes #goal/study-10-h #goal/pass-cpts"))
        assertEquals(listOf("study-10-h", "pass-cpts"), GoalsData.goalsOf("Review session notes #goal/study-10-h #goal/pass-cpts"))
        assertEquals(50, g[1].rollup)
        assertEquals(mapOf("exam" to "cpts", "cpts" to null), s.tree)
        assertEquals(setOf("cpts"), GoalsData.parentsFor("exam", s.tree))
    }

    /** 129: hours as whole minutes, shown short. */
    /** 126b, decided 24 Oct: an estimate makes hours the measure; the count in the title goes. */
    @Test fun anEstimateMakesHoursTheMeasure() {
        val study = GoalItem("Study 10 h (2/10) #goal/study-10-h", false, 2 to 10, "study-10-h", null, hours = 180 to 600)
        assertTrue(GoalsData.byHours(study))
        assertEquals("Study 10 h", GoalsData.title(study))
        val counted = GoalItem("Read books (2/10)", false, 2 to 10, null, null)
        assertFalse(GoalsData.byHours(counted))
        assertEquals("Read books (2/10)", GoalsData.title(counted))
        val loggedOnly = GoalItem("Lab (1/3)", false, 1 to 3, null, null, hours = 90 to 0)
        assertFalse(GoalsData.byHours(loggedOnly))  // hours with no estimate measure nothing
    }

    @Test fun hoursParseAndRead() {
        val g = GoalsData.parse(snap(listOf(goal(est = 360, spent = 90, hours = listOf(135, 420)))))!!.periods.single().goals.single()
        assertEquals(360, g.est)
        assertEquals(135 to 420, g.hours)
        assertEquals("2.25/7h", GoalsData.hoursLabel(135, 420))
        assertEquals("1.5h", GoalsData.hoursLabel(90, 0))       // logged, no estimate
        assertEquals("0/6h", GoalsData.hoursLabel(0, 360))
        assertEquals("Nmap", GoalsData.shownText("Nmap #goal/nmap [est:: 6h] [spent:: 1.5h]"))
        assertEquals(90 to 360, GoalsData.todoHours("Drill [est:: 6h] [spent:: 1.5h]"))
        assertNull(GoalsData.todoHours("Drill"))
        for (bad in listOf(goal(est = -1), goal(spent = 10_000 * 60), goal(hours = listOf(1)), goal(hours = listOf(-1, 2))))
            assertNull(GoalsData.parse(snap(listOf(bad))))
        val b = GoalsData.body(ID, listOf(GoalPick("est", "2026-W43", "Nmap", "6"), GoalPick("log", "2026-W43", "Nmap", "1.5")))!!.getJSONArray("pick")
        assertEquals(setOf("do", "period", "item", "hours"), b.getJSONObject(0).keys().asSequence().toSet())
        assertEquals("1.5", b.getJSONObject(1).getString("hours"))
        for (h in listOf("1.1", "-1", "0", "1h", "1000"))
            assertNull(h, GoalsData.body(ID, listOf(GoalPick("est", "2026-W43", "Nmap", h))))
        assertNull(GoalsData.body(ID, listOf(GoalPick("log", "2026-W43", "Nmap", "25"))))
    }

    /** 126: milestones, goals with a due date; the phone counts the days from its own clock. */
    @Test fun milestonesParseAndCountDays() {
        val s = GoalsData.parse(snap(listOf(goal(due = "2026-10-30"))))!!
        assertEquals("2026-10-30", s.periods.single().goals.single().due)
        assertEquals(listOf(Milestone("cpts", "Pass CPTS #goal/cpts [due:: 2027-03-01]", "2027-03-01", 50)), s.milestones)
        assertEquals("Pass CPTS", GoalsData.shownText(s.milestones[0].text))  // the date is shown apart too
        val today = java.time.LocalDate.of(2026, 10, 18)
        assertEquals("due today", GoalsData.dueLabel("2026-10-18", today))
        assertEquals("1d left", GoalsData.dueLabel("2026-10-19", today))
        assertEquals("12d left", GoalsData.dueLabel("2026-10-30", today))
        assertEquals("3d late", GoalsData.dueLabel("2026-10-15", today))
        assertEquals("", GoalsData.dueLabel("soon", today))
    }

    @Test fun anythingOffShapeIsNull() {
        for (bad in listOf("", "{", snap(key = "../x"), snap(listOf(goal(text = "a\u202Eb"))),
                snap(listOf(goal(progress = listOf(1)))), snap(listOf(goal(goal = "Bad Id"))), snap(List(21) { goal() }),
                snap(listOf(goal(rollup = 101))), snap(listOf(goal(parent = "../x"))), snap(tree = JSONObject().put("Bad Id", JSONObject.NULL)),
                snap(listOf(goal(due = "2026-02-30"))), snap(listOf(goal(due = "2026-10-30 x"))),
                snap(milestones = listOf(milestone(text = "a\u202Eb"))), snap(milestones = listOf(milestone(goal = "../x"))),
                snap(milestones = listOf(milestone(due = "soon"))), snap(milestones = listOf(milestone(rollup = 101))),
                snap(milestones = List(21) { milestone() }), snap(key = "2026-10-25"), periods(4)))
            assertNull(bad, GoalsData.parse(bad))
        assertEquals(3, GoalsData.parse(periods(3))!!.periods.size)
    }

    private fun periods(n: Int) = JSONObject().put("id", ID).put("tree", JSONObject()).put("milestones", JSONArray()).put("periods", JSONArray(
        listOf("2026-W43", "2026-10", "2026", "2027").take(n).map { k ->
            JSONObject().put("key", k).put("label", k).put("note", "goals/$k.md").put("goals", JSONArray()) })).toString()

    // Week or month under the year (223, threat 159): the stored pick is a value read back from storage
    @Test fun theViewIsWeekOrMonthOnly() {
        assertEquals("month", GoalsData.viewOf("month"))
        for (v in listOf(null, "", "week", "Month", "month ", "year", "day", "2026-10"))
            assertEquals(v.toString(), "week", GoalsData.viewOf(v))
    }

    @Test fun theYearAlwaysThenThePickedPeriod() {
        val ps = GoalsData.parse(periods(3))!!.periods
        assertEquals(listOf("2026", "2026-W43"), GoalsData.shown(ps, "week").map { it.key })
        assertEquals(listOf("2026", "2026-10"), GoalsData.shown(ps, "month").map { it.key })
        assertEquals(listOf("year", "month", "week", null), listOf("2026", "2026-10", "2026-W43", "2026-10-25").map { GoalsData.kindOf(it) })
        for (bad in listOf("2026-W4", "../-W43", "2026-W43x", "x2026")) assertNull(bad, GoalsData.kindOf(bad))
    }

    // A card says its key only when the label does not already (223b: "2026  2026")
    @Test fun theKeyShowsOnlyWhenItAddsSomething() {
        assertFalse(GoalsData.keyShown(GoalPeriod("2026", "2026", emptyList())))
        assertTrue(GoalsData.keyShown(GoalPeriod("2026-W43", "This week", emptyList())))
        assertTrue(GoalsData.keyShown(GoalPeriod("2026-10", "October", emptyList())))
    }

    @Test fun aGoalIsNeverOfferedAsItsOwnParentOrUnderItsParts() {
        val tree = mapOf("cpts" to null, "net" to "cpts", "dns" to "net", "linux" to "cpts")
        assertEquals(setOf("cpts", "linux"), GoalsData.parentsFor("net", tree))  // not itself, not its part dns
        assertEquals(emptySet<String>(), GoalsData.parentsFor("cpts", tree))      // everything else is under it
        assertEquals(tree.keys, GoalsData.parentsFor(null, tree))                  // without an id it may go anywhere
    }

    @Test fun changesCarryOnlyTheSnapshotIdAndThePicks() {
        val b = GoalsData.body(ID, listOf(GoalPick("add", "2026-W43", "Walk 10k"), GoalPick("bump", "2026-W43", "Study 10 h (3/10)")))!!
        assertEquals(setOf("action", "sha256", "pick", "via"), b.keys().asSequence().toSet())
        val add = b.getJSONArray("pick").getJSONObject(0)
        assertEquals(setOf("do", "period", "text"), add.keys().asSequence().toSet())
        assertEquals(setOf("do", "period", "item"), b.getJSONArray("pick").getJSONObject(1).keys().asSequence().toSet())
        val tl = GoalsData.body(ID, listOf(GoalPick("target", "2026-W43", "Exam #goal/exam", "5"),
            GoalPick("link", "2026-W43", "Exam #goal/exam", "DNS lab", "study")))!!.getJSONArray("pick")
        assertEquals(setOf("do", "period", "item", "target"), tl.getJSONObject(0).keys().asSequence().toSet())
        assertEquals("5", tl.getJSONObject(0).getString("target"))
        assertEquals(setOf("do", "period", "item", "list", "todo"), tl.getJSONObject(1).keys().asSequence().toSet())
        assertEquals("DNS lab", tl.getJSONObject(1).getString("todo"))
        val nest = GoalsData.body(ID, listOf(GoalPick("nest", "2026-W43", "Study 10 h (3/10)", "cpts")))!!.getJSONArray("pick").getJSONObject(0)
        assertEquals(setOf("do", "period", "item", "under"), nest.keys().asSequence().toSet())
        // 128: unlink sends the same keys as link
        val un = GoalsData.body(ID, listOf(GoalPick("unlink", "2026-W43", "Exam #goal/exam", "DNS lab #goal/exam", "study")))!!.getJSONArray("pick").getJSONObject(0)
        assertEquals(setOf("do", "period", "item", "list", "todo"), un.keys().asSequence().toSet())
        assertEquals("unlink", un.getString("do"))
        // A longer tag is not the same goal (found 18 Oct)
        assertEquals(listOf("net-plus-exam"), GoalsData.goalsOf("Drill #goal/net-plus-exam"))
        val due = GoalsData.body(ID, listOf(GoalPick("due", "2026-W43", "Study 10 h (3/10)", "2026-10-30")))!!.getJSONArray("pick").getJSONObject(0)
        assertEquals(setOf("do", "period", "item", "due"), due.keys().asSequence().toSet())
        assertEquals("2026-10-30", due.getString("due"))
        assertNull(GoalsData.body(ID, listOf(GoalPick("due", "2026", "Exam", "2026-02-30"))))
        assertNull(GoalsData.body(ID, listOf(GoalPick("due", "2026", "Exam", "20261030"))))
        assertNull(GoalsData.body(ID, listOf(GoalPick("target", "2026", "Exam", "0"))))
        assertNull(GoalsData.body(ID, listOf(GoalPick("target", "2026", "Exam", "ten"))))
        assertNull(GoalsData.body(ID, emptyList()))
        assertNull(GoalsData.body("short", listOf(GoalPick("tick", "2026", "x"))))
        assertNull(GoalsData.body(ID, listOf(GoalPick("delete", "2026", "x"))))
    }

    // A goal's page, HTB style (227): what is done and what is left, named from what the phone holds
    @Test fun aGoalsPageNamesItsParts() {
        val cpts = GoalItem("Pass CPTS #goal/cpts [due:: 2027-03-01]", false, null, "cpts", 2 to 5, rollup = 40, parts = 5,
            due = "2027-03-01", est = 600, spent = 180, hours = 180 to 600)
        val net = GoalItem("Net+ #goal/net [in:: cpts]", true, null, "net", null, parent = "cpts", rollup = 100)
        val read = GoalItem("Kerberos chapter (1/3) [in:: cpts]", false, 1 to 3, null, null, parent = "cpts")
        val periods = listOf(GoalPeriod("2026", "2026", listOf(cpts, net)), GoalPeriod("2026-W43", "This week", listOf(read)))
        val tree = mapOf("cpts" to null, "net" to "cpts", "ad" to "cpts")  // ad lives in a note the phone has not
        val todos = listOf(TodoList("study", 1, 3, listOf("Subnetting drill #goal/cpts", "unrelated #goal/cpts-old"),
            doneItems = listOf("DNS lab #goal/cpts [spent:: 1h]"), doing = listOf("AD lab #goal/cptsx")))
        val d = GoalsData.detail(cpts, periods, tree, todos)
        assertEquals("Pass CPTS", d.title)
        assertEquals(40, d.percent)
        assertEquals(listOf("Net+" to "100%", "DNS lab" to null), d.done.map { it.text to it.progress })
        assertEquals(listOf("Kerberos chapter" to "1/3", "Subnetting drill" to null), d.left.map { it.text to it.progress })
        assertEquals(1, d.unnamedDone)   // linked 2 done, one named here: the other is in a finished list
        assertEquals(2, d.unnamedLeft)   // linked 3 open, one named here (cpts-old and cptsx are other tags)
        assertEquals(1, d.elsewhere)     // ad: a child goal in a note the phone has not
        assertEquals(180 to 600, d.hours)
        // A goal with no id has no tagged todos or child goals: just itself
        val plain = GoalsData.detail(read, periods, tree, todos)
        assertEquals(33, plain.percent)
        assertTrue(plain.done.isEmpty() && plain.left.isEmpty() && plain.unnamedDone == 0 && plain.elsewhere == 0)
        assertEquals(100, GoalsData.detail(net, periods, tree, emptyList()).percent)
    }
}
