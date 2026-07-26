#!/bin/bash

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo "Submit this manifest-freeze script through sbatch." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export the absolute synced repository root}"
: "${AMT_BATCH_SPEC:?Export the absolute batch specification path}"
: "${AMT_BATCH_MANIFEST:?Export the absolute frozen manifest output path}"

ROOT_PYTHON="${AMT_ROOT_PYTHON:-$AMT_REPO_ROOT/.venv/bin/python}"
for path in "$AMT_REPO_ROOT" "$ROOT_PYTHON" "$AMT_BATCH_SPEC" "$AMT_BATCH_MANIFEST"; do
  if [[ "$path" != /* ]]; then
    echo "All Task008 freeze paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" || ! -f "$AMT_BATCH_SPEC" ]]; then
  echo "Task008 Python or batch specification is unavailable." >&2
  exit 2
fi

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
echo "SLURM_JOB_ACCOUNT=${SLURM_JOB_ACCOUNT:-}"
echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-}"

cd "$AMT_REPO_ROOT"
srun "$ROOT_PYTHON" "$AMT_REPO_ROOT/scripts/manage_hyak_batch.py" freeze \
  --spec "$AMT_BATCH_SPEC" \
  --output "$AMT_BATCH_MANIFEST"
