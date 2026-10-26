package app.julz.chat

import app.julz.settings.Settings
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

data class ChatSummary(val id: String, val title: String, val updated: Long)
/** Why an answer ended, from julz-chat (26k): the window filled, or the model stopped */
enum class End { LENGTH, STOP }

data class ChatMessage(val id: String, val user: Boolean, val text: String, val done: Boolean, val time: Long, val error: String?,
                       val end: End? = null)
data class ChatView(val id: String, val title: String, val busy: Boolean, val messages: List<ChatMessage>,
                    val archived: Boolean = false, val mode: String = "")
data class Sent(val chat: String, val message: String)

/** julz-chat on the laptop, the native chat's only way to Open WebUI (SECURITY.md 136, 138).
 *  Its address comes from the checked server setting, never from a reply; paths are built here
 *  from checked ids only; replies become plain fields, capped. */
object ChatApi {
    const val MAX_TEXT = 8_000  // julz-chat's own limit
    const val MAX_TITLE = 200
    const val MAX_ANSWER = 200_000
    const val MAX_ERROR = 500
    /** julz-chat's mode names (135, threat 151); the words for each live on the laptop */
    val MODES = setOf("learn")
    private const val MAX_REPLY = 2_000_000
    private val ID = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    private val MESSAGE_ID = Regex("[A-Za-z0-9-]{1,64}")

    /** The push server's name on julz-chat's port: https://<name>:8445 */
    fun origin(server: String): String? =
        if (Settings.validServer(server)) server.removeSuffix(":8444") + ":8445" else null

    fun list(page: Int): String? = if (page in 1..20) "/api/chats?page=$page" else null
    fun view(id: String): String? = id.takeIf { ID.matches(it) }?.let { "/api/chats/$it" }
    fun last(id: String): String? = view(id)?.let { "$it/last" }
    fun stop(id: String): String? = view(id)?.let { "$it/stop" }
    /** A new chat for null, else the next message in that chat */
    fun send(id: String?): String? = if (id == null) "/api/chats" else view(id)?.let { "$it/messages" }
    // v2 (26b, 136): archive and delete one, retry and edit; never anything for all chats
    fun archived(page: Int): String? = if (page in 1..20) "/api/chats/archived?page=$page" else null
    fun archive(id: String): String? = view(id)?.let { "$it/archive" }
    fun unarchive(id: String): String? = view(id)?.let { "$it/unarchive" }
    fun retry(id: String): String? = view(id)?.let { "$it/retry" }
    fun edit(id: String): String? = view(id)?.let { "$it/edit" }
    /** With the DELETE method; the same path as the chat itself */
    fun delete(id: String): String? = view(id)

    /** The text and, when one is on, a mode's name; "" is no mode */
    fun body(text: String, mode: String = ""): String? =
        if (text.isBlank() || text.length > MAX_TEXT || '\u0000' in text || (mode != "" && mode !in MODES)) null
        else JSONObject().put("text", text).apply { if (mode != "") put("mode", mode) }.toString()

    private fun obj(raw: String): JSONObject? = try { JSONObject(raw) } catch (e: Exception) { null }

    fun parseList(raw: String): List<ChatSummary>? {
        val rows = obj(raw)?.optJSONArray("chats") ?: return null
        return (0 until rows.length()).mapNotNull { i ->
            val r = rows.optJSONObject(i) ?: return@mapNotNull null
            val id = r.opt("id") as? String ?: return@mapNotNull null
            if (!ID.matches(id)) return@mapNotNull null
            ChatSummary(id, r.optString("title", "").take(MAX_TITLE), (r.opt("updated") as? Number)?.toLong() ?: 0L)
        }
    }

    fun parseMessage(raw: String): ChatMessage? = obj(raw)?.let { message(it) }

    private fun message(m: JSONObject): ChatMessage? {
        val user = when (m.opt("role")) { "user" -> true; "assistant" -> false; else -> return null }
        val id = (m.opt("id") as? String)?.takeIf { MESSAGE_ID.matches(it) } ?: return null
        val error = (m.opt("error") as? String)?.take(MAX_ERROR)
        val end = when (m.opt("end")) { "length" -> End.LENGTH; "stop" -> End.STOP; else -> null }
        return ChatMessage(id, user, m.optString("text", "").take(MAX_ANSWER), m.optBoolean("done", true),
            (m.opt("time") as? Number)?.toLong() ?: 0L, error, end)
    }

    fun parseView(raw: String): ChatView? {
        val o = obj(raw) ?: return null
        val id = (o.opt("id") as? String)?.takeIf { ID.matches(it) } ?: return null
        val rows = o.optJSONArray("messages") ?: JSONArray()
        val messages = (0 until rows.length()).mapNotNull { i -> rows.optJSONObject(i)?.let { message(it) } }
        return ChatView(id, o.optString("title", "").take(MAX_TITLE), o.optBoolean("busy", false), messages,
            o.opt("archived") == true, (o.opt("mode") as? String)?.takeIf { it in MODES } ?: "")
    }

    fun parseArchived(raw: String): Boolean? = obj(raw)?.opt("archived") as? Boolean

    fun parseDeleted(raw: String): Boolean = obj(raw)?.opt("deleted") == true

    fun parseSent(raw: String): Sent? {
        val o = obj(raw) ?: return null
        val chat = (o.opt("chat") as? String)?.takeIf { ID.matches(it) } ?: return null
        val message = (o.opt("message") as? String)?.takeIf { ID.matches(it) } ?: return null
        return Sent(chat, message)
    }

    // No answer at all, by cause (128): codes no HTTP status can be
    const val UNREACHABLE = 0
    const val NO_NAME = -1
    const val SLOW = -2
    const val TLS = -3

    /** What a refusal means, in words for the screen; 0 and below is no answer at all. */
    fun problem(code: Int): String = when (code) {
        409 -> "Julz is still answering"
        429 -> "Too many messages this hour"
        401 -> "The phone token was refused"
        404 -> "That chat is gone"
        413, 400 -> "That message is too long"
        NO_NAME -> "The phone cannot find the laptop. Is Tailscale running on the phone?"
        SLOW -> "The laptop took too long to answer. Try again"
        TLS -> "The laptop's certificate was refused"
        UNREACHABLE -> "The laptop is not reachable. Is it on and Tailscale up?"
        else -> "Open WebUI did not answer"
    }

    /** Why a call got no answer. A cold model never lands here: julz-chat answers at once and
     *  the words follow (measured 26 Oct, every call under 0.1 s while Ollama loaded for 34 s). */
    fun failure(e: Exception, connected: Boolean): Int = when {
        e is java.net.UnknownHostException -> NO_NAME
        e is javax.net.ssl.SSLException && !connected -> TLS  // the handshake is in connect()
        e is java.net.SocketTimeoutException && connected -> SLOW
        else -> UNREACHABLE
    }

    /** (status, body); status 0 or below when the laptop gave no answer, see failure. The phone
     *  token goes to the derived origin only; no Origin header, so julz-chat knows no browser
     *  sent it; no redirects. */
    fun call(origin: String, path: String, token: String, body: String? = null, delete: Boolean = false,
             readMs: Int = 35_000, connectMs: Int = 10_000): Pair<Int, String> {
        var connected = false
        return try { exchange(origin, path, token, body, delete, readMs, connectMs) { connected = true } }
        catch (e: Exception) { failure(e, connected) to "" }
    }

    private fun exchange(origin: String, path: String, token: String, body: String?, delete: Boolean, readMs: Int, connectMs: Int,
                         connected: () -> Unit): Pair<Int, String> {
        val conn = URL(origin + path).openConnection() as HttpURLConnection
        return try {
            conn.connectTimeout = connectMs
            conn.readTimeout = readMs  // julz-chat waits up to 30 s on Open WebUI
            conn.useCaches = false
            conn.instanceFollowRedirects = false
            conn.setRequestProperty("Accept", "application/json")
            conn.setRequestProperty("Authorization", "Bearer $token")
            if (delete) conn.requestMethod = "DELETE"
            else if (body != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
            }
            // On its own, so a timeout after this is a slow laptop, not an unreachable one
            conn.connect()
            connected()
            if (body != null && !delete) conn.outputStream.use { it.write(body.toByteArray()) }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.use { s ->
                val bytes = s.readNBytes(MAX_REPLY + 1)
                if (bytes.size > MAX_REPLY) "" else String(bytes, Charsets.UTF_8)
            } ?: ""
            code to text
        } finally { conn.disconnect() }
    }
}

/** An answer saved into Inbox through the approver, signed with the device key (SECURITY.md
 *  139): the text and its hash; the laptop builds what I sign and checks the hash. Cut to fit
 *  the approver's 16 KB body; the laptop cuts again at 3800 with a line saying so. */
object SaveToNotes {
    const val MAX = 3_900

    fun body(text: String): org.json.JSONObject? {
        val t = text.trim().take(MAX)
        if (t.isEmpty()) return null
        val sha = java.security.MessageDigest.getInstance("SHA-256").digest(t.toByteArray())
            .joinToString("") { "%02x".format(it) }
        return org.json.JSONObject().put("action", "save").put("text", t).put("sha256", sha).put("via", "device")
    }
}

/** A bad answer kept as an eval case through the approver, signed (SECURITY.md 153): my
 *  question, her answer, the mode as a fixed word, and the hash of question NUL answer; the
 *  laptop builds what I sign and cuts each again (1200 and 2400) with a line saying so. */
object KeepCase {
    const val MAX_Q = 1_300
    const val MAX_A = 2_600
    val MODES = setOf("none", "learn", "unknown")

    fun body(question: String, answer: String, mode: String): org.json.JSONObject? {
        val q = question.trim().take(MAX_Q)
        val a = answer.trim().take(MAX_A)
        if (q.isEmpty() || a.isEmpty() || mode !in MODES) return null
        val sha = java.security.MessageDigest.getInstance("SHA-256").digest("$q\u0000$a".toByteArray())
            .joinToString("") { "%02x".format(it) }
        return org.json.JSONObject().put("action", "case").put("question", q).put("answer", a)
            .put("mode", mode).put("sha256", sha).put("via", "device")
    }
}

/** The screen's rules, without the screen. */
object ChatLogic {
    /** My message that a finished answer replies to, for an eval case (155); null when there
     *  is none, as for an answer with no question of mine before it. */
    fun questionFor(v: ChatView, m: ChatMessage): String? {
        val i = v.messages.indexOf(m)
        if (i < 1 || m.user || !m.done || m.text.isBlank()) return null
        return v.messages[i - 1].takeIf { it.user && it.text.isNotBlank() }?.text
    }

    /** The mode an answer ran in, as the case states it: the view knows only the current
     *  branch's, so an older answer says unknown and I name it at the desk. */
    fun modeFor(v: ChatView, m: ChatMessage): String =
        if (v.messages.lastOrNull() != m) "unknown" else if (v.mode == "") "none" else v.mode

    /** How long to wait before the next poll of /last; null when nothing is running. Fast at
     *  first, so words appear as they come; slower for a long answer. */
    fun pollDelay(busy: Boolean, sinceSendMs: Long): Long? = when {
        !busy -> null
        sinceSendMs < 120_000 -> 300L
        else -> 1_000L
    }

    /** The polled message in place of the shown last one; null when it is another message,
     *  and the whole chat must be read again. */
    fun withLast(v: ChatView, m: ChatMessage): ChatView? {
        val last = v.messages.lastOrNull() ?: return null
        if (last.id != m.id) return null
        return v.copy(busy = !m.done, messages = v.messages.dropLast(1) + m)
    }

    /** julz-chat opens only chats it has listed since it started (136): after a restart (every
     *  deploy) a 404 lists again once and repeats the request (215). Safe for a send, since
     *  julz-chat refuses an unknown chat before it does anything */
    suspend fun relisting(call: suspend () -> Pair<Int, String>, list: suspend () -> Boolean): Pair<Int, String> {
        val first = call()
        return if (first.first == 404 && list()) call() else first
    }

    /** An edit goes while she answers: julz-chat stops that answer first (203) */
    fun canSend(text: String, busy: Boolean, sending: Boolean, editing: Boolean = false): Boolean =
        (!busy || editing) && !sending && text.isNotBlank() && text.length <= ChatApi.MAX_TEXT

    /** Julz is working (a tool, the model loading) and has no words yet */
    fun thinking(v: ChatView): Boolean {
        val last = v.messages.lastOrNull() ?: return false
        return v.busy && !last.user && !last.done && last.text.isEmpty()
    }

    /** Retry the last answer only, finished, after a message of mine */
    fun canRetry(v: ChatView, m: ChatMessage): Boolean {
        val n = v.messages.size
        return !v.busy && !m.user && n >= 2 && v.messages[n - 1].id == m.id && v.messages[n - 2].user
    }

    /** Edit my last message only: when nothing runs, or while she answers it (203) */
    fun canEdit(v: ChatView, m: ChatMessage): Boolean {
        if (!m.user || v.messages.lastOrNull { it.user }?.id != m.id) return false
        if (!v.busy) return true
        val n = v.messages.size
        return n >= 2 && !v.messages[n - 1].user && v.messages[n - 2].id == m.id
    }

    private val LIST_LINE = Regex("""^\s*([-*+]|\d{1,3}[.)])\s""")
    private const val SHORT_WORDS = 6
    private const val ENDS = ".!?…:;)]}\"'»`*_>~"

    /** A finished answer whose last line is prose that ends in a letter, digit or comma: cut off
     *  (26k, a long chat ran out of context and stopped mid sentence, marked done). Lists,
     *  tables, headings and code end however they like. A whole answer of a few words ("OK",
     *  "three") is a reply, not a cut: those were marked (found 24 Oct). julz-chat's end word is the
     *  sure sign and wins; the guess is for answers without one (older ones, an older laptop) */
    fun cutOff(m: ChatMessage): Boolean {
        if (m.user || !m.done) return false
        m.end?.let { return it == End.LENGTH }
        val whole = m.text.trim()
        if ('\n' !in whole && whole.split(Regex("\\s+")).size < SHORT_WORDS) return false
        val last = m.text.trimEnd().substringAfterLast('\n').trim()
        if (last.isEmpty() || LIST_LINE.containsMatchIn(last) || last.startsWith("|") || last.startsWith("#") ||
            last.startsWith("```")) return false
        return last.last() !in ENDS
    }

    fun title(raw: String): String = raw.trim().takeIf { it.isNotEmpty() && it != "New Chat" } ?: "New chat"
}
