# Phone app design

How the Julz phone app looks, decided on 2026-10-16 from mockups. The mockups live in a
private canvas. The files here are their source and the shared sizes, so the Android build
can follow them.

`tokens.css` holds every size, colour and motion value the screens use. `mockups/` holds the
screens as they were drawn. They are reference, not app code, and they load the stylesheet
from the canvas, so they do not open on their own.

## Sizes

Text is in sp and space in dp, so the phone's font size scales everything.

- Text sizes are 14, 15, 17, 20, 24, 32 and 40. Body text is 17 and nothing is smaller than 14.
- Line heights sit on a 4 dp grid (44, 36, 32, 28, 24, 20, 16), so lines keep one rhythm
  across screens (TypeGridTest).
- The name of a thing I open or act on (a notice, a tool, a setting, a folder, a tile, a theme)
  is `J.item`, 17 at weight 600 everywhere; `itemUnread` (700) only means unread. Tasks and
  goals are content, body text, as lines in a note.
- Space goes in steps of 4, named by role in the Layout system below.
- Every tap target is at least 48. Main buttons are 56, list rows and tabs 64, small controls
  (`SmallPill`, the wheel) look 36.
- Corners are 12 for small things, 20 for rows and 28 for cards.

## Layout system

Set on 18 Oct 2026 (BACKLOG 22d, 22f), after every screen was walked at 100 and 200 percent text
and in landscape. A new screen uses these pieces, so it holds up at any text size without its
own fixes. They live in `Theme.kt` (tokens) and `Components.kt` (pieces).

- **Big text** is the app's text scale from 150 percent up (`J.big`: Android's font size times
  Julz's own). Then the spacing tightens a step, so the words get the room instead of margins.
- **Spacing by role**, not by size, as Carbon and Atlassian split it: `inset` inside a card
  (20, big 16), `gap` between cards (12, big 8), `rowGap` between rows of a list (8, big 4),
  `section` between groups (32, big 24), `gutter` at the screen's edge (20, big 16), `end` at a
  screen's end (112 clear of the bottom bar, 24 with the rail). The raw steps of 4 stay for
  fine work inside a component.
- **Size classes, not orientation**: Android's window size classes decide the frame. The tabs
  stand as a rail when the height is compact (under 480), not when the screen is merely wider
  than tall, so split screen keeps the bottom bar (`SizeClass`, worked out without a library).
- **ScreenHeader** is every screen's top: back, the title (32), a line under it, one action.
  Its buttons line up with the title's first line however many lines the words take. One
  title size on every screen.
- **A row of labels has one size**: tabs, the tab bar, a segmented control. The size is the one
  the widest label fits at (`rememberRowSize`), never under 11 as at 100 percent, never broken
  inside a word.
- **Buttons keep room around their words**: 12 above and below, a second line centred.
- **Text fields**: one line is a pill (28 corners) like a button beside it, more lines a card
  (20). The hairline when empty, the accent while typing (`fieldShape`, `fieldColors`).
- **Primary and secondary actions**: one big action per item (Tick, Approve), the rest small
  pills that look 36 tall and keep a 48 touch area (`SmallPill`), grouped by purpose under a
  small caption.
- **Two levels of picking**, as Material 3 splits primary and secondary tabs. The tabs
  (`Segmented`) pick a destination and sit in a glass track at 48. A filter or a view inside a
  destination is one level down, like h2 under h1: the wheel (`WheelPicker`) has no track, is
  `small` (36) tall like `SmallPill`, and shows the picked word under the same light in 14.
  It is a fixed row with ends, not a loop (iOS's picker, for what is
  not cyclic), so a word never stands twice. Past an end the strip pulls stiffer and springs
  back, a flick into an end bounces, and quiet ticks stand past each end so no side looks empty.
  A short flick steps one word. A count that only repeats another (Board's) is left off. The light is elastic: between two
  words its edge on the way runs ahead and the other catches up, a few percent thinner while
  stretched (squash and stretch), and a landing pick swells it for a moment with a springy settle;
  a plain slide when the phone asks for less motion. In the chat box
  it shows one word as tall as the send button, and a swipe up or down steps it.
- **Wheels sit under the thumb** (257, after iOS Photos): a list's filter wheel floats at the
  bottom, right over the tab bar, on the dark end of a fade as soft as the bar's own. The list's
  end clears it by its measured height and TalkBack still reads the filter first. A floating band
  pads by `barClear()`, and the design check holds every one to that.
- **Space counts what you see.** A touch area never adds visible space: Compose widens a small
  control to 48 by itself, so a 36 control takes 36 in the layout and the role gaps sit around
  its visible edge.
- **No size by eye.** A new size is a named token in `Theme.kt` with a line here. The design
  check counts sizes typed by hand per file; the old ones are a baseline that only shrinks.
- **At big text, stack instead of squeeze**: a side column (History's time, Tools' icon)
  moves above or steps aside so the main text keeps the width; a status pill goes under the
  name.
- **Landscape**: the tabs stand as a rail on the left, the Feed header is one line, and
  nothing goes under the system's buttons on either side.
- **Titles wrap between words, never inside one**: the longest word sets the title's size.
- **The window before the first frame** is the app's near black with the launcher icon, never
  the stock grey (the `Theme.Julz` splash).
- **Loud only for what needs me**: in lists of many notices (History) cards are one family of
  dark glass with a line and glow in their kind's colour; a warning or an approval is the same
  card, stronger: a brighter line, a wider glow, tinted glass (Von Restorff). One word per kind everywhere, the same as the Messages filters.
- **Spec lines** for data (`SpecLine`): the label muted, the value mono in the readable accent;
  a short value beside its label, a longer one under it. The laptop writes such facts as
  "Label: value", fixed words with numbers and times only (threat 122).
- **Colours by meaning**: `warn`, `good`, `info`, `caution` for states and the kinds built on them;
  `bar`, `sheet`, `scrim`, `lineStrong` for surfaces, `bar` and `sheet` from the theme's background;
  the glow ring and highlights from the accent. A screen never types a colour.
- **Words**: one vocabulary in the app and in the laptop's notices. A spec is what I approve,
  a task its whole life, a run one step of it; a refusal is always "<what> refused"; the
  short title drops "Julz:" and shows the id as a small code on its own line.
- **One of each**: `IconBadge` is the only icon in a circle (glass, a line and the icon in a
  colour), `Tag` the only status word, `kindCard` the only notice card (History and Details),
  `SpecLine` the only label and value. Lists of notices share one time column (`J.time`).
- **The design check** (`tests/test_design_lint.py`) fails the build when a screen types a
  colour, corner (also `CornerRadius` in draw code), font size, icon circle or a new size by hand; the
  few component internals it allows are named there with their reason.
- **Corners by role**: `rS` small, `rM` rows, `rL` cards, `pill` buttons, tabs and chips,
  `sheetTop` for sheets (`ShapeSet`). Round by default; Look and feel's Industrial cuts them,
  as on the spec sheet reference, and spaces the capitals of section titles. Bars, dots and
  round icons keep their shapes. A screen never types a corner by hand.
- **A long press names a tab**: its name large in a solid bubble over the tab for a moment,
  the large content viewer pattern, so a shrunk or hidden label never hides what it is.
- **Arrive assembled, never pop** (after Arwes): what comes with a screen, its cards and
  sheets, traces its frame in the accent and then shows its content, 450 ms on the HyDE curve,
  still when the phone asks for less motion. Once per session for a card with a key: coming back
  to a screen is not an arrival. Never on list rows while scrolling.
- **A setting that changes layout applies when let go**, never while dragging (the text size
  slider dropped the drag when the screen re-laid out under the finger).

## Look

- Surfaces are frosted glass, white at 4 percent with a 14 blur and a hairline border, over a
  soft magenta and cyan glow. The page is the accent's glow at the top right and the info cyan's from
  the left edge lower down (`PageGlow`, read from tokens.css by a test). A band that hides what
  scrolls under it draws the page where it sits (`pageBackdrop`), never a flat block, and a
  fade eases in (smoothstep), so no row edge floats alone in it. A list fades at its top too
  once it has moved. Reduce transparency in Accessibility turns them solid.
- At most one glowing button per screen, for the action that matters there.
- Motion uses the HyDE standard curve, cubic-bezier(0.05, 0.9, 0.1, 1.05), about 0.7 s.
  All of it stops when the phone asks for less motion.
- Text contrast is at least 4.5 to 1, and no state is shown by colour alone.
- Layouts reflow from 360 to 430 dp, in landscape and with text at 200 percent.

## Screens

Feed with Now, Messages and History. Notice details. Approve. Tools, which lists the
integrations. Settings, Look and feel, Accessibility. The lock screen.

## Security notes from the design

- A theme is data only. Colours, corners and a font picked from a fixed list, never code or
  web addresses, so a shared theme cannot run anything.
- Fonts ship inside the APK. The mockups load Google Fonts, the app will not, because that
  would tell Google each time the app opens.
- The Needs you tile on the feed is always first and cannot be hidden.
- The approver keeps its address bar visible, so I can check where the passkey prompt comes
  from.
- The note field on Approve is new input to Claude Code. It gets a threat row before it is
  built.
