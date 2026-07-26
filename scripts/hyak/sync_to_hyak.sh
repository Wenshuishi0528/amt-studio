#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HYAK_HOST="${HYAK_HOST:-klone.hyak.uw.edu}"
REMOTE_ROOT="${HYAK_PERSIST_ROOT:-/gscratch/stf/$USER/amt-studio}"

rsync -azP --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '.pytest_cache/' \
  --exclude '.ruff_cache/' \
  --exclude '.uv-cache/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  --exclude 'hyak-results/' \
  --exclude 'data/private/' \
  --exclude 'projects/private/' \
  --exclude 'weights/' \
  --exclude 'datasets/' \
  --exclude 'model-cache/' \
  --exclude 'runs/' \
  "$ROOT/" "$HYAK_HOST:$REMOTE_ROOT/repo/"

cat <<EOF
Code synced to $HYAK_HOST:$REMOTE_ROOT/repo/
Private audio/projects are excluded. Sync an authorized project separately and deliberately.
EOF
