package app.julz.feed

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** SECURITY.md threats 100 and 113: the snapshot from the laptop, and what the app sends to tick. */
class TodosTest {
    private val L = "\u241E"
    private val F = "\u241F"
    private val ID = "c".repeat(64)
    private val HEAD = "v2${F}$ID"
    // v2: head with the snapshot id; per list name, done, total, how many open, open tasks, done tasks
    private val GOOD = "$HEAD${L}physio${F}2${F}3${F}1${F}Review session notes${F}Call the clinic" +
        "${L}week${F}3${F}5${F}2${F}Walk 10k${F}Book the exam"

    /** 126b: a list's file name read as words; the picks still use the name as it is. */
    @Test fun listNamesReadAsWords() {
        assertEquals("Get job", TodoSnapshot.listLabel("get_job"))
        assertEquals("Meet sasha", TodoSnapshot.listLabel("meet-sasha"))
        assertEquals("Physio", TodoSnapshot.listLabel("physio"))
        assertEquals("Week 42 plan", TodoSnapshot.listLabel("week  42_plan"))
    }

    @Test fun recordsParse() {
        val s = TodoSnapshot.parse(GOOD)!!
        assertEquals(listOf("physio", "week"), s.map { it.name })
        assertEquals(listOf("Walk 10k", "Book the exam"), s[1].open)
        assertEquals(emptyList<String>(), s[1].doneItems)
        assertEquals(listOf("Review session notes"), s[0].open)
        assertEquals(listOf("Call the clinic"), s[0].doneItems)
        assertEquals(3 to 5, s[1].done to s[1].total)
        assertEquals(ID, TodoSnapshot.id(GOOD))
    }

    /** 127: v3 adds how many are in progress after the open count, and those tasks after the open ones. */
    @Test fun inProgressTasksParse() {
        val v3 = "v3${F}$ID${L}physio${F}1${F}3${F}1${F}1${F}Book physio${F}Stretch daily${F}Call" +
            "${L}rehab${F}0${F}1${F}0${F}1${F}Walk"
        val s = TodoSnapshot.parse(v3)!!
        assertEquals(listOf("Book physio"), s[0].open)
        assertEquals(listOf("Stretch daily"), s[0].doing)
        assertEquals(listOf("Call"), s[0].doneItems)
        assertEquals(emptyList<String>(), s[1].open)
        assertEquals(listOf("Walk"), s[1].doing)
        assertEquals(ID, TodoSnapshot.id(v3))
        assertEquals(emptyList<String>(), TodoSnapshot.parse(GOOD)!![0].doing)  // v2 still reads
        assertEquals("Physio 1/3: Book physio, Stretch daily (in progress)\nRehab 0/1: Walk (in progress)", TodoSnapshot.summary(v3))
    }

    @Test fun aStartSendsTheSameShapeAsATick() {
        val body = TodoSnapshot.tickBody(ID, listOf("week" to "Walk 10k"), "start")!!
        assertEquals("start", body.getString("action"))
        assertEquals(setOf("action", "sha256", "pick", "via"), body.keys().asSequence().toSet())
        assertNull(TodoSnapshot.tickBody(ID, listOf("week" to "Walk 10k"), "delete"))
    }

    @Test fun noOpenTodos() {
        assertEquals(emptyList<TodoList>(), TodoSnapshot.parse("none"))
        assertNull(TodoSnapshot.id("none"))
    }

    @Test fun anythingOffShapeDropsTheSnapshot() {
        val r = "${L}physio${F}"
        for (bad in listOf(
                "physio${F}2${F}3${F}1${F}t",                      // no head (the old format)
                "v2${F}short${r}2${F}3${F}1${F}t",                 // bad id
                "v4${F}$ID${r}2${F}3${F}1${F}t",                   // unknown version
                "v3${F}$ID${r}2${F}3${F}1${F}t",                   // v3 needs the in progress count
                "v3${F}$ID${r}2${F}3${F}0${F}0${F}d",              // v3, nothing open or in progress
                "v3${F}$ID${r}0${F}3${F}1${F}2${F}t${F}u",         // v3, says two in progress, has one
                "$HEAD${r}x${F}3${F}1${F}t", "$HEAD${r}4${F}3${F}1${F}t", "$HEAD${r}-1${F}3${F}1${F}t",
                "$HEAD${r}2${F}3${F}2${F}t",                       // says two open, has one
                "$HEAD${r}2${F}3${F}0", "$HEAD${r}2${F}3${F}0${F}t", // a list with nothing open
                "$HEAD${r}1${F}3${F}1${F}t${F}d1${F}d2",           // more done tasks than done
                "$HEAD${r}2${F}3${F}1${F}${"y".repeat(81)}", "$HEAD${r}2${F}3${F}1${F} ",
                "$HEAD${L}${F}2${F}3${F}1${F}t", HEAD, ""))
            assertNull(bad, TodoSnapshot.parse(bad))
    }

    @Test fun todoMessagesMayBeLongerThanOthers() {
        val long = (1..20).joinToString(F, prefix = "$HEAD${L}list${F}0${F}20${F}20$F") { "task number $it with some words" }
        val line = "{\"id\":\"aaaaaaaa1\",\"time\":5,\"event\":\"message\",\"title\":\"Julz: 20 open todos\"," +
            "\"message\":${org.json.JSONObject.quote(long)},\"tags\":[\"k_todo\"]}"
        assertTrue(long.length > NoticeParser.MAX_MESSAGE)
        assertEquals(Kind.TODO, NoticeParser.parse(line)!!.kind)
        assertEquals(20, TodoSnapshot.parse(NoticeParser.parse(line)!!.message)!![0].open.size)
        assertNull(NoticeParser.parse(line.replace("k_todo", "k_run")))  // other kinds keep 500
        // the biggest snapshot the laptop sends: 20 open and 10 done tasks of 80 characters
        val full = "$HEAD${L}list${F}10${F}30${F}20$F" + List(30) { "t".repeat(78) + "%02d".format(it) }.joinToString(F)
        assertTrue(full.length > 2_500)
        val big = line.replace(org.json.JSONObject.quote(long), org.json.JSONObject.quote(full))
        assertEquals(10, TodoSnapshot.parse(NoticeParser.parse(big)!!.message)!![0].doneItems.size)
    }

    @Test fun aSnapshotReadsAsWordsNotSeparators() {
        assertEquals("Physio 2/3: Review session notes\nWeek 3/5: Walk 10k, Book the exam", TodoSnapshot.summary(GOOD))
        assertEquals("No open todos", TodoSnapshot.summary("none"))
        assertEquals("", TodoSnapshot.summary("physio${F}x${F}3${F}t"))  // off shape: nothing, never the raw text
    }

    @Test fun aTickSendsOnlyTheSnapshotIdAndThePairs() {
        // The server builds the text to sign from its own snapshot (113): no path, no free text
        val body = TodoSnapshot.tickBody(ID, listOf("week" to "Walk 10k", "physio" to "Review session notes"))!!
        assertEquals(setOf("action", "sha256", "pick", "via"), body.keys().asSequence().toSet())
        assertEquals("tick", body.getString("action"))
        assertEquals(ID, body.getString("sha256"))
        assertEquals("device", body.getString("via"))
        val pick = body.getJSONArray("pick")
        assertEquals(2, pick.length())
        assertEquals(setOf("list", "item"), pick.getJSONObject(0).keys().asSequence().toSet())
        assertEquals("Walk 10k", pick.getJSONObject(0).getString("item"))
        assertNull(TodoSnapshot.tickBody(ID, emptyList()))
        assertNull(TodoSnapshot.tickBody("short", listOf("week" to "Walk 10k")))
        assertNull(TodoSnapshot.tickBody(ID, List(21) { "week" to "t$it" }))
    }

    // ----- the Done tab (threat 114) -----

    private fun week(vararg days: String) = "{\"days\":[${days.joinToString(",")}]}"
    private fun day(date: String, vararg items: Pair<String, String>) =
        "{\"date\":\"$date\",\"items\":[" + items.joinToString(",") { "{\"list\":\"${it.first}\",\"item\":\"${it.second}\"}" } + "]}"

    @Test fun aWeekParses() {
        val w = DoneWeek.parse(week(day("2026-10-18", "shop" to "eggs", "physio" to "Exercise plan"), day("2026-10-16", "gym" to "shoes")))!!
        assertEquals(listOf("2026-10-18", "2026-10-16"), w.map { it.date })
        assertEquals(listOf("shop" to "eggs", "physio" to "Exercise plan"), w[0].items)
        assertEquals(emptyList<DoneDay>(), DoneWeek.parse(week()))
    }

    @Test fun anOffShapeWeekIsNull() {
        val ok = "shop" to "eggs"
        for (bad in listOf("", "{", "[]", "{\"days\":5}", week(day("18 Oct", ok)), week(day("2026-10-18", "shop" to "y".repeat(81))),
                week(day("2026-10-18", "shop" to " ")), week(day("2026-10-18", "shop" to "a\u202Eb")), week(*Array(8) { day("2026-10-18", ok) }),
                week(day("2026-10-18", *Array(61) { ok }))))
            assertNull(bad, DoneWeek.parse(bad))
    }

    @Test fun daysReadAsWords() {
        val today = java.time.LocalDate.of(2026, 10, 18)
        assertEquals("Today", DoneWeek.label("2026-10-18", today))
        assertEquals("Yesterday", DoneWeek.label("2026-10-17", today))
        assertEquals("Thu 15 Oct", DoneWeek.label("2026-10-15", today))
    }
}
