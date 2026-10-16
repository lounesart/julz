# Julz handoff (2026-10-16, end of session 7)

## Goal
Julz is a private local AI assistant on my laptop: a study mentor that knows my notes, does
small jobs, and hands bigger tasks to Claude Code behind a human gate. Local first, zero budget,
every limit enforced in code or by the OS. Plan: PLAN.md. Threats: SECURITY.md (1 to 46).

## State (verified)
- Hub as before: `sudo ./run-webui.sh` (127.0.0.1:3100), SearXNG, Speaches, phone via tailscale.
- Phone approval works end to end, tested from the phone 2026-10-16: spec in `Inbox/claude/`,
  ntfy push, approver page (`https://<laptop>.<tailnet>.ts.net:8443`, serve to 127.0.0.1:8765),
  Approve + fingerprint, run starts by itself, push "run done". A blocked run ends with
  `need:`/`why:`; I sign "Done, continue" or "Stop task"; it continues in the same work copy.
  Real test: kernel version spec, need at step 2 and 3, task `done`, project untouched.
- systemd user units in `systemd/` (installed, enabled): approver, run path + timer, notify
  inbox + log, clean timer (daily). `systemctl --user list-units 'julz*'`.
- 299 tests pass. Each new module mutation tested (every check broken once, a test fails).
- Terminal approval `./julz-approve.py` still works next to the phone.

## Decisions
- Passkey (WebAuthn, python-fido2 from Arch extra), not a plain button or TOTP: the container
  runs on the host network and can reach the approver, so only a signature approves.
- Origin checked exactly, port included: fido2's default ignores the port, Open WebUI shares
  the host name on 443 (threat 33). Challenge = sha256(action, exact text) + nonce; the server
  builds the text from its own state, the page cannot choose it.
- One passkey (Google Password Manager, sends a real sign counter), enrolled with a one time
  code from the terminal, stored in `~/.config/julz/approver/`.
- ntfy.sh through the Play app; fixed templates only, never spec text or log reasons.
- Units are default deny: `TemporaryFileSystem=%h:ro` plus only needed paths. The runner is not
  systemd sandboxed (it builds bwrap itself). Cleaner has no network.
- No sudo for Claude. A need is done by me; Phase 2 adds only fixed root verbs, each signed.
- Task state lives on the host (`tasks/`), never in the report. Max 3 continuations, 24 h.

## In progress
- Stop button for a running spec: not started. The approver's sandbox blocks the user D-Bus
  on purpose, so it needs another way to reach `julz-run.service`.
- Still open from session 6: delegate tool shared to the phone account, julz answering in
  Polish over the API, 4B julz dropping "waits for your approval".

## Next steps
1. Stop button: a signed stop on the phone ends a running spec, log shows it, test proves it.
2. Typed answer from the phone: threat row in SECURITY.md first, then build.
3. Phase 2 verbs, one at a time with threat rows: query verbs, `restart-container`, then
   `install-package` (official repos only), `fetch-deps`, `new-project`, `publish`, `expose`.
4. APK with two isolated tabs (julz, approver), notes in Claude memory `phone-app-idea`.
5. Push the 5 local commits on main (ask first; never push `private-history`).

## Gotchas
- Unit tests passed, the phone failed: in a systemd sandbox each bound folder is its own mount,
  a link or rename across them fails (EXDEV). Temp files now sit in the folder they land in
  (`approved/.tmp/`, `tasks/`). `SandboxLayoutTest` runs code under systemd-run to catch it.
- `RuntimeMaxSec` does nothing for `Type=oneshot`; use `TimeoutStartSec` (default infinity).
- `tailscale serve` needs sudo. `--operator=$USER` avoided on purpose.
- A green test can pass for the wrong reason: mutation testing found 4 such tests this session.
- "Done, continue" is my claim, nothing checks it. Do the laptop step first, then tap.
- The notifier starts at the end of runner.log on its first run (no history pushes).
- Older: model id `julz:latest`; `claude setup-token` final token only; tests loading a module
  twice need `run.gate`; Open WebUI keeps an old tool copy until pasted again.

## How to resume
    cd ~/Projects/products/julz
    python3 -m unittest discover -s tests          # 299 tests OK
    systemctl --user list-units 'julz*'            # approver, paths, timers active
    ./julz-clean.py --dry-run                      # what the cleaner would remove
    tail ~/.local/share/julz/runner.log            # approvals, runs, needs
    claude
    > read HANDOFF.md and continue
