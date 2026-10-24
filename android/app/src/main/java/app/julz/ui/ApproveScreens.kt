package app.julz.ui

import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.CancellationSignal
import android.security.keystore.KeyPermanentlyInvalidatedException
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import app.julz.AppLog
import app.julz.approve.ApproverApi
import app.julz.approve.ApproverState
import app.julz.approve.Begun
import app.julz.approve.DeviceKey
import app.julz.approve.DevicePayload
import app.julz.approve.Note
import app.julz.approve.SpecItem
import java.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject


internal suspend fun loadState(origins: Origins): Pair<ApproverState?, app.julz.approve.WorkState?> = withContext(Dispatchers.IO) {
    try {
        val (code, body) = ApproverApi.call(origins, ApproverApi.STATE)
        if (code == 200) ApproverState.parse(body) to app.julz.approve.WorkState.parse(body) else null to null
    } catch (e: Exception) { null to null }
}

private fun localFingerprint(): String? = try { DeviceKey.publicDer()?.let { DevicePayload.fingerprint(it) } } catch (e: Exception) { null }

/** Approve in the app with the Julz device key (SECURITY.md 107 to 111). What I sign is the
 *  text the server sends back for this nonce, shown whole above the fingerprint prompt. */
@Composable
fun ApproveScreen(origins: Origins, notes: Map<String, String>, setNote: (String, String?) -> Unit,
                  seen: (ApproverState?) -> Unit = {}, enroll: () -> Unit) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    var state by remember { mutableStateOf<ApproverState?>(null) }
    var work by remember { mutableStateOf<app.julz.approve.WorkState?>(null) }
    var loaded by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf<String?>(null) }
    var busy by remember { mutableStateOf(false) }
    val signing = remember { mutableStateMapOf<String, Begun>() }
    val local = remember { localFingerprint() }
    // Each load also sets the Approve badge, so it drops the moment a card is done (9b)
    fun reload() = scope.launch { loadState(origins).let { (s, w) -> state = s; work = w; seen(s) }; loaded = true }
    // Fast after I act, so the run's Stop card shows while it goes (9b)
    var fastUntil by remember { mutableStateOf(0L) }
    // A notice this screen keeps out of the tray reloads it at once, not at the next tick
    val fresh by app.julz.JulzService.changes.collectAsState()
    val firstFresh = remember { fresh }
    LaunchedEffect(fresh) { if (fresh != firstFresh) reload() }
    LaunchedEffect(Unit) {
        while (true) {
            reload().join()
            kotlinx.coroutines.delay(app.julz.approve.reloadDelay(work, System.currentTimeMillis(), fastUntil))
        }
    }

    fun sign(spec: SpecItem, action: String) {
        val note = notes[spec.name].orEmpty()
        if (action == "approve") Note.problem(note)?.let { status = "Note: $it"; return }
        busy = true; status = null
        scope.launch {
            val begun = withContext(Dispatchers.IO) {
                try {
                    val body = JSONObject().put("action", action).put("name", spec.name).put("sha256", spec.sha256)
                        .put("via", "device")
                    if (action == "approve" && note.isNotBlank()) body.put("note", note)
                    val (code, raw) = ApproverApi.call(origins, ApproverApi.BEGIN, body)
                    if (code == 200) Begun.parse(raw, action) else { status = errorOf(raw, code); null }
                } catch (e: Exception) { status = "The approver is not reachable"; null }
            }
            if (begun == null) { busy = false; status = status ?: "The approver answered oddly"; return@launch }
            if (!begun.carries(note)) {
                // Never sign without the note I typed, or with one I did not type (93)
                busy = false; status = "The text to sign does not carry your note. Nothing was signed."
                return@launch
            }
            signing[spec.name] = begun  // the exact text is on screen now, above the prompt (109)
            val signer = try { DeviceKey.signer() } catch (e: KeyPermanentlyInvalidatedException) {
                busy = false; signing.remove(spec.name)
                status = "A fingerprint was added to this phone, so its key is gone. Enroll again."
                return@launch
            } catch (e: Exception) {
                busy = false; signing.remove(spec.name); status = "This phone has no approval key. Enroll it in Settings."
                return@launch
            }
            val executor = context.mainExecutor
            val prompt = BiometricPrompt.Builder(context)
                .setTitle(if (action == "approve") "Approve with Julz" else "Deny with Julz")
                .setSubtitle(spec.project)
                .setDescription("Signs the text shown on the screen")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                .setNegativeButton("Cancel", executor) { _, _ -> busy = false; signing.remove(spec.name) }
                .build()
            prompt.authenticate(BiometricPrompt.CryptoObject(signer), CancellationSignal(), executor,
                object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                        // The signer passed in, unlocked by this fingerprint for one signature
                        val sig = signer.run {
                            update(DevicePayload.build(begun.action, begun.text, begun.nonce)); sign()
                        }
                        scope.launch {
                            val reply = withContext(Dispatchers.IO) {
                                try {
                                    ApproverApi.call(origins, ApproverApi.FINISH, JSONObject().put("action", action)
                                        .put("nonce", begun.nonce).put("signature", Base64.getEncoder().encodeToString(sig)))
                                } catch (e: Exception) { 0 to "" }
                            }
                            status = if (reply.first == 200) {
                                val done = runCatching { JSONObject(reply.second).optString("done") }.getOrDefault("done")
                                AppLog.add("approve: $done with the device key")
                                setNote(spec.name, null)
                                done.replaceFirstChar { it.uppercase() } + ". " + spec.project
                            } else errorOf(reply.second, reply.first)
                            signing.remove(spec.name); busy = false
                            fastUntil = System.currentTimeMillis() + 60_000; reload()
                        }
                    }

                    override fun onAuthenticationError(code: Int, message: CharSequence) {
                        busy = false; signing.remove(spec.name)
                        if (code != BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED) status = message.toString()
                    }
                })
        }
    }

    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader("Approve") { RoundButton(Icons.reload, "Reload") { status = null; reload() } }
        Guide(Guides.APPROVE)
        status?.let { Text(it, style = J.sec.copy(color = J.text)) }
        val s = state
        when {
            !loaded -> Text("Asking the laptop", style = J.sec)
            s == null -> Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                Text("The approver is not reachable. Is the laptop on and Tailscale up?", style = J.bodyText)
                PlainButton("Try again") { reload() }
            }
            s.device == null || local == null || s.device != local -> Column(Modifier.fillMaxWidth().glass().padding(J.inset),
                verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                SectionTitle("Approve on this phone")
                Text(if (s.device != null && local != null) "The laptop knows another key than this phone's. Enroll this phone again."
                     else "Enroll this phone once, then approve here with your fingerprint.", style = J.bodyText)
                PlainButton("Enroll this phone", onClick = enroll)
                PlainButton("Open the approver page") { openTab(context, origins.approver) }
            }
            else -> {
                if (s.specs.isEmpty() && s.elsewhere == 0) Text("Nothing waiting for you.", style = J.bodyText.copy(color = J.muted))
                for (spec in s.specs) SpecCard(spec, notes[spec.name].orEmpty(), { setNote(spec.name, it) },
                    signing[spec.name], busy, approve = { sign(spec, "approve") }, deny = { sign(spec, "reject") })
                // Claude's questions, the running job, queued runs and Keep, here in the app (121);
                // the approver page stays as the fallback
                work?.let { w -> WorkCards(origins, w, busy, { busy = it }, { status = it }) { fastUntil = System.currentTimeMillis() + 60_000; reload() } }
                // Only for cards this screen could not show; everything above is handled here (9b)
                val hidden = app.julz.approve.hiddenCards(s, work)
                if (hidden > 0) PlainButton(if (hidden == 1) "1 card only on the approver page" else "$hidden cards only on the approver page") {
                    openTab(context, origins.approver)
                }
            }
        }
        Text("This phone's key: ${local ?: "none"}", style = J.monoCap)
    }
}

/** One action signed with the device key (SECURITY.md 107, 109): begin with `body`, hand the
 *  exact text the server built to `shown` so it is on screen above the prompt, one fingerprint,
 *  finish. `done` gets the server's "done" word, or null and what went wrong. */
internal fun signWithDevice(context: android.content.Context, scope: kotlinx.coroutines.CoroutineScope, origins: Origins,
                            action: String, body: JSONObject, title: String, shown: (Begun?) -> Unit,
                            done: (String?, String?) -> Unit) {
    scope.launch {
        var problem: String? = null
        val begun = withContext(Dispatchers.IO) {
            try {
                val (code, raw) = ApproverApi.call(origins, ApproverApi.BEGIN, body)
                if (code == 200) Begun.parse(raw, action) else { problem = errorOf(raw, code); null }
            } catch (e: Exception) { problem = "The approver is not reachable"; null }
        }
        if (begun == null) { done(null, problem ?: "The approver answered oddly"); return@launch }
        val signer = try { DeviceKey.signer() } catch (e: KeyPermanentlyInvalidatedException) {
            done(null, "A fingerprint was added to this phone, so its key is gone. Enroll again."); return@launch
        } catch (e: Exception) {
            done(null, "This phone has no approval key. Enroll it in Settings."); return@launch
        }
        shown(begun)  // the exact text is on screen now, above the prompt (109)
        val executor = context.mainExecutor
        val prompt = BiometricPrompt.Builder(context)
            .setTitle(title)
            .setDescription("Signs the text shown on the screen")
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
            .setNegativeButton("Cancel", executor) { _, _ -> shown(null); done(null, null) }
            .build()
        prompt.authenticate(BiometricPrompt.CryptoObject(signer), CancellationSignal(), executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                    val sig = signer.run { update(DevicePayload.build(begun.action, begun.text, begun.nonce)); sign() }
                    scope.launch {
                        val reply = withContext(Dispatchers.IO) {
                            try {
                                ApproverApi.call(origins, ApproverApi.FINISH, JSONObject().put("action", action)
                                    .put("nonce", begun.nonce).put("signature", Base64.getEncoder().encodeToString(sig)))
                            } catch (e: Exception) { 0 to "" }
                        }
                        shown(null)
                        if (reply.first == 200) {
                            val word = runCatching { JSONObject(reply.second).optString("done") }.getOrDefault("done")
                            AppLog.add("approve: $word with the device key")
                            done(word, null)
                        } else done(null, errorOf(reply.second, reply.first))
                    }
                }

                override fun onAuthenticationError(code: Int, message: CharSequence) {
                    shown(null)
                    done(null, if (code == BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED) null else message.toString())
                }
            })
    }
}

private fun errorOf(raw: String, code: Int): String =
    runCatching { JSONObject(raw).optString("error") }.getOrNull()?.takeIf { it.isNotBlank() }?.take(200)
        ?.let { "The approver said: $it" } ?: "The approver answered $code"

@Composable
private fun SpecCard(spec: SpecItem, note: String, setNote: (String) -> Unit, begun: Begun?, busy: Boolean,
                     approve: () -> Unit, deny: () -> Unit) {
    val colors = fieldColors()
    Column(Modifier.fillMaxWidth().assemble(key = "spec-${spec.sha256}").glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
        Text("Runs in ${spec.project}", style = J.ts)
        Code("spec", spec.shortId)
        // Plain text only (34): while signing, the exact text the server built, note included (109)
        Text(begun?.text ?: spec.text, style = J.sec.copy(fontFamily = J.mono, color = J.text),
            modifier = Modifier.fillMaxWidth().glass(J.rM).padding(J.sp4))
        if (begun != null) Text("You are signing exactly this.", style = J.cap.copy(color = J.accText, fontWeight = FontWeight(700)))
        OutlinedTextField(note, { if (it.length <= Note.MAX) setNote(it) }, Modifier.fillMaxWidth(),
            label = { Text("Note for Claude · optional") }, singleLine = true, colors = colors, shape = fieldShape(oneLine = true), textStyle = J.bodyText,
            enabled = !busy, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Text, autoCorrectEnabled = true),
            supportingText = { Text(Note.problem(note) ?: "Plain text, sent with your approval. No links.") },
            isError = Note.problem(note) != null)
        GlowButton(if (busy) "Waiting for your fingerprint" else "Approve with fingerprint") { if (!busy) approve() }
        PlainButton("Deny", color = J.warn, border = J.warn.copy(alpha = 0.4f)) { if (!busy) deny() }
    }
}

/** Settings: enroll this phone's key with the code from `julz-approve-web.py --enroll-device`,
 *  then compare the fingerprint with `--device` on the laptop (SECURITY.md 108). */
@Composable
fun EnrollScreen(origins: Origins, back: () -> Unit) {
    val scope = rememberCoroutineScope()
    var code by remember { mutableStateOf("") }
    var message by remember { mutableStateOf<String?>(null) }
    var local by remember { mutableStateOf(localFingerprint()) }
    var busy by remember { mutableStateOf(false) }
    val colors = fieldColors()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader("Approve on this phone", back = back)
        Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp3)) {
            Text("On the laptop run\n./julz-approve-web.py --enroll-device\nand type the code here. A new key replaces any old one.",
                style = J.bodyText)
            OutlinedTextField(code, { code = it.take(40) }, Modifier.fillMaxWidth(), label = { Text("Code from the terminal") },
                singleLine = true, colors = colors, shape = fieldShape(oneLine = true), textStyle = J.bodyText.copy(fontFamily = J.mono),
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Ascii, autoCorrectEnabled = false))
            GlowButton(if (busy) "Enrolling" else "Enroll this phone") {
                if (busy || code.isBlank()) return@GlowButton
                busy = true; message = null
                scope.launch {
                    message = withContext(Dispatchers.IO) {
                        try {
                            val der = DeviceKey.create()
                            val (status, raw) = ApproverApi.call(origins, ApproverApi.ENROLL, JSONObject()
                                .put("code", code.trim()).put("public_key", Base64.getEncoder().encodeToString(der)))
                            val mine = DevicePayload.fingerprint(der)
                            if (status != 200) { DeviceKey.delete(); errorOf(raw, status) }
                            else if (runCatching { JSONObject(raw).optString("fingerprint") }.getOrNull() != mine)
                                "The laptop stored another fingerprint than this phone made. Do not use it: --revoke-device."
                            else {
                                AppLog.add("approve: this phone enrolled")
                                "Enrolled. This phone's key is $mine. Check that\n./julz-approve-web.py --device\nprints the same."
                            }
                        } catch (e: IllegalStateException) {
                            "Add a fingerprint to the phone first: the key needs one."
                        } catch (e: Exception) { "Could not enroll: ${e.javaClass.simpleName}" }
                    }
                    local = localFingerprint(); code = ""; busy = false
                }
            }
            message?.let { Text(it, style = J.bodyText.copy(fontFamily = J.mono)) }
        }
        Text("This phone's key: ${local ?: "none"}", style = J.monoCap)
        if (local != null) PlainButton("Remove the key from this phone", color = J.warn, border = J.warn.copy(alpha = 0.4f)) {
            DeviceKey.delete(); local = null; message = "Removed. Also run --revoke-device on the laptop."
        }
    }
}
