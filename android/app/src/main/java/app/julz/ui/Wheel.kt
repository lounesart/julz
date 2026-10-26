package app.julz.ui

import app.julz.feed.Kind

/** The wheel picker's logic (251): one word in the middle is the pick, its neighbours half
 *  hidden at the sides. One component for every pick of one among several (D1): Messages'
 *  filters, the Todos views, the chat modes. Only picks a view or a mode, never writes. */
object Wheel {
    /** The item whose centre is nearest [mid], from (index, centre) pairs in the same pixels */
    fun nearest(centres: List<Pair<Int, Float>>, mid: Float): Int? =
        centres.minByOrNull { kotlin.math.abs(it.second - mid) }?.first

    /** What TalkBack says for a word: its place, since the row hides most of itself */
    fun say(word: String, index: Int, count: Int) = "$word, ${index + 1} of $count"

    /** Messages: All (null), then the kinds that have notices; the chosen one stays even when
     *  empty, so a notification's filter never vanishes from under me (22d) */
    fun kinds(present: Set<Kind>, chosen: Kind?): List<Kind?> =
        listOf<Kind?>(null) + Kind.entries.filter { it in present || it == chosen }

    // Todos: a list's name comes from a file, which cannot hold a slash, so these never clash
    const val BOARD = "/board"
    const val ALL = "/all"

    /** Todos: the board, all lists, then each list on its own; All lists is the default */
    fun todoViews(lists: List<String>) = listOf(BOARD, ALL) + lists

    /** Where [view] sits; a list that is gone falls back to All lists */
    fun todoIndex(view: String, lists: List<String>) = todoViews(lists).indexOf(view).takeIf { it >= 0 } ?: 1

    /** The chat modes (135, 133b): the key julz-chat gets, and the word shown. At most one on */
    val MODES = listOf("" to "Chat", "learn" to "Learn", "notes" to "Notes")
}
