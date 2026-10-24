"""The native chat screen keeps one state object per value for its whole life (BACKLOG 127).
State made with remember(chatId) is replaced when a new chat gets its id after the first send,
but Send, Stop and the menus can still hold a reference made before (strong skipping): their
writes then land in the old object and never reach the screen. Seen 19 Oct and again 24 Oct:
the second message sent (200) yet never showed, the third was refused as busy.
Run: python3 -m unittest discover -s tests -v"""
import re
import unittest
from pathlib import Path

CHAT = (Path(__file__).resolve().parent.parent / "android" / "app" / "src" / "main" / "java" / "app"
        / "julz" / "ui" / "NativeChat.kt")
KEYED_STATE = re.compile(r"remember\(\s*chatId\s*\)\s*\{\s*mutableStateOf")


def keyed_state(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if KEYED_STATE.search(line)]


class ChatStateLintTest(unittest.TestCase):
    def test_no_state_keyed_by_the_chat(self):
        self.assertEqual(keyed_state(CHAT.read_text()), [],
                         "\nKeep it in plain remember and clear it in LaunchedEffect(chatId)")

    def test_the_lint_catches_what_it_should(self):
        self.assertEqual(len(keyed_state("    var view by remember(chatId) { mutableStateOf<ChatView?>(null) }")), 1)
        self.assertEqual(keyed_state("    val openedAt = remember(chatId) { System.currentTimeMillis() }"), [])


if __name__ == "__main__":
    unittest.main()
