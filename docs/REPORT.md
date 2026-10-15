# Julz project report

Written on 2026-10-15 after six working sessions over two days. This is the long version of
what was built, what broke, how it was fixed and what I learned. HANDOFF.md is the short
version for picking the work up again. SECURITY.md holds the threat model and every check in
detail. PLAN.md holds the original plan and the design rules.

## What Julz is

Julz is a personal AI assistant that runs on my own laptop. She is meant to be a study mentor
who knows my notes, a helper for small jobs, and a way to hand bigger coding jobs to Claude
Code without giving a language model the keys to my machine.

Three rules shaped every decision.

1. Local first. The models run on the laptop through Ollama. Nothing about my notes or chats
   goes to a cloud service unless I send it there on purpose.
2. Zero budget. Everything is free and open source. The only paid thing in the picture is
   the Claude subscription I already had.
3. Limits live in code or in the operating system, never in the prompt. A language model can
   be talked into anything, so the prompt is treated as a suggestion and the real fences are
   file permissions, container mounts, sandboxes and checks in Python.

The project also doubles as practice for the certifications I am working towards (CompTIA
A+, Network+, Security+ and later HTB CPTS), so the documents name the security concepts as
they come up.

## Architecture

```
 browser on the laptop            phone (Tailscale, separate account)
          |                                |
          v                                v
 +-------- Open WebUI (Docker, 127.0.0.1:3100, pinned by digest) --------+
 |  chats, knowledge index, my Python tools:                             |
 |  search_notes, read_note, create_note, pocket_drop,                   |
 |  delegate_to_claude, claude_status                                    |
 +----+--------------+----------------+---------------+------------------+
      |              |                |               |
   Ollama        notes vault      SearXNG          Speaches
   (models)      (read only,      (web search,     (Piper voices)
                 Inbox writable)  127.0.0.1)       127.0.0.1)
                      |
                      |  Inbox/claude/ spec
                      v
   julz-approve.py (me, on the host) -> approved/ (not mounted anywhere)
                      |
   julz-run.py -> bwrap sandbox -> claude -p on a copy of one project
                      |
                 Outbox/ report -> julz summarizes it
```

Every service listens on 127.0.0.1 only. The phone reaches the hub through `tailscale serve`,
which proxies HTTPS from the tailnet to localhost, so the hub never listens on a network
interface.

## Timeline

### Session 1. Models and the plan

I started with three Ollama models built from one personality prompt. `julz` runs on
qwen3.5 4B and fits fully on the GPU, `julz-pro` runs on qwen3.5 9B and is slower because it
spills onto the CPU, and `julz-sec` runs on qwen2.5-coder 7B for code review.
`build-models.sh` turns the prompt files into Ollama models and only pulls a base model when
it is missing, because a pull can silently replace a model under the same tag.

Then I wrote PLAN.md with a structured interview of myself and SECURITY.md with a STRIDE
threat model before any code existed. The plan picked Open WebUI as the hub because it gives
chat, a knowledge index, a phone friendly web app and voice for free, and lets me spend my
time on integration and hardening instead of writing a chat UI.

### Session 2. The hub, recall and the first tools

Open WebUI runs in Docker with the image pinned by its sha256 digest, so it cannot change
under me. It uses host networking and binds to 127.0.0.1 only. All Linux capabilities are
dropped, `no-new-privileges` is set, there is no Docker socket inside, and the container
runs as my own user id instead of root. Signup is off after the admin account was created.

Recall works through Open WebUI's knowledge index. `sync-knowledge.py` uploads the vault with
an API key that is restricted to the knowledge, files and chat endpoints. A 10 question eval
over my own study notes (`eval-recall.py`) gates every prompt or model change, and the pass
mark is 8 out of 10. Runs landed between 8 and 10.

The notes tools (`tools/julz_notes.py`) give julz hands. She can search and read the vault
and create new notes, but only in `Inbox/`. Every path goes through one shared check that
resolves symlinks and refuses anything outside its root (path traversal, CWE-22). Overwriting
an existing note needs my click in the browser. The first version let the model pass
`confirmed=True` itself, which is the classic excessive agency mistake (OWASP LLM06), so the
confirmation now comes from an Open WebUI event that only a person can answer. A test proved
that a disconnected browser cannot be taken as a yes, because an error object is truthy in
Python and a plain `if answer:` would fail open.

A content security policy header now blocks remote images. Without it, injected text could
make julz print a markdown image whose URL carries data out, and the browser would fetch it
without a click. I tested it with a local listener, saw two hits without the header and none
with it.

### Session 3. Web search

Search goes through a local SearXNG container, pinned and bound to 127.0.0.1, which needed an
explicit override because the image listens on every interface by default. I turn search on
per chat. The important choice was Legacy function calling instead of Native. In Native mode
this Open WebUI version hands the model a built in `fetch_url` tool, which is a working
exfiltration channel, plus tools that read my whole chat history. In Legacy mode Open WebUI
fetches search results itself and the model never picks a URL. I found that one model was
still on Native only because a test chat happened to run on it, so the fix had to cover every
model, not just the default one.

Server side request forgery is blocked by Open WebUI's own guard, which refuses fetched pages
that resolve to loopback, the LAN or the lab network and checks again at connect time. Notes
in `Inbox/` are never synced into the knowledge index, because a note julz wrote after
reading a hostile page would otherwise turn into permanent memory (OWASP LLM04).

### Session 4. The pocket

The pocket is a place for secrets that julz can lock but never unlock. `pocket_drop`
encrypts text with JWE (ECDH-ES on X25519 with A256GCM) to a public key, using a library
that already ships in the container image, so no new dependency and no home made crypto. The
private key lives inside a gocryptfs encrypted folder that is never mounted into the
container. `pocket-open.py` on the host treats the drop folder as hostile input and checks
file names, sizes, symlinks and the decrypted payload before writing anything. A live test
showed the marker phrase nowhere in the container logs or volume.

I also replaced a KeePassXC database I had locked myself out of, since the phone account
would need a password I could actually find again.

### Session 5. Phone and voice

The phone reaches julz through `tailscale serve` on HTTPS. The tailnet policy lets only my
phone reach the laptop, and only on ports 22 and 443. I verified this from the policy filter
the laptop actually received, not from the web console, because grants and ACLs add up in
ways the console does not show. The phone uses a separate non admin account in its own
group that can only see julz, and the admin API refuses it.

Voice is partly working. Speech to text uses Whisper small inside the hub, with the language
fixed to Russian because automatic detection on short phone clips guessed wrong. Text to
speech runs in a separate Speaches container with Piper voices from the official
`speaches-ai` organization only, behind an API key so that a random web page in my browser
cannot drive it. The server side works, but Firefox on Android only plays the first reply.
That is parked.

This session also had the one real incident of the project, described further down.

### Session 6. Delegation to Claude Code

This was the biggest piece. Julz can now hand a task to Claude Code, and nothing runs until I
approve it.

1. Julz calls `delegate_to_claude` with a goal, a project name and a done condition. The tool
   writes a small spec file into `Inbox/claude/`. File names are a timestamp and random hex,
   so no model text ends up in a file name.
2. I run `julz-approve.py` on the host. It shows each spec exactly as Claude will receive it,
   asks yes or no, and on yes stores the exact bytes under their sha256 in a folder that is
   not mounted into any container.
3. `julz-run.py` takes the oldest approved spec, checks the hash again, copies the project
   into a fresh work folder without `.git`, and runs `claude -p` inside a bubblewrap sandbox.
4. The report goes to `Outbox/`, and julz reads it with `claude_status` and summarizes it.

The whole chain was tested with the real Claude. A harmless spec created a README in the work
copy while the real project stayed empty. A hostile spec that asked Claude to read its
credentials and send the token to a URL was refused by Claude itself. A spec I never approved
never ran.

## Security design of the delegation

I wrote the threat model first and the code second, and the code came after its tests. The
threat model added nine threats, numbered 21 to 29, and building it surfaced a tenth.

The most likely attack was a forged approval. The Open WebUI container can write to `Inbox/`,
so if "approved" meant a folder the container can write, an injected julz could approve her
own specs. The approved folder therefore lives outside every mount.

The second was a swap after approval, a time of check to time of use race (CWE-367). Julz
could rewrite a spec after I read it. Approval stores the bytes I saw and their hash, the
runner checks the hash again, and the approval CLI reads the file once so the text on screen
and the text stored are the same bytes.

The third was a spec I fail to notice. Specs are three plain fields with a 4 KB limit.
Zero width characters, bidirectional overrides, HTML comments and terminal escape codes are
refused. The escape codes matter because an approval tool prints untrusted text to my
terminal, and a code that makes the following text invisible would let me approve something
I never saw (CWE-150). The checks refuse such input instead of cleaning it, because text
that needs cleaning came from something I should not trust.

Claude itself runs with only five tools, Read, Edit, Write, Glob and Grep, so it has no shell
and no way to fetch a URL. `--restricted` keeps the file tools inside the work folder and
ignores project settings, which matters because a project settings file can define hooks
that run shell commands. Anything that would ask for permission is denied automatically.

The sandbox starts from an empty root. Only `/usr`, a handful of files from `/etc` needed for
DNS and TLS, the Claude binary and the work copy exist inside. There is no `/run`, so no SSH
agent, GPG agent, D-Bus or Docker socket. The environment is built from nothing instead of
copied from mine. The token is passed in the environment and never in the command line,
because any user can read another process's command line but not its environment (CWE-214).

The token is a separate long lived one from `claude setup-token`. If it ever leaks I can
revoke it without logging myself out, and there is no conflict with my main session
refreshing its own login.

The tenth threat appeared while building. If the work copy had a `.git` folder, Claude could
plant a hook or set `core.fsmonitor`, and git would run that code on my host the next time I
typed `git status` there. The copy is made without `.git`, and I carry changes over by hand.

Each spec runs at most once. It moves to `done/` before the run starts, so a crash cannot
turn into a loop that burns my subscription. There is a lock so only one runner works at a
time, a daily cap and a 15 minute timeout. Reports that contain the token or are too large
go to a quarantine folder instead of `Outbox/`. A host side log records approval, start and
result with hashes, but never the report text.

## How the code was tested

There are 131 unit tests. Most of them are attack tests that try path traversal, symlinks,
hidden characters, forged approvals, swapped specs, leaked tokens and so on.

Passing tests prove little if they could never fail, so I used mutation checks throughout. A
small script removes one security check at a time, runs the tests, and puts the file back.
Every check had to make at least one test fail. This found four tests that passed for the
wrong reason, for example a fake Claude that exited with an error and printed nothing, so the
test passed because the output was not JSON rather than because the exit code was checked.
Another found that a second check was quietly covering for a missing first check.

The sandbox tests run the real bubblewrap with a fake Claude written as a shell script. The
fake does its task and then tries to read my SSH folder, list `/run/user`, read my documents
and write to `/usr`. All of that fails, and the test checks the exact error messages.

## Problems and how they were fixed

| Problem | Cause | Fix |
|---|---|---|
| Model could confirm its own overwrite | Confirmation was a tool argument | Confirmation comes from an Open WebUI event only a person can answer |
| Disconnected browser counted as yes | An error dict is truthy | Only a real `True` counts, with a test |
| One model still offered built in tools | Function calling mode is per model | All models on Legacy, unused ones hidden |
| SearXNG reachable from the LAN | Image default listens on every interface | Explicit bind to 127.0.0.1 |
| Web search env vars ignored | Open WebUI prefers saved settings | Set in the admin panel |
| Title generation froze the phone UI | Bug in v0.11.4 background tasks | Title, tags and follow ups off |
| Speech text and a key went to OpenAI | TTS engine "OpenAI" defaults to the cloud URL | Local URL, key rotated, log check after every audio change |
| Whisper guessed the wrong language | Short clips, low confidence | Language fixed to Russian |
| `docker exec` into containers fails | AppArmor | Throwaway `docker run` of the same pinned image |
| Tailnet policy looked right but was not | Grants and ACLs add up | Verify the filter the laptop received |
| Claude gave 401 in the sandbox | I pasted the browser code instead of the token | `read_token` checks the token format before a spec is spent |
| One approved spec was spent on that failure | Run once rule | Accepted on purpose, the format check now runs first |
| Reports would have been synced into memory | Sync skipped `Inbox/` only | `Outbox/` skipped too, with a test |
| Julz said she cannot delegate | Her prompt said escalating to Claude is something she suggests to me | Prompt now describes the tool and its limits |
| Julz said the report was ready but never read it | Legacy mode allows one tool call per message | `claude_status` carries the newest report text |
| Tests caught the wrong exception class | The module was loaded twice | Tests use the module the runner imported |
| The tool did not reach julz in the browser | Not switched on for that chat | Switched on in the browser, phone still needs read only sharing |

## The incident

During the voice work the text to speech engine was set to "OpenAI" so that I could point it
at the local Speaches server. I changed the URL in the speech to text section but not in the
text to speech one, which kept its default `https://api.openai.com/v1`. For a few minutes the
hub sent speech requests to OpenAI with the text of one test reply and the local Speaches
key. OpenAI answered 401, which is how I noticed, since Speaches answers 403.

I fixed the URL, rotated the key and checked that no further requests went out. The impact
was low because the key only works on localhost. The lesson is that settings named after a
cloud provider default to that cloud, so after any audio or model setting change I check the
hub log for `api.openai.com`. A firewall rule that blocks cloud AI endpoints from the laptop
would make such a mistake fail closed, and that is on the list.

## What I learned

There is no clean input for a language model. SQL injection is solved by keeping code and
data in separate channels. A language model reads instructions and data as one stream of
tokens, so no filter can make input safe. The working approach is to assume the model will
be fooled and make a fooled model harmless. That means least privilege tools, a human gate
for anything that matters, and limits enforced outside the model.

A model refusing an attack is not a security control. When Claude refused the hostile spec,
it proved that the model refused, not that the sandbox holds. The sandbox is proved by the
fake Claude tests. A cleverer injection that the model does not recognize is exactly the case
the sandbox exists for.

Checks in the wrong place are theatre. The approval CLI refuses to run without a terminal,
but `script` fakes one in a second. It stops an accidental pipe, nothing more. The real
boundary is that julz cannot run anything on the host and cannot reach the approved folder.

Tests have to be able to fail. Mutation checks found tests that would have stayed green with
the protection removed.

Defaults are dangerous. Container images that listen on every interface, an engine called
"OpenAI" that points to OpenAI, a settings panel that ignores environment variables. Each of
these was caught only by checking what actually happened instead of what the configuration
said.

Small models need simple tools. The 4B model handles one tool call per message well and
drops instructions buried in tool output. Designing the tool around the model worked better
than prompting the model around the tool.

## Strategies that worked

1. Threat model first, then tests, then code. Every feature started with STRIDE at each trust
   boundary, written down in SECURITY.md.
2. Refuse instead of clean. Input that fails a check is rejected and logged, not repaired.
3. Prove every check with a mutation. If removing it changes nothing, the test is wrong.
4. One kind of risk at a time. Notes and actions first, then web input, then the phone, then
   delegation, each with its own threat model.
5. Verify the real state. Port bindings with `ss`, tailnet rules from the received filter,
   outgoing requests from the logs.
6. Pin everything. Images by digest, models only pulled when missing, no community plugins.
7. Keep secrets out of reach. Keys in mode 600 files outside the repo, tokens in the
   environment rather than the command line, a gitleaks hook before every commit.

## Open issues

1. The delegate tool works in the laptop browser. The phone account needs it shared as read
   only. Never with write access, because an Open WebUI tool is Python that runs inside the
   server, so edit rights on a tool mean code execution (CWE-94).
2. Julz sometimes answers in Polish to an English question over the API.
3. The 4B model drops the sentence that a spec waits for approval.
4. A hostile spec that looks harmless but needs a shell would test the tool layer for real.
5. Voice on the phone plays only the first reply, recordings are never cleaned up, and there
   is no egress block for cloud AI APIs yet.
6. The report check only finds the token as an exact string. An encoded token would pass. The
   real protection is that Claude has no tool that can send anything out.

## Resource footprint

About 26 GB in total. The models take about 14 GB, the Docker images and the Open WebUI
volume about 11.5 GB, system packages about 0.4 GB and the voices about 0.36 GB. My own code
and notes are under 2 MB. docs/UNINSTALL.md lists everything that would have to go to get
that space back.

## Publishing notes

The repository was published with a fresh history. The development history contains network
details of my own setup, so it stays on my laptop in a local branch and was never pushed.
Host names, network addresses, user names and device details were replaced with roles such as
"the laptop" or "the LAN address". The launch scripts read paths from the home folder of the
user who runs them instead of hard coding one.

## Certification map

| Topic in this project | Where it maps |
|---|---|
| STRIDE threat modelling, defence in depth, least privilege | Security+ |
| Path traversal, race conditions, injection, CSP | Security+, OWASP Top 10 (A01, A03, A05, A08, A10) |
| Prompt injection, excessive agency, data poisoning | OWASP Top 10 for LLM applications (LLM01, LLM04, LLM06, LLM10) |
| Port binding, firewall rules, VPN overlay, DNS | Network+ |
| Disk encryption, file permissions, containers | A+, Security+ |
| Passive recon ideas for the planned OSINT profile | HTB CPTS information gathering |
