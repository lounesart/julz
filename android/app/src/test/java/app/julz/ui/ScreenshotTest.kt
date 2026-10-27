package app.julz.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import app.cash.paparazzi.DeviceConfig
import app.cash.paparazzi.Paparazzi
import app.julz.feed.Kind
import app.julz.feed.Notice
import org.junit.After
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import java.util.Locale
import java.util.TimeZone

/** Screenshots of the main screens against goldens in src/test/snapshots (184, threat 150).
 *  The regressions of 19 Oct (126, 127) were layout ones no unit test could see: rows and the
 *  pinned button under the floating tab bar. So screens are drawn in the real Shell. */
class ScreenshotTest {
    @get:Rule
    val paparazzi = Paparazzi(deviceConfig = DeviceConfig.PIXEL_5)

    // Times on screen follow the zone and locale: fixed, so a golden is the same on any machine
    private val zone = TimeZone.getDefault()
    private val locale = Locale.getDefault()

    @Before fun fix() { TimeZone.setDefault(TimeZone.getTimeZone("UTC")); Locale.setDefault(Locale.US) }
    @After fun restore() { TimeZone.setDefault(zone); Locale.setDefault(locale) }

    private val origins = Origins.from("https://laptop.tail1234.ts.net:8444")!!

    @Composable
    private fun shell(section: Screen, content: @Composable () -> Unit) =
        // On the page as App draws it, glows included, so the bar's band shows what the phone does (257)
        androidx.compose.foundation.layout.Box(androidx.compose.ui.Modifier.fillMaxSize().page()) {
            Shell(wide = false, bar = { TabBar(section, 2, it, {}, {}, {}, {}, {}) }, content = content)
        }

    private val todos = run {
        val l = "␞"; val f = "␟"
        Notice("t1", 1761400800, Kind.TODO, "Todos",
            "v3${f}${"c".repeat(64)}" +
                "${l}cpts${f}2${f}7${f}4${f}1${f}Finish the SQL injection module${f}Write up the AD lab" +
                "${f}Review nmap flags${f}Redo the pivoting box${f}Read the Kerberos chapter" +
                "${f}Set up the lab VM${f}Take notes on Responder" +
                "${l}get_job${f}1${f}4${f}3${f}0${f}Update the CV${f}Apply to two helpdesk roles" +
                "${f}Practise the A+ questions${f}Send the cover letter" +
                "${l}week${f}0${f}3${f}3${f}0${f}Physio on Tuesday${f}Call the bank${f}Buy a USB hub")
    }

    private val inbox = app.julz.feed.InboxSnapshotData("d".repeat(64), listOf(
        app.julz.feed.InboxNote("subnetting", "Inbox/subnetting.md", "a".repeat(64), 900, "2026-10-24",
            "# Subnetting\n\nA /26 gives 64 addresses, 62 hosts.\nPractise ten a day until it is quick."),
        app.julz.feed.InboxNote("ideas", "Inbox/ideas.md", "b".repeat(64), 400, "2026-10-23",
            "- a reranker for notes\n- the board view on the laptop"),
        app.julz.feed.InboxNote("call notes", "Inbox/call notes.md", "e".repeat(64), 300, "2026-10-22",
            "Ask about the helpdesk shift pattern.")),
        listOf("study", "daily", "study/network-plus"))

    @Composable
    private fun inbox(picked: List<String>) = shell(Screen.INBOX) {
        InboxContent(inbox, null, mapOf("study" to 12, "daily" to 30), picked, {}, false, null,
            reload = {}, apply = {}, browse = {}, back = {})
    }

    @Test
    fun firstRun() = paparazzi.snapshot {
        FirstRun("The server refused the token. Enter the new one.") { _, _, _ -> null }
    }

    // A picked task brings the pinned Apply bar: it must sit above the tab bar (126)
    @Test
    fun todosPicked() = paparazzi.snapshot {
        shell(Screen.TODOS) {
            TodosScreen(listOf(todos), origins, listOf(pickKey("cpts", "Review nmap flags")), {}) {}
        }
    }

    @Test
    fun todosUnpicked() = paparazzi.snapshot {
        shell(Screen.TODOS) { TodosScreen(listOf(todos), origins, emptyList(), {}) {} }
    }

    @Test
    fun inboxUnpicked() = paparazzi.snapshot { inbox(emptyList()) }

    // A move and a delete picked: the Apply bar above the tab bar, Will move and Will delete (126)
    @Test
    fun inboxPicked() = paparazzi.snapshot {
        inbox(listOf(app.julz.feed.InboxPick("Inbox/subnetting.md", "move", "study/network-plus").key,
                     app.julz.feed.InboxPick("Inbox/ideas.md", "delete").key))
    }

    private val inboxHash = "741af55b4ec085a58dfd86cafdc21e8cea5779638953e3d10ca753559857dd3b"

    @Composable
    private fun signScreen(title: String, text: String, reading: Boolean) =
        androidx.compose.foundation.layout.BoxWithConstraints {
            SignScreen(SignPanel.Ask(title, text, {}, {}), maxHeight * SignPanel.ABOVE,
                androidx.compose.foundation.rememberScrollState(), reading, {}, {})
        }

    // While I sign: a screen of its own, the text in the top part, the hash short and quiet; the
    // system's fingerprint sheet comes up over the empty bottom half (219, 219b)
    @Test
    fun signShort() = paparazzi.snapshot {
        signScreen("Change 2 notes", "inbox: $inboxHash\nmove: Inbox/subnetting.md -> study/network-plus/subnetting.md\n" +
            "delete: Inbox/ideas.md\n", reading = false)
    }

    // After reading a long text, the top part keeps its cap: the sheet must not cover its end (219)
    @Test
    fun signTopCapped() = paparazzi.snapshot {
        signScreen("Approve with Julz", (1..40).joinToString("\n") { "Line $it of a long spec" }, reading = false)
    }

    // Too long for the top: read whole first, Sign and Cancel at the bottom by the thumb (219)
    @Test
    fun signReadFirst() = paparazzi.snapshot {
        signScreen("Save to notes", "save: Inbox/subnetting answer.md\n\n" +
            (1..60).joinToString("\n") { "Line $it of the answer: a /26 gives 64 addresses, 62 hosts." }, reading = true)
    }

    // The mode chips in both composer layouts (135, 133b): left of send when roomy, above the box
    // when single line; on, the placeholder says she teaches
    @Composable
    private fun composer(roomy: Boolean, mode: String, draft: String = "", web: Boolean = false) =
        androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().background(J.bg),
            verticalArrangement = androidx.compose.foundation.layout.Arrangement.Bottom) {
            Composer(draft, {}, busy = false, sending = false, focus = null, roomy = roomy, mode = mode,
                setMode = {}, send = {}, stop = {}, web = web)
        }

    // A change Julz asked for in the chat (208, threat 156): the card text whole and plain, then
    // the two buttons, above the tab bar
    @Test fun proposalCards() {
        // Seen already, so the arrival frame is skipped: Paparazzi's one frame caught it at nothing
        for (k in listOf("a", "b")) Arrived.first("change-" + k.repeat(64))
        paparazzi.snapshot { proposalCardsScreen() }
    }

    @Composable
    private fun proposalCardsScreen() {
        shell(Screen.APPROVE) {
            androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().padding(horizontal = J.gutter),
                verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(J.gap)) {
                ProposalCard(app.julz.approve.Proposal("1760000000-00000001.json",
                    "Julz asks to add to daily/week.md:\n\n- [ ] buy bread\n- [ ] call mum\n", "a".repeat(64)), false, {}, {})
                ProposalCard(app.julz.approve.Proposal("1760000001-00000002.json",
                    "Julz asks to change study/network-plus/dhcp.md\n\nBefore:\nRelay agents.\n\nAfter:\n" +
                        "Relay agents forward DHCP across subnets.\n", "b".repeat(64)), false, {}, {})
            }
        }
    }

    // Last week's open goals, read only (126b(3), threat 157): words and bar, nothing to tap
    @Test fun pastGoals() = paparazzi.snapshot {
        shell(Screen.TODOS) {
            androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().padding(horizontal = J.gutter)) {
                PastGoalsCard(listOf(
                    app.julz.feed.GoalPeriod("2026-W42", "Last week", listOf(
                        app.julz.feed.GoalItem("Study 10 h (2/10) #goal/study-10-h [in:: pass-cpts] [est:: 10h] [spent:: 3h]", false,
                            2 to 10, "study-10-h", null, "pass-cpts", 30, 0, null, 600, 180, 180 to 600),
                        app.julz.feed.GoalItem("Read the Kerberos chapter (1/3)", false, 1 to 3, null, null))),
                    app.julz.feed.GoalPeriod("2025", "2025", listOf(app.julz.feed.GoalItem("Get A+", false, null, null, null)))))
            }
        }
    }

    // The year always, then week or month by pills (223): both picks, a goal in each card
    private fun goalCards(view: String) = paparazzi.snapshot {
        shell(Screen.TODOS) {
            androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().padding(horizontal = J.gutter),
                verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(J.sp3)) {
                val s = app.julz.feed.GoalsSnapshot("c".repeat(64), listOf(
                    app.julz.feed.GoalPeriod("2026-W43", "This week", listOf(
                        app.julz.feed.GoalItem("Study 10 h (3/10)", false, 3 to 10, null, null))),
                    app.julz.feed.GoalPeriod("2026-10", "October", listOf(
                        app.julz.feed.GoalItem("Finish the Network+ course #goal/net-plus [in:: pass-cpts]", false, null, "net-plus", 2 to 5,
                            "pass-cpts", 40, 5))),
                    app.julz.feed.GoalPeriod("2026", "2026", listOf(
                        app.julz.feed.GoalItem("Pass CPTS #goal/pass-cpts", false, null, "pass-cpts", null, null, 40, 1)))))
                GoalCards(s, view, {}, GoalsUi(), emptyList(), {})
            }
        }
    }
    @Test fun goalsWeek() = goalCards("week")
    // A goal's page, HTB style (227): percent, bar, hours and due, Done and Left by name, counts
    @Test fun goalPage() = paparazzi.snapshot {
        shell(Screen.TODOS) {
            androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().padding(horizontal = J.gutter)) {
                GoalPage(app.julz.feed.GoalDetail("Pass CPTS", 40, 180 to 600, "2027-03-01",
                    listOf(app.julz.feed.GoalPart("Net+", true, "100%"), app.julz.feed.GoalPart("DNS lab", true)),
                    listOf(app.julz.feed.GoalPart("Kerberos chapter", false, "1/3"), app.julz.feed.GoalPart("Subnetting drill", false)),
                    1, 0, 1), java.time.LocalDate.of(2026, 10, 25))
            }
        }
    }
    // The ghost row open, with a kept draft (223c): the field and Add in the row's place
    @Test fun inlineAddOpen() = paparazzi.snapshot {
        shell(Screen.TODOS) {
            androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().padding(horizontal = J.gutter),
                verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(J.sp3)) {
                InlineAdd("Add a goal", "Read the DNS chapter", {}, true) {}
                InlineAdd("Add a goal", "", {}, true) {}
            }
        }
    }
    @Test fun goalsMonth() = goalCards("month")

    @Test fun composerRoomy() = paparazzi.snapshot { composer(roomy = true, mode = "") }
    @Test fun composerRoomyLearn() = paparazzi.snapshot { composer(roomy = true, mode = "learn") }
    @Test fun composerLineLearn() = paparazzi.snapshot { composer(roomy = false, mode = "learn", draft = "What is a /26?") }
    @Test fun composerLineNotes() = paparazzi.snapshot { composer(roomy = false, mode = "notes") }
    // Web search (26d): on is the globe and a word in a pill; greyed with Notes; send only with words (262)
    @Test fun composerRoomyWeb() = paparazzi.snapshot { composer(roomy = true, mode = "learn", draft = "What is SearXNG?", web = true) }
    @Test fun composerRoomyNotesNoWeb() = paparazzi.snapshot { composer(roomy = true, mode = "notes", web = true) }
    @Test fun composerLineWeb() = paparazzi.snapshot { composer(roomy = false, mode = "", draft = "and its license?", web = true) }
    // The single line box with a long draft (262): words full width on top, controls in a row
    // under them, never squeezed between the wheel, the globe and send
    @Test fun composerLineLong() = paparazzi.snapshot {
        composer(roomy = false, mode = "learn", web = true, draft = "Explain how a /26 subnet splits a /24 and how many hosts each part " +
            "gets, then quiz me on it with three questions")
    }
    @Test fun composerLineBreak() = paparazzi.snapshot { composer(roomy = false, mode = "", draft = "Two lines\nhere") }
    // The web icon in the Industrial look (264): the cut globe off, the slit eye on
    @Test fun composerWebOffCut() = industrial { composer(roomy = true, mode = "", draft = "What is SearXNG?") }
    @Test fun composerWebOnCut() = industrial { composer(roomy = true, mode = "", draft = "What is SearXNG?", web = true) }

    private fun industrial(content: @Composable () -> Unit) {
        Look.prefs = LookPrefs(industrial = true)
        try { paparazzi.snapshot { content() } } finally { Look.prefs = LookPrefs() }
    }

    // Code colours and the system label (204): bash and PowerShell side by side, an unknown
    // language stays plain
    @Test fun codeBlocks() = paparazzi.snapshot {
        androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().background(J.bg)
            .padding(J.gutter)) {
            MarkdownView(app.julz.feed.ObsidianMd.parse("List the rules:\n\n```bash\n\$ sudo nft list ruleset # all tables\n" +
                "if [ -f \"\$HOME/.ssh/id_ed25519\" ]; then echo ok; fi\n```\n\nOn Windows:\n\n```powershell\n" +
                "PS C:\\> Get-NetFirewallRule -Enabled True | Select -First 5\n<# the first five #>\n\$env:PATH\n```\n\n" +
                "```text\nplain 42 \"stays\" # plain\n```", links = true))
        }
    }

    // The Sources sheet (238), drawn as the sheet's body: Links after a web turn (the queries,
    // then each page's real host above its title), and Notes with a Claude note marked
    private val webAnswer = app.julz.chat.ChatMessage("a1", false, "x", true, 1, null,
        sources = listOf("study/cert-map.md", "Claude/cpts/00-cpts-overview.md"),
        searched = listOf("SearXNG license", "searxng agpl"),
        links = listOf(app.julz.chat.WebLink("https://docs.searxng.org/", "docs.searxng.org", "Welcome to SearXNG \u2014 SearXNG Documentation"),
            app.julz.chat.WebLink("https://github.com/searxng/searxng", "github.com", "searxng/searxng: SearXNG is a free internet metasearch engine which aggregates results from various search services and databases"),
            app.julz.chat.WebLink("https://en.wikipedia.org/wiki/Searx", "en.wikipedia.org", "")))

    @Composable
    private fun sheetBody(content: @Composable androidx.compose.foundation.layout.ColumnScope.() -> Unit) =
        androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().background(J.sheet).padding(J.gutter),
            verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(J.sp4), content = content)

    @Test fun sourcesLinks() = paparazzi.snapshot { sheetBody { SourcesBody(webAnswer, {}, {}) } }
    @Test fun sourcesNotes() = paparazzi.snapshot { sheetBody { SourcesBody(webAnswer.copy(links = emptyList(), searched = emptyList()), {}, {}) } }
}
