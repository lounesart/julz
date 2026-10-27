# julz

A private AI assistant that runs on my own laptop. She is a study mentor who knows my notes,
does small jobs through tools I wrote myself, and can hand bigger coding tasks to Claude Code
behind a manual approval step. Everything runs locally on free software, and every limit is
enforced in code or by the operating system rather than by the prompt.

There is also an Android app, so I can talk to her, see my todos and notes, and approve her
work with my fingerprint from the phone. It reaches the laptop over a private network only.

## What is in here

| Part | Files |
|---|---|
| Models built from one personality prompt | `modelfiles/`, `build-models.sh` |
| Hardened launchers for Open WebUI, SearXNG and Speaches | `run-webui.sh`, `run-searxng.sh`, `run-speaches.sh` |
| Tools julz can call inside Open WebUI | `tools/julz_notes.py`, `tools/julz_pocket.py`, `tools/julz_delegate.py` |
| Filters for the reply language, done tasks and honest saves (a warning when she claims a change no tool made) | `functions/` |
| Approval gate and sandboxed runner for Claude Code | `julz_gate.py`, `julz-approve.py`, `julz-run.py`, `julz-clean.py` |
| Approver for the phone, signed with a passkey or the phone's own device key | `julz-approve-web.py`, `julz_webauthn.py`, `julz_devicekey.py`, `approver/` |
| The phone app, in Kotlin with Jetpack Compose | `android/` |
| Gateway between the app's chat and Open WebUI, with web search through my own SearXNG and the sources shown | `julz-chat.py` |
| Push notices to the phone from my own server | `julz-notify.py`, `julz-ntfy.py` |
| Encrypted drop box that julz can lock but not open | `pocket-keygen.py`, `pocket-open.py` |
| Notes vault in git, with the changes I confirmed applied by a unit | `julz_vault.py`, `julz-vault.py` |
| Her memory of my notes, kept in step with the vault | `sync-knowledge.py`, `julz-mem-sync.py`, `julz-keep.py`, `julz-keep-sync.py` |
| Evals for recall, formatting, honest tool replies, and web pages that try to give her orders | `eval-*.py`, `eval/` |
| systemd user units, each locked down on its own | `systemd/` |
| Deploy of a tested, tagged commit for the units, with rollback | `deploy.py` |
| Tests, about 1,650 in Python and 400 in the app | `tests/`, `android/app/src/test/` |

| Model | Base | Use |
|---|---|---|
| julz | qwen3.5:4b | everyday questions, fast, fits on the GPU |
| julz-pro | qwen3.5:9b | harder questions, slower, too big for a 6 GB GPU |
| julz-sec | qwen2.5-coder:7b | code and security review |

Every push runs the tests and a gitleaks scan of the whole history on GitHub Actions.

## Reading order

1. systemd/README.md for the units and how they are set up.
2. docs/TESTING.md for the checks that run before every merge and on the phone.
3. docs/design/README.md for the app's design system.
4. .github/SECURITY.md for how to report a security problem.
5. docs/UNINSTALL.md for removing it all again.

My plans, notes and the full threat model stay private.

## Running the tests

```
python3 -m unittest discover -s tests
```

The sandbox tests need `bwrap` and skip themselves without it, and the unit tests skip without
a systemd user session.
