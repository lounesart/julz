package app.julz.ui

import app.julz.feed.shown
import android.content.ActivityNotFoundException
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.background
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import kotlin.math.roundToInt
import androidx.compose.ui.semantics.Role
import androidx.compose.foundation.selection.toggleable
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import app.julz.feed.Kind
import app.julz.feed.Notice

@Composable
fun DetailScreen(n: Notice, back: () -> Unit, approve: () -> Unit, reply: AskJulz.Reply?, ask: () -> Unit,
                 chat: (String) -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader("Details", back = back, backLabel = "Back to feed")
        // The notice in History's card family, stronger; an approval keeps the accent, as on Now,
        // since its card holds the action. The same word and short title as History (22d integrity)
        val approval = n.kind == Kind.APPROVAL
        val hero = if (approval) Modifier.clip(J.rL).background(J.heroBrush) else Modifier.kindCard(J.tint(n.kind), strong = true)
        val ink = if (approval) J.onAcc else J.text
        val (title, id) = Words.shortTitle(n.title)
        Column(Modifier.fillMaxWidth().assemble(key = "notice-${n.id}").then(hero).padding(J.inset),
            verticalArrangement = Arrangement.spacedBy(J.sp4)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                Tag(Words.status(n.kind), if (approval) J.onAcc else J.tint(n.kind))
                Text(Words.day(n.time).lowercase() + " " + Words.time(n.time), style = J.monoCap.copy(color = if (approval) J.onAcc else J.muted))
            }
            Text(title, style = J.tl.copy(color = ink))
            if (Look.prefs.showIds) id?.let { Code(Words.status(n.kind), it) }
            if (approval) GlowButton("Review and approve", approve)
        }
        Column(Modifier.fillMaxWidth().assemble(key = "meaning-${n.id}").glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            SectionTitle("What this means")
            Text(Words.meaning(n.kind), style = J.bodyText)
        }
        Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp1)) {
            Text("The notice", style = J.sec)
            Text(n.shown, style = J.bodyText)  // plain text, never a link (91)
            // Kind and time are on the card above; the id as a code, the same as the logs (22c)
            if (Look.prefs.showIds) Code("notice", n.id)
        }
        // Julz's answer, plain text with links as text (106)
        when (reply) {
            null -> PlainButton("Ask Julz about it", onClick = ask)
            AskJulz.Reply.Pending -> Row(Modifier.fillMaxWidth().glass().padding(J.inset),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
                androidx.compose.material3.CircularProgressIndicator(Modifier.size(24.dp), color = J.acc, strokeWidth = 3.dp)
                Text("Julz is thinking", style = J.bodyText)
            }
            AskJulz.Reply.Failed -> Column(Modifier.fillMaxWidth().glass().padding(J.inset),
                verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                Text("Julz could not answer. If the chat asks you to sign in, do that once, then try again.",
                    style = J.bodyText)
                PlainButton("Try again", onClick = ask)
            }
            is AskJulz.Reply.Answer -> Column(Modifier.fillMaxWidth().glass().padding(J.inset),
                verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                SectionTitle("Julz says")
                Text(reply.text, style = J.bodyText)
                PlainButton("Continue in chat") { chat(reply.text) }
            }
        }
    }
}

@Composable
fun ToolsScreen(origins: Origins, lastContact: Long) {
    var items by remember { mutableStateOf<List<app.julz.approve.Integration>?>(null) }
    var problem by remember { mutableStateOf<String?>(null) }
    var open by remember { mutableStateOf<String?>(null) }
    var reloads by remember { mutableStateOf(0) }
    androidx.compose.runtime.LaunchedEffect(reloads) {
        val reply = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            try { app.julz.approve.ApproverApi.call(origins, app.julz.approve.ApproverApi.INTEGRATIONS) } catch (e: Exception) { 0 to "" }
        }
        val parsed = if (reply.first == 200) app.julz.approve.Integrations.parse(reply.second) else null
        if (parsed != null) { items = parsed; problem = null }
        else problem = if (reply.first == 0) "The approver is not reachable. Is the laptop on and Tailscale up?" else "The laptop answered oddly"
    }
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.rowGap)) {
        ScreenHeader("Tools", "What Julz runs on its own", mono = false) { RoundButton(Icons.reload, "Reload") { reloads++ } }
        Guide(Guides.TOOLS)
        val list = items
        when {
            problem != null -> Text(problem!!, style = J.sec)
            list == null -> Text("Asking the laptop", style = J.sec)
            // As the Integrations mockup, in the Messages row style: a neutral circle, the name,
            // what it does, the status as a word on its colour; a tap shows the facts (122)
            else -> for (it in list) {
                val facts = if (it.id == "push" && lastContact > 0) listOf("Last contact: " + Words.time(lastContact)) + it.facts else it.facts
                Column(Modifier.fillMaxWidth().glass(J.rM).androidx_clickable(if (open == it.id) "Hide facts" else "Show facts") {
                    open = if (open == it.id) null else it.id
                }.padding(J.sp3), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
                    // At big text the status goes under the name: beside it, Delegation broke in two (22d);
                    // the layout system's own threshold (it had its own, 160 against 150 percent)
                    val big = J.big
                    val status = @Composable { Tag(it.status, statusColor(it.status)) }
                    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
                        // At big text the icon steps aside: the name and its words need the width (22f)
                        if (!big) IconBadge(Icons.integration(it.id), statusColor(it.status))
                        Column(Modifier.weight(1f)) {
                            Text(it.name, style = J.item)
                            Text(it.what, style = J.sec)
                            if (big) Spacer(Modifier.height(J.sp2))
                            if (big) status()
                        }
                        if (!big) status()
                    }
                    // The facts at the card's full width under a hairline, an even rhythm (22d integrity)
                    if (open == it.id) androidx.compose.foundation.layout.Box(Modifier.fillMaxWidth().height(1.dp).background(J.line))
                    if (open == it.id) Column(Modifier.padding(horizontal = J.sp1), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
                        // fixed words and numbers (122); "Label: value" as a spec line (22e)
                        for (f in facts) app.julz.approve.Integrations.specLine(f)?.let { (l, v) -> SpecLine(l, v) }
                            ?: Text("\u00b7 $f", style = J.sec.copy(color = J.text))
                    }
                }
            }
        }
    }
}

/** A status's colour, always next to its word (never colour alone). */
private fun statusColor(status: String) = when (status) {
    "On" -> J.good; "Gated" -> J.info; "Check" -> J.caution; else -> J.muted
}

private fun tryStart(context: Context, vararg intents: Intent) {
    for (i in intents) try {
        context.startActivity(i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); return
    } catch (e: ActivityNotFoundException) { } catch (e: SecurityException) { }
}

@Composable
fun SettingsScreen(server: String, lastContact: Long, stored: Int, wipe: () -> Unit, licenses: () -> Unit,
                accessibility: () -> Unit, look: () -> Unit, logs: () -> Unit, enroll: () -> Unit) {
    val context = LocalContext.current
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader("Settings")
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            ListRow("Look and feel", "Themes and accent", onClick = look) {
                Text("Open", style = J.sec.copy(color = J.text))
            }
            ListRow("Accessibility", "Text size, bold, contrast, transparency, tab names", onClick = accessibility) {
                Text("Open", style = J.sec.copy(color = J.text))
            }
        }
        Spacer(Modifier.height(J.sp4))
        SectionTitle("Chat")
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            // New (26): off keeps Open WebUI's page; on, the page stays one tap away under My chats
            Toggle("Chat in the app", "New: Julz's own chat screen instead of Open WebUI's page",
                ChatPrefs.native) { ChatPrefs.set(context, it) }
            Toggle("Roomy message box", "Two rows with send under the text; off is a single line",
                ChatPrefs.roomy) { ChatPrefs.setRoomy(context, it) }
        }
        Spacer(Modifier.height(J.sp4))
        SectionTitle("Connection")
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            ListRow(if (lastContact == 0L) "Not connected yet" else "Last contact " + Words.time(lastContact))
            ListRow("Server, over Tailscale only", server)
            ListRow("Phone token", "Locked in the Android Keystore")
            ListRow("Approve on this phone", "A key behind your fingerprint", onClick = enroll) {
                Text("Open", style = J.sec.copy(color = J.text))
            }
        }
        Spacer(Modifier.height(J.sp4))
        SectionTitle("Stay awake on HyperOS")
        // As the Settings mockup: each check says if it is really set; what Android does not let an
        // app read says so, and keeps its shortcut (base 6)
        val nm = context.getSystemService(android.app.NotificationManager::class.java)
        val power = context.getSystemService(android.os.PowerManager::class.java)
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            ListRow("Notifications allowed", if (nm.areNotificationsEnabled()) "On" else "Off: Julz cannot tell you anything", onClick = {
                tryStart(context, Intent(AndroidSettings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(AndroidSettings.EXTRA_APP_PACKAGE, "app.julz"))
            }) { Badge(nm.areNotificationsEnabled()) }
            ListRow("Autostart", "Must be on, or HyperOS stops Julz", onClick = {
                tryStart(context, Intent().setComponent(ComponentName("com.miui.securitycenter",
                    "com.miui.permcenter.autostart.AutoStartManagementActivity")),
                    Intent(AndroidSettings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:app.julz")))
            }) { Badge(null) }
            val unrestricted = power.isIgnoringBatteryOptimizations("app.julz")
            ListRow("Battery: No restrictions", if (unrestricted) "Set" else "HyperOS may stop Julz in the background", onClick = {
                tryStart(context, Intent(AndroidSettings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:app.julz")))
            }) { Badge(unrestricted) }
            ListRow("Tailscale always on", "Android settings, VPN, Tailscale", onClick = {
                tryStart(context, Intent(AndroidSettings.ACTION_VPN_SETTINGS))
            }) { Badge(null) }
        }
        Spacer(Modifier.height(J.sp4))
        SectionTitle("Channels \u00b7 the lock screen shows names only")
        // One row per kind with its level now; the level is Android's to change, so a tap opens it
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            for (kind in Kind.entries) {
                val id = app.julz.Notifier.channelId(kind)
                val level = nm.getNotificationChannel(id)?.importance ?: 0
                ListRow(Words.label(kind), app.julz.approve.Integrations.level(level), onClick = {
                    tryStart(context, Intent(AndroidSettings.ACTION_CHANNEL_NOTIFICATION_SETTINGS)
                        .putExtra(AndroidSettings.EXTRA_APP_PACKAGE, "app.julz").putExtra(AndroidSettings.EXTRA_CHANNEL_ID, id))
                }) { Text("Open", style = J.sec.copy(color = J.text)) }
            }
        }
        Spacer(Modifier.height(J.sp4))
        SectionTitle("On this phone")
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            ListRow("Keep notices", "30 days")
            ListRow("Stored", "$stored notices")
            ListRow("Font licenses", "SIL Open Font License", onClick = licenses)
            ListRow("Logs", "What the app did, kept until it closes", onClick = logs) {
                Text("Open", style = J.sec.copy(color = J.text))
            }
        }
        Spacer(Modifier.height(J.sp2))
        PlainButton("Wipe feed and sign out", color = J.warn, border = J.warn.copy(alpha = 0.4f), onClick = wipe)
        val version = runCatching { context.packageManager.getPackageInfo(context.packageName, 0).versionName }.getOrNull()
        Text("Julz ${version ?: "?"} · built and signed on the laptop", style = J.monoCap,
            modifier = Modifier.fillMaxWidth().padding(top = J.sp3))
    }
}

@Composable
fun FirstRun(message: String?, save: (String, String, String) -> String?) {
    var server by remember { mutableStateOf("https://") }
    var topic by remember { mutableStateOf("julz-") }
    var token by remember { mutableStateOf("") }
    var error by remember { mutableStateOf(message) }
    val colors = fieldColors()
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(J.gutter),
        verticalArrangement = Arrangement.spacedBy(J.sp4)) {
        Spacer(Modifier.height(J.sp6))
        Text("Julz", style = J.tl)
        Text("Connect to the push server on the laptop.", style = J.bodyText.copy(color = J.muted))
        OutlinedTextField(server, { server = it }, Modifier.fillMaxWidth().keepsKeyboard(), label = { Text("Server") },
            singleLine = true, colors = colors, shape = fieldShape(oneLine = true), textStyle = J.bodyText,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, autoCorrectEnabled = false))
        OutlinedTextField(topic, { topic = it }, Modifier.fillMaxWidth().keepsKeyboard(), label = { Text("Topic") },
            singleLine = true, colors = colors, shape = fieldShape(oneLine = true), textStyle = J.bodyText,
            keyboardOptions = KeyboardOptions(autoCorrectEnabled = false))
        OutlinedTextField(token, { token = it }, Modifier.fillMaxWidth().keepsKeyboard(), label = { Text("Phone token") },
            singleLine = true, colors = colors, shape = fieldShape(oneLine = true), textStyle = J.bodyText,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false))
        error?.let { Text(it, style = J.sec.copy(color = J.warn)) }
        GlowButton("Save and connect") { error = save(server, topic, token) }
    }
}

/** What the app did (threat 105): its own lines only, newest first, in memory only. */
@Composable
fun LogsScreen(back: () -> Unit) {
    var lines by remember { mutableStateOf(app.julz.AppLog.lines()) }
    androidx.compose.runtime.LaunchedEffect(Unit) {
        while (true) { kotlinx.coroutines.delay(2000); lines = app.julz.AppLog.lines() }
    }
    val clock = java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.ROOT)
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.rowGap)) {
        ScreenHeader("Logs", back = back, backLabel = "Back to Settings") {
            // Sized to its word: a full width button in this row left the title one letter wide
            PlainButton("Clear", modifier = Modifier.widthIn(min = 112.dp)) { app.julz.AppLog.clear(); lines = emptyList() }
        }
        if (lines.isEmpty()) Text("Nothing yet.", style = J.bodyText.copy(color = J.muted))
        for (l in lines.asReversed()) Row {
            Text(clock.format(java.util.Date(l.time * 1000)), style = J.monoCap.copy(color = J.muted),
                modifier = Modifier.padding(end = J.sp3))
            Text(l.text, style = J.sec.copy(color = J.text))
        }
    }
}

@Composable
fun LicenseScreen(text: String, back: () -> Unit) {
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(J.gutter)) {
        ScreenHeader("Font licenses", back = back, backLabel = "Back to Settings")
        Text(text, style = J.cap.copy(color = J.muted))
    }
}


@Composable
fun AccessibilityScreen(back: () -> Unit) {
    var draft by remember(A11y.prefs.scale) { mutableStateOf(A11y.prefs.scale) }
    val context = LocalContext.current
    val p = A11y.prefs
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader("Accessibility", back = back, backLabel = "Back to Settings")
        Column(Modifier.fillMaxWidth().glass().padding(J.inset), verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Text size", style = J.ts, modifier = Modifier.weight(1f))
                Text("${(draft * 100).roundToInt()}%", style = J.monoCap)
            }
            Text("On top of Android's font size. This whole screen follows it.", style = J.sec)
            // Applied when I let go (22f): applying while dragging re-laid the screen out under the
            // finger, and Android dropped the drag, so only taps worked
            // It snaps in 5 percent steps without drawing a dot for each (asked 18 Oct)
            JulzSlider(draft, { draft = (it * 20).roundToInt() / 20f }, 0.85f..2.0f, 22) {
                A11y.set(context, p.copy(scale = A11yPrefs.clampScale(draft)))
            }
            if (p.scale != 1.0f) PlainButton("Reset to 100%") { draft = 1.0f; A11y.set(context, p.copy(scale = 1.0f)) }
        }
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            Toggle("Bold text", "Heavier letters everywhere", p.bold) { A11y.set(context, p.copy(bold = it)) }
            Toggle("High contrast", "Brighter grey text and lines", p.contrast) { A11y.set(context, p.copy(contrast = it)) }
            Toggle("Reduce transparency", "Solid cards instead of glass", p.solid) { A11y.set(context, p.copy(solid = it)) }
            Toggle("Tab names", "Words under the bottom bar icons; on by itself from 160 %", p.labels) {
                A11y.set(context, p.copy(labels = it))
            }
            Toggle("Show guides", "A short how-to under the title of Approve, Todos, Inbox and Tools", p.guides) {
                A11y.set(context, p.copy(guides = it))
            }
        }
        Text("Julz follows Android first: font size, Remove animations, TalkBack. These apply to Julz only.",
            style = J.sec, modifier = Modifier.padding(horizontal = J.sp1))
    }
}

/** One TalkBack stop: the row is the switch, with its title, words and state (22d); the switch
 *  only shows the state, so it is not a second, nameless stop. */
@Composable
private fun Toggle(title: String, sub: String, on: Boolean, set: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().heightIn(min = J.row)
        .toggleable(on, role = Role.Switch, onValueChange = set).padding(vertical = J.sp3),
        verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
        Column(Modifier.weight(1f)) {
            Text(title, style = J.item)
            Text(sub, style = J.sec)
        }
        JulzSwitch(on)
    }
}


@Composable
fun LookScreen(back: () -> Unit) {
    val context = LocalContext.current
    val p = Look.prefs
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = J.gutter)
        .padding(bottom = J.end), verticalArrangement = Arrangement.spacedBy(J.gap)) {
        ScreenHeader("Look and feel", back = back, backLabel = "Back to Settings")
        Column(Modifier.fillMaxWidth().clip(J.rL).background(J.heroBrush).padding(J.inset),
            verticalArrangement = Arrangement.spacedBy(J.sp3)) {
            Text("preview", style = J.monoCap.copy(color = J.onAcc))
            Text("Julz: 1 spec waiting", style = J.tm.copy(color = J.onAcc))
            GlowButton("Review and approve") {}
        }
        SectionTitle("Themes")
        for (preset in Palette.presets) {
            val on = p.theme == preset.id
            Row(Modifier.fillMaxWidth().glass(J.rM, if (on) J.acc else J.line)
                .androidx_clickable { Look.set(context, p.copy(theme = preset.id, accent = null)) }.heightIn(min = J.row).padding(J.sp4),
                verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
                androidx.compose.foundation.layout.Box(Modifier.size(44.dp).clip(J.rS)
                    .background(androidx.compose.ui.graphics.Brush.linearGradient(listOf(Color(preset.accent), Color(preset.deep)))))
                Column(Modifier.weight(1f)) {
                    Text(preset.name, style = J.item)
                    Text(preset.note, style = J.sec)
                }
            }
        }
        SectionTitle("Accent")
        androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(J.sp2),
            verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            for ((name, color) in Palette.accents) {
                val on = p.accentColor == color
                androidx.compose.foundation.layout.Box(Modifier.size(J.tap).clip(androidx.compose.foundation.shape.CircleShape)
                    .background(Color(color))
                    .border(3.dp, if (on) J.text else Color.Transparent, androidx.compose.foundation.shape.CircleShape)
                    .androidx_clickable(name) { Look.set(context, p.copy(accent = color)) }
                    .semantics {
                        contentDescription = "$name accent" + if (on) ", selected" else ""
                    })
            }
        }
        SectionTitle("Options")
        Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
            Toggle("Show ids", "Short ids in Messages, History and Details. Approve always shows the spec id: you match " +
                "it with what Julz said before you sign", p.showIds) { Look.set(context, p.copy(showIds = it)) }
            Toggle("Industrial", "Cut corners and spaced capitals, as on a spec sheet; with any theme",
                p.industrial) { Look.set(context, p.copy(industrial = it)) }
            Toggle("Outline the selected item", "An accent line around the chosen tab, filter or pick, instead of white",
                p.outline) { Look.set(context, p.copy(outline = it)) }
            Toggle("History as bright cards", "Every History card in its kind's colour, as before; off, only warnings and approvals",
                p.brightHistory) { Look.set(context, p.copy(brightHistory = it)) }
            Toggle("Coloured folders", "Each top folder in its own colour in Move to and Notes: study, daily, Inbox, Claude",
                p.colorFolders) { Look.set(context, p.copy(colorFolders = it)) }
            Toggle("Icon follows the accent", "The home screen icon in your accent, changed when you leave Julz. " +
                "Some launchers drop it from the home screen then; add it again from the app list", p.icon) { Look.set(context, p.copy(icon = it)) }
        }
        Text("Themes live on this phone. A theme is a preset and an accent from this list, never code " +
            "or web addresses, so nothing from outside can change how Julz looks.", style = J.sec,
            modifier = Modifier.padding(horizontal = J.sp1))
    }
}

private fun Modifier.androidx_clickable(label: String? = null, onClick: () -> Unit) =
    this.clickable(role = androidx.compose.ui.semantics.Role.Button, onClickLabel = label, onClick = onClick)

/** Set (lime) or Fix (yellow) with the word, or a quiet Check where Android does not tell an app. */
@Composable
private fun Badge(set: Boolean?) {
    if (set == null) { Text("Check", style = J.sec.copy(color = J.muted)); return }
    Tag(if (set) "Set" else "Fix", if (set) J.good else J.caution)
}
