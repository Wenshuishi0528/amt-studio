#!/bin/bash
#SBATCH --job-name=amt-t007b-blind-fusion-seal
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
  echo "Submit with sbatch; do not fuse or seal blind output on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${TASK007_PROJECTS_ROOT:?Export the persistent private projects root}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
DEVELOPMENT_PROJECT="$TASK007_PROJECTS_ROOT/vocadito-task007b-development-v2"
BLIND_PROJECT="$TASK007_PROJECTS_ROOT/vocadito-task007b-blind-v2"
BLIND_PACK="$BLIND_PROJECT/annotations/external-note-task007b-blind-v2"
CALIBRATION_DIR="$DEVELOPMENT_PROJECT/fusion/task007b-calibration-v2"
FUSION_DIR="$BLIND_PROJECT/fusion/task007b-blind-fusion-v2"
SEAL_PATH="$BLIND_PROJECT/fusion-seals/task007b-blind-fusion-v2-attempt-2.json"
LOG_DIR="${TASK007B_LOG_ROOT:-$TASK007_PROJECTS_ROOT/task007b-logs}/blind-fusion-seal/${SLURM_JOB_ID}"

for path in \
  "$REPO_ROOT" "$ROOT_PYTHON" "$TASK007_PROJECTS_ROOT" \
  "$DEVELOPMENT_PROJECT" "$BLIND_PROJECT" "$BLIND_PACK" \
  "$CALIBRATION_DIR" "$FUSION_DIR" "$SEAL_PATH" "$LOG_DIR"
do
  if [[ "$path" != /* ]]; then
    echo "All Task 007B blind fusion paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" ||
      ! -f "$BLIND_PACK/benchmark_manifest.json" ||
      ! -f "$BLIND_PACK/candidate_set_seal.json" ||
      ! -f "$CALIBRATION_DIR/profiles.json" ||
      ! -f "$CALIBRATION_DIR/config.json" ||
      ! -f "$CALIBRATION_DIR/calibration.json" ||
      ! -f "$CALIBRATION_DIR/run_manifest.json" ]]; then
  echo "Blind candidate seal, calibration, or root Python is unavailable." >&2
  exit 2
fi

mkdir -p "$LOG_DIR" "$BLIND_PROJECT/fusion" "$(dirname "$SEAL_PATH")"
exec > >(tee "$LOG_DIR/stdout.log") 2> >(tee "$LOG_DIR/stderr.log" >&2)

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
"$ROOT_PYTHON" --version
git -C "$REPO_ROOT" rev-parse HEAD
git -C "$REPO_ROOT" status --porcelain

cd "$REPO_ROOT"
if [[ -e "$FUSION_DIR" || -L "$FUSION_DIR" ]]; then
  echo "fusion_output_exists=1; seal will independently verify it before reuse"
else
  srun "$ROOT_PYTHON" "$REPO_ROOT/scripts/run_fusion.py" \
    --candidate "game-vocal-a=$BLIND_PROJECT/runs/game-t007b-voc-blind-medium" \
    --candidate \
    "basic-pitch-vocal-a=$BLIND_PROJECT/runs/basic-pitch-t007b-voc-blind-onnx" \
    --profiles "$CALIBRATION_DIR/profiles.json" \
    --config "$CALIBRATION_DIR/config.json" \
    --calibration "$CALIBRATION_DIR/calibration.json" \
    --run-id "task007b-blind-fusion-v2" \
    --output "$FUSION_DIR"
fi

srun "$ROOT_PYTHON" "$REPO_ROOT/scripts/evaluate_fusion.py" seal \
  --pack-dir "$BLIND_PACK" \
  --fusion-run "$FUSION_DIR" \
  --profiles "$CALIBRATION_DIR/profiles.json" \
  --config "$CALIBRATION_DIR/config.json" \
  --calibration "$CALIBRATION_DIR/calibration.json" \
  --minimum-candidates 2 \
  --output "$SEAL_PATH" \
  --confirm-blind-output-uninspected \
  --confirm-reference-not-used
