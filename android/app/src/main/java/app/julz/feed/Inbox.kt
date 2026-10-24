package app.julz.feed

import org.json.JSONArray
import org.json.JSONObject

data class InboxNote(val name: String, val note: String, val sha256: String, val size: Int,
                     val modified: String, val preview: String)

data class InboxSnapshotData(val id: String, val notes: List<InboxNote>, val folders: List<String>)

/** One change I picked: delete a note, or move it to a folder from the snapshot. */
data class InboxPick(val note: String, val action: String, val to: String? = null) {
    /** One string, so picks survive in rememberSaveable at app level (HANDOFF gotcha). */
    val key: String get() = listOfNotNull(note, action, to).joinToString(SEP)

    companion object {
        private const val SEP = "\u0000"
        fun from(key: String): InboxPick? {
            val f = key.split(SEP)
            return when {
                f.size == 2 && f[1] == "delete" -> InboxPick(f[0], "delete")
                f.size == 3 && f[1] == "move" -> InboxPick(f[0], "move", f[2])
                else -> null
            }
        }
    }
}

/** The Inbox from the approver's /api/inbox (SECURITY.md 116), checked again here. Off shape
 *  gives null. Acting sends only the snapshot id and the picks (117). */
object InboxSnapshot {
    const val MAX_NOTES = 20
    private const val MAX_PREVIEW = 2000
    private val ID = Regex("[0-9a-f]{64}")
    private val NOTE = Regex("Inbox/\\w[\\w .-]{0,99}\\.md")
    private val FOLDER = Regex("(daily|study)(/[a-z0-9][a-z0-9-]{0,39})?")
    private val DATE = Regex("\\d{4}-\\d{2}-\\d{2}")
    // Hidden, control and bidi marks; newlines and tabs are fine. The laptop already turned
    // them into U+FFFD, so any left means the file was not written by julz-vault
    private val HIDDEN = Regex("[\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}\\x00-\\x08\\x0B-\\x1F\\x7F]")

    /** The Now card's line, from the live count; null while it is not known. */
    fun line(count: Int?): String = when {
        count == null -> "Notes waiting to be sorted"
        count == 0 -> "Empty, nothing to sort"
        count == 1 -> "1 note waiting to be sorted"
        count >= MAX_NOTES -> "$MAX_NOTES or more notes waiting to be sorted"
        else -> "$count notes waiting to be sorted"
    }

    fun parse(raw: String): InboxSnapshotData? {
        val j = try { JSONObject(raw) } catch (e: Exception) { return null }
        val id = j.optString("id")
        val notes = j.optJSONArray("notes") ?: return null
        val folders = j.optJSONArray("folders") ?: return null
        if (!(ID.matches(id) || (id.isEmpty() && notes.length() == 0)) || notes.length() > MAX_NOTES) return null
        val list = (0 until notes.length()).map { i ->
            val n = notes.optJSONObject(i) ?: return null
            val note = n.optString("note"); val sha = n.optString("sha256")
            val preview = n.optString("preview"); val modified = n.optString("modified")
            if (!NOTE.matches(note) || !ID.matches(sha) || !DATE.matches(modified) || preview.length > MAX_PREVIEW ||
                HIDDEN.containsMatchIn(preview) || HIDDEN.containsMatchIn(n.optString("name"))) return null
            InboxNote(n.optString("name"), note, sha, n.optInt("size"), modified, preview)
        }
        val dirs = (0 until folders.length()).map { folders.optString(it).takeIf { f -> FOLDER.matches(f) } ?: return null }
        return InboxSnapshotData(id, list, dirs)
    }

    /** What the app sends to begin: the snapshot id it saw and the picks, never a path it made up. */
    fun body(id: String, picks: List<InboxPick>): JSONObject? {
        if (!ID.matches(id) || picks.isEmpty() || picks.size > MAX_NOTES) return null
        val arr = JSONArray()
        for (p in picks) {
            val o = JSONObject().put("note", p.note).put("do", p.action)
            when {
                p.action == "delete" && p.to == null -> {}
                p.action == "move" && p.to != null -> o.put("to", p.to)
                else -> return null
            }
            arr.put(o)
        }
        return JSONObject().put("action", "inbox").put("sha256", id).put("pick", arr).put("via", "device")
    }
}
