#!/bin/bash
#SBATCH --job-name=amt-muscriptor-gap
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
: "${MUSCRIPTOR_GAP_CONFIG:?Missing MUSCRIPTOR_GAP_CONFIG}"

case "$(hostname)" in
  *-login*|klone-login*)
    echo "Refusing to run the MuScriptor gap probe on a login node." >&2
    exit 2
    ;;
esac

ROOT_PYTHON="${AMT_ROOT_PYTHON:-$AMT_REPO_ROOT/.venv/bin/python}"
WORKER_ENV="${MUSCRIPTOR_ENV:-$AMT_REPO_ROOT/workers/muscriptor/.venv}"
if ! command -v ffmpeg >/dev/null 2>&1; then
  set +u
  module load "${AMT_FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"
  set -u
fi
FFMPEG="$(command -v ffmpeg)"

cd "$AMT_REPO_ROOT"
date --iso-8601=seconds
hostname
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

srun "$ROOT_PYTHON" workers/muscriptor/gap_probe.py \
  --project "$PROJECT_DIR" \
  --config "$MUSCRIPTOR_GAP_CONFIG" \
  --worker-env "$WORKER_ENV" \
  --weight-provenance "$MUSCRIPTOR_WEIGHT_PROVENANCE" \
  --ffmpeg "$FFMPEG"
