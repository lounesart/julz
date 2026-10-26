package app.julz.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Shape
import androidx.compose.foundation.shape.CutCornerShape
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.layout.layout
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.julz.R
import app.julz.feed.Kind

/** The design system from docs/design/tokens.css. Sizes in sp follow the phone's font size. */
object J {
    // Live: the theme preset and accent from Look and feel
    val bg get() = Color(Look.prefs.preset.bg)
    // Live: Reduce transparency makes glass solid, High contrast brightens lines and grey text
    val surface get() = if (A11y.prefs.solid) Color(0xFF1C1820) else Color(0x0AFFFFFF)
    val raise = Color(0x14FFFFFF)
    val line get() = if (A11y.prefs.contrast) Color(0x99FFFFFF) else Color(0x1AFFFFFF)
    val text = Color(0xFFF5F2F4)
    val muted get() = if (A11y.prefs.contrast) Color(0xFFEEEEEE) else Color(0xFFABA4AC)
    val faint = Color(0xFF7E777F)
    val acc get() = Color(Look.prefs.accentColor)
    val accDeep get() = Color(Look.prefs.preset.deep)
    /** The accent for text: readable at 4.5:1 on every theme (22c); shapes and fills keep acc */
    /** Look and feel option: the selected item outlined in the accent instead of filled */
    val outline get() = Look.prefs.outline
    val accText get() = Color(Palette.readable(Look.prefs.accentColor, Look.prefs.preset.bg))
    /** Text on the accent: dark on a light accent, so it keeps 4.5:1 */
    val onAcc get() = if (Palette.isLight(Look.prefs.accentColor)) Color(0xFF09070A) else Color.White
    val onPastel = Color(0xFF120A10)

    // Semantic colours (22d integrity): what a colour means, in one place; the kinds and the
    // statuses take theirs from here, so a warning is the same red everywhere
    val warn = Color(0xFFFF8F80)
    val good = Color(0xFFC4F07A)
    val info = Color(0xFF7FE3F0)
    val caution = Color(0xFFF7D58B)
    /** A stronger hairline: plain buttons, the sheet's handle */
    val lineStrong = Color(0x33FFFFFF)
    /** The dimmed screen under a sheet */
    val scrim = Color(0xAA000000)
    /** The tab bar and rail over the page, from the theme's background (it was magenta's black on every theme) */
    val bar get() = bg.copy(alpha = 0.6f)
    /** A sheet: the theme's background, a step lighter (it was magenta's on every theme) */
    val sheet get() = androidx.compose.ui.graphics.lerp(bg, Color.White, 0.07f)
    /** Text on a pastel card, softer */
    val onPastelSoft = onPastel.copy(alpha = 0.8f)
    val onPastelFaint = onPastel.copy(alpha = 0.6f)

    fun tint(kind: Kind) = when (kind) {
        Kind.APPROVAL -> Color(0xFFFF7AB6)
        Kind.TODO -> caution
        Kind.INBOX -> Color(0xFFC9B8F0)
        Kind.RUN -> info
        Kind.REVIEW -> good
        Kind.CHANGE -> Color(0xFFB9B2BA)
        Kind.WARNING -> warn
    }

    /** Code colours (204), from the semantic hues: each at least 4.5:1 on the code box (raise) on
     *  every theme, PaletteTest. A comment and a prompt are grey, so the command stands out */
    fun code(t: app.julz.feed.Tok) = when (t) {
        app.julz.feed.Tok.KEYWORD -> tint(Kind.APPROVAL)
        app.julz.feed.Tok.STRING -> good
        app.julz.feed.Tok.NUMBER -> caution
        app.julz.feed.Tok.VARIABLE -> info
        app.julz.feed.Tok.COMMENT, app.julz.feed.Tok.PROMPT -> muted
        app.julz.feed.Tok.PLAIN -> text
    }

    // Spacing, steps of 4 (System board)
    val sp1: Dp = 4.dp; val sp2: Dp = 8.dp; val sp3: Dp = 12.dp; val sp4: Dp = 16.dp
    val sp5: Dp = 20.dp; val sp6: Dp = 24.dp; val sp8: Dp = 32.dp
    // Adaptive (22f): the text scale the app runs at (Android's times Julz's own), set by App.
    // From 150 percent the margins and card padding tighten a step, so words get the room
    var scale by androidx.compose.runtime.mutableFloatStateOf(1f)
    val big get() = scale >= 1.5f
    val gutter: Dp get() = if (big) 16.dp else 20.dp
    /** The HyDE standard curve from the desktop, as the design README says */
    val ease = androidx.compose.animation.core.CubicBezierEasing(0.05f, 0.9f, 0.1f, 1.05f)
    /** Set by App: the tabs stand as a rail (compact height, SizeClass) */
    var rail by androidx.compose.runtime.mutableStateOf(false)

    // Spacing by role, as Carbon and Atlassian split it (22f): inside a component, between them,
    // between groups, the screen's edge; each with its value at big text. Screens use these, not
    // the raw steps, so a change is one line
    /** Inside a card */
    val inset: Dp get() = if (big) sp4 else sp5
    /** Between cards on a screen */
    val gap: Dp get() = if (big) sp2 else sp3
    /** Between rows of a list (Messages, Tools) */
    val rowGap: Dp get() = if (big) sp1 else sp2
    /** Between rows inside a card: the title and what is under it (Todos, Goals, Done keep one rhythm) */
    val stack: Dp get() = if (big) sp2 else sp3
    /** Between groups of cards */
    val section: Dp get() = if (big) sp6 else sp8
    /** Room at a screen's end: clear of the bottom bar, or a little with the rail */
    /** Room the floating tab bar takes at the bottom (22i), measured by App; a list's end clears it */
    var barSpace by androidx.compose.runtime.mutableStateOf(112.dp)
    val end: Dp get() = if (rail) sp6 else barSpace + sp4
    val tap: Dp = 48.dp; val tapL: Dp = 56.dp; val row: Dp = 64.dp
    /** A secondary control's visible height (SmallPill, the wheel): one level under the tabs'
     *  [tap], as h2 under h1. Compose widens its touch area to 48 without a layout gap */
    val small: Dp = 36.dp
    /** An icon button's visible size, inside a [tap] target (Material 3: 40 in 48) */
    val iconButton: Dp = 40.dp
    // Corners by role (22b): round, or cut like a spec sheet with Look and feel's Industrial
    private val shapes get() = if (Look.prefs.industrial) ShapeSet.cut else ShapeSet.round
    val rS: Shape get() = shapes.small
    val rM: Shape get() = shapes.row
    val rL: Shape get() = shapes.card
    /** Buttons, tabs, chips, pills */
    val pill: Shape get() = shapes.pill
    val sheetTop: Shape get() = shapes.sheetTop

    private fun variable(res: Int, weight: Int) =
        Font(res, FontWeight(weight), variationSettings = FontVariation.Settings(FontVariation.weight(weight)))

    val display = FontFamily((400..800 step 100).map { variable(R.font.tektur, it) })
    val body = FontFamily((400..800 step 100).map { variable(R.font.plus_jakarta_sans, it) })
    val mono = FontFamily((400..800 step 100).map { variable(R.font.jetbrains_mono, it) })

    // Type scale: nothing under 14, body 17. Bold text adds weight to everything
    private fun w(base: Int) = FontWeight(if (A11y.prefs.bold) (base + 200).coerceAtMost(800) else base)
    val hero get() = TextStyle(fontFamily = display, fontWeight = w(500), fontSize = 40.sp, lineHeight = 44.sp, color = text)
    val tl get() = TextStyle(fontFamily = display, fontWeight = w(500), fontSize = 32.sp, lineHeight = 36.sp, color = text)
    val tm get() = TextStyle(fontFamily = display, fontWeight = w(500), fontSize = 24.sp, lineHeight = 32.sp, color = text)
    val ts get() = TextStyle(fontFamily = body, fontWeight = w(600), fontSize = 20.sp, lineHeight = 28.sp, color = text)
    val bodyText get() = TextStyle(fontFamily = body, fontWeight = w(400), fontSize = 17.sp, lineHeight = 24.sp, color = text)
    val sec get() = TextStyle(fontFamily = body, fontWeight = w(400), fontSize = 15.sp, lineHeight = 20.sp, color = muted)
    val cap get() = TextStyle(fontFamily = body, fontWeight = w(400), fontSize = 14.sp, lineHeight = 20.sp, color = muted)
    // Type on a 4 dp grid (22d): every line height a multiple of 4, so lines keep one rhythm
    /** The name of a thing I open or act on: a notice, a tool, a setting, a folder, a tile, a
     *  theme. One weight everywhere; heavier only to mean unread. Tasks and goals are content,
     *  body text, as lines in a note are */
    val item get() = TextStyle(fontFamily = body, fontWeight = w(600), fontSize = 17.sp, lineHeight = 24.sp, color = text)
    val itemUnread get() = item.copy(fontWeight = w(700))
    val cardTitle get() = item
    val cardText get() = sec
    /** A status tag's word */
    val tag get() = TextStyle(fontFamily = body, fontWeight = w(700), fontSize = 14.sp, lineHeight = 16.sp, color = text)
    /** A time in a list's time column */
    val time get() = TextStyle(fontFamily = display, fontWeight = w(400), fontSize = 15.sp, lineHeight = 20.sp, color = text)
    val monoCap get() = TextStyle(fontFamily = mono, fontWeight = w(400), fontSize = 14.sp, lineHeight = 20.sp, color = muted)

    val page get() = Brush.radialGradient(listOf(acc.copy(alpha = 0.2f), acc.copy(alpha = 0f)), radius = 1400f,
        center = androidx.compose.ui.geometry.Offset(1200f, 0f))
    val heroBrush get() = Brush.linearGradient(listOf(acc, accDeep, bg))
}

/** A stock component that needs more width than the gutters leave uses them too: Material's
 *  date picker wants 360 dp and a 375 dp phone with 20 dp gutters gives it 335 (22c). Its own
 *  edges keep its content off the screen's edge. */
fun Modifier.bleed(by: Dp) = this.layout { m, c ->
    if (!c.hasBoundedWidth) return@layout m.measure(c).let { p -> layout(p.width, p.height) { p.place(0, 0) } }
    val side = by.roundToPx()
    val p = m.measure(c.copy(minWidth = c.minWidth + 2 * side, maxWidth = c.maxWidth + 2 * side))
    layout(c.maxWidth, p.height) { p.place(-side, 0) }
}

/** Frosted glass, without the backdrop blur (the background is a still glow, see SECURITY 97). */
fun Modifier.glass(shape: Shape = J.rL, border: Color = J.line) =
    this.background(J.surface, shape).border(1.dp, border, shape)

/** Icons drawn from the mockups' own SVG paths, so no icon library is needed. */
object Icons {
    private fun icon(name: String, d: String, stroke: Float = 2f) = ImageVector.Builder(
        name = name, defaultWidth = 24.dp, defaultHeight = 24.dp, viewportWidth = 24f, viewportHeight = 24f,
    ).addPath(
        pathData = PathParser().parsePathString(d).toNodes(), fill = null,
        stroke = SolidColor(Color.White), strokeLineWidth = stroke,
        strokeLineCap = StrokeCap.Round, strokeLineJoin = StrokeJoin.Round,
    ).build()

    val feed = icon("feed", "M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z", 1.9f)
    val chat = icon("chat", "M4 5h16v11H9l-5 4z", 1.9f)
    val approve = icon("approve", "M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z M9 12l2 2 4-4", 1.9f)
    val links = icon("links", "M8 3v5 M16 3v5 M6 8h12v4a6 6 0 01-12 0z M12 18v3", 1.9f)
    val setup = icon("setup", "M12 15a3 3 0 100-6 3 3 0 000 6z M19 12a7 7 0 00-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 00-2-1.2L14 3h-4l-.5 2.6a7 7 0 00-2 1.2l-2.4-1-2 3.4 2 1.6a7 7 0 000 2.4l-2 1.6 2 3.4 2.4-1a7 7 0 002 1.2L10 21h4l.5-2.6a7 7 0 002-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2z", 1.9f)
    val back = icon("back", "M15 5l-7 7 7 7")
    val arrow = icon("arrow", "M5 12h14 M13 6l6 6-6 6", 2.4f)
    val check = icon("check", "M5 12l5 5L19 7", 2.4f)
    val reload = icon("reload", "M20 12a8 8 0 11-2.4-5.7 M20 4v6h-6")
    val feedback = icon("feedback", "M4 5h16v11H9l-5 4z M12 8v3 M12 13.5h.01", 1.9f)
    val bad = icon("bad", "M8 4h8.5l2.5 7v3h-5.5l.8 4.3c.2 1-.6 1.7-1.5 1.7L8 13z M8 4v9 M4 4h4v9H4z", 1.9f)
    /** The Integrations mockup's icons, by integration. */
    fun integration(id: String) = when (id) {
        "keep" -> icon("keep", "M4 4h12l4 4v12H4z M8 12h8 M8 16h5")
        "delegate" -> icon("delegate", "M4 5h16v14H4z M8 10l3 2-3 2 M13 15h3")
        "vault" -> icon("vault", "M5 4h11l3 3v13H5z M9 4v5h6V4")
        "push" -> icon("push", "M6 8a6 6 0 0112 0c0 7 3 9 3 9H3s3-2 3-9 M10 21h4")
        "voice" -> icon("voice", "M12 3a3 3 0 013 3v6a3 3 0 01-6 0V6a3 3 0 013-3z M5 11a7 7 0 0014 0 M12 18v3")
        "memlog" -> icon("memlog", "M4 19V5 M4 19h16 M8 15l4-4 3 3 5-6")
        "ci" -> icon("ci", "M6 3v12 M6 15a3 3 0 100 6 3 3 0 000-6z M18 9a3 3 0 100-6 3 3 0 000 6z M18 9c0 5-6 4-12 6")
        else -> links
    }
    // The native chat (26): send, stop, a new chat, my chats, copy
    val send = icon("send", "M4 12l16-8-6 16-3-7z M11 13l9-9", 1.9f)
    val stop = icon("stop", "M7 7h10v10H7z", 2.2f)
    val plus = icon("plus", "M12 5v14 M5 12h14", 2.2f)
    val chats = icon("chats", "M4 6h16 M4 12h16 M4 18h10", 2f)
    val copy = icon("copy", "M9 9h11v11H9z M5 15V4h11", 1.9f)
    val archive = icon("archive", "M4 4h16v5H4z M5 9v11h14V9 M10 13h4", 1.9f)
    val unarchive = icon("unarchive", "M4 4h16v5H4z M5 9v11h14V9 M12 18v-6 M9 15l3-3 3 3", 1.9f)
    val edit = icon("edit", "M4 20h4L19 9l-4-4L4 16z M13 7l4 4", 1.9f)
    val trash = icon("trash", "M4 7h16 M9 7V4h6v3 M6 7l1 13h10l1-13", 1.9f)
    // Callout kinds (26e), as Obsidian marks them
    val info = icon("info", "M12 21a9 9 0 100-18 9 9 0 000 18z M12 11v5 M12 8h.01", 1.9f)
    val alert = icon("alert", "M12 3l9.5 17h-19z M12 10v4 M12 17h.01", 1.9f)
    val question = icon("question", "M12 21a9 9 0 100-18 9 9 0 000 18z M9.5 9.5a2.5 2.5 0 114 2c-1 .7-1.5 1.2-1.5 2.5 M12 17h.01", 1.9f)
    val down = icon("down", "M6 9l6 6 6-6", 2.2f)
    val toEnd = icon("toEnd", "M12 5v14 M6 13l6 6 6-6", 2.2f)
    val folder = icon("folder", "M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2z")

    fun kind(kind: Kind) = when (kind) {
        Kind.APPROVAL -> approve
        Kind.TODO -> icon("todo", "M4 6h2 M4 12h2 M4 18h2 M9 6h11 M9 12h11 M9 18h7")
        Kind.INBOX -> icon("inbox", "M4 13l2-8h12l2 8 M4 13v6h16v-6 M4 13h5l1 2h4l1-2h5")
        Kind.RUN -> icon("run", "M4 5h16v14H4z M8 10l3 2-3 2 M13 15h3")
        Kind.REVIEW -> icon("review", "M12 21a9 9 0 100-18 9 9 0 000 18z M12 7v5l3 2")
        Kind.CHANGE -> icon("change", "M3 7h6l2 2h10v10H3z M10 14h6 M14 12l2 2-2 2")
        Kind.WARNING -> icon("warning", "M12 4l9 16H3z M12 10v4 M12 17h.01")
    }
}

/** The app's corners by role (22b): round by default; cut, as on the spec sheet reference, with
 *  Look and feel's Industrial. Bars, dots and round icons keep their own shapes. */
class ShapeSet(cut: Boolean) {
    val small: Shape = if (cut) CutCornerShape(6.dp) else RoundedCornerShape(12.dp)
    val row: Shape = if (cut) CutCornerShape(9.dp) else RoundedCornerShape(20.dp)
    val card: Shape = if (cut) CutCornerShape(14.dp) else RoundedCornerShape(28.dp)
    val pill: Shape = if (cut) CutCornerShape(10.dp) else RoundedCornerShape(50)
    val sheetTop: Shape = if (cut) CutCornerShape(topStart = 16.dp, topEnd = 16.dp) else RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp)

    companion object {
        val round = ShapeSet(false)
        val cut = ShapeSet(true)
    }
}

/** Room a screen leaves at its bottom for the floating tab bar (22i): its measured height, none
 *  with the rail. A screen that pins an area under its list pads by this, or the bar covers the
 *  area (126); a list's end uses J.end. The keyboard slides over the bar, so the chat pads by the
 *  larger of the two (127) */
fun barClear(): Dp = if (J.rail) 0.dp else J.barSpace
