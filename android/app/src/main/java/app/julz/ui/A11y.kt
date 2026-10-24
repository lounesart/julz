package app.julz.ui

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/** Accessibility settings, on top of what Android itself sets. Stored as one short string. */
data class A11yPrefs(
    val scale: Float = 1.0f,
    val bold: Boolean = false,
    val contrast: Boolean = false,
    val solid: Boolean = false,
    val labels: Boolean = false,
    val guides: Boolean = true,
) {
    /** Big text needs words under the icons: from 160 % they show on their own. */
    val showLabels get() = labels || scale >= 1.6f

    fun encode() = "scale=$scale;bold=$bold;contrast=$contrast;solid=$solid;labels=$labels;guides=$guides"

    companion object {
        fun clampScale(s: Float) = if (s.isNaN()) 1.0f else s.coerceIn(0.85f, 2.0f)

        fun decode(s: String): A11yPrefs {
            val m = s.split(";").mapNotNull { it.split("=").takeIf { p -> p.size == 2 } }.associate { it[0] to it[1] }
            return A11yPrefs(
                scale = clampScale(m["scale"]?.toFloatOrNull() ?: 1.0f),
                bold = m["bold"] == "true", contrast = m["contrast"] == "true",
                solid = m["solid"] == "true", labels = m["labels"] == "true",
                // on unless I hid them: only "false" counts, as only "true" does above
                guides = m["guides"] != "false",
            )
        }
    }
}

/** The live settings every screen reads; changing one restyles the whole app at once. */
object A11y {
    var prefs by mutableStateOf(A11yPrefs())

    fun load(context: Context) {
        prefs = A11yPrefs.decode(context.getSharedPreferences("julz_ui", Context.MODE_PRIVATE)
            .getString("a11y", "") ?: "")
    }

    fun set(context: Context, p: A11yPrefs) {
        prefs = p
        context.getSharedPreferences("julz_ui", Context.MODE_PRIVATE).edit().putString("a11y", p.encode()).apply()
    }
}
