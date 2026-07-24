#!/usr/bin/env bash
set -euo pipefail

if [[ "$(hostname)" != klone-login* ]]; then
  echo "This setup script is intended for a Klone login node." >&2
fi

PERSIST_ROOT="${HYAK_PERSIST_ROOT:-/gscratch/stf/$USER/amt-studio}"
SCRATCH_ROOT="${HYAK_SCRATCH_ROOT:-/gscratch/scrubbed/$USER/amt-studio}"

mkdir -p \
  "$PERSIST_ROOT/repo" \
  "$PERSIST_ROOT/projects/private" \
  "$PERSIST_ROOT/manifests" \
  "$PERSIST_ROOT/checkpoints" \
  "$PERSIST_ROOT/logs" \
  "$SCRATCH_ROOT/model-cache" \
  "$SCRATCH_ROOT/datasets" \
  "$SCRATCH_ROOT/tmp"

chmod 700 "$PERSIST_ROOT" "$PERSIST_ROOT/projects/private" "$SCRATCH_ROOT"

cat <<EOF
Prepared Hyak directories.
Persistent root: $PERSIST_ROOT
Scratch root:    $SCRATCH_ROOT

Verify storage before use:
  hyakstorage
  ls -ld "$PERSIST_ROOT" "$SCRATCH_ROOT"

Do not run model inference or training on this login node.
EOF
