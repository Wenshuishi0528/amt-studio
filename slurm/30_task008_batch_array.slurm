#!/bin/bash

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" ]]; then
  echo "Submit with scripts/hyak/submit_batch.py; do not run a batch row on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export the absolute synced repository root}"
: "${AMT_BATCH_MANIFEST:?Export the absolute frozen batch manifest}"
: "${AMT_BATCH_CACHE_ROOT:?Export the scrubbed content-addressed cache root}"
: "${AMT_BATCH_SELECTED_ROOT:?Export the persistent selected-result root}"
: "${AMT_BATCH_INDEX_ROOT:?Export the persistent experiment-index root}"
: "${SLURM_ARRAY_TASK_ID:?Submit this script as a Slurm array}"

ROOT_PYTHON="${AMT_ROOT_PYTHON:-$AMT_REPO_ROOT/.venv/bin/python}"
for path in \
  "$AMT_REPO_ROOT" \
  "$ROOT_PYTHON" \
  "$AMT_BATCH_MANIFEST" \
  "$AMT_BATCH_CACHE_ROOT" \
  "$AMT_BATCH_SELECTED_ROOT" \
  "$AMT_BATCH_INDEX_ROOT"
do
  if [[ "$path" != /* ]]; then
    echo "All Task008 paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" || ! -f "$AMT_BATCH_MANIFEST" ]]; then
  echo "Task008 Python or frozen manifest is unavailable." >&2
  exit 2
fi

mkdir -p "$AMT_BATCH_CACHE_ROOT" "$AMT_BATCH_SELECTED_ROOT" "$AMT_BATCH_INDEX_ROOT"
echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
echo "SLURM_ARRAY_JOB_ID=${SLURM_ARRAY_JOB_ID:-}"
echo "SLURM_ARRAY_TASK_ID=$SLURM_ARRAY_TASK_ID"
echo "SLURM_RESTART_COUNT=${SLURM_RESTART_COUNT:-0}"
echo "SLURM_JOB_ACCOUNT=${SLURM_JOB_ACCOUNT:-}"
echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-}"
echo "SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-}"
echo "SLURM_JOB_GPUS=${SLURM_JOB_GPUS:-}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
"$ROOT_PYTHON" --version
if command -v nvidia-smi >/dev/null 2>&1 && [[ -n "${CUDA_VISIBLE_DEVICES:-}" ]]; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
fi

cd "$AMT_REPO_ROOT"
runner_pid=""
on_interrupt() {
  if [[ -n "$runner_pid" ]] && kill -0 "$runner_pid" 2>/dev/null; then
    kill -TERM "$runner_pid" 2>/dev/null || true
    wait "$runner_pid" || true
  fi
  exit 75
}
trap on_interrupt TERM INT

srun "$ROOT_PYTHON" "$AMT_REPO_ROOT/scripts/manage_hyak_batch.py" run-row \
  --manifest "$AMT_BATCH_MANIFEST" \
  --row-index "$SLURM_ARRAY_TASK_ID" \
  --cache-root "$AMT_BATCH_CACHE_ROOT" \
  --selected-root "$AMT_BATCH_SELECTED_ROOT" \
  --index-root "$AMT_BATCH_INDEX_ROOT" \
  --repo-root "$AMT_REPO_ROOT" \
  --python "$ROOT_PYTHON" &
runner_pid=$!
wait "$runner_pid"
