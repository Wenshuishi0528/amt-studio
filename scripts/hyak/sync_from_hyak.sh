#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HYAK_HOST="${HYAK_HOST:-klone.hyak.uw.edu}"
REMOTE_ROOT="${HYAK_PERSIST_ROOT:-/gscratch/stf/$USER/amt-studio}"
LOCAL_RESULTS="$ROOT/hyak-results"

mkdir -p "$LOCAL_RESULTS"
rsync -azP \
  --exclude '.venv/' \
  --exclude 'model-cache/' \
  --exclude 'datasets/' \
  --exclude 'tmp/' \
  "$HYAK_HOST:$REMOTE_ROOT/manifests/" "$LOCAL_RESULTS/manifests/"
rsync -azP \
  "$HYAK_HOST:$REMOTE_ROOT/logs/" "$LOCAL_RESULTS/logs/"
rsync -azP \
  "$HYAK_HOST:$REMOTE_ROOT/indexes/" "$LOCAL_RESULTS/indexes/"
rsync -azP \
  "$HYAK_HOST:$REMOTE_ROOT/selected/" "$LOCAL_RESULTS/selected/"

echo "Manifests, logs, experiment indexes, and persistent output archives synced to $LOCAL_RESULTS"
echo "Unselected cache entries and project run directories remain remote."
