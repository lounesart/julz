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
| Filters that pick the reply language and spot done tasks in what I say | `functions/julz_language.py`, `functions/julz_tasks.py` |
| Approval gate and sandboxed runner for Claude Code | `julz_gate.py`, `julz-approve.py`, `julz-run.py` |
| Encrypted drop box that julz can lock but not open | `pocket-keygen.py`, `pocket-open.py` |
| Notes sync and a recall test over my own notes | `sync-knowledge.py`, `eval-recall.py`, `eval/` |
| Unit that applies the note changes I confirmed to julz and keeps the notes in git | `julz_vault.py`, `julz-vault.py`, `systemd/julz-vault.*` |
| Fuzzy note finder for the terminal | `tools/notes.fish` |
| Deploy of a tested, tagged commit for the units, with rollback | `deploy.py` |
| Attack tests, 697 of them | `tests/` |

| Model | Base | Use |
|---|---|---|
| julz | qwen3.5:4b | everyday questions, fast, fits on the GPU |
| julz-pro | qwen3.5:9b | harder questions, slower, too big for a 6 GB GPU |
| julz-sec | qwen2.5-coder:7b | code and security review |

## Reading order

1. systemd/README.md for the units and how they are set up.
2. docs/TESTING.md for the checks that run before every merge and on the phone.
3. .github/SECURITY.md for how to report a security problem.
4. docs/UNINSTALL.md for removing it all again.

My plans, notes and the full threat model stay private.

## Running the tests

```
python3 -m unittest discover -s tests
```

The sandbox tests need `bwrap` and skip themselves without it.
