#!/bin/bash
#SBATCH --job-name=amt-t007-voc-prepare
#SBATCH --account=cpu-g2-stf
#SBATCH --partition=cpu-g2
#SBATCH --qos=normal
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:30:00
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Submit with sbatch; do not prepare Vocadito data on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${VOCADITO_EXTRACTED_ROOT:?Export the existing extracted Vocadito v3 root}"
: "${TASK007_DATA_ROOT:?Export a persistent Task 007 dataset artifact root}"
: "${TASK007_PROJECTS_ROOT:?Export the persistent private projects root}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
SPLIT_CONFIG="${TASK007_VOCADITO_CONFIG:-$REPO_ROOT/configs/task007/vocadito_v3_split.json}"
LOG_DIR="$TASK007_DATA_ROOT/logs/prepare/${SLURM_JOB_ID}"
FFMPEG_MODULE="${FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"

for path in \
  "$REPO_ROOT" \
  "$ROOT_PYTHON" \
  "$VOCADITO_EXTRACTED_ROOT" \
  "$TASK007_DATA_ROOT" \
  "$TASK007_PROJECTS_ROOT" \
  "$SPLIT_CONFIG"
do
  if [[ "$path" != /* ]]; then
    echo "All Task 007 preparation paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" ||
      ! -f "$SPLIT_CONFIG" ||
      ! -d "$VOCADITO_EXTRACTED_ROOT" ]]; then
  echo "Root Python, split config, or extracted Vocadito root is unavailable." >&2
  exit 2
fi

mkdir -p "$LOG_DIR" "$TASK007_PROJECTS_ROOT"
exec > >(tee "$LOG_DIR/stdout.log") 2> >(tee "$LOG_DIR/stderr.log" >&2)

set +u
if ! type module >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source /etc/profile.d/lmod.sh
  module use /sw/klone /sw/contrib/modulefiles
fi
module --ignore_cache load "$FFMPEG_MODULE"
set -u
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "Pinned FFmpeg module did not provide ffmpeg and ffprobe: $FFMPEG_MODULE" >&2
  exit 2
fi

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-}"
echo "SLURM_CPUS_PER_TASK=${SLURM_CPUS_PER_TASK:-}"
printf 'AMT_REPO_ROOT=%q\n' "$REPO_ROOT"
printf 'VOCADITO_EXTRACTED_ROOT=%q\n' "$VOCADITO_EXTRACTED_ROOT"
printf 'TASK007_DATA_ROOT=%q\n' "$TASK007_DATA_ROOT"
printf 'TASK007_PROJECTS_ROOT=%q\n' "$TASK007_PROJECTS_ROOT"
printf 'TASK007_VOCADITO_CONFIG=%q\n' "$SPLIT_CONFIG"
"$ROOT_PYTHON" --version
ffmpeg -version
ffprobe -version
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO_ROOT" rev-parse HEAD
  git -C "$REPO_ROOT" status --porcelain
fi

cd "$REPO_ROOT"
srun "$ROOT_PYTHON" "$REPO_ROOT/scripts/prepare_vocadito_split.py" \
  --extracted-root "$VOCADITO_EXTRACTED_ROOT" \
  --artifact-root "$TASK007_DATA_ROOT/splits" \
  --projects-root "$TASK007_PROJECTS_ROOT" \
  --config "$SPLIT_CONFIG"
