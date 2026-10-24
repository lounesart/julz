package app.julz.approve

import org.json.JSONObject

data class Integration(val id: String, val name: String, val what: String, val status: String, val facts: List<String>)

/** The Tools tab's list from the approver's /api/integrations (SECURITY.md 122), checked again
 *  here; and Settings' words for a notification channel's level. Watch only. */
object Integrations {
    val STATUSES = listOf("On", "Gated", "Check", "Planned")
    private val ID = Regex("[a-z]{1,20}")
    private val HIDDEN = Regex("[\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}\\p{Cc}]")
    private fun plain(s: String) = s.isNotEmpty() && s.length <= 120 && !HIDDEN.containsMatchIn(s)

    /** A fact written "Label: value" as a spec line (22e): a short label before the first ": ",
     *  a value after it; a time's colon has no space, so "at 10:12" stays a sentence */
    fun specLine(fact: String): Pair<String, String>? {
        val i = fact.indexOf(": ")
        if (i <= 0 || i > 24) return null
        val value = fact.substring(i + 2).trim()
        return if (value.isEmpty()) null else fact.substring(0, i) to value
    }

    fun parse(raw: String): List<Integration>? {
        val items = try { JSONObject(raw).getJSONArray("items") } catch (e: Exception) { return null }
        if (items.length() > 12) return null
        return (0 until items.length()).map { i ->
            val o = items.optJSONObject(i) ?: return null
            val facts = o.optJSONArray("facts") ?: return null
            if (facts.length() > 6) return null
            val f = (0 until facts.length()).map { facts.optString(it).takeIf(::plain) ?: return null }
            val it = Integration(o.optString("id"), o.optString("name"), o.optString("what"), o.optString("status"), f)
            if (!ID.matches(it.id) || it.status !in STATUSES || !plain(it.name) || !plain(it.what)) return null
            it
        }
    }

    /** A channel's importance as Settings says it; the level itself is only Android's to change. */
    fun level(importance: Int): String = when {
        importance >= 4 -> "Sound and pop-up"
        importance == 3 -> "Sound"
        importance == 2 -> "Silent"
        importance == 1 -> "Feed only"
        else -> "Off"
    }
}
