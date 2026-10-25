# Testing Julz

Two layers. The automated checks run before every merge; the phone checklist runs after a
deploy that touches the app, and in full before any release. A step that needs a fingerprint
is marked (finger): only I do those.

## Automated, before every merge

    cd ~/Projects/products/julz
    PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests     # all OK
    (cd android && ./gradlew --offline -q verifyPaparazziDebug; ./gradlew --stop)  # unit tests and screenshots
    ./deploy.py --dev && systemctl --user list-units 'julz*' --state=failed   # none

- Every security check gets a mutation run on a copy (CLAUDE.md): a control copy must pass
  first, then each break must fail a test. A survivor is a gap until it is explained.
- The Trojan Source test refuses hidden characters in code and tests.
- Screenshots (184): a screen that changes on purpose gets its golden recorded again with
  `./gradlew --offline recordPaparazziDebug`, and the new PNG is looked at before it is committed.
  A golden that changed without a reason is the regression the test is there for.

## Phone checklist

Debug build installed (`adb install -r android/app/build/outputs/apk/debug/app-debug.apk`).
Expected results in brackets.

### Feed
1. Open the app. [Header: Julz, live, Feedback alone on the right. Now shows "N unread · See
   them" while something is unread, This week, Todos open, the week bars, Inbox.]
1b. Swipe left and right (22c). [Now, Messages, History; the light in the tabs slides along
   with the finger. History's day pills and Messages' filter chips still scroll sideways
   first. With the phone's animations off, a tab tap jumps.]
1c. Messages, filter Approval, Read all. [Only approvals turn read; the other filters keep
   their unread.]
2. Let a notice arrive while the app is open. [It shows at once, no need to leave the screen.]
3. Messages: Clear, then Undo. History (22d): the strip reaches 30 days back, each day with
   its count and a dot when empty; pick a day. [One family of dark cards with a line and glow in the
   kind's colour, warnings and approvals stronger (brighter line, wider glow, tinted), the pill says the same word as the Messages filter; a
   time once per minute; one todo snapshot a day, +N earlier opens the rest. Look and feel's
   History as bright cards colours them all.]
4. Tap a notification from the tray, app closed, then again with the app open on another
   screen: an approval, a todo, an inbox, a run and a warning notice (13d, 133). [Approve, Todos,
   Inbox, Messages filtered to Runs, to Warnings, the chosen filter in view. Then open Julz from recent apps: it stays where I am, no jump back.]
5. Sort one Inbox note, go back to Now. [The Inbox card says the new count at once.]
6. On Messages, Inbox or Approve, let a notice for that screen arrive. [No tray entry or sound;
   the screen shows it at once.] Go home and let another notice arrive. [It rings, and the one
   already seen does not come back.] A warning still rings on Approve.

### Todos (113, 114)
1. Tick two done tasks (finger). [Bottom bar shows the exact text; after a few seconds both are
   under Done, the Left list shrinks.]
2. Done tab. [Today, Yesterday and dates, archived lists included.]

### Stages (127)
1. Left: tap the empty circle of a task, Start with fingerprint. [The circle turns half filled;
   the task sits under In progress; in Obsidian the line reads `- [/]`.]
2. Tick a task in progress (finger). [It goes to Done.] Pick a start and a tick together.
   [Picking one kind drops the other: one Apply is one kind.]
3. Board. [In progress, Planned, Done across every list, each task with its list name. The
   line with list, goals and hours sits under the task and Tick, at most two lines (22c).]
4. A goal linked to a task in progress. [Its bar does not move until the tick.]

### Goals (123, 124)
1. Add a goal to This week (finger). [It appears with an id, #goal/....]
2. Open the goal. [Tick alone beside it; under the bar Progress (+30m, +1h, +2h) and Plan (Due,
   Target, Estimate, Todos), small pills, Under if it can move (22d).] Plan: Target, 10, Set
   (finger). [The line shows (0/10) and a bar; Progress now starts with +1.]
3. Open it again, +1 (finger). [1 / 10.]
4. Open a goal, link an open todo (finger). [The bar shows 0 of 1 todos.] Tick that todo on
   Left (finger). [The goal's bar shows 1 of 1.]
5. Try a target on a counted goal. [Not offered.] Try a goal with a link in its words.
   [Refused before the fingerprint.]
6. Goal tree (125): open a week goal, Put under a year goal, +1 in the same Apply (finger).
   [The week goal shows "in <parent>"; the year goal shows "N% from 1 part", N its child's %.]
   Open the year goal. [It does not offer itself or its children as a parent.]
7. Milestones (126): open a goal, Plan: Due, pick a day (finger). [Past days greyed; seven even
   columns, Saturday not squeezed, also at 360 dp (22c); the bar line shows "Nd left"; a
   Milestones card on top lists it with its %.] Pick another day for it (finger). [The old
   date is replaced, not added.]
8. Hours (129): open a goal, Plan: Estimate 6, Set; Progress: +1h; Apply (finger). [The line in Obsidian
   gets `[est:: 6h] [spent:: 1h]`; the bar line shows 1/6h, its parent's adds it up.] +2h
   again (finger). [3/6h.] Try Estimate 1.1. [Set stays off.]
9. Unlink (128): open a goal, Plan: Todos. [Linked todos first with a check.] Tap one, Apply
   (finger). [Struck through while picked; after it the tag is gone from the line in Obsidian
   and the bar drops it.]

### Inbox and notes (116 to 119, 148)
1. Inbox: Move a note, choose a folder in the sheet (finger). [The note leaves the Inbox; Notes
   shows it in that folder.] Delete one (finger). [Gone; git has it.]
2. Browse all notes, open a note with a table and code. [Formatted; no image loads; a web link
   is not tappable; a [[wikilink]] to an existing note opens it.]
3. Open a long Cyrillic note, go back, open another. [Asking the laptop, then the text; the list
   comes back as it was. With the laptop off: the not reachable line in the note, not the list.]

### Feedback (120)
1. Feed, the feedback button, send an idea (finger). [Under Open as new; Claude sorts it next
   session and the state changes.] Try one with a link. [Refused before the fingerprint.]

### Approve (107 to 111, 121)
1. With a spec waiting: approve with a note (finger). [Runs; the report arrives.]
2. While a run is going: Stop the run (finger). At a question: Continue or answer (finger).
   After a run with notes: Keep with a topic (finger). [Each acts; the web page stays a fallback.]
3. With cards waiting, no "approver page" button. [It shows only as "N cards only on the
   approver page" when the app could not show one.] Notices say "Approve in Julz".
4. Approve or finish every card. [The Approve badge drops to nothing at once, and the Feed's
   waiting card clears.]
5. Keep: my earlier topics show as pills; tap one. [Its name fills the topic; a new one can
   still be typed.]
6. A question I cannot do from the phone: I did it, continue, and Claude asks the same again.
   [The task ends with "Claude asked the same thing again", no third run.]

### What I sign stays in view (219, 109)
1. Inbox: Delete on a note, Apply. [A screen of its own in the app's look (219b): the title
   "Change 1 note", "Your fingerprint signs this, nothing else.", a card with a short quiet
   hash (12 characters and …) and the delete line; nothing of the Inbox list; the fingerprint
   sheet below the card. The prompt says "Signs the text shown above".] Cancel. [Back on
   Inbox, the pick still there.]
2. Todos: tick a task with fingerprint; Goals: Apply. [Same: text at the top, sheet below.]
3. Chat: Save to notes on a long answer (more than a screen). [First a full screen to read,
   "Sign with fingerprint" and Cancel at the bottom; Sign brings the sheet with the start of the
   text above it.] Back on the read screen. [Cancelled, nothing saved.]
4. Feedback: send. Approve: a spec, then Stop the run. [Text at the top each time.]
5. Big text at the top and landscape: one Inbox delete each. [The text still clear of the sheet;
   if the sheet covers it, 219 is not done.]

### Tools and Settings (122)
1. Tools. [Each integration with its status; tap shows its facts as spec lines (22e): a
   short value beside its label in the accent, a longer one under it.]
2. Settings. [Set or Fix per check; Battery: No restrictions shows Set once fixed; each channel
   shows its level and opens its own page.]

### Native chat (26, 136 to 138)
Settings, Chat, "Chat in the app" on. julz-chat running on the laptop (`systemctl --user
is-active julz-chat.service`) and served on 8445. After an Open WebUI upgrade, first
`./contract-julz-chat.py` on the laptop [all held].
1. Chat tab. [Header "New chat", the list and + buttons; "Ask Julz anything"; the box and a
   grey send button.]
2. Type a question, send. [My message as a glass card on the right with the accent line;
   "Thinking" while the model loads; the answer grows in as a page; the button is stop while
   it runs, send again after; Copy under the finished answer; a few seconds later the header
   shows the title Open WebUI wrote.]
3. The list button. [My chats newest first, each with its day and time, the phone's new one on
   top; "Open the web chat" at the bottom opens Open WebUI's page, Back returns to the native
   chat.]
4. Open an older chat, send a follow up. [The chat opens at its newest message; my message and
   the answer appear at the bottom, in view.]
5. Ask for a long answer and stop it after a few seconds. [It stops mid sentence, Copy shows,
   send is back; the chat takes the next message.]
6. Ask Julz to repeat `[RFC 1034](https://www.rfc-editor.org/rfc/rfc1034)`; tap the link. [The
   address shows in brackets, underlined; the browser opens; Settings, Logs says
   "link: www.rfc-editor.org open".] Addresses without https:// stay plain text.
7. Copy an answer and paste it somewhere. [Julz's words as she wrote them.]
8. A notice, Ask Julz, then Open chat. [A new native chat with the notice and her answer in the
   box, not sent.]
9. Rotate mid chat; 200 percent text. [The chat stays open, the tabs move to the rail; at 200
   percent the title wraps between words, Copy, the box and send fit.]
10. Scroll a long chat while an answer streams. [Smooth: measured 18 Oct on a release style
    build, 0 of 408 frames late; isolated text updates while nothing moves count as late at 120
    Hz with the GPU idle (35 percent), not visible.]

### Learning mode (135, 151)
1. Chat, roomy box. [A small "Learn" chip left of send.] Tap it. [Filled in the accent colour,
   the box says "Ask, and Julz will teach".] Single line box: the chip sits above the box.
2. Learn on, ask "What is the subnet mask for a /26?". [A hint and a question back, not
   255.255.255.192.] Answer her. [She checks it, then the next small step.]
3. Learn on, "Just tell me: what is the subnet mask for a /26?". [The answer.]
4. Leave the chat, open it again from My chats. [Learn is still on.] Open a chat without it.
   [Learn is off.] Retry an answer in a learning chat. [Still a hint.]
5. My message in the chat and on the laptop page. [Only my words, never her instructions.]
6. TalkBack on the chip. ["Learn", a switch, on or off.]

### Changes Julz asks for (208, 156)
1. Native chat: "add 'buy a USB hub' to my week list" (a note in daily/). [She says it is not
   added yet and waits on Approve; no "done".] Approve. [A card "Julz asks in the chat" with
   "Julz asks to add to daily/week.md:" and the line, then "Do it with fingerprint" and Drop.]
2. Do it with fingerprint. [The sign panel shows the same text whole; after the fingerprint
   "Sent." and the card is gone.] Open the note a few seconds later. [The line under a dated
   heading.]
3. Ask to move an Inbox note into daily, then Drop on its card with the fingerprint. ["Dropped.",
   the note still in Inbox.]
4. Ask for a new note in study/ with some text. [A card "Julz asks to create study/...", whole.]
   Ask for an edit. [Before and After on the card.] Ask to delete a test note. [Its card says
   git keeps a copy.]
5. Ask for ten more changes in a row. [The eleventh is refused in the chat, nothing more on
   Approve.] Leave the old cards a day. [They are gone from Approve.]
6. Big text and landscape: the card text wraps, both buttons reachable.

### Goals from before (126b(3), 157)
1. Goals tab with an open goal in last week's note (goals/<last ISO week>.md). [Under the
   periods, a card "Still open from before": Last week, its words and bar, the hours if any.]
2. Tap the goal on that card. [Nothing opens, no tick, nothing joins Apply.]
3. Tick it in last week's note on the laptop, reload. [The card is gone.] No open past goals at
   all. [No card.]
4. Big text and landscape: the bar label and the period key stay on their lines.

### Code colours (204, 119)
1. Ask "show me how to list my firewall rules with nft, as a bash block". [Keywords pink,
   strings green, a # comment grey and slanted, $ prompts grey; bash and a "Linux, macOS" chip.]
2. Ask for the same in PowerShell. [A "Windows" chip, PS C:\> grey, $env:PATH cyan.]
3. Copy on a coloured block, paste it in the box. [Exactly the block, prompt included.]
4. A note in the notes browser with a ```python block. [Coloured the same way.] A block with no
   language or one not listed. [Plain, as before.]
5. A wide block scrolls sideways as before, the colours stay put.

### Native chat v2, release 1 (26b, 136, 139)
1. The box is one row with send inside it, the same gap above, right and below the button;
   on Industrial the box, the button and the header buttons all have cut corners.
2. My chats: swipe a chat. [It goes; "Archived ..." with Undo under the title for 5 s.] Undo.
   [Back in the list.] Archived chats row, swipe one back. [In My chats again.]
3. Hold a chat. [Delete "..."? with Delete for good and Cancel.] Delete a test chat. [Gone here
   and on the laptop page; "Deleted ..." under the title.]
4. Hold an answer. [Copy, Retry, Save to notes.] Retry. [A new answer; the laptop page still has
   the old one.] Hold my last message, Edit. [Its words in the box, the keyboard up, "Editing
   your message" with Cancel.] Send. [A new answer to the changed words.]
5. Save to notes (finger). [The exact text in the sheet, links written without https; after the
   fingerprint "Saved to Inbox"; the note in Inbox within a minute, `from: julz chat`.]
6. An answer with a code block. [Copy on the block copies only the code.]
7. TalkBack on My chats. [Each chat reads its name; Archive is in the actions.]
8. Pull any sheet down from its top. [It follows the finger and closes; a short pull springs back.]
9. Archived chats. [Its own icon, a dashed edge, muted titles.] Open one. [The header says
   "archived · writing brings it back".] Write in it. [It is back in My chats.]
10. Swipe a chat while Julz is still answering in it. ["Julz is still answering in that chat"
    in the sheet; the row comes back after a moment.]
11. Hold an older message of yours. [Copy, and Edit greyed with "Only your last message".]
12. Ask for a long answer; while Julz writes, scroll up a little. [What I read stays still; a
    solid "Julz is writing" button at the bottom; tapping it follows the answer again.]
13. Settings, Chat, Roomy message box. [On: the text over the whole width, send in a row
    under it. Off: one row with send inside. Both grow to six lines.]
14. "Count from 1 to 20000, one number per line, nothing else." [It fills the window: "This
    answer ran out of room." with Retry. An ordinary answer under it shows no line.]
15. A new chat. ["Ask Julz anything" in the display font, centred, four equal starts in a 2 by 2
    grid; a start fills the box and sends nothing.]
16. An answer with a table, a chart, a tip and a warning (after `./build-models.sh`, ask "Compare
    TCP and UDP" and "my scores: Network+ 80, Security+ 62, show them as a chart"). [Columns as
    wide as their cells, a fade when it scrolls; bars with values; a green tip, an amber warning.]
17. Scrolled up after an answer. [A small round arrow; while Julz writes, a "Julz is writing" pill.]
18. Send a message. [It rises into place; "Thinking" with a light sweeping through it in the accent
    and a breathing dot; it leaves when the first words come, never lying over them; Copy fades
    in when the answer is done. With animations off in Android's developer options, all still.]
19. Hold an answer, Bad answer (finger) (155, 153). [The sheet says "Keep as a bad answer" and
    shows mode, my question and her answer, links without https; after the fingerprint "Kept as
    a test case"; `./eval-promote.py` on the laptop lists it as new within a minute.] Hold an
    older answer. [The same; the sheet says `mode: unknown`.] Hold my own message. [No Bad
    answer row.]
19. Icon buttons: the header's, send and the jump arrow. [The same 40 dp shape, each easy to hit.]

### Tab bar (22i)
1. Any screen. [A glass capsule with margins, in the card shape (cut on Industrial); the active tab
   under the same light as Now, Messages, History; the others in readable grey.]
2. Switch tabs. [The light slides to the new tab; still when animations are off.]
3. Something waiting on Approve. [The badge in the theme's shape, a ring around it.]
4. Landscape. [The tabs as a glass column on the left, the same light.]
5. Chat in landscape, a new chat. [The title, one row of two starts, the box; nothing under it.]
6. Scroll a long list on Feed, Messages, Settings. [Cards slide under the bar and fade out above
   it; nothing shows through the bar; the end of each list clears it.]
7. Chat: tap the box. [The bar steps aside, the box sits on the keyboard, the header stays.]
8. Todos: pick a task; Inbox: pick Delete on the lowest note. [The fingerprint button and the
   lowest note's Move and Delete sit above the bar, whole (126).]

### Big text, landscape, TalkBack (22d)
1. Accessibility, Text size to the top. [Tab names, the Feed tabs and Feedback's kinds stay on
   one line, one size for the whole row, never broken inside a word; buttons keep room around
   their words; History's times whole; Tools'
   status under the name.]
2. Turn the phone sideways. [Tabs as a rail on the left, the Feed header on one line, nothing
   under the system's buttons.]
2b. Drag the text size slider from its thumb and let go. [It moves with the finger in 5 percent
   steps, the size applies on release; Reset to 100% shows when off 100 and puts it back.]
2c. At 200 percent: Tools, Feedback, Inbox, History (22f). [Header buttons level with the title,
   History's time above full width cards, Tools without the icon circles.]
2d. Long press a bottom tab, also with tab names off. [Its name large in a solid bubble over
   that tab, for a moment.]
2e. Open Julz, open Approve with a card waiting. [The cards trace in and then show; with the
   phone's animations off they just appear.]
3. TalkBack on Look and feel and Accessibility. [Each switch is one stop that says its name and
   on or off.]

### Integrity (22d)
1. Messages, History, a warning's Details. [The same badges, tags and card family; the short
   title without Julz:, the id as a small code; Details says Warning, not warnings.]
2. Industrial on: the Now, Messages, History switch while swiping. [The light is cut too.]
3. Spec sheet theme: the tab bar and a sheet (Move to). [Navy, not magenta's black.]
4. Any theme: Review and approve. [Its ring in the accent's colours.]

### Words and type (22d)
0. Look and feel, Show ids off. [No ids in Messages, History or Details; Approve still shows
   the spec id.] On again. [They are back.]
1. Messages: [The time alone at the right, the id on its own quiet line under the text; every
   title the same style, unread ones heavier.]
2. A refused tick, move or note: [The title says "tick refused", "move refused", "note refused".]
3. Notes, a note with a task in progress (- [/]) or a field ([est:: 2h]). [A half filled box; a
   quiet mono chip "est 2h".]

### Industrial (22b)
1. Look and feel, Industrial on, then the Spec sheet theme. [Cards, tabs, chips, pills, day
   pills and fields with cut corners, section titles in spaced capitals; navy with signal
   orange. Off: everything round again.]

### Coloured folders (22b)
1. Look and feel, Coloured folders on; Inbox, Move. [Each folder a line, tint and icon in its top
   folder's colour; Notes a dot in the same colour by each top folder. Off: all neutral.]

### Guides (22c)
1. Approve, Todos (Left and Goals), Inbox, Tools. [A dashed card under the title, at most
   three lines, Hide on its right.]
2. Hide on one of them, then visit the others. [No guide anywhere.]
3. Settings, Accessibility, Show guides. [They are back on every screen.]

### Back (22c)
1. Settings, Look and feel, then the Back gesture three times; again with the arrow on Look
   and feel. [Settings, Feed, then Android leaves the app; the arrow also lands on Settings.]
2. Approve, enroll this phone, Back. [Approve again, its tab lit; Settings stays unlit.]
3. Inbox, a folder in Notes, a note, Back three times. [Folder, Notes, Inbox, then Feed.]
4. Settings, Look and feel, tap the Settings tab. [Settings' own page.]
5. A notification tap while deep in Settings, then Back. [Its place, then Feed.]

### Endurance (BACKLOG 10)
1. Leave the phone overnight; in the morning `./julz-notify.py --test`. [It arrives within a
   minute.]
2. Reboot the laptop and wait without logging in. [The phone reconnects by itself.]
3. Reboot the phone. [Julz comes back without opening it.]
