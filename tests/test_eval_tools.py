"""Tests for eval-tools.py (158): the specs it builds must be the ones Open WebUI 0.11.4 builds,
the request the one its Legacy tool calling sends, and the pick read the way it reads it.
Nothing reaches Ollama and no tool runs: the tool file is a fake one in a temp folder."""
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

spec = importlib.util.spec_from_file_location("eval_tools", ROOT / "eval-tools.py")
ev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ev)
UPSTREAM_SHA256 = "1b2f5e07630f7786d65f6ba87a83eef40d62730af1d045a6f08e27ca167d4973"

FAKE = '''
import nothing_here_so_importing_this_file_would_fail

class Tools:
    class Valves:
        def ignored(self):
            pass

    def __init__(self):
        self.valves = None

    def _helper(self, x: str) -> str:
        """Private, never a tool."""

    async def zeta(self, query: str, days: int = 7, __event_call__=None) -> str:
        """
        Find things.
        :param query: words to look for,
            more words
        :param days: how far back
        :return: a list
        """

    async def alpha(self) -> str:
        """
        No arguments here.
        """

    async def beta(self, flag: bool = False, name: str = "") -> str:
        pass
'''


class SpecsTest(unittest.TestCase):
    def setUp(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        self.path = Path(d.name) / "fake.py"
        self.path.write_text(FAKE)
        self.specs = ev.tool_specs(self.path)

    def by_name(self):
        return {s["name"]: s for s in self.specs}

    def test_public_methods_in_dir_order(self):
        # dir() sorts, so Open WebUI lists a tool's functions alphabetically
        self.assertEqual([s["name"] for s in self.specs], ["alpha", "beta", "zeta"])

    def test_description_is_the_raw_docstring_up_to_param(self):
        d = self.by_name()["zeta"]["description"]
        self.assertEqual(d, "\n        Find things.\n        ")

    def test_no_docstring_gives_the_name(self):
        self.assertEqual(self.by_name()["beta"]["description"], "beta")

    def test_parameters_types_defaults_and_required(self):
        p = self.by_name()["zeta"]["parameters"]
        self.assertEqual(p, {
            "properties": {
                "query": {"description": "words to look for,\nmore words", "type": "string"},
                "days": {"default": 7, "description": "how far back", "type": "integer"},
            },
            "required": ["query"],
            "type": "object",
        })

    def test_no_required_key_when_every_argument_has_a_default(self):
        p = self.by_name()["beta"]["parameters"]
        self.assertNotIn("required", p)
        self.assertEqual(p["properties"]["flag"], {"default": False, "type": "boolean"})

    def test_no_arguments(self):
        self.assertEqual(self.by_name()["alpha"]["parameters"], {"properties": {}, "type": "object"})

    def test_underscore_arguments_are_dropped(self):
        self.assertNotIn("__event_call__", self.by_name()["zeta"]["parameters"]["properties"])

    def test_the_real_tools_build(self):
        names = [s["name"] for s in ev.all_specs()]
        self.assertIn("read_note", names)
        self.assertIn("delegate_to_claude", names)
        self.assertEqual(len(names), len(set(names)))


class PayloadTest(unittest.TestCase):
    SPECS = [{"name": "a", "description": "é", "parameters": {"properties": {}, "type": "object"}}]

    def test_system_is_the_template_with_compact_specs(self):
        body = ev.payload(self.SPECS, "read my dhcp note")
        system = body["messages"][0]
        self.assertEqual(system["role"], "system")
        self.assertTrue(system["content"].startswith(
            'Available Tools: [{"name":"a","description":"é","parameters":{"properties":{},"type":"object"}}]\n\n'))
        self.assertIn('"tool_calls": []', system["content"])
        self.assertNotIn("{{TOOLS}}", system["content"])

    def test_template_matches_0_11_4(self):
        # SHA-256 of DEFAULT_TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE in open_webui/config.py v0.11.4
        self.assertEqual(hashlib.sha256(ev.TEMPLATE.encode()).hexdigest(), UPSTREAM_SHA256)

    def test_user_is_the_query_alone_without_history(self):
        body = ev.payload(self.SPECS, "read my dhcp note")
        self.assertEqual(body["messages"][1], {"role": "user", "content": "Query: read my dhcp note"})
        self.assertEqual(len(body["messages"]), 2)
        self.assertIs(body["stream"], False)
        self.assertEqual(body["model"], ev.MODEL)

    def test_history_keeps_the_last_four(self):
        hist = [["user", "one"], ["assistant", "two"], ["user", "three"], ["assistant", "four"], ["user", "five"]]
        content = ev.payload(self.SPECS, "six", hist)["messages"][1]["content"]
        self.assertEqual(content, 'History:\nASSISTANT: """two"""\nUSER: """three"""\n'
                                  'ASSISTANT: """four"""\nUSER: """five"""\nQuery: six')


class PickedTest(unittest.TestCase):
    def test_tool_calls_list(self):
        out = 'Sure {"tool_calls": [{"name": "read_note", "parameters": {"path": "dhcp"}}]} done'
        self.assertEqual(ev.picked(out), [("read_note", {"path": "dhcp"})])

    def test_a_single_object(self):
        self.assertEqual(ev.picked('{"name": "due_notes", "parameters": {}}'), [("due_notes", {})])

    def test_empty_list_is_no_tool(self):
        self.assertEqual(ev.picked('{"tool_calls": []}'), [])

    def test_text_or_broken_json_is_no_tool(self):
        self.assertEqual(ev.picked("A /26 mask is 255.255.255.192."), [])
        self.assertEqual(ev.picked('{"tool_calls": [ '), [])

    def test_missing_parameters_are_empty(self):
        self.assertEqual(ev.picked('{"tool_calls": [{"name": "show_todos"}]}'), [("show_todos", {})])


class JudgeTest(unittest.TestCase):
    NAMES = {"read_note", "search_notes", "due_notes"}

    def test_right_tool_and_argument(self):
        case = {"q": "x", "tool": "read_note", "args": {"path": "dhcp"}}
        self.assertTrue(ev.judge(case, [("read_note", {"path": "Study/DHCP.md"})], self.NAMES))

    def test_argument_must_match(self):
        case = {"q": "x", "tool": "read_note", "args": {"path": "dhcp"}}
        self.assertFalse(ev.judge(case, [("read_note", {"path": "dns"})], self.NAMES))
        self.assertFalse(ev.judge(case, [("read_note", {})], self.NAMES))

    def test_wrong_tool_fails(self):
        case = {"q": "x", "tool": "read_note"}
        self.assertFalse(ev.judge(case, [("search_notes", {"query": "dhcp"})], self.NAMES))

    def test_unknown_names_are_skipped_as_open_webui_does(self):
        case = {"q": "x", "tool": "read_note"}
        self.assertTrue(ev.judge(case, [("open_note", {}), ("read_note", {})], self.NAMES))

    def test_the_first_known_call_counts(self):
        case = {"q": "x", "tool": "read_note"}
        self.assertFalse(ev.judge(case, [("search_notes", {}), ("read_note", {})], self.NAMES))

    def test_no_tool_expected(self):
        case = {"q": "x", "tool": None}
        self.assertTrue(ev.judge(case, [], self.NAMES))
        self.assertTrue(ev.judge(case, [("open_note", {})], self.NAMES))
        self.assertFalse(ev.judge(case, [("due_notes", {})], self.NAMES))

    def test_any_of_several_tools(self):
        case = {"q": "x", "tool": ["search_notes", "read_note"]}
        self.assertTrue(ev.judge(case, [("search_notes", {})], self.NAMES))


class CasesTest(unittest.TestCase):
    def test_cases_name_real_tools_and_arguments(self):
        specs = {s["name"]: s for s in ev.all_specs()}
        cases = json.loads((ROOT / "eval" / "tools.json").read_text())
        self.assertGreaterEqual(len(cases), 30)
        self.assertTrue(any(c["tool"] is None for c in cases))
        for c in cases:
            tools = c["tool"] if isinstance(c["tool"], list) else [c["tool"]] if c["tool"] else []
            for t in tools:
                self.assertIn(t, specs, c["q"])
                for a in c.get("args", {}):
                    self.assertIn(a, specs[t]["parameters"]["properties"], c["q"])


if __name__ == "__main__":
    unittest.main()
