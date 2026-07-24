#!/usr/bin/env bash
set -euo pipefail

if [[ "$#" -ne 1 ]]; then
  echo "Usage: $0 projects/private/PROJECT_ID" >&2
  exit 2
fi

PROJECT_DIR="$(cd "$1" && pwd)"
PROJECT_ID="$(basename "$PROJECT_DIR")"
HYAK_HOST="${HYAK_HOST:-klone.hyak.uw.edu}"
REMOTE_ROOT="${HYAK_PERSIST_ROOT:-/gscratch/stf/$USER/amt-studio}"

read -r -p "Sync private authorized project '$PROJECT_ID' to Hyak? Type YES: " answer
[[ "$answer" == "YES" ]] || { echo "Cancelled"; exit 1; }

rsync -azP \
  --exclude 'runs/' \
  --exclude 'fusion/' \
  --exclude 'exports/' \
  "$PROJECT_DIR/" "$HYAK_HOST:$REMOTE_ROOT/projects/private/$PROJECT_ID/"

echo "Private project synced to $HYAK_HOST:$REMOTE_ROOT/projects/private/$PROJECT_ID/"
