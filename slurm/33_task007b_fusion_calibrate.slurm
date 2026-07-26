#!/bin/bash
#SBATCH --job-name=amt-t007b-fusion-calibrate
#SBATCH --account=cpu-g2-stf
#SBATCH --partition=cpu-g2
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=01:00:00
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Submit with sbatch; do not calibrate fusion on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${TASK007_PROJECTS_ROOT:?Export the persistent private projects root}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
DEVELOPMENT_PROJECT="$TASK007_PROJECTS_ROOT/vocadito-task007b-development-v2"
DEVELOPMENT_PACK="$DEVELOPMENT_PROJECT/annotations/external-note-task007b-development-v2"
SOURCE_METADATA="$REPO_ROOT/configs/task007b/fusion_source_metadata.json"
BASE_CONFIG="$REPO_ROOT/configs/task007b/fusion_base_config.json"
CALIBRATION_DIR="$DEVELOPMENT_PROJECT/fusion/task007b-calibration-v2"
LOG_DIR="${TASK007B_LOG_ROOT:-$TASK007_PROJECTS_ROOT/task007b-logs}/fusion-calibrate/${SLURM_JOB_ID}"

for path in \
  "$REPO_ROOT" "$ROOT_PYTHON" "$TASK007_PROJECTS_ROOT" \
  "$DEVELOPMENT_PROJECT" "$DEVELOPMENT_PACK" "$SOURCE_METADATA" \
  "$BASE_CONFIG" "$CALIBRATION_DIR" "$LOG_DIR"
do
  if [[ "$path" != /* ]]; then
    echo "All Task 007B calibration paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" ||
      ! -f "$DEVELOPMENT_PACK/benchmark_manifest.json" ||
      ! -f "$SOURCE_METADATA" ||
      ! -f "$BASE_CONFIG" ]]; then
  echo "Development benchmark, configuration, or root Python is unavailable." >&2
  exit 2
fi

mkdir -p "$LOG_DIR" "$DEVELOPMENT_PROJECT/fusion"
exec > >(tee "$LOG_DIR/stdout.log") 2> >(tee "$LOG_DIR/stderr.log" >&2)

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
"$ROOT_PYTHON" --version
git -C "$REPO_ROOT" rev-parse HEAD
git -C "$REPO_ROOT" status --porcelain

cd "$REPO_ROOT"
srun "$ROOT_PYTHON" "$REPO_ROOT/scripts/calibrate_fusion.py" \
  --benchmark "$DEVELOPMENT_PACK/benchmark_manifest.json" \
  --candidate "game-vocal-a=$DEVELOPMENT_PROJECT/runs/game-t007b-voc-dev-medium" \
  --candidate \
  "basic-pitch-vocal-a=$DEVELOPMENT_PROJECT/runs/basic-pitch-t007b-voc-dev-onnx" \
  --source-metadata "$SOURCE_METADATA" \
  --base-config "$BASE_CONFIG" \
  --calibration-id "task007b-vocadito-development-v2" \
  --output "$CALIBRATION_DIR"
