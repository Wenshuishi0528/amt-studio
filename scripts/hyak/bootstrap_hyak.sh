#!/usr/bin/env bash
set -euo pipefail

if [[ -n "${SLURM_JOB_ID:-}" ]] || ! command -v sbatch >/dev/null 2>&1; then
  echo "This setup script requires a non-compute host with sbatch available." >&2
  exit 2
fi

PERSIST_ROOT="${HYAK_PERSIST_ROOT:-/gscratch/stf/$USER/amt-studio}"
SCRATCH_ROOT="${HYAK_SCRATCH_ROOT:-/gscratch/scrubbed/$USER/amt-studio}"

mkdir -p \
  "$PERSIST_ROOT/repo" \
  "$PERSIST_ROOT/projects/private" \
  "$PERSIST_ROOT/manifests" \
  "$PERSIST_ROOT/checkpoints" \
  "$PERSIST_ROOT/indexes" \
  "$PERSIST_ROOT/logs" \
  "$PERSIST_ROOT/selected" \
  "$SCRATCH_ROOT/batch-cache" \
  "$SCRATCH_ROOT/model-cache" \
  "$SCRATCH_ROOT/datasets" \
  "$SCRATCH_ROOT/tmp"

chmod 700 \
  "$PERSIST_ROOT" \
  "$PERSIST_ROOT/projects/private" \
  "$PERSIST_ROOT/indexes" \
  "$PERSIST_ROOT/selected" \
  "$SCRATCH_ROOT" \
  "$SCRATCH_ROOT/batch-cache"

cat <<EOF
Prepared Hyak directories.
Persistent root: $PERSIST_ROOT
Scratch root:    $SCRATCH_ROOT

Verify storage before use:
  hyakstorage
  ls -ld "$PERSIST_ROOT" "$SCRATCH_ROOT"

Do not run model inference or training on this login node.
EOF
