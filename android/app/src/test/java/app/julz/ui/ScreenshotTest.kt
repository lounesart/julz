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
        Shell(wide = false, bar = { TabBar(section, 2, it, {}, {}, {}, {}, {}) }, content = content)

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
        InboxContent(inbox, null, mapOf("study" to 12, "daily" to 30), picked, {}, null, false, null,
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

    // Learning mode's chip in both composer layouts (135): left of send when roomy, above the box
    // when single line; on, the placeholder says she teaches
    @Composable
    private fun composer(roomy: Boolean, learn: Boolean, draft: String = "") =
        androidx.compose.foundation.layout.Column(androidx.compose.ui.Modifier.fillMaxSize().background(J.bg),
            verticalArrangement = androidx.compose.foundation.layout.Arrangement.Bottom) {
            Composer(draft, {}, busy = false, sending = false, focus = null, roomy = roomy, learn = learn,
                setLearn = {}, send = {}, stop = {})
        }

    @Test fun composerRoomy() = paparazzi.snapshot { composer(roomy = true, learn = false) }
    @Test fun composerRoomyLearn() = paparazzi.snapshot { composer(roomy = true, learn = true) }
    @Test fun composerLineLearn() = paparazzi.snapshot { composer(roomy = false, learn = true, draft = "What is a /26?") }

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
}
