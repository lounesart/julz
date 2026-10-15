# Julz handoff (2026-10-15, end of session 6)

## Goal
Julz is a private local AI assistant on my laptop: a study mentor that knows my notes, does
small jobs, and hands bigger tasks to Claude Code behind a human gate. Local first, zero
budget, every limit enforced in code or by the OS, never by the prompt. Plan: PLAN.md.
Threats: SECURITY.md. Full story: docs/REPORT.md. Removal list: docs/UNINSTALL.md.

## State (verified)
- Hub: Open WebUI v0.11.4 by digest, `sudo ./run-webui.sh`, 127.0.0.1:3100. SearXNG :8888,
  Speaches :8880. Phone over `tailscale serve`, separate non admin account.
- Delegation works end to end: julz calls `delegate_to_claude`, spec lands in
  `Inbox/claude/`, I approve with `./julz-approve.py`, `./julz-run.py` runs `claude -p` in
  bwrap on a copy of the project, report in `Outbox/`, julz summarizes it via `claude_status`.
- Hostile spec: Claude refused, nothing changed. Unapproved spec: never ran.
- 131 tests pass, every security check mutation tested (removing it fails a test).
- Delegate tool switched on in the laptop browser. Phone: needs the tool shared with group
  `phone` as read only (never write: tool code runs in the server).

## Decisions
- Approval is a host CLI that stores the exact bytes under their sha256, outside every
  container mount. Each spec runs once; it moves to `done/` before the run starts.
- Sandbox is bwrap (already installed): empty home, no /run, only the work copy writable.
- Claude gets `--tools Read,Edit,Write,Glob,Grep --restricted --permission-prompts none`.
  No Bash or fetch, so it has no egress of its own.
- Separate token from `claude setup-token`, in env only (argv is world readable).
- Work copy without `.git` (planted hooks would run on my host later). I merge by hand.
- `claude_status` carries the newest report: Legacy function calling allows one tool call
  per message. Legacy stays, it keeps built in fetch tools away from julz.
- Public repo with a fresh history; the full history lives only in local branch
  `private-history`, never pushed (it holds identifiers).

## In progress
- Phone: share Julz delegate with group `phone`, read only, then test from the phone.
- Julz answers in Polish to English questions over the API. Unknown cause.
- 4B julz drops "it waits for your approval" from her reply.

## Next steps
1. Phone delegation works: a spec from the phone lands in `Inbox/claude/`.
2. Hostile spec that looks harmless but needs Bash: log shows the tool denied.
3. Decide notes as a target: add a `julz-mem` copy to `projects.json`, test one spec.
4. Voice later (Chrome on phone, recordings cleanup, egress block for cloud AI APIs).

## Gotchas
- Model id over the API is `julz:latest`, not `julz`. Tool ids: `julz_delegate`, `julz_notes`.
- `claude setup-token`: copy the final `sk-ant-oat01-` token (about 108 chars), not the
  browser code. `read_token` now refuses anything else before a spec is spent.
- Tests that load a module twice get two exception classes: use `run.gate`.
- `script -qc` fakes a terminal: the isatty check in julz-approve is not a control.
- Launchers need sudo and read paths from `$SUDO_USER`'s home; plain `bash` stops early.
- Open WebUI keeps an old tool copy: after editing a tool, paste it again and save.
- Earlier gotchas (audio, title generation, tailscale ACL, AppArmor and docker exec) are in
  docs/REPORT.md.

## How to resume
    cd ~/Projects/products/julz
    python3 -m unittest discover -s tests     # 131 tests OK
    claude
    > read HANDOFF.md and continue
Hub: `sudo ./run-webui.sh`, then `sudo ./run-searxng.sh`, `sudo ./run-speaches.sh`.
Delegation: `./julz-approve.py`, then `./julz-run.py`.
