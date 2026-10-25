package app.julz.ui

import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.CancellationSignal
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.Dp
import kotlinx.coroutines.flow.filterNotNull
import kotlinx.coroutines.flow.first

/** The text I sign, over every screen while I sign it (219, SECURITY.md 109). The system draws
 *  its fingerprint sheet over the bottom half (HyperOS: from y 1262 of 2712, measured 25 Oct),
 *  where every signing screen used to show this text, so I signed blind. One layer at the top
 *  instead, above the sheet. The sheet takes every touch while it is up, so a text too long to
 *  show whole there opens first in full, to read, with the Sign button by the thumb. */
internal object SignPanel {
    /** One signing: the server's exact text, the system prompt to start, what Cancel does. */
    class Ask(val title: String, val text: String, val prompt: () -> Unit, val cancel: () -> Unit)

    var ask by mutableStateOf<Ask?>(null)

    /** The panel's most height, a share of the window: the sheet left 46 % free on my phone */
    const val ABOVE = 0.38f

    enum class Step { PROMPT, READ }

    /** After the panel is laid out at its top size: nothing to scroll means it is all in view.
     *  ScrollState says Int.MAX_VALUE until it is measured, so no decision before that. */
    fun step(maxScroll: Int): Step? = when (maxScroll) {
        Int.MAX_VALUE -> null
        0 -> Step.PROMPT
        else -> Step.READ
    }

    private val hash = Regex("""\b[0-9a-f]{64}\b""")
    private val ref = Regex("""^[a-z]+: [0-9a-f]{12}…$""")

    /** The text as drawn (219b): a whole word of exactly 64 lowercase hex, a hash, shows as its
     *  first 12 and an ellipsis; every other character whole. The signature covers the text the
     *  server built, never this. */
    fun shown(text: String): String = hash.replace(text) { it.value.take(12) + "…" }

    /** A line that only names what is signed, like "inbox: 741af55b4ec0…": drawn quiet. */
    fun isRef(line: String) = ref.matches(line)

    fun close(a: Ask) { if (ask === a) ask = null }
    fun cancel(a: Ask) { if (ask === a) a.cancel() }
}

/** The one fingerprint prompt for a signature (219): the text goes up in SignPanel first, the
 *  system's prompt comes once it is in view. Exactly one of `succeeded` or `failed` is called,
 *  once; `failed(null)` is a cancel. `signer` is unlocked for one signature on success. */
internal fun askFingerprint(context: android.content.Context, signer: java.security.Signature, title: String,
                            subtitle: String?, text: String, succeeded: () -> Unit, failed: (String?) -> Unit) {
    var over = false
    lateinit var ask: SignPanel.Ask
    fun end(ok: Boolean, why: String?) {
        if (over) return
        over = true
        SignPanel.close(ask)
        if (ok) succeeded() else failed(why)
    }
    val executor = context.mainExecutor
    fun prompt() {
        if (over) return
        val b = BiometricPrompt.Builder(context).setTitle(title)
        if (subtitle != null) b.setSubtitle(subtitle)
        b.setDescription("Signs the text shown above")
            .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
            .setNegativeButton("Cancel", executor) { _, _ -> end(false, null) }
        b.build().authenticate(BiometricPrompt.CryptoObject(signer), CancellationSignal(), executor,
            object : BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) = end(true, null)

                override fun onAuthenticationError(code: Int, message: CharSequence) =
                    end(false, if (code == BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED) null else message.toString())
            })
    }
    ask = SignPanel.Ask(title, text, ::prompt) { end(false, null) }
    SignPanel.ask = ask
}

/** Drawn once in App, over every screen, the tab bar and any sheet. */
@Composable
internal fun SignLayer() {
    val ask = SignPanel.ask ?: return
    var reading by remember(ask) { mutableStateOf(false) }
    val top = remember(ask) { ScrollState(0) }
    LaunchedEffect(ask) {
        // Laid out once at its top size: the prompt now if it all shows, else read it first
        when (snapshotFlow { SignPanel.step(top.maxValue) }.filterNotNull().first()) {
            SignPanel.Step.PROMPT -> ask.prompt()
            SignPanel.Step.READ -> reading = true
        }
    }
    // Leaving (a rotation rebuilds the activity) is a cancel: never a prompt for a dead screen
    DisposableEffect(ask) { onDispose { SignPanel.cancel(ask) } }
    BackHandler(enabled = reading) { SignPanel.cancel(ask) }
    BoxWithConstraints(Modifier.fillMaxSize()) {
        SignScreen(ask, maxHeight * SignPanel.ABOVE, top, reading, sign = { reading = false; ask.prompt() }) {
            SignPanel.cancel(ask)
        }
    }
}

/** The confirmation, a screen of its own in the app's look (219b): the screen behind is no use
 *  while I sign, so nothing of it shows, as payment apps confirm on a page of their own. Text
 *  that fits stays in the top `most`, the fingerprint sheet comes up below it; a longer one
 *  fills the screen to read first, with Sign and Cancel by the thumb. */
@Composable
internal fun SignScreen(ask: SignPanel.Ask, most: Dp, top: ScrollState, reading: Boolean, sign: () -> Unit,
                        cancel: () -> Unit) {
    Column(Modifier.fillMaxSize().background(J.bg).background(J.page).navigationBarsPadding()
        .padding(horizontal = J.gutter), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        if (reading) {
            ScreenHeader(ask.title, "Read it whole. Your fingerprint signs this, nothing else.")
            SignedLines(ask.text, Modifier.weight(1f).fillMaxWidth().glass().clip(J.rL)
                .verticalScroll(rememberScrollState()).padding(J.inset))
            GlowButton("Sign with fingerprint", sign)
            PlainButton("Cancel", onClick = cancel)
            Spacer(Modifier.height(J.sp3))
        } else Column(Modifier.heightIn(max = most), verticalArrangement = Arrangement.spacedBy(J.gap)) {
            ScreenHeader(ask.title, "Your fingerprint signs this, nothing else.")
            // The card keeps its shape at the cap, its lines scroll inside it
            SignedLines(ask.text, Modifier.weight(1f, fill = false).fillMaxWidth().glass().clip(J.rL)
                .verticalScroll(top).padding(J.inset))
        }
    }
}

/** Plain text only (34): the exact text the laptop built for this nonce (109), line by line in
 *  mono as the spec cards show it, a hash short and quiet (219b). */
@Composable
private fun SignedLines(text: String, modifier: Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(J.sp1)) {
        for (line in SignPanel.shown(text.trimEnd()).lines())
            Text(line, style = if (SignPanel.isRef(line)) J.monoCap else J.sec.copy(fontFamily = J.mono, color = J.text))
    }
}
