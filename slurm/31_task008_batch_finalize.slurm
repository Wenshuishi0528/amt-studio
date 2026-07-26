#!/bin/bash

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo "Submit with scripts/hyak/submit_batch.py; do not finalize on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export the absolute synced repository root}"
: "${AMT_BATCH_MANIFEST:?Export the absolute frozen batch manifest}"
: "${AMT_BATCH_CACHE_ROOT:?Export the scrubbed content-addressed cache root}"
: "${AMT_BATCH_SELECTED_ROOT:?Export the persistent selected-result root}"
: "${AMT_BATCH_INDEX_ROOT:?Export the persistent experiment-index root}"

ROOT_PYTHON="${AMT_ROOT_PYTHON:-$AMT_REPO_ROOT/.venv/bin/python}"
cd "$AMT_REPO_ROOT"

srun "$ROOT_PYTHON" "$AMT_REPO_ROOT/scripts/manage_hyak_batch.py" summarize \
  --manifest "$AMT_BATCH_MANIFEST" \
  --cache-root "$AMT_BATCH_CACHE_ROOT" \
  --selected-root "$AMT_BATCH_SELECTED_ROOT" \
  --index-root "$AMT_BATCH_INDEX_ROOT"

srun "$ROOT_PYTHON" "$AMT_REPO_ROOT/scripts/manage_hyak_batch.py" prune \
  --manifest "$AMT_BATCH_MANIFEST" \
  --cache-root "$AMT_BATCH_CACHE_ROOT" \
  --selected-root "$AMT_BATCH_SELECTED_ROOT" \
  --index-root "$AMT_BATCH_INDEX_ROOT" \
  --apply

srun "$ROOT_PYTHON" "$AMT_REPO_ROOT/scripts/manage_hyak_batch.py" summarize \
  --manifest "$AMT_BATCH_MANIFEST" \
  --cache-root "$AMT_BATCH_CACHE_ROOT" \
  --selected-root "$AMT_BATCH_SELECTED_ROOT" \
  --index-root "$AMT_BATCH_INDEX_ROOT"
