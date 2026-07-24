#!/bin/bash
#SBATCH --job-name=amt-muscriptor
#SBATCH --account=gpu-l40-stf
#SBATCH --partition=gpu-l40
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=64G
#SBATCH --gpus=l40:1
#SBATCH --time=06:00:00
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail

: "${PROJECT_DIR:?Export PROJECT_DIR to an initialized private project}"
: "${MUSCRIPTOR_WEIGHT_PROVENANCE:?Export the pinned local provenance JSON path}"

REPO_ROOT="${AMT_REPO_ROOT:-$SLURM_SUBMIT_DIR}"
WORKER_ENV="${MUSCRIPTOR_ENV:-$REPO_ROOT/workers/muscriptor/.venv}"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
RUN_ID="${MUSCRIPTOR_RUN_ID:-muscriptor-large-beam4-hyak-${SLURM_JOB_ID}}"
BEAM_SIZE="${MUSCRIPTOR_BEAM_SIZE:-4}"

cd "$REPO_ROOT"

date --iso-8601=seconds
hostname
nvidia-smi
"$ROOT_PYTHON" --version
"$WORKER_ENV/bin/python" -c \
  'import torch; print({"torch": torch.__version__, "cuda": torch.version.cuda, "available": torch.cuda.is_available()})'
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO_ROOT" rev-parse HEAD
  git -C "$REPO_ROOT" status --porcelain
else
  echo "Git metadata unavailable in the synced HYAK copy; runner records commit=null."
fi

run_baseline() {
  local run_id="$1"
  local runner_args=(
    --project "$PROJECT_DIR"
    --worker-env "$WORKER_ENV"
    --weight-provenance "$MUSCRIPTOR_WEIGHT_PROVENANCE"
    --run-id "$run_id"
    --beam-size "$BEAM_SIZE"
    --device cuda
    --prelude-forcing
  )
  if [[ -n "${MUSCRIPTOR_AUDIO:-}" ]]; then
    runner_args+=(--audio "$MUSCRIPTOR_AUDIO")
  fi
  srun "$ROOT_PYTHON" workers/muscriptor/run_baseline.py \
    "${runner_args[@]}"
}

run_baseline "$RUN_ID"
if [[ -n "${MUSCRIPTOR_SECOND_RUN_ID:-}" ]]; then
  run_baseline "$MUSCRIPTOR_SECOND_RUN_ID"
fi
