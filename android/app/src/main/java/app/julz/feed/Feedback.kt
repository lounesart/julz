package app.julz.feed

import java.security.MessageDigest
import org.json.JSONObject

data class FeedbackItem(val name: String, val done: Boolean, val created: String, val kind: String,
                        val state: String, val where: String, val text: String)

/** Feedback from the app (SECURITY.md 120): the list from the approver's /api/feedback, checked
 *  again here, and what the app sends to begin a signed note. */
object FeedbackList {
    val KINDS = listOf("bug", "idea", "change")
    const val MAX_TEXT = 2000
    private const val MAX_ITEMS = 70
    private const val MAX_PREVIEW = 600
    private val NAME = Regex("\\w[\\w .-]{0,99}")
    private val DATE = Regex("\\d{4}-\\d{2}-\\d{2}")
    private val HIDDEN = Regex("[\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}\\x00-\\x08\\x0B-\\x1F\\x7F]")

    fun parse(raw: String): List<FeedbackItem>? {
        val items = try { JSONObject(raw).getJSONArray("items") } catch (e: Exception) { return null }
        if (items.length() > MAX_ITEMS) return null
        return (0 until items.length()).map { i ->
            val o = items.optJSONObject(i) ?: return null
            val it = FeedbackItem(o.optString("name"), o.optBoolean("done"), o.optString("created"), o.optString("kind"),
                o.optString("state"), o.optString("where"), o.optString("text"))
            if (!NAME.matches(it.name) || !(it.created.isEmpty() || DATE.matches(it.created)) ||
                !(it.kind.isEmpty() || it.kind in KINDS) || it.state.length > 20 || it.where.length > 60 ||
                it.text.length > MAX_PREVIEW || listOf(it.state, it.where, it.text).any { s -> HIDDEN.containsMatchIn(s) }) return null
            it
        }
    }

    /** The kind, my words and their hash; the laptop builds the text I sign and checks the hash. */
    fun body(kind: String, text: String): JSONObject? {
        if (kind !in KINDS || text.isBlank() || text.length > MAX_TEXT) return null
        val sha = MessageDigest.getInstance("SHA-256").digest(text.toByteArray()).joinToString("") { "%02x".format(it) }
        return JSONObject().put("action", "feedback").put("kind", kind).put("text", text).put("sha256", sha).put("via", "device")
    }
}
