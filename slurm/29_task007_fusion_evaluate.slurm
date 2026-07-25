#!/bin/bash
#SBATCH --job-name=amt-t007-fusion-evaluate
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
  echo "Submit with sbatch; do not evaluate blind output on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${TASK007_PROJECTS_ROOT:?Export the persistent private projects root}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
DEVELOPMENT_PROJECT="$TASK007_PROJECTS_ROOT/vocadito-task007-development-v1"
BLIND_PROJECT="$TASK007_PROJECTS_ROOT/vocadito-task007-blind-v1"
BLIND_PACK="$BLIND_PROJECT/annotations/external-note-task007-blind-v1"
CALIBRATION_DIR="${TASK007_CALIBRATION_DIR:-$DEVELOPMENT_PROJECT/fusion/task007-calibration-v1}"
FUSION_DIR="${TASK007_BLIND_FUSION_DIR:-$BLIND_PROJECT/fusion/task007-blind-fusion-v1}"
SEAL_PATH="${TASK007_FUSION_SEAL_PATH:-$BLIND_PROJECT/fusion-seals/task007-blind-fusion-v1.json}"
EVALUATION_DIR="${TASK007_FUSION_EVALUATION_DIR:-$BLIND_PROJECT/evaluations/task007-blind-fusion-v1}"
LOG_DIR="${TASK007_LOG_ROOT:-$TASK007_PROJECTS_ROOT/task007-logs}/fusion-evaluate/${SLURM_JOB_ID}"

for path in \
  "$REPO_ROOT" \
  "$ROOT_PYTHON" \
  "$TASK007_PROJECTS_ROOT" \
  "$DEVELOPMENT_PROJECT" \
  "$BLIND_PROJECT" \
  "$BLIND_PACK" \
  "$CALIBRATION_DIR" \
  "$FUSION_DIR" \
  "$SEAL_PATH" \
  "$EVALUATION_DIR" \
  "$LOG_DIR"
do
  if [[ "$path" != /* ]]; then
    echo "All Task 007 evaluation paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" ||
      ! -f "$BLIND_PACK/benchmark_manifest.json" ||
      ! -f "$BLIND_PACK/candidate_set_seal.json" ||
      ! -f "$FUSION_DIR/run_manifest.json" ||
      ! -f "$SEAL_PATH" ||
      ! -f "$CALIBRATION_DIR/profiles.json" ||
      ! -f "$CALIBRATION_DIR/config.json" ||
      ! -f "$CALIBRATION_DIR/calibration.json" ]]; then
  echo "Sealed blind fusion, calibration, or root Python is unavailable." >&2
  exit 2
fi

mkdir -p "$LOG_DIR" "$BLIND_PROJECT/evaluations"
exec > >(tee "$LOG_DIR/stdout.log") 2> >(tee "$LOG_DIR/stderr.log" >&2)

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-}"
printf 'FUSION_DIR=%q\n' "$FUSION_DIR"
printf 'SEAL_PATH=%q\n' "$SEAL_PATH"
printf 'EVALUATION_DIR=%q\n' "$EVALUATION_DIR"
"$ROOT_PYTHON" --version

cd "$REPO_ROOT"
srun "$ROOT_PYTHON" "$REPO_ROOT/scripts/evaluate_fusion.py" evaluate \
  --pack-dir "$BLIND_PACK" \
  --fusion-run "$FUSION_DIR" \
  --profiles "$CALIBRATION_DIR/profiles.json" \
  --config "$CALIBRATION_DIR/config.json" \
  --calibration "$CALIBRATION_DIR/calibration.json" \
  --seal "$SEAL_PATH" \
  --output-dir "$EVALUATION_DIR"
