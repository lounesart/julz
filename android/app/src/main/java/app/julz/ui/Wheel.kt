package app.julz.ui

import app.julz.feed.Kind

/** The wheel picker's logic (251): one word in the middle is the pick, its neighbours half
 *  hidden at the sides. One component for every pick of one among several (D1): Messages'
 *  filters, the Todos views, the chat modes. Only picks a view or a mode, never writes. */
object Wheel {
    /** The item whose centre is nearest [mid], from (index, centre) pairs in the same pixels */
    fun nearest(centres: List<Pair<Int, Float>>, mid: Float): Int? =
        centres.minByOrNull { kotlin.math.abs(it.second - mid) }?.first

    /** Copies of the words in a loop: the last word is followed by the first again, so a word
     *  always stands on both sides (an empty side was my note, 26 Oct). One word does not loop */
    const val LOOP = 1000
    fun slots(count: Int) = if (count > 1) count * LOOP else count

    /** The word at slot [slot] */
    fun real(slot: Int, count: Int) = slot % count

    /** The slot holding word [target] nearest to slot [from], so a pick rolls the short way round */
    fun closest(from: Int, target: Int, count: Int): Int {
        val ahead = Math.floorMod(target - from, count)
        return if (ahead <= count / 2) from + ahead else from + ahead - count
    }

    /** One swipe, one step, round the loop (the chat's wheel shows one word): up or left goes to
     *  the next, as TabSwipe does, and a swipe shorter than [threshold] stays */
    fun step(selected: Int, count: Int, d: Float, threshold: Float): Int = when {
        d <= -threshold -> (selected + 1) % count
        d >= threshold -> (selected - 1 + count) % count
        else -> selected
    }

    /** Where a roll by hand settles: the nearest word, but a short flick that left the start word
     *  nearest still steps one in its direction ([moved] is how far that word's centre now sits
     *  from the middle, negative when it went left or up), so no precise swipe is needed */
    fun settle(start: Int, nearest: Int, moved: Float, threshold: Float): Int = when {
        nearest != start -> nearest
        moved <= -threshold -> start + 1
        moved >= threshold -> start - 1
        else -> start
    }

    /** What TalkBack says for a word: its place, since the row hides most of itself */
    fun say(word: String, index: Int, count: Int) = "$word, ${index + 1} of $count"

    /** Messages: All (null), then the kinds that have notices; the chosen one stays even when
     *  empty, so a notification's filter never vanishes from under me (22d) */
    fun kinds(present: Set<Kind>, chosen: Kind?): List<Kind?> =
        listOf<Kind?>(null) + Kind.entries.filter { it in present || it == chosen }

    // Todos: a list's name comes from a file, which cannot hold a slash, so these never clash
    const val BOARD = "/board"
    const val ALL = "/all"

    /** Todos: the board, all lists, then each list on its own; All lists is the default. One list
     *  gets no view of its own: it would show the same card as All lists */
    fun todoViews(lists: List<String>) = listOf(BOARD, ALL) + if (lists.size > 1) lists else emptyList()

    /** Where [view] sits; a list that is gone falls back to All lists */
    fun todoIndex(view: String, lists: List<String>) = todoViews(lists).indexOf(view).takeIf { it >= 0 } ?: 1

    /** The chat modes (135, 133b): the key julz-chat gets, and the word shown. At most one on */
    val MODES = listOf("" to "Chat", "learn" to "Learn", "notes" to "Notes")
}
