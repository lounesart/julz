package app.julz.approve

import org.json.JSONArray
import org.json.JSONObject

data class NeedItem(val root: String, val step: Int, val project: String, val goal: String, val need: String,
                    val why: String, val text: String, val sha256: String, val work: String, val stopped: Boolean)
data class RunItem(val sha256: String, val project: String, val goal: String, val step: Int, val text: String,
                   val textSha: String)
data class QueuedItem(val sha256: String, val goal: String, val step: Int, val kind: String, val overridden: Boolean,
                      val overrideText: String?, val overrideSha: String?)
data class KeepFile(val path: String, val size: Int)
data class KeepItem(val root: String, val goal: String, val project: String, val files: List<KeepFile>,
                    val rejected: List<Pair<String, String>>, val rejectedCount: Int, val stopped: String?, val sha256: String)
data class WorkState(val needs: List<NeedItem>, val running: RunItem?, val queued: List<QueuedItem>, val keeps: List<KeepItem>,
                     val topics: List<String> = emptyList()) {
    companion object {
        private val HEX64 = Regex("[0-9a-f]{64}")
        private val PROJECT = Regex("[a-z0-9][a-z0-9-]{0,39}")
        private val KEEP_PATH = Regex("[\\w.-]+(/[\\w.-]+){0,7}")
        private val HIDDEN = Regex("[\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}\\x00-\\x08\\x0B-\\x1F\\x7F]")
        private const val MAX_FIELD = 500
        private const val MAX_TOPICS = 20
        private val TOPIC = Regex("[a-z0-9][a-z0-9-]{0,39}")
        private val MAX_TEXT = ApproverState.MAX_TEXT

        /** Plain text of at most max characters, or null: Claude wrote it (121). */
        private fun JSONObject.plain(key: String, max: Int = MAX_FIELD): String? =
            optString(key).takeIf { it.length <= max && !HIDDEN.containsMatchIn(it) }

        private fun <T> JSONArray?.cards(one: (JSONObject) -> T?): List<T> =
            if (this == null) emptyList() else (0 until length()).mapNotNull { optJSONObject(it)?.let(one) }

        /** The work cards of /api/state. A card that is off in any way is dropped; the rest show. */
        fun parse(raw: String): WorkState? {
            if (raw.length > ApproverState.MAX_BYTES) return null
            val j = try { JSONObject(raw) } catch (e: Exception) { return null }
            val needs = j.optJSONArray("needs").cards { n ->
                val root = n.optString("root"); val sha = n.optString("sha256"); val project = n.optString("project")
                if (!HEX64.matches(root) || !HEX64.matches(sha) || !PROJECT.matches(project)) return@cards null
                NeedItem(root, n.optInt("step"), project, n.plain("goal") ?: return@cards null, n.plain("need") ?: return@cards null,
                    n.plain("why") ?: return@cards null, n.plain("text", MAX_TEXT)?.takeIf { it.isNotEmpty() } ?: return@cards null,
                    sha, n.plain("work") ?: return@cards null, n.optBoolean("stopped"))
            }
            val running = j.optJSONObject("running")?.let { r ->
                val sha = r.optString("sha256"); val textSha = r.optString("text_sha256")
                if (!HEX64.matches(sha) || !HEX64.matches(textSha)) null
                else RunItem(sha, r.plain("project") ?: "", r.plain("goal") ?: "", r.optInt("step"),
                    r.plain("text", MAX_TEXT) ?: return@let null, textSha)
            }
            val queued = j.optJSONArray("queued").cards { q ->
                val sha = q.optString("sha256")
                if (!HEX64.matches(sha)) return@cards null
                val o = q.optJSONObject("override")
                val oSha = o?.optString("sha256")?.takeIf { HEX64.matches(it) }
                QueuedItem(sha, q.plain("goal") ?: return@cards null, q.optInt("step"), q.plain("kind", 20) ?: "",
                    q.optBoolean("overridden"), oSha?.let { o.plain("text", MAX_TEXT) }, oSha)
            }
            val keeps = j.optJSONArray("keeps").cards { k ->
                val root = k.optString("root"); val sha = k.optString("sha256"); val project = k.optString("project")
                if (!HEX64.matches(root) || !HEX64.matches(sha) || !PROJECT.matches(project)) return@cards null
                val files = k.optJSONArray("files").cards { f ->
                    f.optString("path").takeIf { KEEP_PATH.matches(it) && ".." !in it.split('/') }?.let { KeepFile(it, f.optInt("size")) }
                }
                if (files.size != (k.optJSONArray("files")?.length() ?: 0) || files.isEmpty()) return@cards null
                val rejected = k.optJSONArray("rejected").cards { r -> r.plain("path", 200)?.let { p -> r.plain("reason", 200)?.let { p to it } } }
                KeepItem(root, k.plain("goal") ?: return@cards null, project, files, rejected, k.optInt("rejected_count"),
                    if (k.isNull("stopped")) null else k.plain("stopped"), sha)
            }
            // My Keep topics so far, as choices; the server checks the one I sign again (131)
            val topics = j.optJSONArray("topics")?.let { a -> (0 until a.length()).mapNotNull { a.optString(it).takeIf(TOPIC::matches) } }
                .orEmpty().distinct().take(MAX_TOPICS)
            return WorkState(needs, running, queued, keeps, topics)
        }
    }
}

/** Cards the server counts that the app dropped as off (121): only these need the approver
 *  page. Every card shown here is handled here (found 18 Oct, 9b). */
fun hiddenCards(s: ApproverState, w: WorkState?): Int = if (w == null) s.elsewhere else
    maxOf(0, s.needs - w.needs.size) + maxOf(0, s.keeps - w.keeps.size) + maxOf(0, s.queued - w.queued.size) +
        (if (s.running && w.running == null) 1 else 0)

/** How long Approve waits before it asks the laptop again: 3 s while a run goes or waits in
 *  line, or for a minute after I acted (a run starts a few seconds later), else 15 s. A run
 *  can take 5 s, and its Stop card has to show while it goes (found 18 Oct, 9b). */
fun reloadDelay(w: WorkState?, now: Long, fastUntil: Long): Long =
    if (w?.running != null || w?.queued?.isNotEmpty() == true || now < fastUntil) 3_000L else 15_000L

/** What the app sends to begin each action, the same as the approver page sends (approve.js):
 *  only ids, hashes and the one value I give. The server builds the text I sign (121, 109). */
object WorkBodies {
    private val TOPIC = Regex("[a-z0-9][a-z0-9-]{0,39}")
    const val MAX_ANSWER = 300

    /** Continue when the box is empty, else the answer; null when the answer breaks the note rules (93). */
    fun need(n: NeedItem, answer: String): JSONObject? {
        val a = answer.trim()
        val body = JSONObject().put("root", n.root).put("sha256", n.sha256).put("via", "device")
        if (a.isEmpty()) return body.put("action", "continue")
        if (a.length > MAX_ANSWER || Note.problem(a) != null) return null
        return body.put("action", "answer").put("answer", a)
    }

    /** Stop a task waiting for me, or delete a stopped one's work copy. */
    fun stop(n: NeedItem): JSONObject = JSONObject().put("action", if (n.stopped) "discard" else "stop")
        .put("root", n.root).put("sha256", n.sha256).put("via", "device")

    fun halt(r: RunItem): JSONObject = JSONObject().put("action", "halt").put("run", r.sha256).put("sha256", r.textSha).put("via", "device")

    fun override(q: QueuedItem): JSONObject? = q.overrideSha?.let {
        JSONObject().put("action", "override").put("item", q.sha256).put("sha256", it).put("via", "device")
    }

    /** The ticked paths, in the card's order; null for a bad topic, none ticked or a path not in the card. */
    fun keep(k: KeepItem, topic: String, picked: List<String>): JSONObject? {
        val paths = k.files.map { it.path }
        if (!TOPIC.matches(topic) || picked.isEmpty() || picked.any { it !in paths }) return null
        return JSONObject().put("action", "keep").put("root", k.root).put("sha256", k.sha256).put("topic", topic)
            .put("pick", JSONArray(paths.filter { it in picked })).put("via", "device")
    }
}
