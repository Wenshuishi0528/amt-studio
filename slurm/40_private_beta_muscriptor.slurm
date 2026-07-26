#!/bin/bash
#SBATCH --job-name=amt-private-beta
#SBATCH --account=gpu-l40-stf
#SBATCH --partition=gpu-l40
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=64G
#SBATCH --gpus=l40:1
#SBATCH --time=03:00:00
#SBATCH --export=ALL

set -euo pipefail

: "${AMT_REPO_ROOT:?Missing AMT_REPO_ROOT}"
: "${PROJECT_DIR:?Missing PROJECT_DIR}"
: "${MUSCRIPTOR_WEIGHT_PROVENANCE:?Missing MUSCRIPTOR_WEIGHT_PROVENANCE}"
: "${MUSCRIPTOR_RUN_ID:?Missing MUSCRIPTOR_RUN_ID}"
: "${AMT_BUNDLE_ID:?Missing AMT_BUNDLE_ID}"

case "$(hostname)" in
  *-login*|klone-login*)
    echo "Refusing to run transcription on a login node." >&2
    exit 2
    ;;
esac

ROOT_PYTHON="${AMT_ROOT_PYTHON:-$AMT_REPO_ROOT/.venv/bin/python}"
WORKER_ENV="${MUSCRIPTOR_ENV:-$AMT_REPO_ROOT/workers/muscriptor/.venv}"
RUN_DIR="$PROJECT_DIR/runs/$MUSCRIPTOR_RUN_ID"
BUNDLE_DIR="$PROJECT_DIR/exports/$AMT_BUNDLE_ID"

cd "$AMT_REPO_ROOT"
hostname
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

srun "$ROOT_PYTHON" workers/muscriptor/run_baseline.py \
  --project "$PROJECT_DIR" \
  --worker-env "$WORKER_ENV" \
  --weight-provenance "$MUSCRIPTOR_WEIGHT_PROVENANCE" \
  --run-id "$MUSCRIPTOR_RUN_ID" \
  --beam-size 4 \
  --device cuda \
  --prelude-forcing \
  --skip-midi

"$ROOT_PYTHON" -m amt_core.cli build-muscriptor-multitrack \
  "$PROJECT_DIR" \
  --run "$RUN_DIR" \
  --output "$BUNDLE_DIR"
