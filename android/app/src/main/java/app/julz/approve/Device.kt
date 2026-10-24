package app.julz.approve

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.security.keystore.StrongBoxUnavailableException
import app.julz.ui.Origins
import java.net.HttpURLConnection
import java.net.URL
import java.security.KeyPairGenerator
import java.security.KeyStore
import java.security.MessageDigest
import java.security.PrivateKey
import java.security.Signature
import java.security.spec.ECGenParameterSpec
import org.json.JSONObject

/** What the phone signs and shows, the same bytes as julz_devicekey.py (SECURITY.md 107, 108). */
object DevicePayload {
    private val DOMAIN = "julz-device-v1\u0000".toByteArray()
    private val HEX64 = Regex("[0-9a-f]{64}")

    fun build(action: String, text: String, nonce: String): ByteArray {
        require(HEX64.matches(nonce)) { "bad nonce" }
        val bind = MessageDigest.getInstance("SHA-256").digest(action.toByteArray() + byteArrayOf(0) + text.toByteArray())
        return DOMAIN + bind + nonce.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    }

    /** Shown after enrolling, to compare with `julz-approve-web.py --device` on the laptop. */
    fun fingerprint(der: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }
            .take(16).chunked(4).joinToString("-")
}

/** The gate's rules for my note (93), so I see a problem before the fingerprint. The server
 *  checks again and is the one that decides. */
object Note {
    const val MAX = 280
    private val LINK = Regex("(?i)\\b[a-z][a-z0-9+.-]*://|\\bwww\\.")
    private val SECRET = Regex("(?<![A-Za-z0-9])(ghp_|gho_|ghu_|ghs_|ghr_|github_pat_|glpat-|sk-|AKIA|xox[abprs]-)")
    private val RUN = Regex("[A-Za-z0-9_+=-]{32,}")
    private val HIDDEN = Regex("[\\p{Cc}\\p{Cf}\\p{Co}\\p{Cs}\\p{Cn}]")

    /** null when the note is fine (or empty: no note), else what is wrong. */
    fun problem(note: String): String? {
        val n = note.trim()
        return when {
            n.isEmpty() -> null
            n.length > MAX -> "at most $MAX characters"
            HIDDEN.containsMatchIn(n) -> "one line, no hidden characters"
            "<<<" in n || ">>>" in n || "<!--" in n -> "no <<< or >>> markers"
            LINK.containsMatchIn(n) -> "no links"
            SECRET.containsMatchIn(n) || "-----BEGIN" in n || RUN.findAll(n).any { m ->
                m.value.any { it.isUpperCase() } && m.value.any { it.isLowerCase() } && m.value.any { it.isDigit() }
            } -> "looks like a secret: do that at the laptop"
            else -> null
        }
    }
}

/** The approver's API, at the derived approver origin only (SECURITY.md 111). */
object ApproverApi {
    const val STATE = "/api/state"
    const val BEGIN = "/api/begin"
    const val FINISH = "/api/finish"
    const val ENROLL = "/api/device/enroll"
    const val DONE = "/api/done"  // the Done tab, read only (114)
    const val INBOX = "/api/inbox"  // the Inbox screen, read only (116)
    const val NOTES = "/api/notes"  // the notes browser, read only (118)
    const val FEEDBACK = "/api/feedback"  // the feedback list, read only (120)
    const val INTEGRATIONS = "/api/integrations"  // the Tools tab, read only (122)
    const val GOALS = "/api/goals"  // the Goals tab, read only (123)
    private val PATHS = setOf(STATE, BEGIN, FINISH, ENROLL, DONE, INBOX, NOTES, FEEDBACK, INTEGRATIONS, GOALS)
    private const val MAX_REPLY = 256_000

    fun origin(o: Origins): String = o.approver.trimEnd('/')

    fun urlOrNull(o: Origins, path: String): String? = if (path in PATHS) origin(o) + path else null

    fun url(o: Origins, path: String): String = urlOrNull(o, path)!!

    /** (status, body). The approver's own Origin, so its POST rules stay as they are; the
     *  signature, not the header, authorizes. */
    fun call(o: Origins, path: String, body: JSONObject? = null): Pair<Int, String> {
        val conn = URL(url(o, path)).openConnection() as HttpURLConnection
        try {
            conn.connectTimeout = 10_000
            conn.readTimeout = 20_000
            conn.useCaches = false
            conn.instanceFollowRedirects = false
            conn.setRequestProperty("Accept", "application/json")
            if (body != null) {
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Origin", origin(o))
                conn.setRequestProperty("Content-Type", "application/json")
                conn.outputStream.use { it.write(body.toString().toByteArray()) }
            }
            val code = conn.responseCode
            val stream = if (code in 200..299) conn.inputStream else conn.errorStream
            val text = stream?.use { s ->
                val bytes = s.readNBytes(MAX_REPLY + 1)
                if (bytes.size > MAX_REPLY) "" else String(bytes, Charsets.UTF_8)
            } ?: ""
            return code to text
        } finally { conn.disconnect() }
    }
}

data class SpecItem(val name: String, val project: String, val text: String, val sha256: String) {
    /** What Julz says in the chat, so the two can be matched by eye (39b). */
    val shortId get() = sha256.take(8)
}

/** /api/state as the app uses it: specs to approve here, the rest counted for the page. */
data class ApproverState(val specs: List<SpecItem>, val device: String?, val needs: Int = 0, val queued: Int = 0,
                         val keeps: Int = 0, val running: Boolean = false) {
    val elsewhere: Int get() = needs + queued + keeps + (if (running) 1 else 0)
    /** The Approve badge: what waits for my decision. A run going or in line does not (9b). */
    val waitingForMe: Int get() = specs.size + needs + keeps

    /** What waits on the approver page, one (title, line) per kind that is really there. */
    fun onThePage(): List<Pair<String, String>> = buildList {
        fun n(count: Int, one: String, many: String) = if (count == 1) "1 $one" else "$count $many"
        if (needs > 0) add((if (needs == 1) "Question from Claude" else "Questions from Claude") to
            n(needs, "task waits for your answer", "tasks wait for your answer"))
        if (running) add("Running now" to "Claude is working")
        if (queued > 0) add("Waiting to run" to "$queued approved, in line")
        if (keeps > 0) add("Keep" to n(keeps, "finished task: choose notes to keep", "finished tasks: choose notes to keep"))
    }

    companion object {
        const val MAX_BYTES = 256_000
        const val MAX_TEXT = 4096
        private val NAME = Regex("[a-z0-9][a-z0-9-]{0,60}\\.md")
        private val PROJECT = Regex("[a-z0-9][a-z0-9-]{0,39}")
        private val HEX64 = Regex("[0-9a-f]{64}")
        private val FINGERPRINT = Regex("[0-9a-f]{4}(-[0-9a-f]{4}){3}")

        fun parse(raw: String): ApproverState? {
            if (raw.length > MAX_BYTES) return null
            val j = try { JSONObject(raw) } catch (e: Exception) { return null }
            val list = j.optJSONArray("specs") ?: return null
            val specs = (0 until list.length()).mapNotNull { i ->
                val s = list.optJSONObject(i) ?: return@mapNotNull null
                val name = s.optString("name"); val sha = s.optString("sha256")
                val text = s.optString("text"); val project = s.optString("project")
                if (NAME.matches(name) && HEX64.matches(sha) && PROJECT.matches(project) &&
                    text.isNotEmpty() && text.length <= MAX_TEXT) SpecItem(name, project, text, sha) else null
            }
            val device = j.optString("device").takeIf { FINGERPRINT.matches(it) }
            fun count(key: String) = j.optJSONArray(key)?.length() ?: 0
            return ApproverState(specs, device, count("needs"), count("queued"), count("keeps"),
                j.optJSONObject("running") != null)
        }
    }
}

/** The server's answer to a device begin: the nonce and the exact text to show and sign (109). */
data class Begun(val nonce: String, val action: String, val text: String) {
    /** The text to sign ends with exactly the note I typed, or has none when I typed none.
     *  A deny never carries one (93). */
    fun carries(note: String): Boolean {
        if (action != "approve") return true
        val n = note.trim()
        val last = text.trimEnd('\n').substringAfterLast('\n')
        return if (n.isEmpty()) !last.startsWith("note:") else last == "note: $n" && text.endsWith("\n")
    }

    companion object {
        private val HEX64 = Regex("[0-9a-f]{64}")

        fun parse(raw: String, action: String): Begun? {
            val j = try { JSONObject(raw) } catch (e: Exception) { return null }
            val nonce = j.optString("nonce"); val text = j.optString("text")
            if (!HEX64.matches(nonce) || j.optString("action") != action || text.isEmpty() ||
                text.length > ApproverState.MAX_TEXT) return null
            return Begun(nonce, action, text)
        }
    }
}

/** The Julz device key in the hardware keystore (SECURITY.md 107, 110): P-256, never leaves
 *  the keystore, a strong fingerprint for each signature, dies when a fingerprint is added. */
object DeviceKey {
    private const val ALIAS = "julz-approver"
    private fun store() = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    fun publicDer(): ByteArray? = store().getCertificate(ALIAS)?.publicKey?.encoded

    /** A new key in place of any old one. StrongBox when the phone has it, else the TEE. */
    fun create(): ByteArray {
        delete()
        fun spec(strongBox: Boolean) = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_SIGN)
            .setAlgorithmParameterSpec(ECGenParameterSpec("secp256r1"))
            .setDigests(KeyProperties.DIGEST_SHA256)
            .setUserAuthenticationRequired(true)
            .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)  // every use
            .setInvalidatedByBiometricEnrollment(true)
            .setUnlockedDeviceRequired(true)
            .setIsStrongBoxBacked(strongBox)
            .build()
        val gen = KeyPairGenerator.getInstance(KeyProperties.KEY_ALGORITHM_EC, "AndroidKeyStore")
        try {
            gen.initialize(spec(true)); gen.generateKeyPair()
        } catch (e: StrongBoxUnavailableException) {
            gen.initialize(spec(false)); gen.generateKeyPair()
        }
        return publicDer()!!
    }

    /** A signer ready for BiometricPrompt. Throws KeyPermanentlyInvalidatedException after a
     *  fingerprint was added: the app then asks me to enroll again. */
    fun signer(): Signature = Signature.getInstance("SHA256withECDSA").apply {
        initSign(store().getKey(ALIAS, null) as PrivateKey)
    }

    fun delete() {
        store().takeIf { it.containsAlias(ALIAS) }?.deleteEntry(ALIAS)
    }
}
