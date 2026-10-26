"""functions/julz_saves.py: a reply that claims a change no tool made gets a warning line above
it (SECURITY.md 141). The filter never removes or rewrites her words."""
import copy
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("julz_saves", ROOT / "functions" / "julz_saves.py")
saves = importlib.util.module_from_spec(spec)
spec.loader.exec_module(saves)


def body(reply):
    return {"model": "julz:latest", "chat_id": "c1", "id": "m2",
            "messages": [{"id": "m1", "role": "user", "content": "create a to-do list: buy bread"},
                         {"id": "m2", "role": "assistant", "content": reply}]}


def tool(name, result, flag=True):
    """A Legacy tool result as 0.11.4 keeps it in metadata['sources']."""
    src = {"source": {"name": name}, "document": [result],
           "metadata": [{"source": name, "parameters": {}}]}
    if flag:
        src["tool_result"] = True
    return src


def meta(*sources):
    return {"chat_id": "c1", "message_id": "m2", "sources": list(sources)}


# What a write tool answers when the change went to the phone as a card (tools/julz_notes.py)
CARD = ("Not {} yet: this chat has no confirm button, so the change went to Approve on the user's "
        "phone as a card. Nothing changes until they sign it there. Tell the user exactly that; "
        "do not say it is done.")
CLAIM = "I've saved your tasks in Inbox/today.md:\n- [ ] buy bread"


class HonestSavesTest(unittest.TestCase):
    def setUp(self):
        self.f = saves.Filter()

    def reply(self, text, metadata):
        return self.f.outlet(body(text), __metadata__=metadata)["messages"][-1]["content"]

    def assert_warned(self, text, metadata):
        out = self.reply(text, metadata)
        self.assertTrue(out.startswith("> [!warning] Nothing was saved"), out)
        self.assertTrue(out.endswith("\n\n" + text), out)  # her words stay, whole
        return out

    def assert_carded(self, text, metadata):
        out = self.reply(text, metadata)
        self.assertTrue(out.startswith("> [!warning] Not saved yet"), out)
        self.assertNotIn("no note tool reported a change", out)
        self.assertTrue(out.endswith("\n\n" + text), out)
        return out

    def assert_kept(self, text, metadata):
        self.assertEqual(self.reply(text, metadata), text)

    # ----- warned -----

    def test_claim_with_no_tool_call(self):
        # items eval 24 Oct: "I've added your tasks to daily/todo.md", no call in the log
        self.assert_warned("I've added your tasks to **daily/todo.md**: buy bread.", meta())
        self.assert_warned(CLAIM, None)
        self.assert_warned(CLAIM, {})

    def test_claim_after_a_refusal(self):
        refused = tool("julz_notes/create_note", "Refused: a to-do list holds only tasks the user named")
        self.assert_warned("I created a to-do list in Inbox/trip.md with passport and ID.", meta(refused))
        no_dialog = tool("julz_notes/append_note", "Not saved: adding to dhcp.md was not confirmed."
                         " Nothing was changed: this chat has no confirm button")
        self.assert_warned("I added the line to your DHCP note.", meta(no_dialog))

    def test_claim_forms(self):
        for text in ("I saved the following tasks to your daily folder.",
                     "I created your to-do list in daily/todays-tasks.md with two items.",
                     "I have moved physio to daily.", "Your list is saved as Inbox/trip.md.",
                     "The note has been created.", "I just ticked buy milk.",
                     "I've updated the passage.", "I deleted the old note.",
                     "Done! I wrote it into your notes.",
                     # a denial counts only in its own clause
                     "I could not find your old list. I created a new one in daily.",
                     "No problem, I've saved it."):
            with self.subTest(text=text):
                self.assert_warned(text, meta())

    def test_claim_after_a_card_says_it_waits(self):
        # 241, 26 Oct: a real card (create_note_proposed), then "I saved the new test-cards list"
        for name, what in (("create_note", "saved"), ("append_note", "added"), ("edit_note", "changed"),
                           ("move_note", "moved"), ("delete_note", "deleted"), ("save_feedback", "saved")):
            with self.subTest(tool=name):
                self.assert_carded("I saved the new test-cards todo list in daily.",
                                   meta(tool(f"julz_notes/{name}", CARD.format(what))))

    def test_card_words_count_only_from_a_write_tool(self):
        # A note read aloud, a knowledge file or another tool may carry the card's words too
        for src in (tool("julz_notes/read_note", CARD.format("saved")),
                    tool("julz_notes/create_note", CARD.format("saved"), flag=False),
                    tool("other_tool/create_note", CARD.format("saved")),
                    tool("julz_notes/create_note", "Refused: " + CARD.format("saved"))):
            with self.subTest(src=src["source"]["name"]):
                self.assert_warned(CLAIM, meta(src))

    def test_a_save_and_a_card_in_one_turn_is_kept(self):
        saved = tool("julz_notes/append_note", "Added to the end of daily/week.md under a dated heading.")
        self.assert_kept(CLAIM, meta(tool("julz_notes/create_note", CARD.format("saved")), saved))

    def test_a_card_described_right_is_kept(self):
        card = meta(tool("julz_notes/append_note", CARD.format("added")))
        for text in ("Nothing is saved yet: the change waits on Approve on your phone.",
                     "It went to your phone as a card; sign it there and the line goes in."):
            with self.subTest(text=text):
                self.assert_kept(text, card)

    def test_a_read_result_cannot_fake_a_save(self):
        # A note opened with read_note may start with any words, planted ones too
        read = tool("julz_notes/read_note", "Saved Inbox/x.md as a new note")
        self.assert_warned(CLAIM, meta(read))

    def test_only_julz_notes_counts(self):
        self.assert_warned(CLAIM, meta(tool("other_tool/create_note", "Saved Inbox/x.md")))
        self.assert_warned(CLAIM, meta(tool("create_note", "Saved Inbox/x.md")))

    def test_a_knowledge_file_cannot_fake_a_save(self):
        # Retrieved notes sit in the same list without the tool_result flag
        self.assert_warned(CLAIM, meta(tool("julz_notes/create_note", "Saved Inbox/x.md", flag=False)))
        self.assert_warned(CLAIM, meta({"source": {"id": "kb"}, "document": ["Saved Inbox/x.md"]}))

    def test_odd_sources_do_not_break_it(self):
        odd = [None, "x", {"tool_result": True}, {"tool_result": True, "source": "julz_notes/create_note"},
               {"tool_result": True, "source": {"name": "julz_notes/create_note"}, "document": None},
               {"tool_result": True, "source": {"name": "julz_notes/create_note"}, "document": [None, 3]}]
        self.assert_warned(CLAIM, meta(*odd))
        self.assert_warned(CLAIM, {"sources": "Saved Inbox/x.md"})

    # ----- kept as it is -----

    def test_a_real_save_is_not_warned(self):
        for name, result in (
                ("create_note", "Saved Inbox/today.md as a new note, made just now; nothing was there before"),
                ("create_note", "Saved daily/t.md as a new note, in a few seconds; nothing was there before"),
                ("save_feedback", "Saved feedback/x.md. Claude Code reads it at the start of the next session."),
                ("append_note", "Added to the end of study/dhcp.md under a dated heading, in a few seconds."),
                ("edit_note", "Changed study/dhcp.md in a few seconds. Only that passage changed."),
                ("move_note", "Moved Inbox/physio.md to daily/physio.md, in a few seconds."),
                ("delete_note", "Deleted Inbox/x.md, in a few seconds. It can be restored from git on the laptop."),
                ("tick_task", "Ticked 'buy milk' in daily/week.md. When every task is ticked, the note moves"),
                ("tick_task", "Ticked: buy milk; walk 10k."),
                ("mark_reviewed", "Marked study/dhcp.md as reviewed today."),
                ("resolve_feedback", "Solved and moved to feedback/done: voice.")):
            with self.subTest(tool=name):
                refused = tool("julz_notes/create_note", "Refused: too many notes in the last minute.")
                self.assert_kept(CLAIM, meta(refused, tool(f"julz_notes/{name}", result)))

    def test_honest_replies_are_not_warned(self):
        for text in ("Nothing was saved: this chat has no confirm button.",
                     "Nothing was added because there is no confirmation button in this chat.",
                     "I cannot add that line; your DHCP note remains unchanged.",
                     "I didn't save anything because you didn't name the tasks.",
                     "Your note was not saved.", "I have not saved it yet.",
                     "I could not create the list.", "The note was never created.",
                     "Which tasks should I save?", "I will save it once you tell me the tasks.",
                     "Your DHCP lab note covers the DORA process."):
            with self.subTest(text=text):
                self.assert_kept(text, meta())

    def test_success_words_match_the_tool(self):
        # Reworded in julz_notes.py and every real save would be warned: keep them together
        src = (ROOT / "tools" / "julz_notes.py").read_text()
        for name, words in saves.WRITES.items():
            self.assertIn(f"async def {name}(", src)
            for w in words:
                with self.subTest(tool=name, words=w):
                    self.assertRegex(src, r'return \(?f?"' + w.replace("(", r"\("))

    def test_card_words_match_the_tool(self):
        src = (ROOT / "tools" / "julz_notes.py").read_text()
        self.assertIn('return f"Not {what}" + ON_THE_PHONE', src)
        self.assertIn('ON_THE_PHONE = ("' + saves.CARD, src)

    def test_warned_once(self):
        once = self.reply(CLAIM, meta())
        self.assertEqual(self.reply(once, meta()), once)
        card = meta(tool("julz_notes/create_note", CARD.format("saved")))
        once = self.reply(CLAIM, card)
        self.assertEqual(self.reply(once, card), once)

    def test_only_her_last_answer(self):
        b = body(CLAIM)
        b["messages"].append({"id": "m3", "role": "user", "content": "thanks"})
        self.assertEqual(self.f.outlet(copy.deepcopy(b), __metadata__=meta()), b)
        older = {"messages": [{"role": "assistant", "content": CLAIM},
                              {"role": "assistant", "content": "Your note covers DORA."}]}
        out = self.f.outlet(copy.deepcopy(older), __metadata__=meta())
        self.assertEqual(out["messages"][0]["content"], CLAIM)
        self.assertEqual(out["messages"][1]["content"], "Your note covers DORA.")

    def test_empty_or_odd_bodies(self):
        for b in ({}, {"messages": []}, {"messages": None}, {"messages": [None]},
                  {"messages": [{"role": "assistant", "content": None}]},
                  {"messages": [{"role": "assistant", "content": ["x"]}]}):
            with self.subTest(body=b):
                self.assertEqual(self.f.outlet(copy.deepcopy(b), __metadata__=None), b)


if __name__ == "__main__":
    unittest.main()
