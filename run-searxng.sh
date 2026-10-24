#!/usr/bin/env bash
# Start SearXNG, the local search engine Julz uses. Run with: sudo ./run-searxng.sh
# Same hardening as run-webui.sh (SECURITY.md threats 2, 9, 10, 15).
set -euo pipefail

# 2026.9.30-a9d990033, pinned by digest (threat 10)
IMAGE="searxng/searxng@sha256:a07a5cd2da2c63d66e559f9e4d3a3db106cfc6c32fb0ac70abe91cc28bcd7350"

# Paths live under the home of the user who ran sudo, not under /root
ME="${SUDO_USER:?run this with sudo from your own account}"
USER_HOME="$(getent passwd "$ME" | cut -d: -f6)"

# SEARXNG_SECRET lives outside the repo
ENV_FILE="$USER_HOME/.config/julz/searxng.env"
CONFIG_DIR="$(cd "$(dirname "$0")" && pwd)/searxng"

docker rm -f searxng 2>/dev/null || true

# Host network, like Open WebUI. The image listens on GRANIAN_HOST="::" (every interface,
# IPv4 and IPv6) unless told otherwise, so 127.0.0.1 here is what keeps it off the LAN.
# Read only root filesystem; only /tmp and the cache are writable, and only in RAM.
docker run -d \
  --name searxng \
  --network host \
  --env-file "$ENV_FILE" \
  -e GRANIAN_HOST=127.0.0.1 \
  -e SEARXNG_PORT=8888 \
  -e FORCE_OWNERSHIP=false \
  -v "$CONFIG_DIR":/etc/searxng:ro \
  --tmpfs /tmp:uid=1000,gid=1000 \
  --tmpfs /var/cache/searxng:uid=1000,gid=1000 \
  --read-only \
  --user 1000:1000 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --restart unless-stopped \
  "$IMAGE"
