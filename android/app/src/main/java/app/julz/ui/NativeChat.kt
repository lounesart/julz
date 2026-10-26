package app.julz.ui

import android.content.Context
import android.net.Uri
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.isImeVisible
import androidx.compose.foundation.layout.union
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.animation.animateContentSize
import androidx.compose.animation.core.animateFloat
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.input.nestedscroll.nestedScroll
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.graphics.drawOutline
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.customActions
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import app.julz.chat.ChatApi
import app.julz.chat.ChatLogic
import app.julz.chat.ChatMessage
import app.julz.chat.ChatSummary
import app.julz.chat.ChatView
import app.julz.chat.End
import app.julz.chat.KeepCase
import app.julz.chat.SaveToNotes
import app.julz.feed.ObsidianMd
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlin.math.roundToInt

/** Which chat the Chat tab shows (26): the native screen, or Open WebUI's page as before. Off
 *  until the native one has passed my checklist; then it becomes the default. */
object ChatPrefs {
    var native by mutableStateOf(false)

    fun load(context: Context) {
        native = context.getSharedPreferences("julz_ui", Context.MODE_PRIVATE).getBoolean("chat_native", false)
        roomy = context.getSharedPreferences("julz_ui", Context.MODE_PRIVATE).getBoolean("chat_roomy", true)
    }

    fun set(context: Context, on: Boolean) {
        native = on
        context.getSharedPreferences("julz_ui", Context.MODE_PRIVATE).edit().putBoolean("chat_native", on).apply()
    }

    /** The message box: roomy (two rows, the default since 19 Oct) or a single line */
    var roomy by mutableStateOf(true)

    fun setRoomy(context: Context, on: Boolean) {
        roomy = on
        context.getSharedPreferences("julz_ui", Context.MODE_PRIVATE).edit().putBoolean("chat_roomy", on).apply()
    }
}

/** Julz working, before her first words (asked 19 Oct, as Gemini shows it): a soft light sweeps
 *  across the word and a small accent dot breathes beside it. Still when the phone asks for less
 *  motion. Drawn by the shader of one brush, so it costs one layer, not a recomposition. */
@Composable
private fun Thinking(still: Boolean) {
    if (still) { Text("Thinking", style = J.sec.copy(color = J.muted)); return }
    val loop = androidx.compose.animation.core.rememberInfiniteTransition(label = "thinking")
    // Across the word and a little past it, so the light is on the word most of the time
    val sweep by loop.animateFloat(-0.3f, 1.3f, androidx.compose.animation.core.infiniteRepeatable(
        androidx.compose.animation.core.tween(1400, easing = androidx.compose.animation.core.LinearEasing)), label = "sweep")
    val breath by loop.animateFloat(0.35f, 1f, androidx.compose.animation.core.infiniteRepeatable(
        androidx.compose.animation.core.tween(800, easing = J.ease), androidx.compose.animation.core.RepeatMode.Reverse), label = "breath")
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
        Box(Modifier.size(8.dp).graphicsLayer { alpha = breath; scaleX = 0.7f + 0.3f * breath; scaleY = scaleX }
            .clip(J.pill).background(J.acc))
        val width = with(LocalDensity.current) { 80.dp.toPx() }
        Text("Thinking", style = J.sec.copy(brush = androidx.compose.ui.graphics.Brush.linearGradient(
            listOf(J.muted, J.text, J.accText, J.text, J.muted),
            start = androidx.compose.ui.geometry.Offset(width * sweep - width / 2, 0f),
            end = androidx.compose.ui.geometry.Offset(width * sweep + width / 2, 0f))))
    }
}

/** A message that arrives while I watch rises 16 dp and fades in, 350 ms on the HyDE curve */
@Composable
private fun Modifier.arrive(now: Boolean): Modifier {
    if (!now) return this
    val p = remember { androidx.compose.animation.core.Animatable(0f) }
    LaunchedEffect(Unit) { p.animateTo(1f, androidx.compose.animation.core.tween(350, easing = J.ease)) }
    val rise = with(LocalDensity.current) { 16.dp.toPx() }
    return this.graphicsLayer { alpha = p.value; translationY = (1f - p.value) * rise }
}

/** Ways to start a chat, from what I use Julz for: study, the planner, Claude */
private val STARTS = listOf("Quiz me on Network+", "Explain a note of mine", "Plan my study day", "Ask Claude to")

/** What the chats sheet shows: my chats, the archived ones, or a delete to confirm. */
private sealed interface ChatsSheet {
    data object Mine : ChatsSheet
    data object Archived : ChatsSheet
    data class Delete(val chat: ChatSummary, val from: ChatsSheet) : ChatsSheet
}

/** The native chat (26, SECURITY.md 136 to 139): my chats through julz-chat on the laptop,
 *  Julz's answers as pages through our parser, mine as cards. Chats live in Open WebUI; the
 *  phone keeps them in memory only. [chatId] null is a new chat. */
@Composable
fun NativeChat(origins: Origins, origin: String, token: String, chatId: String?, setChat: (String?) -> Unit,
               draft: String, setDraft: (String) -> Unit, openWeb: () -> Unit, openNote: (String) -> Unit = {}) {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val clipboard = androidx.compose.ui.platform.LocalClipboardManager.current
    // send() can run from a reference made when the box was empty: strong skipping keeps such a
    // reference, and it sent "0 chars" while the box held my words (found 19 Oct). It reads the
    // newest values through these instead
    val draftNow by androidx.compose.runtime.rememberUpdatedState(draft)
    val chatNow by androidx.compose.runtime.rememberUpdatedState(chatId)
    // One object each for the screen's life, cleared when the chat changes: Send, Stop and the
    // menus may hold a reference from before a new chat got its id, and their writes must still
    // reach the screen (127: the second message sent but never showed, the third refused as busy)
    var view by remember { mutableStateOf<ChatView?>(null) }
    var chats by remember { mutableStateOf<List<ChatSummary>?>(null) }
    var archived by remember { mutableStateOf<List<ChatSummary>?>(null) }
    var sheet by remember { mutableStateOf<ChatsSheet?>(null) }
    var undo by remember { mutableStateOf<ChatSummary?>(null) }
    var menu by remember { mutableStateOf<ChatMessage?>(null) }
    // Edit: my last message's words in the box; send then replaces it (26b, 136)
    var editing by remember { mutableStateOf<ChatMessage?>(null) }
    var sending by remember { mutableStateOf(false) }
    var problem by remember { mutableStateOf<String?>(null) }
    var note by remember { mutableStateOf<String?>(null) }
    var sentAt by remember { mutableStateOf(0L) }
    // A mode (135 learn, 133b notes) or "": its name goes with each message; an opened chat
    // brings its own back
    var chatMode by remember { mutableStateOf("") }
    val modeNow by androidx.compose.runtime.rememberUpdatedState(chatMode)

    suspend fun call(path: String, body: String? = null, delete: Boolean = false) =
        withContext(Dispatchers.IO) { ChatApi.call(origin, path, token, body, delete) }

    suspend fun loadList(): Boolean {
        val (code, raw) = call(ChatApi.list(1)!!)
        if (code == 200) ChatApi.parseList(raw)?.let { chats = it; return true }
        problem = ChatApi.problem(code)
        return false
    }

    suspend fun loadArchived() {
        val (code, raw) = call(ChatApi.archived(1)!!)
        if (code == 200) ChatApi.parseList(raw)?.let { archived = it; return }
        problem = ChatApi.problem(code)
    }

    suspend fun load(id: String) {
        val path = ChatApi.view(id) ?: return
        val (code, raw) = ChatLogic.relisting({ call(path) }, { loadList() })
        if (code == 200) ChatApi.parseView(raw)?.let { view = it; problem = null }
        else problem = ChatApi.problem(code)
    }

    LaunchedEffect(chatId) {
        problem = null
        if (view?.id != chatId) { view = null; editing = null }
        if (chatId != null) load(chatId) else if (chats == null) loadList()
    }
    // While Julz answers: poll the last message, fast at first; another message means read it all
    LaunchedEffect(view?.id, view?.busy) {
        while (true) {
            val v = view ?: break
            val wait = ChatLogic.pollDelay(v.busy, System.currentTimeMillis() - sentAt) ?: break
            delay(wait)
            val (code, raw) = call(ChatApi.last(v.id) ?: break)
            val m = if (code == 200) ChatApi.parseMessage(raw) else null
            if (m == null) { if (code != 200) problem = ChatApi.problem(code); continue }
            val merged = ChatLogic.withLast(v, m)
            if (merged != null) view = merged else load(v.id)
            // Done: read it once more for the title Open WebUI writes alongside, a moment later
            if (merged?.busy == false) {
                load(v.id)
                if (ChatLogic.title(view?.title ?: "") == "New chat") { delay(4_000); load(v.id) }
            }
        }
    }
    // Only when another chat opens: a poll must not undo the tap I made before sending
    LaunchedEffect(view?.id) { view?.let { chatMode = it.mode } }
    LaunchedEffect(undo) { if (undo != null) { delay(5_000); undo = null } }
    LaunchedEffect(note) { if (note != null) { delay(5_000); note = null } }

    /** One request that starts an answer: a message, an edit or a retry */
    fun start(path: String?, body: String?) {
        if (path == null || body == null) return
        sending = true; problem = null
        scope.launch {
            val (code, raw) = ChatLogic.relisting({ call(path, body) }, { loadList() })
            // The status only, never the text: a send that failed left no trace (found 19 Oct)
            app.julz.AppLog.add("chat: send ${path.substringAfterLast('/')} -> $code")
            val sent = if (code == 200) ChatApi.parseSent(raw) else null
            if (sent == null) problem = ChatApi.problem(code)
            else {
                setDraft(""); editing = null
                sentAt = System.currentTimeMillis()
                if (sent.chat != chatNow) { chats = null; setChat(sent.chat) } else load(sent.chat)
            }
            sending = false
        }
    }

    fun send() {
        val draft = draftNow
        if (!ChatLogic.canSend(draft, view?.busy == true, sending, editing != null)) {
            app.julz.AppLog.add("chat: send refused here (busy ${view?.busy}, sending $sending, ${draft.length} chars)")
            return
        }
        val id = chatNow
        // Writing in an archived chat brings it back to My chats first, as WhatsApp and Gmail do;
        // else my new message would sit in a chat I cannot see in the list
        if (id != null && view?.archived == true) {
            sending = true
            scope.launch {
                val (code, raw) = call(ChatApi.unarchive(id) ?: return@launch, "{}")
                sending = false
                if (code != 200 || ChatApi.parseArchived(raw) != false) { problem = ChatApi.problem(code); return@launch }
                view = view?.copy(archived = false); note = "Back in My chats"
                send()
            }
            return
        }
        if (editing != null && id != null) start(ChatApi.edit(id), ChatApi.body(draft, modeNow))
        else start(ChatApi.send(id), ChatApi.body(draft, modeNow))
    }

    fun stop() {
        val id = view?.id ?: return
        scope.launch {
            val (code, _) = call(ChatApi.stop(id) ?: return@launch, "{}")
            if (code != 200) problem = ChatApi.problem(code)
            load(id)
        }
    }

    fun archive(c: ChatSummary, on: Boolean) {
        scope.launch {
            val (code, raw) = call((if (on) ChatApi.archive(c.id) else ChatApi.unarchive(c.id)) ?: return@launch, "{}")
            if (code != 200 || ChatApi.parseArchived(raw) != on) {
                problem = if (code == 409) "Julz is still answering in that chat: archive it when she is done" else ChatApi.problem(code)
                return@launch
            }
            if (on) { chats = chats?.filter { it.id != c.id }; undo = c; if (c.id == chatNow) setChat(null) }
            else {
                archived = archived?.filter { it.id != c.id }; undo = null
                if (c.id == chatNow) view = view?.copy(archived = false)
            }
            loadList()
        }
    }

    fun delete(c: ChatSummary) {
        scope.launch {
            val (code, raw) = call(ChatApi.delete(c.id) ?: return@launch, delete = true)
            if (code != 200 || !ChatApi.parseDeleted(raw)) { problem = ChatApi.problem(code); return@launch }
            chats = chats?.filter { it.id != c.id }; archived = archived?.filter { it.id != c.id }
            if (c.id == chatNow) setChat(null)
            note = "Deleted \"${ChatLogic.title(c.title)}\""
        }
    }

    /** Into Inbox through the approver, signed (139): the exact text shows in the sign panel, then my fingerprint */
    fun save(m: ChatMessage) {
        val body = SaveToNotes.body(m.text) ?: return
        signWithDevice(context, scope, origins, "save", body, "Save to notes") { word, why ->
            note = if (word != null) "Saved to Inbox. Sort it there when you have read it." else why
        }
    }

    /** A bad answer with my question into feedback/eval/ through the approver, signed (155, 153) */
    fun keep(v: ChatView, m: ChatMessage) {
        val q = ChatLogic.questionFor(v, m) ?: return
        val body = KeepCase.body(q, m.text, ChatLogic.modeFor(v, m)) ?: return
        signWithDevice(context, scope, origins, "case", body, "Keep as a bad answer") { word, why ->
            note = if (word != null) "Kept as a test case. It waits on the laptop for you." else why
        }
    }

    // The tab bar floats over the screen (22i) and the keyboard slides over the bar: the box sits
    // on whichever is higher, frame by frame, so it never drops before rising (127)
    Column(Modifier.fillMaxSize().windowInsetsPadding(
        WindowInsets.ime.union(WindowInsets(bottom = barClear())))) {
        // On its side the phone has about 570 px left over the keyboard: the header took 200 of
        // them, the messages got none and the box was squeezed until its text clipped (127). While
        // I type there, the header steps aside; the rail shows the same short height
        @OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
        val short = J.rail && WindowInsets.isImeVisible
        if (!short) Box(Modifier.padding(horizontal = J.gutter)) {
            // An archived chat says so: writing in it brings it back (26b)
            ScreenHeader(ChatLogic.title(view?.title ?: ""), sub = if (view?.archived == true) "archived · writing brings it back" else null,
                content = true, action = {
                Row(horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                    RoundButton(Icons.chats, "My chats") { sheet = ChatsSheet.Mine; scope.launch { loadList() } }
                    RoundButton(Icons.plus, "New chat") { editing = null; setChat(null) }
                }
            })
        }
        val list = rememberLazyListState()
        val messages = view?.messages.orEmpty()
        val still = stillMotion()
        // Messages from before this moment are history and do not animate when a chat opens
        val openedAt = remember(chatId) { System.currentTimeMillis() / 1000 - 2 }
        // 26j: reading up while Julz writes, the list dragged me down. It was newest at the bottom
        // with the growing answer anchored there (reverse layout), so each new line pushed what I
        // read upwards. Now a plain list: new lines land below and nothing moves by itself; the
        // list follows only while I am at its end, and a button brings me back when I left it
        // One state for the screen's life: the scroll watchers below hold on to it. Keyed by the
        // chat it was replaced on a new chat while they kept switching the old one (found 19 Oct)
        var follow by remember { mutableStateOf(true) }
        LaunchedEffect(chatId) { follow = true }
        val leftEnd = remember {
            object : androidx.compose.ui.input.nestedscroll.NestedScrollConnection {
                override fun onPreScroll(available: androidx.compose.ui.geometry.Offset,
                                         source: androidx.compose.ui.input.nestedscroll.NestedScrollSource): androidx.compose.ui.geometry.Offset {
                    // My finger pulling the list down means reading up: stop following
                    if (source == androidx.compose.ui.input.nestedscroll.NestedScrollSource.UserInput && available.y > 0) follow = false
                    return androidx.compose.ui.geometry.Offset.Zero
                }
            }
        }
        // A scroll that settles at the end: follow again. Only when it settles: a drag starts at
        // the end, and checking then turned following straight back on (found on the phone)
        LaunchedEffect(list) {
            androidx.compose.runtime.snapshotFlow { list.isScrollInProgress to list.canScrollForward }
                .collect { (moving, more) -> if (!moving && !more) follow = true }
        }
        val lastLength = messages.lastOrNull()?.text?.length ?: 0
        // A new message (mine or hers) brings the end into view and follows again
        LaunchedEffect(messages.lastOrNull()?.id) {
            if (messages.isNotEmpty()) { follow = true; list.scrollToItem(list.layoutInfo.totalItemsCount - 1, 100_000) }
        }
        // While it grows: keep the end in view, only while I follow
        LaunchedEffect(lastLength, view?.busy) {
            if (follow && messages.isNotEmpty()) list.scrollToItem(list.layoutInfo.totalItemsCount - 1, 100_000)
        }
        // The keyboard shrinks the list from below, frame by frame: keep the end in view while I
        // follow, or her newest answer hides under the box (127, seen 24 Oct)
        LaunchedEffect(list) {
            androidx.compose.runtime.snapshotFlow { list.layoutInfo.viewportSize.height }
                .collect { if (follow && list.layoutInfo.totalItemsCount > 0) list.scrollToItem(list.layoutInfo.totalItemsCount - 1, 100_000) }
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            LazyColumn(Modifier.fillMaxSize().fadeOutBottom(28.dp).nestedScroll(leftEnd), state = list,
                contentPadding = androidx.compose.foundation.layout.PaddingValues(horizontal = J.gutter, vertical = J.sp4),
                verticalArrangement = Arrangement.spacedBy(J.section)) {
                items(messages, key = { it.id }) { m ->
                    // Moves smoothly when the list changes; a message that arrives while I watch rises in
                    // No fade out: a removed row stayed drawn over its place while it faded, and "Thinking"
                    // lay on the first lines of the answer (found 19 Oct)
                    Box((if (still) Modifier else Modifier.animateItem(fadeOutSpec = null)).arrive(m.time >= openedAt && !still)) {
                    if (m.user) Mine(m) { menu = m } else Answer(m, context, { menu = m }, openNote, retry = {
                        val vv = view
                        if (vv != null && ChatLogic.canRetry(vv, m)) start(ChatApi.retry(vv.id), "{}")
                    }) {
                        clipboard.setText(androidx.compose.ui.text.AnnotatedString(m.text)); note = "Copied"
                    }
                    }
                }
                if (view?.let { ChatLogic.thinking(it) } == true) item(key = "thinking") {
                    Thinking(still)
                }
            }
            // A new chat (26e, asked 19 Oct): the title in the app's own type, centred in the empty
            // space as Claude and ChatGPT do, and a few starts that fill the box, never send
            // Low height (landscape, big text): one row of starts, the second slid under the box
            val roomFor = with(LocalDensity.current) { list.layoutInfo.viewportSize.height.toDp() }
            val starts = if (roomFor in 1.dp..360.dp) STARTS.take(2) else STARTS
            if (messages.isEmpty() && chatId == null) Column(Modifier.align(Alignment.Center).padding(horizontal = J.gutter),
                horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(J.sp5)) {
                Text("Ask Julz anything", style = J.tl.copy(textAlign = androidx.compose.ui.text.style.TextAlign.Center))
                // A 2 by 2 grid of equal cards: a wrapping row left two alone and two paired
                Column(verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                    for (pair in starts.chunked(2)) Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min),
                        horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
                        for (start in pair) Text(start, style = J.sec.copy(color = J.text),
                            modifier = Modifier.weight(1f).fillMaxHeight().heightIn(min = J.row).clip(J.rM).background(J.surface)
                                .border(1.dp, J.line, J.rM).clickable(role = Role.Button, onClickLabel = "Put in the box") { setDraft("$start ") }
                                .padding(J.sp4))
                    }
                }
            }
            // Away from the end while there is more below: one tap back, as Claude and ChatGPT do
            // Solid, so the answer under it never shows through (it read as one jumble, found 19 Oct).
            // Idle: a small round arrow, as Claude and ChatGPT have it, so it hides little of what
            // I read; while Julz writes, a pill that says so
            if (!follow && list.canScrollForward) {
                val writing = view?.busy == true
                val jump = {
                    follow = true
                    scope.launch { list.animateScrollToItem(list.layoutInfo.totalItemsCount - 1, 100_000) }
                    Unit
                }
                if (!writing) Box(Modifier.align(Alignment.BottomCenter).padding(bottom = J.sp2)) {
                    IconButton(Icons.toEnd, "Jump to the newest", J.sheet, J.text, onClick = jump)
                } else Row(Modifier.align(Alignment.BottomCenter).padding(bottom = J.sp3)
                    .heightIn(min = J.tap).clip(J.pill).background(J.sheet).background(J.raise).border(1.dp, J.lineStrong, J.pill)
                    .clickable(role = Role.Button, onClickLabel = "Jump to the newest", onClick = jump)
                    .padding(horizontal = J.sp5), verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
                    Icon(Icons.toEnd, null, tint = J.text, modifier = Modifier.size(16.dp))
                    Text("Julz is writing", maxLines = 1, style = J.sec.copy(color = J.text, fontWeight = FontWeight(600)))
                }
            }
        }
        (problem ?: note)?.let {
            Text(it, style = J.sec.copy(color = if (problem != null) J.warn else J.text),
                modifier = Modifier.padding(horizontal = J.gutter, vertical = J.sp1))
        }
        editing?.let {
            Row(Modifier.fillMaxWidth().padding(horizontal = J.gutter), verticalAlignment = Alignment.CenterVertically) {
                Text("Editing your message", style = J.sec.copy(color = J.accText, fontWeight = FontWeight(600)),
                    modifier = Modifier.weight(1f))
                Text("Cancel", style = J.sec.copy(color = J.text, fontWeight = FontWeight(600)),
                    modifier = Modifier.heightIn(min = J.tap).clickable(role = Role.Button) { editing = null; setDraft("") }
                        .padding(horizontal = J.sp3, vertical = J.sp3))
            }
        }
        // While I edit, the button sends the edit; Cancel brings Stop back (203)
        Composer(draft, setDraft, busy = view?.busy == true && editing == null, sending = sending, focus = editing?.id, roomy = ChatPrefs.roomy,
            mode = chatMode, setMode = { chatMode = it }, send = ::send, stop = ::stop)
    }

    // One sheet at a time: what a message offers, the text I sign, or my chats
    // Read once into locals: the sheet layer may draw a body a frame after its state went back
    // to null, and a `sheet!!` there closed the app (found 18 Oct on the phone, a crash)
    val held = menu
    val v = view
    val mode = sheet
    when {
        held != null && v != null -> JulzSheet(onDismiss = { menu = null }) {
            SheetTitle(if (held.user) "Your message" else "Julz's answer")
            Column(Modifier.fillMaxWidth().glass().padding(horizontal = J.inset)) {
                MenuRow(Icons.copy, "Copy", "The whole text, as written") {
                    menu = null; clipboard.setText(androidx.compose.ui.text.AnnotatedString(held.text)); note = "Copied"
                }
                if (held.user) {
                    // Always shown, greyed with its reason when it cannot be used: a menu with only
                    // Copy looked broken (found 18 Oct)
                    val can = ChatLogic.canEdit(v, held)
                    val sub = when {
                        !can -> "Only your last message"
                        v.busy -> "Stops her answer, then sends your new words"
                        else -> "Change it and send again"
                    }
                    MenuRow(Icons.edit, "Edit", sub,
                        enabled = can) { menu = null; editing = held; setDraft(held.text) }
                } else {
                    val can = ChatLogic.canRetry(v, held)
                    MenuRow(Icons.reload, "Retry", if (can) "A new answer; the old one stays on the laptop" else "Only the last answer, when it is done",
                        enabled = can) { menu = null; start(ChatApi.retry(v.id), "{}") }
                    val saveable = held.done && held.text.isNotBlank()
                    MenuRow(Icons.folder, "Save to notes", "Into Inbox, signed with your fingerprint", enabled = saveable) {
                        menu = null; save(held)
                    }
                    val keepable = ChatLogic.questionFor(v, held) != null
                    MenuRow(Icons.bad, "Bad answer", if (keepable) "Kept with your question as a test case, signed"
                        else "Only a finished answer to a message of yours", enabled = keepable) {
                        menu = null; keep(v, held)
                    }
                }
            }
        }
        mode != null -> JulzSheet(onDismiss = { sheet = null }) {
            ChatsSheetBody(mode, chats, archived, undo, note, problem, chatId,
                open = { sheet = null; editing = null; setChat(it.id) },
                archive = { c, on -> archive(c, on) },
                askDelete = { c -> sheet = ChatsSheet.Delete(c, mode) },
                delete = { c, back -> delete(c); sheet = back },
                show = { s -> sheet = s; if (s == ChatsSheet.Archived) scope.launch { loadArchived() } },
                openWeb = { sheet = null; openWeb() })
        }
    }
}

@Composable
private fun ChatsSheetBody(mode: ChatsSheet, chats: List<ChatSummary>?, archived: List<ChatSummary>?, undo: ChatSummary?,
                           note: String?, problem: String?, current: String?, open: (ChatSummary) -> Unit, archive: (ChatSummary, Boolean) -> Unit,
                           askDelete: (ChatSummary) -> Unit, delete: (ChatSummary, ChatsSheet) -> Unit,
                           show: (ChatsSheet) -> Unit, openWeb: () -> Unit) {
    when (mode) {
        is ChatsSheet.Delete -> {
            // Delete is permanent in Open WebUI: never a gesture, always this (26b)
            SheetTitle("Delete \"${ChatLogic.title(mode.chat.title)}\"?",
                "It goes from Open WebUI for good, on the laptop too. Archive keeps it out of the list instead.")
            Column(verticalArrangement = Arrangement.spacedBy(J.sp3)) {
                PlainButton("Delete for good", color = J.warn, border = J.warn.copy(alpha = 0.4f)) { delete(mode.chat, mode.from) }
                PlainButton("Cancel") { show(mode.from) }
            }
        }
        else -> {
            val mine = mode == ChatsSheet.Mine
            SheetTitle(if (mine) "My chats" else "Archived chats",
                if (mine) "Swipe a chat to archive it; hold it to delete." else "Out of My chats, kept on the laptop. Swipe one back; hold it to delete.",
                icon = if (mine) null else Icons.archive)
            // A delete's word and a refusal show here too: under the chat they hid behind this sheet
            if (problem != null) Text(problem, style = J.sec.copy(color = J.warn))
            else if (note != null && undo == null) Text(note, style = J.sec.copy(color = J.text))
            // Under the title, where the eye is: below a long list it was off screen (found on the phone)
            if (undo != null && mine) Row(Modifier.fillMaxWidth().glass(J.rM).padding(horizontal = J.inset),
                verticalAlignment = Alignment.CenterVertically) {
                Text("Archived \"${ChatLogic.title(undo.title)}\"", style = J.sec.copy(color = J.text), modifier = Modifier.weight(1f))
                Text("Undo", style = J.sec.copy(color = J.accText, fontWeight = FontWeight(700)),
                    modifier = Modifier.heightIn(min = J.tap).clickable(role = Role.Button) { archive(undo, false) }
                        .padding(start = J.sp3, top = J.sp3, bottom = J.sp3))
            }
            val rows = if (mine) chats else archived
            // Archived is a place, not an action: a row at the top of the list, as WhatsApp and
            // Gmail have it (it was an outlined button beside the web chat's)
            // Archived looks set apart: its own icon, a dashed edge, the chats in muted words
            // A row that leaves (archive, delete) closes its gap smoothly instead of a jump
            Column(Modifier.fillMaxWidth().then(if (stillMotion()) Modifier else Modifier.animateContentSize())
                .then(if (mine) Modifier.glass() else Modifier.dashed())
                .padding(horizontal = J.inset)) {
                if (mine) MenuRow(Icons.archive, "Archived chats", "Out of the list, kept on the laptop") { show(ChatsSheet.Archived) }
                else MenuRow(Icons.back, "My chats", "Back to the list") { show(ChatsSheet.Mine) }
                if (rows != null) for (c in rows) androidx.compose.runtime.key(c.id) {
                    SwipeRow(if (mine) "Archive" else "Back to My chats", if (mine) Icons.archive else Icons.unarchive,
                        onSwipe = { archive(c, mine) }) {
                        ChatRow(c, c.id == current, archived = !mine, onClick = { open(c) }, onLong = { askDelete(c) })
                    }
                }
            }
            // An empty or loading list is a line of text, never a card that looks like a button
            when {
                rows == null -> Text("Loading", style = J.sec)
                rows.isEmpty() -> Text(if (mine) "No chats yet." else "Nothing archived.", style = J.sec)
            }
            // What is not native yet (files, models, settings) stays in Open WebUI's page (26)
            if (mine) PlainButton("Open the web chat") { openWeb() }
        }
    }
}

/** A sheet's title and the line that explains it, kept together; the sheet's own gap comes
 *  after them (found 18 Oct: every part of a sheet sat 16 dp apart, title and line included). */
@Composable
private fun SheetTitle(title: String, sub: String? = null, icon: androidx.compose.ui.graphics.vector.ImageVector? = null) {
    Row(horizontalArrangement = Arrangement.spacedBy(J.sp3), verticalAlignment = Alignment.CenterVertically) {
        if (icon != null) IconBadge(icon)
        Column(verticalArrangement = Arrangement.spacedBy(J.sp1)) {
            Text(title, style = J.ts)
            if (sub != null) Text(sub, style = J.sec)
        }
    }
}

/** One row of a sheet's menu: an icon, what it does and a line on it, the same height each;
 *  greyed with its reason when it cannot run. */
@Composable
private fun MenuRow(icon: androidx.compose.ui.graphics.vector.ImageVector, title: String, sub: String,
                    enabled: Boolean = true, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().heightIn(min = J.row).clickable(role = Role.Button, enabled = enabled, onClick = onClick)
        .padding(vertical = J.sp3), verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(J.sp4)) {
        Icon(icon, null, tint = if (enabled) J.accText else J.faint, modifier = Modifier.size(22.dp))
        Column(Modifier.weight(1f)) {
            Text(title, style = J.item.copy(color = if (enabled) J.text else J.faint))
            Text(sub, style = J.sec.copy(color = if (enabled) J.muted else J.faint))
        }
    }
}

/** A dashed edge in the theme's card shape: what is set aside, here the archived chats. */
@Composable
private fun Modifier.dashed(): Modifier {
    val shape = J.rL
    val color = J.lineStrong
    return this.clip(shape).drawBehind {
        val outline = shape.createOutline(size, layoutDirection, this)
        drawOutline(outline, color, style = androidx.compose.ui.graphics.drawscope.Stroke(width = 1.5.dp.toPx(),
            pathEffect = androidx.compose.ui.graphics.PathEffect.dashPathEffect(floatArrayOf(10f, 8f))))
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ChatRow(c: ChatSummary, current: Boolean, archived: Boolean, onClick: () -> Unit, onLong: () -> Unit) {
    Column(Modifier.fillMaxWidth().heightIn(min = J.row)
        .combinedClickable(role = Role.Button, onClickLabel = "Open", onLongClickLabel = "Delete", onLongClick = onLong, onClick = onClick)
        .padding(vertical = J.sp3)) {
        Text(ChatLogic.title(c.title), style = J.item.copy(color = when {
            current -> J.accText; archived -> J.muted; else -> J.text }))
        if (c.updated > 0) Text("${Words.day(c.updated)} ${Words.time(c.updated)}", style = J.sec)
    }
}

/** A row that a sideways swipe acts on (26b). It follows the finger with no lag; behind it a
 *  soft accent strip shows the action's icon and name; the moving row keeps the card's look and
 *  corners. Past 35 percent of its width a tick of vibration says letting go will act; short of
 *  that it springs back. TalkBack reads the row and offers the action, for anyone who cannot
 *  swipe. (It was a hard dark block over the card, the name clipped behind it, and choppy: each
 *  finger move started its own animation, found 18 Oct.) */
@Composable
private fun SwipeRow(action: String, icon: androidx.compose.ui.graphics.vector.ImageVector, onSwipe: () -> Unit,
                     content: @Composable () -> Unit) {
    val scope = rememberCoroutineScope()
    val haptics = androidx.compose.ui.platform.LocalHapticFeedback.current
    var drag by remember { androidx.compose.runtime.mutableFloatStateOf(0f) }
    BoxWithConstraints(Modifier.fillMaxWidth().semantics {
        customActions = listOf(androidx.compose.ui.semantics.CustomAccessibilityAction(action) { onSwipe(); true })
    }) {
        val width = with(LocalDensity.current) { maxWidth.toPx() }
        val past = kotlin.math.abs(drag) > width * 0.35f
        if (drag != 0f) Row(Modifier.matchParentSize().clip(J.rS).background(J.acc.copy(alpha = if (past) 0.28f else 0.14f))
            .padding(horizontal = J.sp4), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = if (drag > 0) Arrangement.Start else Arrangement.End) {
            Icon(icon, null, tint = J.accText, modifier = Modifier.size(20.dp))
            Box(Modifier.width(J.sp2))
            Text(action, style = J.sec.copy(color = J.accText, fontWeight = FontWeight(700)), maxLines = 1)
        }
        Box(Modifier.offset { IntOffset(drag.roundToInt(), 0) }
            .then(if (drag != 0f) Modifier.clip(J.rS).background(J.sheet).background(J.surface) else Modifier)
            .draggable(rememberDraggableState { d ->
                val before = kotlin.math.abs(drag) > width * 0.35f
                drag += d
                if (before != kotlin.math.abs(drag) > width * 0.35f) haptics.performHapticFeedback(
                    androidx.compose.ui.hapticfeedback.HapticFeedbackType.TextHandleMove)
            }, Orientation.Horizontal, onDragStopped = { v ->
                val go = kotlin.math.abs(drag) > width * 0.35f || kotlin.math.abs(v) > 3000f && kotlin.math.abs(drag) > width * 0.15f
                val target = if (!go) 0f else if (drag >= 0) width else -width
                scope.launch {
                    androidx.compose.animation.core.animate(drag, target, initialVelocity = v) { x, _ -> drag = x }
                    if (go) {
                        onSwipe()
                        // Still here a moment later: the laptop refused (an answer running, no
                        // network), so the row comes back instead of staying off screen (found 19 Oct)
                        delay(1_500)
                        androidx.compose.animation.core.animate(drag, 0f) { x, _ -> drag = x }
                    }
                }
            })) { content() }
    }
}

/** My message: a compact glass card on the right with an accent line; hold it for more. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun Mine(m: ChatMessage, hold: () -> Unit) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
        Row(Modifier.fillMaxWidth(0.86f).height(IntrinsicSize.Min).clip(J.rM)
            .combinedClickable(onLongClickLabel = "More", onLongClick = hold, onClick = {})
            .glass(J.rM).padding(J.sp4), horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
            Box(Modifier.width(3.dp).fillMaxHeight().clip(J.rS).background(J.acc))
            Text(m.text, style = J.bodyText, modifier = Modifier.weight(1f))
        }
    }
}

/** Julz's answer: a full width page through our parser, links through the check (104, 138);
 *  hold it for more. */
@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun Answer(m: ChatMessage, context: Context, hold: () -> Unit, open: (String) -> Unit, retry: () -> Unit, copy: () -> Unit) {
    Column(Modifier.fillMaxWidth().combinedClickable(onLongClickLabel = "More", onLongClick = hold, onClick = {}),
        verticalArrangement = Arrangement.spacedBy(J.sp3)) {
        if (m.text.isNotEmpty()) {
            // Parsed off the main thread, the last version shown until the new one is ready: a
            // streaming answer parsed in the frame made 44 percent of frames late (18 Oct)
            val blocks by androidx.compose.runtime.produceState(remember { ObsidianMd.parse(m.text, links = true) }, m.text) {
                value = withContext(Dispatchers.Default) { ObsidianMd.parse(m.text, links = true) }
            }
            MarkdownView(blocks, link = { LinkCheck.open(context, Uri.parse(it)) })
        }
        m.error?.let { Text("Julz could not answer: $it", style = J.sec.copy(color = J.warn)) }
        // 26k: cut by the window (julz-chat's end word), or guessed from a last line that stops mid sentence
        androidx.compose.animation.AnimatedVisibility(ChatLogic.cutOff(m), enter = androidx.compose.animation.fadeIn(),
            exit = androidx.compose.animation.fadeOut()) { Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(J.sp3)) {
            Text(if (m.end == End.LENGTH) "This answer ran out of room." else "This answer stops mid sentence.", style = J.sec.copy(color = J.caution), modifier = Modifier.weight(1f, fill = false))
            Text("Retry", style = J.sec.copy(color = J.accText, fontWeight = FontWeight(700)),
                modifier = Modifier.heightIn(min = J.tap).clickable(role = Role.Button, onClick = retry).padding(horizontal = J.sp2, vertical = J.sp3))
        } }
        // 133c, threat 165: the notes retrieval found, drawn by the app outside the answer's text;
        // found, not used, so the words claim no more
        if (m.done && m.sources.isNotEmpty()) NotesFound(m.sources, open)
        // Starts at the answer's text edge; the tap area reaches right, not left (found 18 Oct)
        androidx.compose.animation.AnimatedVisibility(m.done && m.text.isNotEmpty(), enter = androidx.compose.animation.fadeIn(
            androidx.compose.animation.core.tween(300, delayMillis = 150))) { Row(Modifier.heightIn(min = J.tap).clip(J.pill)
            .clickable(role = Role.Button, onClickLabel = "Copy the answer", onClick = copy)
            .padding(end = J.sp3), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
            Icon(Icons.copy, null, tint = J.muted, modifier = Modifier.size(18.dp))
            Text("Copy", style = J.sec.copy(color = J.muted, fontWeight = FontWeight(600)))
        } }
    }
}

/** Pinned at the bottom (26b, 26l). Roomy (the default, asked 19 Oct): two rows as Claude and
 *  ChatGPT draw a tall box, the text across the whole width and a thin row of controls under
 *  it with send on the right (release 2's + goes on the left). Single line: one row with send
 *  inside, the same 6 dp from the box on its three outer sides. Either way the box grows with
 *  the text to six lines. (The first try, two empty lines with send in the corner, left the
 *  button alone at the bottom with uneven margins.) */
@Composable
internal fun Composer(draft: String, setDraft: (String) -> Unit, busy: Boolean, sending: Boolean, focus: String?,
                      roomy: Boolean, mode: String, setMode: (String) -> Unit, send: () -> Unit, stop: () -> Unit) {
    val can = ChatLogic.canSend(draft, busy, sending)
    val sendNow by androidx.compose.runtime.rememberUpdatedState(send)
    val stopNow by androidx.compose.runtime.rememberUpdatedState(stop)
    // Edit puts my words in the box: the box takes focus, the cursor at their end, the keyboard
    // up, so I can type at once (found 18 Oct: it needed a tap first)
    val requester = remember { androidx.compose.ui.focus.FocusRequester() }
    var value by remember { mutableStateOf(androidx.compose.ui.text.input.TextFieldValue(draft)) }
    if (value.text != draft) value = androidx.compose.ui.text.input.TextFieldValue(draft, androidx.compose.ui.text.TextRange(draft.length))
    LaunchedEffect(focus) { if (focus != null) requester.requestFocus() }
    // The shared icon button: a 40 dp shape in a 48 dp target, so 2 dp here puts the shape 6 dp
    // from the box on its three outer sides, as before
    val inset = 2.dp
    val button = J.tap
    var lines by remember { mutableStateOf(1) }
    val shape = if (roomy || lines > 1) J.rL else J.pill
    val field = @Composable { modifier: Modifier ->
        BasicTextField(value, { if (it.text.length <= ChatApi.MAX_TEXT) { value = it; setDraft(it.text) } },
            modifier.focusRequester(requester).keepsKeyboard(), textStyle = J.bodyText, maxLines = 6,
            cursorBrush = SolidColor(J.acc), onTextLayout = { lines = it.lineCount },
            decorationBox = { inner ->
                Box(contentAlignment = Alignment.CenterStart) {
                    if (draft.isEmpty()) Text(when (mode) { "learn" -> "Ask, and Julz will teach"; "notes" -> "Ask your notes"; else -> "Message Julz" },
                        style = J.bodyText.copy(color = J.faint), maxLines = 1)
                    inner()
                }
            })
    }
    val sendButton = @Composable { modifier: Modifier ->
        Box(modifier.keepsKeyboard()) {  // typing goes on after Send (228)
            IconButton(if (busy) Icons.stop else Icons.send, if (busy) "Stop the answer" else "Send",
                if (busy || can) J.acc else J.raise, if (busy || can) J.onAcc else J.faint, enabled = busy || can,
                line = false) { if (busy) stopNow() else sendNow() }
        }
    }
    val box = Modifier.fillMaxWidth().padding(horizontal = J.gutter, vertical = J.sp2)
        .clip(shape).background(J.surface).border(1.dp, J.lineStrong, shape)
    if (roomy) Column(box.padding(start = J.sp4, end = inset, top = J.sp3, bottom = inset)) {
        field(Modifier.fillMaxWidth().padding(end = J.sp3, bottom = J.sp2))
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            ModeWheel(mode, setMode)
            Box(Modifier.weight(1f))
            sendButton(Modifier)
        }
    } else Column {
        ModeWheel(mode, setMode, Modifier.padding(start = J.gutter + J.sp2, top = J.sp1))
        Row(box.heightIn(min = button + inset * 2).padding(start = J.sp4, end = inset),
            verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(J.sp2)) {
            // One line of 24 sp, centred against the button: (40 + 12 - 24) / 2 above and below
            field(Modifier.weight(1f).padding(vertical = 14.dp))
            sendButton(Modifier.padding(vertical = inset))
        }
    }
}

/** Notes found under an answer (133c): a tap opens the note in the notes browser. Compact as
 *  the mode chips; a Claude note says so, as its name does in retrieval (58). */
@Composable
internal fun NotesFound(paths: List<String>, open: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(J.sp2)) {
        Text("Notes found", style = J.cap.copy(color = J.muted))
        androidx.compose.foundation.layout.FlowRow(horizontalArrangement = Arrangement.spacedBy(J.sp2),
            verticalArrangement = Arrangement.spacedBy(J.sp2)) {
            for (p in paths) {
                val name = p.substringAfterLast('/').removeSuffix(".md")
                Row(Modifier.heightIn(min = 32.dp).clip(J.pill).border(1.dp, J.line, J.pill).background(J.raise)
                    .clickable(role = Role.Button, onClickLabel = "Open the note") { open(p) }
                    .padding(horizontal = J.sp3), verticalAlignment = Alignment.CenterVertically) {
                    Text(if (p.startsWith("Claude/")) "Claude \u00b7 $name" else name,
                        style = J.cap.copy(color = J.text, fontWeight = FontWeight(600)), maxLines = 1,
                        overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis)
                }
            }
        }
    }
}

/** The modes, at most one on: learning (135) and notes only (133b), on the wheel (251): one
 *  pick of three, where two switches read as if both could be on */
@Composable
private fun ModeWheel(mode: String, set: (String) -> Unit, modifier: Modifier = Modifier) {
    WheelPicker(Wheel.MODES.map { it.second }, Wheel.MODES.indexOfFirst { it.first == mode }.coerceAtLeast(0),
        modifier.width(192.dp)) { set(Wheel.MODES[it].first) }
}
