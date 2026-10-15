# julz

A private AI assistant that runs on my own laptop. She is a study mentor who knows my notes,
does small jobs through tools I wrote myself, and can hand bigger coding tasks to Claude Code
behind a manual approval step. Everything runs locally on free software, and every limit is
enforced in code or by the operating system rather than by the prompt.

## What is in here

| Part | Files |
|---|---|
| Models built from one personality prompt | `modelfiles/`, `build-models.sh` |
| Hardened launchers for Open WebUI, SearXNG and Speaches | `run-webui.sh`, `run-searxng.sh`, `run-speaches.sh` |
| Tools julz can call inside Open WebUI | `tools/julz_notes.py`, `tools/julz_pocket.py`, `tools/julz_delegate.py` |
| Approval gate and sandboxed runner for Claude Code | `julz_gate.py`, `julz-approve.py`, `julz-run.py` |
| Encrypted drop box that julz can lock but not open | `pocket-keygen.py`, `pocket-open.py` |
| Notes sync and a recall test over my own notes | `sync-knowledge.py`, `eval-recall.py`, `eval/` |
| Attack tests, 131 of them | `tests/` |

| Model | Base | Use |
|---|---|---|
| julz | qwen3.5:4b | everyday questions, fast, fits on the GPU |
| julz-pro | qwen3.5:9b | harder questions, slower |
| julz-sec | qwen2.5-coder:7b | code and security review |

## Reading order

1. PLAN.md for what I set out to build and why.
2. SECURITY.md for the threat model and every check that was run.
3. docs/REPORT.md for the full story, problems and lessons.
4. docs/UNINSTALL.md for removing it all again.

## Running the tests

```
python3 -m unittest discover -s tests
```

The sandbox tests need `bwrap` and skip themselves without it.
