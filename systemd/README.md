# julz systemd user units

| Unit | Job |
|---|---|
| `julz-approver.service` | Phone approver on 127.0.0.1:8765, sandboxed (empty home, only its own paths) |
| `julz-chat.service` | Native chat gateway on 127.0.0.1:8766 (julz-chat.py), sandboxed, nothing writable |
| `julz-run.path` | A new file in `approved/` starts `julz-run.service` |
| `julz-run.timer` | Every 10 minutes, for an approval that landed during a run |
| `julz-run.service` | `julz-run.py --until-empty`, at most 90 minutes |
| `julz-notify-inbox.path` and `.service` | Inbox change, then "N specs waiting" (rate limited) |
| `julz-notify-log.path` and `.service` | New `runner.log` line, then a short notice |
| `julz-clean.timer` and `.service` | Daily, removes leftovers (julz-clean.py), sandboxed, no network |
| `julz-clean.path` | A change in `tasks/` runs the cleaner, so Delete on the phone acts within seconds |
| `julz-keep.path` and `.service` | A signed Keep copies Claude's checked notes into `julz-mem/Claude`, sandboxed, no network |
| `julz-keep.timer` | Every 10 minutes, for a Keep signed while a run held the gate lock |
| `julz-keep-sync.path`, `.service` and `.timer` | After a Keep, rebuild the julz-claude collection in Open WebUI; retried every 10 minutes |
| `julz-vault.path`, `.service` and `.timer` | Applies julz's confirmed note changes, commits the vault every 15 minutes, counts due notes |
| `julz-vault-refresh.path` and `.service` | A save in `Inbox/` or `daily/` rebuilds the phone's snapshots within seconds, vault read only, no commit |
| `julz-notify-notes.path` and `.service` | New notes in the snapshot, then "N new notes" in the Feed (counts only, once a minute at most) |
| `julz-notify-weekly.timer` and `.service` | Sundays 18:00, "N notes in Inbox" |
| `julz-notify-due.timer` and `.service` | Daily 19:00, "N notes due for review" when 3 or more |
| `julz-memlog.timer` and `.service` | Every 10 minutes, RAM per group to `~/.local/state/julz-memlog/rss.csv`; `julz-memlog.py --report` shows growth per hour |

Every unit runs `~/.local/lib/julz/current`, a release `deploy.py` exported from a tested
commit, never this working tree. Editing code here changes nothing live until a deploy.

    git tag v1.x && ./deploy.py    # main, clean, tagged; runs the suite in the export
    ./deploy.py --dev              # any branch, untagged, still clean and tested
    ./deploy.py --rollback         # the release before, one step
    ./deploy.py --status

A deploy copies the unit files and reloads systemd. A unit new to this machine still has to
be enabled once, and the deploy prints the line for it.

The first install by hand, before deploy.py existed, was: copy the units and enable them. Every folder a unit binds must exist first, or the unit stops
at start. These are the ones Keep added:

    mkdir -m 700 ~/.local/share/julz/manifests ~/.local/share/julz/keep ~/.local/share/julz/sync
    mkdir -m 755 ~/Documents/julz-mem/Claude
    cp systemd/julz-* ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now julz-approver.service julz-run.path julz-run.timer
    systemctl --user enable --now julz-notify-inbox.path julz-notify-log.path
    systemctl --user enable --now julz-clean.timer julz-clean.path
    systemctl --user enable --now julz-keep.path julz-keep.timer
    systemctl --user enable --now julz-keep-sync.path julz-keep-sync.timer

The phone reaches the approver through tailscale serve. That needs sudo once, outside systemd,
and tcp 8443 for the phone in the tailnet grant.

    sudo tailscale serve --bg --https=8443 http://127.0.0.1:8765

julz-ntfy is the push server for the phone app (threats 86, 87). The wrapper installs ntfy from
its release tarball only if both pinned hashes match, and setup writes the users and tokens to
600 files without printing a token. The state folder must exist before the first start.

    python3 -I ~/.local/lib/julz/current/julz-ntfy.py --install ntfy_2.29.0_linux_amd64.tar.gz
    python3 -I ~/.local/lib/julz/current/julz-ntfy.py --setup
    mkdir -m 700 ~/.local/share/julz-ntfy
    systemctl --user enable --now julz-ntfy.service

The phone reaches it through tailscale serve on 8444: sudo once, tcp 8444 for the phone in the
tailnet grant, and 8444 next to 8443 in nftables if the rule lists ports.

    sudo tailscale serve --bg --https=8444 http://127.0.0.1:8090

julz-vault keeps the notes vault in git and adds the lines julz asked for once I confirmed them
in the chat. Its state folder must exist before the first start.

    mkdir -m 700 ~/.local/share/julz/vault
    cp systemd/julz-vault.* ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now julz-vault.path julz-vault.timer

`git -C ~/Documents/julz-mem log` shows every change, mine and julz's apart.

A save in Inbox or daily shows on the phone within seconds, with a "N new notes" card (209).

    cp systemd/julz-vault-refresh.* systemd/julz-notify-notes.* ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now julz-vault-refresh.path julz-notify-notes.path

A push every Sunday at 18:00 says how many notes wait in Inbox (the count, never names).

    cp systemd/julz-notify-weekly.* ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now julz-notify-weekly.timer

A push every day at 19:00 when 3 or more study notes are due for review. julz-vault (no
network) writes the count, the push unit reads only that number, never a note.

    cp systemd/julz-notify-due.* ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now julz-notify-due.timer

ollama itself is a system service, so its limits are a drop-in installed with sudo once.
It keeps at most two models loaded (julz and the bge-m3 embedder, threat 144) and caps ollama's RAM at 7G, so a model too big for the
GPU gets killed instead of the desktop session.

    sudo mkdir -p /etc/systemd/system/ollama.service.d
    sudo cp systemd/ollama-limits.conf /etc/systemd/system/ollama.service.d/
    sudo systemctl daemon-reload
    sudo systemctl restart ollama

`systemctl show ollama -p MemoryMax` prints `MemoryMax=7516192768` when it is active, and
`-p MemorySwapMax` prints `MemorySwapMax=1073741824` (threat 145).

To check them, run `systemctl --user list-units 'julz*'` and
`journalctl --user -u julz-run.service`. `./julz-clean.py --dry-run` shows what the next
cleanup would remove. docs/UNINSTALL.md lists how to remove everything.

julz-chat, the native chat's gateway (SECURITY.md 136), once: its config, the tailnet port,
then the unit. It reads `chat.env` (user@'s key) and the phone's ntfy token, both mode 600.

    printf '{"origin": "https://<laptop>.<tailnet>.ts.net:8445", "port": 8766}\n' > ~/.config/julz/chat.json
    chmod 600 ~/.config/julz/chat.json
    tailscale serve --bg --https=8445 http://127.0.0.1:8766
    systemctl --user enable --now julz-chat.service
    ./contract-julz-chat.py    # after an Open WebUI upgrade too
