package app.julz.feed

import org.json.JSONObject

/** A note in the list: no text, that comes by [id] when the note is opened (206). */
data class VaultNote(val name: String, val note: String, val modified: String, val size: Int, val id: String,
                     val tags: List<String> = emptyList())

data class VaultFolder(val folder: String, val notes: List<VaultNote>)

/** The notes browser from the approver's /api/notes (SECURITY.md 118, 148), read only and
 *  checked again here. Off shape gives null. */
object VaultNotes {
    private const val MAX_NOTES = 300
    private const val MAX_TEXT = 4000
    private val FOLDER = Regex("(study|daily|Inbox|Claude|Outbox|feedback)(/\\w[\\w .-]{0,99})*")
    private val DATE = Regex("\\d{4}-\\d{2}-\\d{2}")
    private val ID = Regex("[0-9a-f]{64}")
    private val HIDDEN = Regex("[\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}\\x00-\\x08\\x0B-\\x1F\\x7F]")
    // A tag (149): a letter, then letters, digits, _ - /, lower case, as the approver checks it
    private val TAG = Regex("\\p{L}[\\p{L}\\p{N}_/-]{0,39}")
    private const val MAX_NOTE_TAGS = 10
    private const val MAX_TAGS = 200

    private fun isTag(t: String) = TAG.matches(t) && t == t.lowercase()

    fun parse(raw: String): List<VaultFolder>? {
        val o = try { JSONObject(raw) } catch (e: Exception) { return null }
        val folders = o.optJSONArray("folders") ?: return null
        // Tags come as one table, each note's as indexes into it (212)
        val table = o.optJSONArray("tags") ?: return null
        if (table.length() > MAX_TAGS) return null
        val tags = (0 until table.length()).map { (table.opt(it) as? String)?.takeIf(::isTag) ?: return null }
        if (tags.toSet().size != tags.size) return null
        var count = 0
        return (0 until folders.length()).map { i ->
            val f = folders.optJSONObject(i) ?: return null
            val name = f.optString("folder"); val notes = f.optJSONArray("notes") ?: return null
            if (!FOLDER.matches(name) || name.startsWith("Inbox/")) return null
            VaultFolder(name, (0 until notes.length()).map { j ->
                val n = notes.optJSONObject(j) ?: return null
                val note = n.optString("note"); val id = n.optString("id"); val modified = n.optString("modified")
                if (note.substringBeforeLast('/') != name || !note.endsWith(".md") || !DATE.matches(modified) ||
                    !ID.matches(id) || HIDDEN.containsMatchIn(n.optString("name")) || ++count > MAX_NOTES) return null
                val idx = n.optJSONArray("tags") ?: return null
                if (idx.length() > MAX_NOTE_TAGS) return null
                val mine = (0 until idx.length()).map { k -> tags.getOrNull(idx.opt(k) as? Int ?: return null) ?: return null }
                if (mine.toSet().size != mine.size) return null
                VaultNote(n.optString("name"), note, modified, n.optInt("size"), id, mine)
            })
        }
    }

    /** One note's text from /api/notes/<id>. The reply must name the note that was [asked]
     *  for, with only its text beside it. Off shape gives null. */
    fun one(raw: String, asked: String): String? {
        val o = try { JSONObject(raw) } catch (e: Exception) { return null }
        if (o.keys().asSequence().toSet() != setOf("note", "text") || o.optString("note") != asked) return null
        val text = o.opt("text") as? String ?: return null
        return if (text.length > MAX_TEXT || HIDDEN.containsMatchIn(text)) null else text
    }

    /** The notes with [tag], across folders, in the list's order (212). */
    fun withTag(folders: List<VaultFolder>, tag: String): List<VaultNote> = folders.flatMap { it.notes }.filter { tag in it.tags }

    /** A tag as the list names it, from a #tag in a note or a front matter tag: no #, no quotes,
     *  lower case. Null when it is not shaped like a tag. */
    fun tagKey(raw: String): String? = raw.trim().trim('\'', '"').removePrefix("#").lowercase().takeIf(::isTag)

    /** How many notes each folder holds, for the Move panel. */
    fun counts(folders: List<VaultFolder>): Map<String, Int> = folders.associate { it.folder to it.notes.size }
}
