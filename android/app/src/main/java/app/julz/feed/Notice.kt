package app.julz.feed

import org.json.JSONException
import org.json.JSONObject

/** The channels and filters of the app. A notice of any other kind is dropped. */
enum class Kind(val tag: String) {
    APPROVAL("k_approval"), TODO("k_todo"), INBOX("k_inbox"), RUN("k_run"),
    REVIEW("k_review"), CHANGE("k_change"), WARNING("k_warning");

    companion object {
        fun fromTags(tags: List<String>): Kind? {
            val found = entries.filter { it.tag in tags }
            return found.singleOrNull()
        }
    }
}

/** One notice as the app keeps it. On purpose it has no field for a link, a button or an
 *  attachment: whatever a message carries beyond these can never reach the screen (threat 86). */
data class Notice(
    val id: String,
    val time: Long,
    val kind: Kind,
    val title: String,
    val message: String,
)

/** Turns one line of the ntfy JSON stream into a Notice, or null. SECURITY.md threat 91:
 *  validate and drop, never repair. */
object NoticeParser {
    const val MAX_LINE = 4_096
    const val MAX_TITLE = 120
    const val MAX_MESSAGE = 500
    const val MAX_TODO_MESSAGE = 4_000  // 20 open and 10 done tasks; the laptop keeps it under 4000 bytes (100, 113)
    private val ID = Regex("[A-Za-z0-9]{8,32}")

    fun parse(line: String): Notice? {
        if (line.length > MAX_LINE) return null
        val json = try {
            JSONObject(line)
        } catch (e: JSONException) {
            return null
        }
        if (json.optString("event") != "message") return null
        val id = json.opt("id") as? String ?: return null
        val time = (json.opt("time") as? Number)?.toLong() ?: return null
        val title = json.opt("title") as? String ?: return null
        val message = json.opt("message") as? String ?: return null
        val tagArray = json.optJSONArray("tags") ?: return null
        val tags = (0 until tagArray.length()).map { tagArray.opt(it) as? String ?: return null }
        val kind = Kind.fromTags(tags) ?: return null
        if (!ID.matches(id) || time <= 0) return null
        if (title.length > MAX_TITLE || !plain(title)) return null
        val limit = if (kind == Kind.TODO) MAX_TODO_MESSAGE else MAX_MESSAGE
        if (message.length > limit || !plain(message)) return null
        return Notice(id, time, kind, title, message)
    }

    /** No control, format (zero width, bidi overrides), private use, surrogate or unassigned
     *  code points, so nothing hidden can change how a line reads. */
    private fun plain(s: String): Boolean = s.codePoints().allMatch { cp ->
        when (Character.getType(cp).toByte()) {
            Character.CONTROL, Character.FORMAT, Character.PRIVATE_USE,
            Character.SURROGATE, Character.UNASSIGNED -> false
            else -> true
        }
    }
}
