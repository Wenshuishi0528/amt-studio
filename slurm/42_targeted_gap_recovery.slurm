#!/bin/bash
#SBATCH --job-name=amt-gap-recovery
#SBATCH --account=gpu-l40-stf
#SBATCH --partition=gpu-l40
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=64G
#SBATCH --gpus=l40:1
#SBATCH --time=01:00:00
#SBATCH --export=ALL

set -euo pipefail

: "${AMT_REPO_ROOT:?Missing AMT_REPO_ROOT}"
: "${PROJECT_DIR:?Missing PROJECT_DIR}"
: "${MUSCRIPTOR_WEIGHT_PROVENANCE:?Missing MUSCRIPTOR_WEIGHT_PROVENANCE}"
: "${TARGETED_GAP_CONFIG:?Missing TARGETED_GAP_CONFIG}"
: "${AMT_BUNDLE_ID:?Missing AMT_BUNDLE_ID}"

case "$(hostname)" in
  *-login*|klone-login*)
    echo "Refusing to run targeted gap recovery on a login node." >&2
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
hostname
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

srun "$ROOT_PYTHON" -m workers.muscriptor.targeted_gap_recovery \
  --project "$PROJECT_DIR" \
  --config "$TARGETED_GAP_CONFIG" \
  --output-bundle "$AMT_BUNDLE_ID" \
  --worker-env "$WORKER_ENV" \
  --weight-provenance "$MUSCRIPTOR_WEIGHT_PROVENANCE" \
  --ffmpeg "$FFMPEG" \
  --device cuda
