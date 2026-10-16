# julz systemd user units

| Unit | Job |
|---|---|
| `julz-approver.service` | Phone approver on 127.0.0.1:8765, sandboxed (empty home, only its own paths) |
| `julz-run.path` | A new file in `approved/` starts `julz-run.service` |
| `julz-run.timer` | Every 10 minutes, for an approval that landed during a run |
| `julz-run.service` | `julz-run.py --until-empty`, at most 90 minutes |
| `julz-notify-inbox.path` and `.service` | Inbox change, then "N specs waiting" (rate limited) |
| `julz-notify-log.path` and `.service` | New `runner.log` line, then a short notice |
| `julz-clean.timer` and `.service` | Daily, removes leftovers (julz-clean.py), sandboxed, no network |
| `julz-clean.path` | A change in `tasks/` runs the cleaner, so Delete on the phone acts within seconds |

To install, copy the units and enable them. They are copies, so a change in the repo does not
change a running unit by itself.

    cp systemd/julz-* ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now julz-approver.service julz-run.path julz-run.timer
    systemctl --user enable --now julz-notify-inbox.path julz-notify-log.path
    systemctl --user enable --now julz-clean.timer julz-clean.path

The phone reaches the approver through tailscale serve. That needs sudo once, outside systemd,
and tcp 8443 for the phone in the tailnet grant.

    sudo tailscale serve --bg --https=8443 http://127.0.0.1:8765

To check them, run `systemctl --user list-units 'julz*'` and
`journalctl --user -u julz-run.service`. `./julz-clean.py --dry-run` shows what the next
cleanup would remove. docs/UNINSTALL.md lists how to remove everything.
