#!/usr/bin/env python3
"""Measure which tool Julz picks for a request (BACKLOG 158, PLAN: 27 of 30).

In Legacy tool calling, Open WebUI 0.11.4 picks the tool in a call of its own, before the
answer: a system message made of its default template with every tool's spec, then
"Query: <my words>" after at most four earlier messages. That system message takes the place
of the Modelfile's, so nothing in personality.txt reaches the pick; only the tools' names,
docstrings and arguments do. This script builds the same specs from tools/*.py (read with ast,
never imported, so no tool code runs), sends the same request to Ollama and reads the answer
the way Open WebUI does. No tool is ever called: the pick is the measure.

It skips Open WebUI, so it must copy what Open WebUI adds; checked on the admin pages 25 Oct:
Task Model and the tools prompt are default, the julz model's Advanced Params all Default but
think (Ollama) Off, sent here too. Check them again after an upgrade or a change there. Not
copied: a System Prompt on the julz model's page (Open WebUI would add it to this call too) and
my account's tool access.

Usage: ./eval-tools.py [--runs N] [--only WORD]   (julz:latest; pass mark 90% every run)
"""
import argparse
import ast
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TOOLS = ("julz_notes", "julz_pocket", "julz_delegate")  # julz-chat's tool_ids, in its order
MODEL = "julz:latest"
OLLAMA = "http://127.0.0.1:11434/api/chat"
CASES = ROOT / "eval" / "tools.json"
PASS_SHARE = 0.9  # PLAN's 27 of 30, kept as a share so cases can be added
# Tools that change something when picked, with no click or with one; the rest only read
WRITES = {"create_note", "append_note", "edit_note", "move_note", "delete_note", "tick_task",
          "mark_reviewed", "resolve_feedback", "save_feedback", "pocket_drop", "delegate_to_claude"}
READS = {"search_notes", "read_note", "list_notes", "due_notes", "show_folders", "recent_notes",
         "show_todos", "done_tasks", "show_feedback", "claude_status"}

# open_webui/config.py, DEFAULT_TOOLS_FUNCTION_CALLING_PROMPT_TEMPLATE, v0.11.4; its one trailing
# space is \x20 so an editor cannot strip it
TEMPLATE = """Available Tools: {{TOOLS}}

Your task is to choose and return the correct tool(s) from the list of available tools based on the query. Follow these guidelines:

- Return only the JSON object, without any additional text or explanation.

- If no tools match the query, return an empty array:\x20
   {
     "tool_calls": []
   }

- If one or more tools match the query, construct a JSON response containing a "tool_calls" array with objects that include:
   - "name": The tool's name.
   - "parameters": A dictionary of required parameters and their corresponding values.

The format for the JSON response is strictly:
{
  "tool_calls": [
    {"name": "toolName1", "parameters": {"key1": "value1"}},
    {"name": "toolName2", "parameters": {"key2": "value2"}}
  ]
}"""

JSON_TYPES = {"str": "string", "int": "integer", "bool": "boolean", "float": "number"}


def param_descriptions(doc):
    """open_webui/utils/tools.py parse_docstring: :param lines, continued on the next lines."""
    out, current = {}, None
    for line in (doc or "").splitlines():
        line = line.strip()
        m = re.match(r":param (\w+):\s*(.*)", line)
        if m:
            name, text = m.groups()
            current = None if name.startswith("__") else name
            if current:
                out[current] = text
            continue
        if line.startswith(":"):
            current = None
            continue
        if current and line:
            out[current] = "\n".join(filter(None, [out[current], line]))
    return out


def function_spec(fn):
    """One spec as pydantic, langchain's convert_to_openai_function and get_tools leave it."""
    doc = ast.get_docstring(fn, clean=False)
    described = param_descriptions(doc)
    args = fn.args.args[1:]  # self
    defaults = [None] * (len(args) - len(fn.args.defaults)) + fn.args.defaults
    props, required = {}, []
    for a, d in zip(args, defaults):
        if a.arg.startswith("__"):
            continue
        prop = {}
        if d is not None:
            value = ast.literal_eval(d)
            if value is not None:
                prop["default"] = value
        else:
            required.append(a.arg)
        if a.arg in described:
            prop["description"] = described[a.arg]
        hint = a.annotation.id if isinstance(a.annotation, ast.Name) else None
        prop["type"] = JSON_TYPES.get(hint, "string")
        props[a.arg] = prop
    params = {"properties": props, **({"required": required} if required else {}), "type": "object"}
    description = re.split(":(param|return)", doc, maxsplit=1)[0] if doc and doc.strip() else fn.name
    return {"name": fn.name, "description": description, "parameters": params}


def tool_specs(path):
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Tools")
    fns = [n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
           and not n.name.startswith("_")]
    return [function_spec(fn) for fn in sorted(fns, key=lambda f: f.name)]


def all_specs():
    return [s for t in TOOLS for s in tool_specs(ROOT / "tools" / f"{t}.py")]


def payload(specs, query, history=()):
    """middleware.py get_tools_function_calling_payload, history as [role, text] pairs."""
    system = TEMPLATE.replace("{{TOOLS}}", json.dumps(specs, ensure_ascii=False, separators=(",", ":")))
    recent = list(history)[-4:]
    past = "\n".join(f'{role.upper()}: """{text}"""' for role, text in recent)
    prompt = f"History:\n{past}\nQuery: {query}" if past else f"Query: {query}"
    # think off: the julz model's Advanced Params in Open WebUI, which routers/ollama.py applies
    # to the task call too (checked 25 Oct; everything else there is Default)
    return {"model": MODEL, "messages": [{"role": "system", "content": system},
                                         {"role": "user", "content": prompt}],
            "stream": False, "think": False}


def picked(content):
    """The calls Open WebUI would make from an answer: [(name, parameters)], [] for none."""
    content = content[content.find("{"):content.rfind("}") + 1]
    try:
        result = json.loads(content)
    except ValueError:
        return []
    if not isinstance(result, dict):
        return []
    calls = result["tool_calls"] if result.get("tool_calls") else [result] if "name" in result else []
    return [(c.get("name"), c.get("parameters") or {}) for c in calls if isinstance(c, dict)]


def first_pick(calls, names):
    """The first call to a tool that exists is the pick; an unknown name runs nothing."""
    return next(((n, p) for n, p in calls if n in names), None)


def wanted(case):
    want = case["tool"]
    return [] if want is None else want if isinstance(want, list) else [want]


def judge(case, calls, names):
    pick = first_pick(calls, names)
    if pick is None:
        return case["tool"] is None
    name, params = pick
    if name not in wanted(case):
        return False
    return all(re.search(rx, str(params.get(arg, "")), re.I) for arg, rx in case.get("args", {}).items())


def unasked_write(case, calls, names):
    """A pick that changes something the case did not ask for: the miss that costs me."""
    pick = first_pick(calls, names)
    return pick is not None and pick[0] in WRITES and pick[0] not in wanted(case)


def ask(body):
    req = urllib.request.Request(OLLAMA, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.load(r)["message"]["content"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", default="", help="cases whose request contains this word")
    ap.add_argument("--cases", type=Path, default=CASES,
                    help="another case file, such as my real chats kept outside the repo")
    a = ap.parse_args()
    specs = all_specs()
    names = {s["name"] for s in specs}
    cases = [c for c in json.loads(a.cases.read_text(encoding="utf-8")) if a.only.lower() in c["q"].lower()]
    print(f"{len(specs)} tools, {len(payload(specs, '')['messages'][0]['content'])} characters of specs and template")
    totals, writes = [], []
    for run in range(1, a.runs + 1):
        good = bad_writes = 0
        for i, c in enumerate(cases, 1):
            out = ask(payload(specs, c["q"], c.get("history", ())))
            calls = picked(out)
            ok = judge(c, calls, names)
            good += ok
            bad_writes += unasked_write(c, calls, names)
            if not ok:
                got = ", ".join(f"{n}({json.dumps(p, ensure_ascii=False)})" for n, p in calls) or "no tool"
                print(f"FAIL {run}.{i} want {c['tool']} got {got}: {c['q']}")
        totals.append(good)
        writes.append(bad_writes)
        print(f"run {run}: {good}/{len(cases)}, {bad_writes} unasked writes")
    mark = math.ceil(PASS_SHARE * len(cases))
    print(f"\n{' '.join(map(str, totals))} of {len(cases)} with {MODEL} (pass mark {mark} every run); "
          f"unasked writes {' '.join(map(str, writes))}")
    sys.exit(0 if all(t >= mark for t in totals) else 1)


if __name__ == "__main__":
    main()
