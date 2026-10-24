package app.julz.ui

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue

/** A theme preset and its colours. Presets live in the app; nothing is read from outside. */
data class Preset(val id: String, val name: String, val note: String, val bg: Int, val accent: Int, val deep: Int)

object Palette {
    val presets = listOf(
        Preset("magenta", "Magenta poster", "default", 0xFF09070A.toInt(), 0xFFE3197A.toInt(), 0xFF7A0C3F.toInt()),
        Preset("redstone", "Red Stone", "from HyDE", 0xFF060101.toInt(), 0xFFB41211.toInt(), 0xFF522929.toInt()),
        Preset("acid", "Acid", "green night", 0xFF080A06.toInt(), 0xFFB8FF3C.toInt(), 0xFF1E3300.toInt()),
        // From the spec sheet reference (22b): navy with a signal orange; best with Industrial
        Preset("specsheet", "Spec sheet", "navy and signal orange", 0xFF0A1322.toInt(), 0xFFFF7A3D.toInt(), 0xFF1E3352.toInt()),
    )
    val accents = listOf(
        "Magenta" to 0xFFE3197A.toInt(), "Red Stone" to 0xFFB41211.toInt(), "Acid" to 0xFFB8FF3C.toInt(),
        "Cyan" to 0xFF7FE3F0.toInt(), "Sand" to 0xFFF7D58B.toInt(), "Lavender" to 0xFFC9B8F0.toInt(),
        "Orange" to 0xFFFF7A3D.toInt(),
    )

    /** WCAG relative luminance, 0 for black to 1 for white. */
    private fun lum(argb: Int): Double {
        fun ch(v: Int): Double = (v / 255.0).let { if (it <= 0.03928) it / 12.92 else Math.pow((it + 0.055) / 1.055, 2.4) }
        return 0.2126 * ch(argb shr 16 and 0xFF) + 0.7152 * ch(argb shr 8 and 0xFF) + 0.0722 * ch(argb and 0xFF)
    }

    /** Relative luminance above 0.4: text on it must be dark. */
    fun isLight(argb: Int): Boolean = lum(argb) > 0.4

    /** WCAG contrast ratio of two colours, from 1 to 21. */
    fun contrast(a: Int, b: Int): Double {
        val x = lum(a); val y = lum(b)
        return (maxOf(x, y) + 0.05) / (minOf(x, y) + 0.05)
    }

    /** The accent for text (22c): as it is when it reads at 4.5:1 on the background, else mixed
     *  toward white just enough (WCAG 1.4.3). Red Stone was 2.9:1, Magenta 4.48:1. */
    fun readable(accent: Int, bg: Int): Int {
        var c = accent
        var step = 0
        while (contrast(c, bg) < 4.5 && step < 20) {
            step++
            val t = step / 20.0
            fun mix(shift: Int) = ((accent shr shift and 0xFF) * (1 - t) + 255 * t).toInt() shl shift
            c = (0xFF shl 24) or mix(16) or mix(8) or mix(0)
        }
        return c
    }
}

/** [outline]: the selected item outlined in the accent instead of filled white (22b, 22c).
 *  [icon]: the launcher icon follows the accent (135). Both off unless stored as "true". */
data class LookPrefs(val theme: String = "magenta", val accent: Int? = null, val outline: Boolean = false,
                     val icon: Boolean = false, val brightHistory: Boolean = false, val colorFolders: Boolean = false,
                     val industrial: Boolean = false, val showIds: Boolean = true) {
    val preset get() = Palette.presets.first { it.id == theme }
    val accentColor get() = accent ?: preset.accent

    fun encode() = "theme=$theme;accent=${accent ?: ""};outline=$outline;icon=$icon;bright=$brightHistory;folders=$colorFolders;cut=$industrial;ids=$showIds"

    companion object {
        fun decode(s: String): LookPrefs {
            val m = s.split(";").mapNotNull { it.split("=").takeIf { p -> p.size == 2 } }.associate { it[0] to it[1] }
            val theme = m["theme"]?.takeIf { id -> Palette.presets.any { it.id == id } } ?: return LookPrefs()
            val accent = m["accent"]?.toIntOrNull()?.takeIf { a -> Palette.accents.any { it.second == a } }
            return LookPrefs(theme, accent, outline = m["outline"] == "true", icon = m["icon"] == "true",
                brightHistory = m["bright"] == "true", colorFolders = m["folders"] == "true", industrial = m["cut"] == "true",
                // on unless I hid them: only "false" counts, as for guides
                showIds = m["ids"] != "false")
        }
    }
}

object Look {
    var prefs by mutableStateOf(LookPrefs())

    fun load(context: Context) {
        prefs = LookPrefs.decode(context.getSharedPreferences("julz_ui", Context.MODE_PRIVATE)
            .getString("look", "") ?: "")
    }

    fun set(context: Context, p: LookPrefs) {
        prefs = p
        context.getSharedPreferences("julz_ui", Context.MODE_PRIVATE).edit().putString("look", p.encode()).apply()
        // The icon itself switches when I leave Julz (MainActivity.onStop)
    }
}

/** The launcher icon in the accent (135): one alias of MainActivity per accent in the manifest,
 *  the same names as check-apk.py's ICONS. Only names from this list are ever switched, picked by
 *  the accent colour; never a name from settings or an intent. */
object LauncherIcon {
    private const val DEFAULT = "IconMagenta"
    private fun alias(accentName: String) = "Icon" + accentName.replace(" ", "")
    val names = Palette.accents.map { alias(it.first) }

    /** Off is the Magenta icon, whatever the accent; an unknown accent is Magenta too */
    fun aliasFor(p: LookPrefs): String =
        if (!p.icon) DEFAULT else Palette.accents.firstOrNull { it.second == p.accentColor }?.let { alias(it.first) } ?: DEFAULT

    /** The new icon on first, then every other off: Julz always has a launcher entry */
    fun steps(chosen: String): List<Pair<String, Boolean>> =
        listOf(chosen to true) + names.filter { it != chosen }.map { it to false }

    fun apply(context: Context, p: LookPrefs) {
        val pm = context.packageManager
        for ((name, on) in steps(aliasFor(p))) {
            val c = android.content.ComponentName(context, "${context.packageName}.$name")
            val want = if (on) android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                else android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DISABLED
            // Only a real change: each one makes the launcher redraw its icons
            val now = pm.getComponentEnabledSetting(c)
            val enabledNow = now == android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_ENABLED ||
                (now == android.content.pm.PackageManager.COMPONENT_ENABLED_STATE_DEFAULT && name == DEFAULT)
            if (enabledNow != on) pm.setComponentEnabledSetting(c, want, android.content.pm.PackageManager.DONT_KILL_APP)
        }
    }
}
