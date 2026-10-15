# Removing Julz

Everything Julz uses, in the order it should be removed, with the space each part frees.
Measured on 2026-10-15, about 26 GB in total. Commands with sudo are run by me in my own
terminal. Nothing here runs by itself.

Before deleting anything, decide about the three things that hold real content. They are
marked KEEP OR BACK UP below. Everything else can be recreated.

## 1. Stop the services

```
sudo docker rm -f open-webui searxng speaches
sudo tailscale serve reset
```

The first line stops and removes the three containers (about 7 MB). The second stops serving
the hub to the phone over the tailnet.

## 2. Docker images (about 9.9 GB)

```
sudo docker rmi ghcr.io/open-webui/open-webui@sha256:9591b13f13843c7721c2b8eaf7382846c81b3ffe126526d1888d1fed50c6a33f
sudo docker rmi ghcr.io/speaches-ai/speaches@sha256:21e3df06d842fb7802ab470dd77c25f0e8c0d22950e8d8c6ae886e851af53ef8
sudo docker rmi searxng/searxng@sha256:a07a5cd2da2c63d66e559f9e4d3a3db106cfc6c32fb0ac70abe91cc28bcd7350
```

| Image | Size on disk |
|---|---|
| Open WebUI | 6.47 GB |
| Speaches | 3.03 GB |
| SearXNG | 0.38 GB |

The Juice Shop image is not part of Julz. It is my practice target and stays.

## 3. Open WebUI volume (about 1.6 GB), KEEP OR BACK UP

Holds every chat, the knowledge index, the Whisper model, users and settings.

```
sudo docker volume rm open-webui
```

## 4. Ollama models (about 14 GB)

```
ollama rm julz julz-pro julz-sec
ollama rm qwen3.5:4b qwen3.5:9b qwen2.5-coder:7b
```

The first line removes only the prompts on top of the base models and frees almost nothing.
The second frees the space. Keep a base model if something else uses it.

## 5. Files in my home folder

| Path | What it is | Size |
|---|---|---|
| `~/.local/share/julz/` | voices, gate folders, work copies, runner log | about 362 MB |
| `~/.local/state/julz/` | julz action log | a few KB |
| `~/.config/julz/` | env files with keys, Claude token, project list, pocket public key | a few KB |
| `~/.pocket-drop/` | encrypted drops waiting to be opened | usually empty |
| `~/Projects/sandbox/julz-sandbox/` | the project Claude works on | empty |
| `~/Projects/products/julz/` | this repository, including the local `private-history` branch | about 1.4 MB |
| `~/Documents/julz-mem/` | KEEP OR BACK UP, my study notes, Inbox, Outbox reports | about 64 KB |
| `~/.pocket.enc/` and `~/Private/` | KEEP OR BACK UP, the encrypted pocket and its unlocked view | small |

Unmount the pocket before touching it (`fusermount3 -u ~/Private`). Open any waiting drops
with `pocket-open.py` first, or they are lost with the private key.

## 6. Accounts and keys outside the laptop

1. Revoke the long lived Claude token made with `claude setup-token` in my Claude account.
   Do this before deleting `~/.config/julz/`, so the token is dead even if a copy exists.
2. Remove the Julz grants for the phone from the Tailscale policy. Keep the SSH grant if I
   still use it.
3. Delete the Julz entries (admin, phone account, pocket password) from KeePassXC.
4. Delete the GitHub repository if I no longer want it public (`gh repo delete`).
5. Delete the Claude Code memory folder for this project under `~/.claude/projects/`.

## 7. System packages (about 0.4 GB), only if nothing else needs them

```
sudo pacman -Rs ollama-vulkan gocryptfs python-joserfc
```

Docker (with containerd, runc and docker-compose, about 245 MB) also runs my Juice Shop lab,
so it stays unless I give up the lab too. Tailscale (about 51 MB) also carries SSH from the
phone, so it stays unless I drop that as well.

## Checks afterwards

```
sudo docker ps -a
sudo docker volume ls
ollama list
ss -tln
```

None of the Julz containers, the `open-webui` volume or the models should be listed, and
nothing should listen on ports 3100, 8888, 8880 or 11434.
