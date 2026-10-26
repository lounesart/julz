package app.julz.feed

/** A horizontal swipe on a tabbed screen moves one tab, never two, and stops at the ends. A
 *  swipe left (negative dx) goes to the next tab. Only moves the view: a gesture never writes. */
object TabSwipe {
    fun next(tab: Int, count: Int, dx: Float, threshold: Float): Int = when {
        dx <= -threshold -> (tab + 1).coerceAtMost(count - 1)
        dx >= threshold -> (tab - 1).coerceAtLeast(0)
        else -> tab
    }
}
