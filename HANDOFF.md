# Julz handoff (2026-10-16, end of session 7)

## Goal
Julz is a private local AI assistant on my laptop. It is a study mentor that knows my notes,
does small jobs, and hands bigger tasks to Claude Code behind a human gate. Local first, zero
budget, and every limit is enforced in code or by the OS. Plan in PLAN.md, threats 1 to 46 in
SECURITY.md.

## State (verified)
- The hub runs as before with `sudo ./run-webui.sh` (127.0.0.1:3100), plus SearXNG and Speaches.
- Phone approval works end to end, tested from the phone on 2026-10-16. A spec lands in
  `Inbox/claude/`, ntfy pushes a notice, and I open the approver at
  `https://<laptop>.<tailnet>.ts.net:8443` (tailscale serve to 127.0.0.1:8765). Approve and a
  fingerprint start the run, and a push says when it is done. A blocked run ends with `need:`
  and `why:`. I sign "Done, continue" or "Stop task", and the task carries on in the same work
  copy. The real test was a kernel version spec. It needed me at step 2 and 3 and ended `done`.
- From the phone I can also stop a running spec (stopped one second after the tap), then
  Continue it or Delete it. Delete removed the work copy within the same second. The page
  lists the last 5 runs and reloads itself every 5 seconds while open.
- The systemd user units in `systemd/` are installed and enabled. They are the approver, the
  run path and timer, the inbox and log notifiers, and the cleaner (daily, and on every change
  in `tasks/`).
- 335 tests pass. Every new module was mutation tested, so each check has a test that fails
  without it.
- The terminal tool `./julz-approve.py` still works next to the phone.

## Decisions
- Passkeys (WebAuthn with python-fido2 from Arch extra), not a plain button or TOTP. The
  container runs on the host network and can reach the approver, so only a signature approves.
- The origin is checked exactly, port included. fido2's default ignores the port, and Open
  WebUI uses the same host name on 443 (threat 33). The challenge is sha256 of the action and
  the exact text plus a nonce. The server builds that text, the page cannot choose it.
- One passkey in Google Password Manager. It sends a real sign counter. It was enrolled with a
  one time code from the terminal and lives in `~/.config/julz/approver/`.
- ntfy.sh through the Play app. Messages are fixed templates and never carry spec text.
- Units are default deny, an empty read only home plus only the paths they need. The runner
  has no systemd sandbox because it builds its own with bwrap. The cleaner has no network.
- No sudo for Claude. I do what a need asks. Phase 2 may add fixed root verbs, each signed.
- Task state lives on the host in `tasks/`, never in a report. At most 3 continuations, 24 h.
- Stop goes through a file, because the approver's sandbox blocks the user D-Bus. The runner
  polls `control/stop-<hash>` once a second and kills bwrap. A stopped run waits like a need.
- Delete only marks the task. The approver never gets access to `work/`. The sandboxed cleaner
  removes the copy, started by `julz-clean.path`.

## In progress
- Nothing half done. Phase 1 is complete.
- Still open from session 6. The delegate tool is not yet shared to the phone account, julz
  answers in Polish over the API, and 4B julz drops "waits for your approval".

## Next steps
1. Typed answer from the phone. Write its threat row in SECURITY.md first, then build it.
2. Continue a stopped run for real (the Continue button is tested only in code so far).
3. Phase 2 verbs, one at a time with threat rows. Query verbs and `restart-container` first,
   then `install-package` (official repos only), `fetch-deps`, `new-project`, `publish`, `expose`.
4. An APK with two isolated tabs for julz and the approver. Notes are in Claude memory
   `phone-app-idea`.

## Gotchas
- Unit tests passed and the phone still failed. In a systemd sandbox each bound folder is its
  own mount, and a link or rename across them fails with EXDEV. Temp files now sit in the
  folder they land in (`approved/.tmp/`, `tasks/`). `SandboxLayoutTest` runs code under
  systemd-run to catch this.
- `RuntimeMaxSec` does nothing for `Type=oneshot`. Use `TimeoutStartSec`, which defaults to
  infinity.
- `tailscale serve` needs sudo. I did not set `--operator=$USER`, on purpose.
- A green test can pass for the wrong reason. Mutation testing found five of them this
  session. A test of a limit must measure the limit, not only the result.
- A stopped run writes no `.stderr` file, so Claude's error output for that run is lost.
- Five Claude runs a day (UTC). Testing uses them up fast.
- "Done, continue" is my claim and nothing checks it. Do the laptop step first, then tap.
- On its first run the notifier starts at the end of `runner.log`, so old lines are not pushed.
- Older ones. The model id is `julz:latest`. Copy only the final `claude setup-token` token.
  Tests that load a module twice need `run.gate`. Open WebUI keeps an old tool copy until it
  is pasted again.

## How to resume
    cd ~/Projects/products/julz
    python3 -m unittest discover -s tests          # 335 tests OK
    systemctl --user list-units 'julz*'            # approver, paths, timers active
    ./julz-clean.py --dry-run                      # what the cleaner would remove
    tail ~/.local/share/julz/runner.log            # approvals, runs, needs
    claude
    > read HANDOFF.md and continue
