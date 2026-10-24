package app.julz.ui

/** Window size classes as Android defines them (22f): a layout follows the space the app gets,
 *  width and height apart, not the device or its orientation. Worked out here from the screen's
 *  dp, so no library is added for it (threat 97). */
enum class SizeClass {
    COMPACT, MEDIUM, EXPANDED;

    companion object {
        fun ofHeight(dp: Int) = when {
            dp < 480 -> COMPACT
            dp < 900 -> MEDIUM
            else -> EXPANDED
        }

        /** Tabs as a rail on the left when the height is compact: a phone on its side. Not when
         *  merely wider than tall: in split screen the bottom bar still fits */
        fun rail(widthDp: Int, heightDp: Int) = ofHeight(heightDp) == COMPACT && widthDp > heightDp
    }
}

/** A folder's colour by its top folder (22b), the same everywhere it shows; unknown ones stay
 *  neutral. Shown only with Look and feel's Coloured folders, and then as a line and a tint,
 *  in the cards' family, never a filled blob (folders were made neutral on purpose, 18 Oct). */
object Folders {
    private val tops = mapOf(
        "study" to 0xFFC4F07A.toInt(), "daily" to 0xFFF7D58B.toInt(), "Inbox" to 0xFFC9B8F0.toInt(),
        "Claude" to 0xFF7FE3F0.toInt(), "Outbox" to 0xFFFF7AB6.toInt(), "feedback" to 0xFFFF8F80.toInt(),
    )

    fun argb(path: String): Int? = tops[path.substringBefore('/')]
}
