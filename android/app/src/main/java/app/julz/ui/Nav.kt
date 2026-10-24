package app.julz.ui

/** Where Back goes (22c): the gesture and the arrow both go one level up, to where I came from.
 *  A tab or a notification tap starts a fresh path from the Feed, so the path never keeps an
 *  old place an intent did not name (133), and a place already on it is gone back to, never
 *  stacked twice: the path is never longer than the number of screens. */
data class Nav<T>(val path: List<T>) {
    constructor(home: T) : this(listOf(home))

    val here: T get() = path.last()
    val canGoBack: Boolean get() = path.size > 1
    /** The tab to light: the place the path started from after the Feed */
    val section: T get() = path.getOrElse(1) { path.first() }

    /** A tab or a notification tap: the Feed, then that place; the tab I am in goes to its top */
    fun tab(to: T) = Nav(if (to == path.first()) listOf(to) else listOf(path.first(), to))

    /** One level down */
    fun open(to: T): Nav<T> {
        val i = path.indexOf(to)
        return Nav(if (i >= 0) path.take(i + 1) else path + to)
    }

    /** One level up; at the Feed nothing, so Android's own Back leaves the app */
    fun back() = if (canGoBack) Nav(path.dropLast(1)) else this
}
