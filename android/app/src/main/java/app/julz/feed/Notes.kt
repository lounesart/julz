package app.julz.feed

import org.json.JSONObject

data class VaultNote(val name: String, val note: String, val modified: String, val size: Int, val text: String)

data class VaultFolder(val folder: String, val notes: List<VaultNote>)

/** The notes browser from the approver's /api/notes (SECURITY.md 118), read only and checked
 *  again here. Off shape gives null. */
object VaultNotes {
    private const val MAX_NOTES = 300
    private const val MAX_TEXT = 4000
    private val FOLDER = Regex("(study|daily|Inbox|Claude|Outbox|feedback)(/\\w[\\w .-]{0,99})*")
    private val DATE = Regex("\\d{4}-\\d{2}-\\d{2}")
    private val HIDDEN = Regex("[\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}\\x00-\\x08\\x0B-\\x1F\\x7F]")

    fun parse(raw: String): List<VaultFolder>? {
        val folders = try { JSONObject(raw).getJSONArray("folders") } catch (e: Exception) { return null }
        var count = 0
        return (0 until folders.length()).map { i ->
            val f = folders.optJSONObject(i) ?: return null
            val name = f.optString("folder"); val notes = f.optJSONArray("notes") ?: return null
            if (!FOLDER.matches(name) || name.startsWith("Inbox/")) return null
            VaultFolder(name, (0 until notes.length()).map { j ->
                val n = notes.optJSONObject(j) ?: return null
                val note = n.optString("note"); val text = n.optString("text"); val modified = n.optString("modified")
                if (note.substringBeforeLast('/') != name || !note.endsWith(".md") || !DATE.matches(modified) ||
                    text.length > MAX_TEXT || HIDDEN.containsMatchIn(text) || HIDDEN.containsMatchIn(n.optString("name")) ||
                    ++count > MAX_NOTES) return null
                VaultNote(n.optString("name"), note, modified, n.optInt("size"), text)
            })
        }
    }

    /** How many notes each folder holds, for the Move panel. */
    fun counts(folders: List<VaultFolder>): Map<String, Int> = folders.associate { it.folder to it.notes.size }
}
