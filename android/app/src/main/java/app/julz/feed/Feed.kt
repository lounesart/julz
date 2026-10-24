package app.julz.feed

import java.io.File
import org.json.JSONObject

/** Notices kept on the phone: 30 days, at most MAX_ENTRIES, one JSON object per line in the app's
 *  no backup folder. Every line read back is checked like a fresh notice (threats 89, 91). */
class FeedStore(private val file: File, private val now: () -> Long) {
    private var items: MutableList<Notice> = load()

    /** Newest first; notices of the same second keep their arrival order, newest first. */
    fun all(): List<Notice> = items.withIndex()
        .sortedWith(compareByDescending<IndexedValue<Notice>> { it.value.time }.thenByDescending { it.index })
        .map { it.value }

    fun lastId(): String? = all().firstOrNull()?.id

    /** False for a notice already kept: catch up may send it again (threat 92). */
    @Synchronized fun add(notice: Notice): Boolean {
        if (items.any { it.id == notice.id }) return false
        items.add(notice)
        if (items.size > MAX_ENTRIES) {
            items = all().take(MAX_ENTRIES).reversed().toMutableList()
        }
        save()
        return true
    }

    @Synchronized fun purge(): Int {
        val cutoff = now() - KEEP_SECONDS
        val before = items.size
        items.removeAll { it.time < cutoff }
        if (items.size != before) save()
        return before - items.size
    }

    @Synchronized fun wipe() {
        items.clear()
        file.delete()
    }

    /** [kindSeen]: per kind, up to when the open screen showed it (no tray entry then). */
    fun unreadSince(seenUpTo: Long, kindSeen: Map<Kind, Long> = emptyMap()): Map<Kind, Int> =
        items.filter { it.time > maxOf(seenUpTo, kindSeen[it.kind] ?: 0L) }.groupingBy { it.kind }.eachCount()

    private fun load(): MutableList<Notice> {
        if (!file.exists()) return mutableListOf()
        return file.readLines().mapNotNull(::fromLine).distinctBy { it.id }.toMutableList()
    }

    private fun save() {
        val tmp = File(file.parentFile, file.name + ".tmp")
        tmp.writeText(items.joinToString("") { toLine(it) + "\n" })
        tmp.renameTo(file)
    }

    companion object {
        const val MAX_ENTRIES = 2_000
        const val KEEP_SECONDS = 30L * 86_400

        fun toLine(n: Notice): String = JSONObject()
            .put("id", n.id).put("time", n.time).put("kind", n.kind.name)
            .put("title", n.title).put("message", n.message).toString()

        /** Back through the stream parser's own rules, so a changed file earns nothing. */
        fun fromLine(line: String): Notice? {
            val json = try { JSONObject(line) } catch (e: Exception) { return null }
            val kind = Kind.entries.firstOrNull { it.name == json.opt("kind") } ?: return null
            val event = JSONObject()
                .put("event", "message").put("id", json.opt("id")).put("time", json.opt("time"))
                .put("title", json.opt("title")).put("message", json.opt("message"))
                .put("tags", org.json.JSONArray().put(kind.tag))
            return NoticeParser.parse(event.toString())
        }
    }
}

/** The address of the live stream with catch up. Built only from checked parts (threat 92). */
object Stream {
    private val TOPIC = Regex("julz-[0-9a-f]{32}")
    private val ID = Regex("[A-Za-z0-9]{8,32}")

    fun url(server: String, topic: String, lastId: String?): String? {
        if (!app.julz.settings.Settings.validServer(server) || !TOPIC.matches(topic)) return null
        if (lastId != null && !ID.matches(lastId)) return null
        return "$server/$topic/json?since=${lastId ?: "48h"}"
    }

    fun validTopic(topic: String) = TOPIC.matches(topic)
}

/** What a notification may say: a kind and a count, never a notice title (threat 90). */
object Shade {
    private val words = mapOf(
        Kind.APPROVAL to ("Approvals" to ("approval" to "approvals")),
        Kind.TODO to ("Todos" to ("todo" to "todos")),
        Kind.INBOX to ("Inbox" to ("draft" to "drafts")),
        Kind.RUN to ("Runs" to ("run" to "runs")),
        Kind.REVIEW to ("Review" to ("review" to "reviews")),
        Kind.CHANGE to ("Changes" to ("change" to "changes")),
        Kind.WARNING to ("Warnings" to ("warning" to "warnings")),
    )

    fun text(kind: Kind, count: Int): Pair<String, String> {
        val (channel, forms) = words.getValue(kind)
        val word = if (count == 1) forms.first else forms.second
        return "Julz · $channel" to "$count new $word"
    }
}
