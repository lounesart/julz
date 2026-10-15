#!/usr/bin/env bash
# Start Speaches, the local voice (Piper TTS) Julz speaks with. Run with: sudo ./run-speaches.sh
# Same hardening as run-searxng.sh (SECURITY.md threats 2, 9, 10).
set -euo pipefail

# v0.8.3 CPU build (2025-09-19), pinned by digest (threat 10)
IMAGE="ghcr.io/speaches-ai/speaches@sha256:21e3df06d842fb7802ab470dd77c25f0e8c0d22950e8d8c6ae886e851af53ef8"

# API_KEY lives outside the repo. Without it any web page in my browser could call
# 127.0.0.1:8880 and make Speaches download arbitrary models (localhost CSRF, A01, A08).
# Paths live under the home of the user who ran sudo, not under /root
ME="${SUDO_USER:?run this with sudo from your own account}"
USER_HOME="$(getent passwd "$ME" | cut -d: -f6)"
ENV_FILE="$USER_HOME/.config/julz/speaches.env"
# Downloaded voices, owned by me, not by root
CACHE_DIR="$USER_HOME/.local/share/julz/speaches"

docker rm -f speaches 2>/dev/null || true

# Host network, like Open WebUI. The image listens on UVICORN_HOST=0.0.0.0 unless told
# otherwise, so 127.0.0.1 here is what keeps it off the LAN. Port 8880: 8000 is too common.
docker run -d \
  --name speaches \
  --network host \
  --env-file "$ENV_FILE" \
  -e UVICORN_HOST=127.0.0.1 \
  -e UVICORN_PORT=8880 \
  -e ENABLE_UI=false \
  -v "$CACHE_DIR":/home/ubuntu/.cache/huggingface:rw \
  --tmpfs /tmp:uid=1000,gid=1000 \
  --read-only \
  --user 1000:1000 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --restart unless-stopped \
  "$IMAGE"
