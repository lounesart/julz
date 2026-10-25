package app.julz.ui

import kotlinx.coroutines.launch
import android.content.Context
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.draw.clip
import androidx.compose.foundation.layout.height
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.navigationBars
import androidx.compose.foundation.layout.only
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.width
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.ui.unit.dp
import app.julz.JulzService
import app.julz.feed.Kind
import app.julz.feed.Notice
import app.julz.settings.ConfigStore

internal enum class Screen { FEED, TOOLS, SETTINGS, LICENSES, A11Y, LOOK, TODOS, CHAT, LOGS, APPROVE, ENROLL, INBOX, NOTES, FEEDBACK }

/** The whole app. [version] changes whenever the activity resumes, so the feed is read again. */
@Composable
fun App(version: Int, opened: app.julz.Notifier.Target? = null, openedFilter: Kind? = null, onOpened: () -> Unit = {},
        onShowing: (app.julz.Notifier.Target?) -> Unit = {}, onSaved: () -> Unit) {
    val context = LocalContext.current
    val config = remember(version) { ConfigStore.load(context) }
    val refused = remember(version) { JulzService.refused(context) }
    // Text size: the app's own scale on top of Android's font size, so every sp grows together
    val base = androidx.compose.ui.platform.LocalDensity.current
    // One place for sheets, over every screen and the tab bar (JulzSheet, SheetLayer)
    val sheets = remember { SheetHost() }
    androidx.compose.runtime.CompositionLocalProvider(androidx.compose.ui.platform.LocalDensity provides
        androidx.compose.ui.unit.Density(base.density, base.fontScale * A11y.prefs.scale), LocalSheetHost provides sheets) {
    androidx.compose.runtime.SideEffect { J.scale = base.fontScale * A11y.prefs.scale }
    // Clear of the navigation bar on the side too: in landscape it stood over the app's right edge (22d)
    Box(Modifier.fillMaxSize().background(J.bg).background(J.page).statusBarsPadding()
        .windowInsetsPadding(androidx.compose.foundation.layout.WindowInsets.navigationBars
            .only(androidx.compose.foundation.layout.WindowInsetsSides.Horizontal))) {
        if (config == null || refused) {
            FirstRun(if (refused) "The server refused the token. Enter the new one." else null) { s, t, k ->
                val err = ConfigStore.save(context, s, t, k)
                if (err == null) {
                    JulzService.markRefused(context, false)
                    onSaved()
                }
                err
            }
            return@Box
        }
        val origins = Origins.from(config.server)!!
        // Where I am and how I got there; Back goes one level up (22c)
        var nav by remember { mutableStateOf(Nav(Screen.FEED)) }
        val screen = nav.here
        var tab by remember { mutableIntStateOf(0) }
        // Messages' filter lives here, so a notification tap can set it
        var messagesFilter by remember { mutableStateOf<Kind?>(null) }
        var detail by remember { mutableStateOf<Notice?>(null) }
        // One chat WebView for the life of the screen, so a conversation survives tab switches (102)
        // Created when it is first attached (a WebView created before that may never draw)
        val chatHolder = remember(config.server) { arrayOfNulls<android.webkit.WebView>(1) }
        var pendingUrl by remember { mutableStateOf<String?>(null) }
        // The native chat (26): which chat, and what I was typing, kept across tabs and rebuilds;
        // webChat shows Open WebUI's page over it, for what is not native yet
        var chatId by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf<String?>(null) }
        var chatDraft by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf("") }
        var webChat by remember { mutableStateOf(false) }
        val showWeb = !ChatPrefs.native || webChat
        // Without an address the chat shows as I left it; only a tick brings its own address
        fun openChat(url: String? = null) {
            detail = null; nav = nav.tab(Screen.CHAT)
            if (url == null || !ChatRules.inside(origins, url)) return
            chatHolder[0]?.loadUrl(url) ?: run { pendingUrl = url }
        }
        // Ask Julz about a notice, answered in the app (106): one reply per notice id
        var asks by remember { mutableStateOf(mapOf<String, AskJulz.Reply>()) }
        val scope = androidx.compose.runtime.rememberCoroutineScope()
        fun askJulz(n: Notice) {
            asks = asks + (n.id to AskJulz.Reply.Pending)
            val web = chatHolder[0] ?: ChatWeb.create(context, origins).also { chatHolder[0] = it }
            scope.launch {
                val reply = ask(web, origins, n)
                asks = asks + (n.id to reply)
            }
        }
        var read by remember(version) { mutableStateOf(ReadState.load(context)) }
        var cleared by remember { mutableStateOf(ReadState.load(context, "cleared")) }
        // Notes typed on Approve, by spec file: kept when I leave the screen and when Android
        // rebuilds the app, so an approval never goes out without the note I typed (93)
        var approveNotes by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(mapOf<String, String>()) }
        var picked by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(listOf<String>()) }
        var inboxPicked by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(listOf<String>()) }
        var notesStart by remember { mutableStateOf<String?>(null) }
        // A feedback draft survives leaving the screen and Android rebuilding the app
        var feedbackDraft by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf("") }
        var feedbackKind by androidx.compose.runtime.saveable.rememberSaveable { mutableStateOf(0) }
        val fresh by JulzService.changes.collectAsState()
        val notices = remember(version, read, fresh) { JulzService.feed(context).all() }
        fun markRead(n: Notice) {
            read = read.read(n.id); ReadState.save(context, read)
        }
        // The Approve badge counts what waits on the laptop, not unread notices: those stayed
        // after I approved (found 18 Oct, 9b). Nothing waiting marks the approval notices read
        var liveWaiting by remember { mutableStateOf<Int?>(null) }
        fun settleBadge(s: app.julz.approve.ApproverState?) {
            liveWaiting = s?.waitingForMe
            if (liveWaiting == 0) {
                val open = notices.filter { it.kind == Kind.APPROVAL && !read.isRead(it.id) }
                if (open.isNotEmpty()) { read = open.fold(read) { r, n -> r.read(n.id) }; ReadState.save(context, read) }
            }
        }
        LaunchedEffect(fresh, screen) { settleBadge(loadState(origins).first) }
        // The Inbox card counts what the laptop has now, not what an old notice said
        var liveInbox by remember { mutableStateOf<Int?>(null) }
        LaunchedEffect(fresh, screen) {
            if (screen != Screen.FEED) return@LaunchedEffect
            val reply = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
                try { app.julz.approve.ApproverApi.call(origins, app.julz.approve.ApproverApi.INBOX) } catch (e: Exception) { 0 to "" }
            }
            liveInbox = if (reply.first == 200) app.julz.feed.InboxSnapshot.parse(reply.second)?.notes?.size else null
        }
        // A notification tap names a fixed screen only (13d, threat 133)
        LaunchedEffect(opened) {
            when (opened ?: return@LaunchedEffect) {
                app.julz.Notifier.Target.APPROVE -> nav = nav.tab(Screen.APPROVE)
                app.julz.Notifier.Target.TODOS -> nav = nav.tab(Screen.TODOS)
                app.julz.Notifier.Target.INBOX -> nav = nav.tab(Screen.INBOX)
                // Messages filtered to the tapped notice's kind (asked 18 Oct)
                app.julz.Notifier.Target.MESSAGES -> { nav = nav.tab(Screen.FEED); tab = 1; messagesFilter = openedFilter }
            }
            detail = null
            onOpened()
        }
        // What this screen shows, so the service keeps those notices out of the tray
        val showing = when {
            detail != null -> null
            screen == Screen.APPROVE -> app.julz.Notifier.Target.APPROVE
            screen == Screen.TODOS -> app.julz.Notifier.Target.TODOS
            screen == Screen.INBOX -> app.julz.Notifier.Target.INBOX
            screen == Screen.FEED && tab == 1 -> app.julz.Notifier.Target.MESSAGES
            else -> null
        }
        LaunchedEffect(showing) { onShowing(showing) }
        BackHandler(enabled = detail != null || nav.canGoBack || (screen == Screen.CHAT && webChat)) {
            when {
                detail != null -> detail = null
                screen == Screen.CHAT && showWeb && chatHolder[0]?.canGoBack() == true -> chatHolder[0]!!.goBack()
                screen == Screen.CHAT && webChat -> webChat = false
                else -> nav = nav.back()
            }
        }
        // In landscape the tabs stand on the left as a rail, so the screen keeps its height (22d)
        // compact height, as Android's size classes say (22f): not merely wider than tall
        val cfg = androidx.compose.ui.platform.LocalConfiguration.current
        val wide = SizeClass.rail(cfg.screenWidthDp, cfg.screenHeightDp)
        androidx.compose.runtime.SideEffect { J.rail = wide }
        val waiting = liveWaiting ?: notices.count { it.kind == Kind.APPROVAL && !read.isRead(it.id) }
        val bar = @Composable { vertical: Boolean ->
            TabBar(nav.section, waiting, vertical,
                feed = { detail = null; nav = nav.tab(Screen.FEED) },
                chat = { openChat() },
                approve = { detail = null; nav = nav.tab(Screen.APPROVE) },
                tools = { detail = null; nav = nav.tab(Screen.TOOLS) },
                settings = { detail = null; nav = nav.tab(Screen.SETTINGS) })
        }
        // The bar floats over the content (22i): lists scroll on under it and fade out, their end
        // clears it (J.end). In the layout below the content it cut the last card with a hard
        // edge and left a block of background around the capsule (found 19 Oct). It stays put
        // while the keyboard is up and the keyboard slides over it: hiding it in one step while
        // the keyboard moved frame by frame made the chat jump about 400 px (127, measured 24 Oct)
        Shell(wide, bar) {
                val d = detail
                when {
                    d != null -> DetailScreen(d, back = { detail = null },
                        approve = { detail = null; nav = nav.tab(Screen.APPROVE) }, reply = asks[d.id], ask = { askJulz(d) },
                        chat = { answer ->
                            // Native: a new chat with the same words in the box, never sent (101)
                            if (ChatPrefs.native) { webChat = false; chatId = null; chatDraft = AskJulz.prefill(d, answer); openChat() }
                            else openChat(AskJulz.chatUrl(origins, d, answer))
                        })
                    screen == Screen.CHAT && !showWeb -> NativeChat(origins, app.julz.chat.ChatApi.origin(config.server)!!, config.token,
                        chatId, { chatId = it }, chatDraft, { chatDraft = it }, openWeb = { webChat = true })
                    screen == Screen.CHAT -> androidx.compose.ui.viewinterop.AndroidView({ ctx ->
                        val web = chatHolder[0] ?: ChatWeb.create(ctx, origins, pendingUrl ?: origins.chat).also {
                            chatHolder[0] = it; pendingUrl = null
                        }
                        (web.parent as? android.view.ViewGroup)?.removeView(web)
                        web
                    }, Modifier.fillMaxSize())
                    screen == Screen.TOOLS -> ToolsScreen(origins, JulzService.lastContact(context))
                    screen == Screen.TODOS -> TodosScreen(notices, origins, picked, { picked = it }) { nav = nav.back() }
                    screen == Screen.INBOX -> InboxScreen(origins, inboxPicked, { inboxPicked = it },
                        browse = { notesStart = it; nav = nav.open(Screen.NOTES) }) { nav = nav.back() }
                    screen == Screen.NOTES -> NotesScreen(origins, notesStart) { nav = nav.back() }
                    screen == Screen.FEEDBACK -> FeedbackScreen(origins, feedbackDraft, { feedbackDraft = it },
                        feedbackKind, { feedbackKind = it }) { nav = nav.back() }
                    screen == Screen.LICENSES -> LicenseScreen(licenseText(context)) { nav = nav.back() }
                    screen == Screen.A11Y -> AccessibilityScreen { nav = nav.back() }
                    screen == Screen.LOOK -> LookScreen { nav = nav.back() }
                    screen == Screen.LOGS -> LogsScreen { nav = nav.back() }
                    screen == Screen.APPROVE -> ApproveScreen(origins, approveNotes,
                        { name, note -> approveNotes = if (note == null) approveNotes - name else approveNotes + (name to note) },
                        seen = { s -> settleBadge(s) }
                    ) { nav = nav.open(Screen.ENROLL) }
                    screen == Screen.ENROLL -> EnrollScreen(origins) { nav = nav.back() }
                    screen == Screen.SETTINGS -> SettingsScreen(config.server, JulzService.lastContact(context), notices.size,
                        wipe = {
                            JulzService.stop(context)
                            ChatWeb.wipe()
                            runCatching { app.julz.approve.DeviceKey.delete() }  // and the approval key (110)
                            JulzService.feed(context).wipe()
                            ConfigStore.wipe(context)
                            onSaved()
                        }, licenses = { nav = nav.open(Screen.LICENSES) }, accessibility = { nav = nav.open(Screen.A11Y) },
                        look = { nav = nav.open(Screen.LOOK) }, logs = { nav = nav.open(Screen.LOGS) },
                        enroll = { nav = nav.open(Screen.ENROLL) })
                    else -> FeedScreen(notices, read, JulzService.lastContact(context), tab, { tab = it }, liveInbox,
                        messagesFilter, { messagesFilter = it },
                        open = { markRead(it); detail = it },
                        approve = { markRead(it); nav = nav.tab(Screen.APPROVE) },
                        markRead = { list -> read = read.with(list.map { it.id }); ReadState.save(context, read) }, todos = { nav = nav.open(Screen.TODOS) }, inbox = { notices.firstOrNull { it.kind == Kind.INBOX }?.let { markRead(it) }; nav = nav.open(Screen.INBOX) },
                        feedback = { nav = nav.open(Screen.FEEDBACK) }, cleared = cleared,
                        setCleared = { cleared = it; ReadState.save(context, it, "cleared") })
                }
        }
        SheetLayer(sheets)
    }
}
}

/** The screen with the tab bar over it (22i), or the rail beside it in landscape (22d). Its own
 *  function so a screenshot test draws the real bar over a screen (184, 126). */
@Composable
internal fun Shell(wide: Boolean, bar: @Composable (Boolean) -> Unit, content: @Composable () -> Unit) {
    val density = androidx.compose.ui.platform.LocalDensity.current
    Row(Modifier.fillMaxSize()) {
      if (wide) bar(true)
      Box(Modifier.weight(1f)) {
        Box(Modifier.fillMaxSize()) { content() }
        if (!wide) Column(Modifier.align(Alignment.BottomCenter).fillMaxWidth()) {
            // Content slides out through a short fade, then the band the bar sits on is solid
            // page colour: the glass showed the list through its icons (found 19 Oct). The
            // page is this colour at the bottom, so the band has no seam
            Box(Modifier.fillMaxWidth().height(J.sp6).background(androidx.compose.ui.graphics.Brush.verticalGradient(
                listOf(Color.Transparent, J.bg))))
            // Under the keyboard the bar is out of sight, so TalkBack must not reach it either;
            // only its semantics go, its place stays (a layout step made the chat jump, 127)
            @OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
            val covered = androidx.compose.foundation.layout.WindowInsets.isImeVisible
            Box(Modifier.fillMaxWidth().background(J.bg)
                .then(if (covered) Modifier.clearAndSetSemantics { } else Modifier)
                .onSizeChanged { J.barSpace = with(density) { it.height.toDp() } }) { bar(false) }
        }
      }
    }
}

private fun licenseText(context: Context): String =
    listOf("tektur", "plusjakartasans", "jetbrainsmono").joinToString("\n\n") { name ->
        context.assets.open("licenses/$name-OFL.txt").bufferedReader().use { it.readText() }
    }

@Composable
internal fun TabBar(section: Screen, waiting: Int, vertical: Boolean, feed: () -> Unit, chat: () -> Unit,
                   approve: () -> Unit, tools: () -> Unit, settings: () -> Unit) {
    // 22i, asked 19 Oct ("too rigid, out of the theme"): a floating glass capsule like the app's
    // own switches, the active tab under the same light as Now, Messages, History (filled, or an
    // accent outline when Look and feel says outline), sliding to the tab I pick; the theme's
    // pill shape, so cut on Industrial. It was a flat strip with a 5 dp dot under the icon
    var labelSize by remember { mutableStateOf(J.cap.fontSize) }
    val index = when (section) {
        Screen.CHAT -> 1; Screen.APPROVE -> 2; Screen.TOOLS -> 3; Screen.SETTINGS -> 4
        else -> 0  // the tab of the place the path started from; Todos, Inbox, Notes and Feedback are the Feed's
    }
    val still = stillMotion()
    val slide by androidx.compose.animation.core.animateFloatAsState(index.toFloat(),
        if (still) androidx.compose.animation.core.snap() else androidx.compose.animation.core.tween(320, easing = J.ease), label = "tab")
    val tabs = @Composable { m: Modifier ->
        Tab(Icons.feed, "Feed", index == 0, 0, m, labelSize, feed)
        Tab(Icons.chat, "Chat", index == 1, 0, m, labelSize, chat)
        Tab(Icons.approve, "Approve", index == 2, waiting, m, labelSize, approve)
        Tab(Icons.links, "Tools", index == 3, 0, m, labelSize, tools)
        Tab(Icons.setup, "Settings", index == 4, 0, m, labelSize, settings)
    }
    val shape = J.pill
    // The light, drawn behind the tabs at the sliding position: one tab's cell in the pill shape
    val light = Modifier.drawBehind {
        val gap = J.sp1.toPx()
        val n = TAB_NAMES.size
        val cell = if (vertical) androidx.compose.ui.geometry.Size(size.width, (size.height - gap * (n - 1)) / n)
            else androidx.compose.ui.geometry.Size((size.width - gap * (n - 1)) / n, size.height)
        val at = if (vertical) androidx.compose.ui.geometry.Offset(0f, (cell.height + gap) * slide)
            else androidx.compose.ui.geometry.Offset((cell.width + gap) * slide, 0f)
        translate(at.x, at.y) {
            val o = shape.createOutline(cell, layoutDirection, this)
            if (J.outline) drawOutline(o, J.acc, style = androidx.compose.ui.graphics.drawscope.Stroke(1.dp.toPx()))
            else drawOutline(o, J.text)
        }
    }
    if (vertical) Box(Modifier.fillMaxHeight().navigationBarsPadding().padding(J.sp2), contentAlignment = Alignment.Center) {
        Column(Modifier.width(80.dp).glass(J.rL).padding(J.sp1).then(light), verticalArrangement = Arrangement.spacedBy(J.sp1)) {
            labelSize = rememberRowSize(TAB_NAMES, J.cap, 72.dp)
            tabs(Modifier.fillMaxWidth())
        }
    }
    else androidx.compose.foundation.layout.BoxWithConstraints(Modifier.fillMaxWidth().navigationBarsPadding()
        .padding(start = J.gutter, end = J.gutter, top = J.sp1, bottom = J.sp2)) {
        labelSize = rememberRowSize(TAB_NAMES, J.cap, (maxWidth - J.sp1 * 6) / TAB_NAMES.size - 4.dp)
        Row(Modifier.fillMaxWidth().glass(shape).padding(J.sp1).then(light), horizontalArrangement = Arrangement.spacedBy(J.sp1)) {
            tabs(Modifier.weight(1f))
        }
    }
}

private val TAB_NAMES = listOf("Feed", "Chat", "Approve", "Tools", "Settings")

@Composable
private fun Tab(icon: ImageVector, label: String, on: Boolean, badge: Int, modifier: Modifier,
                labelSize: androidx.compose.ui.unit.TextUnit, onClick: () -> Unit) {
    // A long press shows the name large for a moment (22f, the large content viewer pattern):
    // a shrunk label or a tab without its name never hides what the tab is
    var named by remember { mutableStateOf(false) }
    Column(modifier.heightIn(min = 56.dp).clip(J.pill).combinedClickable(role = Role.Tab, onClickLabel = label, onClick = onClick,
        onLongClickLabel = "Show the name", onLongClick = { named = true }),
        horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
        // inside the tab, so the bubble stands over its own tab; solid, so nothing shows through
        if (named) {
            androidx.compose.runtime.LaunchedEffect(Unit) { kotlinx.coroutines.delay(1500); named = false }
            androidx.compose.ui.window.Popup(alignment = if (J.rail) Alignment.CenterEnd else Alignment.TopCenter,
                offset = if (J.rail) androidx.compose.ui.unit.IntOffset(260, 0) else androidx.compose.ui.unit.IntOffset(0, -230),
                onDismissRequest = { named = false }) {
                Box(Modifier.background(J.bg, J.rM).glass(J.rM).padding(horizontal = J.sp5, vertical = J.sp3)) {
                    Text(label, style = J.tm)
                }
            }
        }
        // On the light: dark on a filled one, the accent on an outlined one; off it muted, not
        // faint, so an icon keeps 3:1 against the bar (WCAG 1.4.11)
        val ink = if (!on) J.muted else if (J.outline) J.accText else J.bg
        Box {
            Icon(icon, contentDescription = label, tint = ink, modifier = Modifier.size(24.dp))
            // The badge in the theme's shape with a ring of the bar, so it reads over the icon
            if (badge > 0) Box(Modifier.offset(x = 14.dp, y = (-7).dp).size(20.dp).clip(J.pill).background(J.sheet)
                .padding(2.dp).clip(J.pill).background(J.acc), contentAlignment = Alignment.Center) {
                Text(badge.coerceAtMost(9).toString(), style = J.monoCap.copy(color = J.onAcc))
            }
        }
        if (A11y.prefs.showLabels) Text(label, style = J.cap.copy(color = ink, fontSize = labelSize,
            fontWeight = if (on) FontWeight(700) else FontWeight(500)),
            maxLines = 1, softWrap = false, modifier = Modifier.padding(horizontal = 2.dp))
    }
}

/** Waits for the chat page, asks inside it, and polls for the answer (106). */
private suspend fun ask(web: android.webkit.WebView, origins: Origins, n: Notice): AskJulz.Reply {
    var waited = 0
    while (!(web.progress == 100 && web.url?.let { ChatRules.inside(origins, it) } == true)) {
        if (waited >= 30_000) return AskJulz.Reply.Failed
        kotlinx.coroutines.delay(500); waited += 500
    }
    val id = AskJulz.newId()
    web.evaluateJavascript(AskJulz.script(id, AskJulz.body(AskJulz.question(n))), null)
    app.julz.AppLog.add("ask: sent about a ${n.kind.name.lowercase()} notice")
    repeat(240) {  // 2 minutes
        kotlinx.coroutines.delay(500)
        val raw = kotlin.coroutines.suspendCoroutine<String?> { c -> web.evaluateJavascript(AskJulz.poll(id)) { c.resumeWith(Result.success(it)) } }
        val reply = AskJulz.read(raw)
        if (reply != AskJulz.Reply.Pending) {
            app.julz.AppLog.add("ask: " + if (reply is AskJulz.Reply.Answer) "answered" else "failed")
            return reply
        }
    }
    app.julz.AppLog.add("ask: no answer in 2 minutes")
    return AskJulz.Reply.Failed
}
