package app.julz.approve

import java.security.MessageDigest
import org.json.JSONObject

/** One change Julz asked for where the chat has no dialog (208): the laptop's card text. */
data class Proposal(val id: String, val text: String, val sha256: String)

/** The cards from /api/proposals (SECURITY.md 156). The laptop builds each text from a checked
 *  request in fixed words; here it is checked again as if anyone could have written it, and the
 *  hash must be the text's own. Anything off is no list at all. */
object Proposals {
    const val MAX = 10
    private val ID = Regex("\\d{10}-[0-9a-f]{8}\\.json")
    // The card has line breaks; nothing else hidden, no right to left or zero width (Trojan Source)
    private val HIDDEN = Regex("[\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}\\x00-\\x09\\x0B-\\x1F\\x7F]")
    private val KEYS = setOf("id", "text", "sha256")
    private val ACTIONS = setOf("change", "drop")

    fun sha256(s: String): String =
        MessageDigest.getInstance("SHA-256").digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    fun parse(raw: String): List<Proposal>? {
        val items = try { JSONObject(raw).getJSONArray("proposals") } catch (e: Exception) { return null }
        if (items.length() > MAX) return null
        return (0 until items.length()).map { i ->
            val o = items.optJSONObject(i) ?: return null
            if (o.keys().asSequence().toSet() != KEYS) return null
            val p = Proposal(o.optString("id"), o.optString("text"), o.optString("sha256"))
            if (!ID.matches(p.id) || p.text.isEmpty() || p.text.length > ApproverState.MAX_TEXT ||
                HIDDEN.containsMatchIn(p.text) || sha256(p.text) != p.sha256) return null
            p
        }
    }

    /** Sign it (change) or drop it: the card's id and the hash of the text I see; the laptop
     *  builds the text to sign again from its file and refuses any other. */
    fun body(p: Proposal, action: String): JSONObject {
        require(action in ACTIONS)
        return JSONObject().put("action", action).put("id", p.id).put("sha256", p.sha256).put("via", "device")
    }
}
