#!/usr/bin/env bash
# Build the Julz models in Ollama from the prompt files in modelfiles/.
# Edit personality.txt or sec-addon.txt, then run this again to apply the changes.
set -euo pipefail
cd "$(dirname "$0")/modelfiles"

# name        base model           context  temperature  extra prompt
models=(
  "julz        qwen3.5:4b           16384    0.6          -"
  "julz-pro    qwen3.5:9b           8192     0.6          -"
  "julz-sec    qwen2.5-coder:7b     8192     0.3          sec-addon.txt"
)

for row in "${models[@]}"; do
  read -r name base ctx temp addon <<<"$row"
  echo "== $name (from $base)"
  # Pull only when missing: a pull can silently swap in a newer model under the same tag
  ollama show "$base" >/dev/null 2>&1 || ollama pull "$base"
  {
    echo "FROM $base"
    echo "PARAMETER num_ctx $ctx"
    echo "PARAMETER temperature $temp"
    echo 'SYSTEM """'
    cat personality.txt
    [ "$addon" != "-" ] && cat "$addon"
    echo '"""'
  } > "$name.Modelfile"
  ollama create "$name" -f "$name.Modelfile"
done

echo; ollama list
