# Julz plan (2026-10-14)

## Summary
Julz is a private AI assistant that runs on my laptop. In v1 she is a study mentor who knows my
notes, can roast me, and takes small jobs like writing a note or locking a secret in my pocket.
She runs on local models through Ollama with Open WebUI as the hub, and my own small Python tools
give her hands. Nothing leaves the laptop and nothing costs money. When a job is too big for the
small models, Julz writes a spec note and I take it to Claude Code myself. Each release adds one
kind of risk at a time: v1 notes and actions, v2 web search, v3 more actions.

## Decisions

| Decision | Choice | Why |
|---|---|---|
| Daily job | Mentor + recall over my notes + roast + delegated small tasks | Real daily use, maps to A+/Net+/Sec+ study |
| Releases | v1 mentor, roast, recall, create_note, pocket_drop. Web search and phone pulled forward into v1 (2026-10-14) under the controls in the next rows. v3 more actions (project scaffolding), Claude spec handoff | Originally web input and actions were kept in separate releases (LLM01). Changed by choice: instead of keeping them apart, a hijacked model must not be able to do damage. Residual risk in SECURITY.md |
| Web search | Local SearXNG (pinned, 127.0.0.1:8888), turned on per chat by me | Free, no API key, no profile at a search company. Julz never searches on her own |
| Function calling | `julz` uses **Legacy** mode, not Native | In Native mode v0.11.4 gives the model built in `fetch_url` (a working exfil channel) and `search_chats`/`view_chat` (all my history). In Legacy, Open WebUI fetches search results itself and the model never picks a URL |
| SSRF | `ENABLE_LOCAL_WEB_FETCH=false` (default, set explicitly) | Fetched pages may not resolve to loopback, LAN or the lab net; checked at connect time and on every redirect (A10) |
| Memory poisoning | `Inbox/` is never synced into Knowledge | A note Julz wrote after reading a hostile page would otherwise become permanent memory (LLM04). I review Inbox notes and move them myself |
| Vault content | Nothing worth stealing in `julz-mem`: no passwords, keys or private data | Data minimization is the backstop when every other control fails |
| Notes vault | New Obsidian style vault at `~/Documents/julz-mem/` with `Inbox/` | No existing vault. Kept out of the code repo |
| What Julz reads | Allowlist only, starting with `julz-mem` | Least privilege. Denylists fail open |
| Private pocket | gocryptfs folder, encrypted data `~/.pocket.enc/`, unlocked view at `~/Private`, locked by default | Julz runs as my user, so only encryption is a real boundary |
| Pocket from phone or voice | Write only drop box. `pocket_drop` encrypts to a public key (JWE, X25519) into `~/.pocket-drop/`. No remote read | Julz can lock but never unlock. Private key stays with me |
| Pocket chats | Use Temporary Chat, not saved to history | The plaintext would otherwise sit in chat history |
| Credentials | KeePassXC, not the pocket | Right tool for passwords |
| Backbone | Open WebUI in Docker, image pinned to a version, plus my own Python tools | Mature, gives RAG, PWA and voice for free. I learn integration and hardening |
| Third party tools | No community Open WebUI tools or functions | They run arbitrary Python with server rights (LLM03, A08) |
| Sandbox | Docker mounts: vault read only, `Inbox/` and `~/.pocket-drop/` read write, private key and `~/Private` never mounted | The prompt is not a security boundary, mounts are |
| Action policy | New files freely. Overwrite or append to an existing note only after my confirmation, enforced in tool code. Every action written to `julz-actions.log` | Protects existing notes, gives accountability |
| Pulling notes | Two paths. Knowledge (RAG) for "what do I know about X", plus `search_notes` and `read_note` tools that read the live vault on request | RAG returns fragments and may miss new notes. Tools return whole, current notes |
| Path safety | Both tools reject `..` and absolute paths. `read_note` must resolve inside `julz-mem/`, `create_note` inside `Inbox/` | Path traversal, CWE-22, OWASP A01 |
| Container network | Host network, Open WebUI on `HOST=127.0.0.1`, reaches Ollama on 127.0.0.1:11434 | Simplest, no nftables forward rule. Mounts and dropped caps are the sandbox. See SECURITY.md |
| Access | Open WebUI stays bound to 127.0.0.1. Phone via `tailscale serve` (HTTPS) to 127.0.0.1:3100, Tailscale ACL lets only the phone in, nftables allows 443 on `tailscale0` only from the phone's 100.x IP | Two independent locks, and the hub never listens on another interface |
| Phone account | Separate non-admin user, may use only `julz`; shorter session (`JWT_EXPIRES_IN`) | A stolen unlocked phone does not give admin (least privilege) |
| Login | Admin account, then signup disabled, long password in KeePassXC | First user becomes admin, open signup is a takeover |
| Lost phone | Remove the device in the Tailscale admin console | Instant revocation |
| Budget | Zero. Everything free and open source | Hard constraint |
| Big tasks | Julz writes a spec note in `Inbox/`, I hand it to Claude Code manually. No API | Zero cost, data leaves only by my hand |
| Models | Existing `julz`, `julz-pro`, `julz-sec`. Embeddings model to be chosen at step 2 (ask before pulling) | Already built and tested |

## MVP scope (v1)

In:
- Chat with Julz in Open WebUI on the laptop (mentor, quiz, `/roast`)
- Recall over `julz-mem` with the source note cited
- On request, pull notes live from disk with my own read only tools: `search_notes` (title and
  text search) and `read_note` (whole note). Covers fresh notes the index has not seen yet
- `create_note` tool with path checks, overwrite confirmation, audit log
- `pocket_drop` tool with JWE encryption (X25519, A256GCM), used from Temporary Chat
- gocryptfs pocket at `~/Private`

Explicitly out:
- Native function calling, `fetch_url` and other built in tools for the model
- Voice (after phone)
- Project scaffolding, running commands, "create a tool" (v3 or the Claude Code handoff)
- Reading the pocket through Julz, ever
- Paid APIs and free hosted model tiers
- zarl (github.com/zarldev/zarl). Reference for ideas only (tool profiles, sensors). Not run on the host

## How we know v1 works
1. Recall eval set: 10 questions about my own notes with known answers. Pass is 8/10 or better,
   each answer cites its note. Rerun after any model or prompt change.
2. Mentor: quizzes me on one Network+ topic and catches one deliberately wrong answer.
3. Roast: `/roast` works and stays in character.
4. Security tests that must fail the attacker:
   - `create_note` with `../../.bashrc` is rejected
   - `read_note` with `../../.bashrc` or `/etc/passwd` is rejected
   - overwriting an existing note without confirmation is refused
   - a pocket drop file cannot be decrypted inside the container
   - Open WebUI is unreachable from another LAN device (`ss -tlnp` shows 127.0.0.1 only)
   - signup is disabled
5. Usage: I use Julz at least 5 days a week for 2 weeks. If not, the problem from Q1 was wrong.

## Risks and open questions
- "Analyse stuff" is undefined. Logs, PDFs, code or finances decide whether a local model fits.
- RAM: Open WebUI, embeddings and `julz-pro` together with the Kali VM may not fit in 15 GB.
  Default to `julz` (4b) and measure with `ollama ps` and `free -h`.
- Index freshness: as far as I know Open WebUI Knowledge stores uploaded copies and does not
  watch a folder. Verify at step 2. If true, re-sync after adding notes, and rely on
  `read_note` for anything new.
- Small models still hallucinate. Recall answers must cite the note; facts get checked with tldr/man.
- Docker networking: solved by host network, so no forward rule is needed. Check that
  `ss -tlnp` shows Open WebUI on 127.0.0.1 only, since host network binds directly on the host.
- Temporary Chat discipline for the pocket depends on me remembering. Check whether the tool
  can warn when called from a saved chat.
- Installs needed (ask first each time): Open WebUI image, embeddings model, python-joserfc (host, was age), gocryptfs, KeePassXC.
- Threat model done, see SECURITY.md. Its top 3 actions are part of steps 1 and 3.

## First 3 steps
1. Vault and hub. Create `~/Documents/julz-mem/Inbox/`, run Open WebUI in Docker (pinned image,
   127.0.0.1 only), create the admin, disable signup, connect to Ollama.
   Goal: chat with `julz` in the browser, `ss -tlnp` shows the port on 127.0.0.1 only, and a
   second signup attempt is refused.
2. Recall. Write 10 or more study notes into the vault, mount it read only, set up Knowledge with
   a local embeddings model, write the 10 question eval set.
   Goal: 8/10 correct with cited notes.
3. First hands. Write `search_notes`, `read_note` and `create_note` as my own Open WebUI tools
   with one shared path check, overwrite confirmation and `julz-actions.log`, plus pytest tests
   for the attack cases.
   Goal: "show me my note on nftables" returns the whole note, and `pytest` passes, including
   the `../../.bashrc` read and write tests and the unconfirmed overwrite test.

## Next steps (internet and phone, agreed 2026-10-14)
4. Internet. SearXNG container (`run-searxng.sh`), web search env in `run-webui.sh`, `julz` on
   Legacy function calling, `Inbox/` excluded from sync.
   Goal: `ss -tlnp` shows 8888 on 127.0.0.1 only; a search in a chat cites web results; asking
   for `http://127.0.0.1:11434` content is refused; notes tools still work in Legacy (dialog on
   overwrite); unit tests pass including the Inbox sync test; recall 8/10 or better.
5. KeePassXC open item (HANDOFF.md). Needed before phone, since the phone account needs a
   password I can actually retrieve.
6. Phone. Tailscale (ask before install), `tailscale serve`, ACL + nftables, non-admin account.
   Goal: the phone works; any other tailnet device and the LAN time out; CSP header present on
   the phone; phone account gets 403 on admin pages.

## Future: OSINT (noted 2026-10-15, not started)
Goal: Julz helps with OSINT (open source intelligence) for study and authorized work, maps to
the CPTS information gathering module.
Open questions to settle before building, with a threat model first:
- Scope: my own footprint, CTF/HTB targets, authorized engagements only. Passive sources
  (search, public records, DNS, certificate logs) on the host; anything active (scans, crawlers,
  username sweeps) lives in the Kali lab VM, never the host.
- Each new tool that fetches arbitrary URLs reopens the exfil channel closed by Legacy mode
  (LLM01, LLM06) and needs the same SSRF guard (A10). Prefer tools that call fixed APIs with
  fixed parameters over generic "fetch this URL".
- Results about people are personal data (GDPR in the EU). They must not land in `julz-mem`
  (vault stays nothing worth stealing) or in saved chats; decide where they live and for how long.
- People search (socials, usernames): targets come only from an allowlist file I write, enforced
  in the tool code: me, CTF/HTB personas, and engagement targets with a reference to the written
  authorization. Anyone not on the list is refused. No open "find anyone" search.
- Probably a separate model profile (e.g. julz-osint) with its own tools, not added to julz.

## Parsing and delegation: design rules (agreed 2026-10-15, not started)
Goal: julz gathers and parses documents, web pages and my commands, and can delegate tasks to
Claude Code (subscription, not API) and report back. Threat model before building.
Base rule: there is no clean input for an LLM. SQL injection is fixed by parameterized queries
(code and data in separate channels); an LLM reads instructions and data as one token stream,
so no filter makes input safe. Assume julz will be injected and make an injected julz harmless.
Layers, strongest first:
1. Reading is separate from acting (dual LLM pattern). Whatever reads untrusted input has no
   action tools and returns only structured data (fixed JSON fields, length limits). Plain code
   parses where it can, a model only where it must.
2. Taint tracking in tool code: once a chat has touched web or parsed content, action tools
   refuse or ask for approval. Enforced in Python, never in the prompt.
3. Least privilege tools: as now (notes only to Inbox, pocket write only, no shell).
4. Human gate for privileged actions. Delegation: julz writes a spec to `Inbox/claude/`, I
   approve by hand (e.g. move to `Approved/`), a runner starts a sandboxed `claude -p` only on
   approved specs (own project folder, tool allowlist, no `~/.ssh`, `~/Private`, vault or
   push), report lands in `Outbox/`, julz tells me.
5. Sanitizing, the WAF layer: strip hidden text, zero width characters, HTML comments and
   invisible CSS, log suspicious input. Weakest layer, never the main one.
6. Output and egress limits: CSP (done), tools that act make no outbound requests.
7. Logging: the action log records what ran.
Order: documents first, then web pages and data, then commands into actions (only after the
gate in layer 4 exists). Maps to OWASP LLM01, LLM05, LLM06; defence in depth (Security+).
