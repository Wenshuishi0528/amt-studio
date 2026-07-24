#!/bin/bash
#SBATCH --job-name=amt-separator-baseline
#SBATCH --account=stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt-gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gpus=a40:1
#SBATCH --time=06:00:00
#SBATCH --requeue
#SBATCH --signal=B:TERM@120
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Submit this script with sbatch; do not run inference on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${PROJECT_DIR:?Export PROJECT_DIR as the initialized private project}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
WORKER_ENV="${SEPARATOR_ENV:-$REPO_ROOT/workers/separator/.venv}"
PINS_PATH="${SEPARATOR_PINS:-$REPO_ROOT/workers/separator/pins.json}"
INPUT_AUDIO="${SEPARATOR_AUDIO:-$PROJECT_DIR/audio/canonical/mix.flac}"
RUN_PREFIX="${SEPARATOR_RUN_ID_PREFIX:-separator-hyak-${SLURM_JOB_ID}}"
VOCAL_BASE_RUN_ID="${SEPARATOR_VOCAL_RUN_ID:-${RUN_PREFIX}-vocal-quality-a}"
MULTISTEM_BASE_RUN_ID="${SEPARATOR_MULTISTEM_RUN_ID:-${RUN_PREFIX}-multistem-quality-a}"
VERIFY_RUN_MANIFEST="$REPO_ROOT/scripts/verify_run_manifest.py"
FFMPEG_MODULE="${FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"

validate_run_id() {
  local run_id="$1"
  if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ||
        "$run_id" == *".."* ||
        ${#run_id} -gt 128 ]]; then
    echo "Unsafe run ID: $run_id" >&2
    exit 2
  fi
}

validate_base_run_id() {
  local run_id="$1"
  validate_run_id "$run_id"
  if [[ ${#run_id} -gt 110 ]]; then
    echo "Base run ID is too long to add a safe attempt suffix: $run_id" >&2
    exit 2
  fi
}

print_env_value() {
  local name="$1"
  if [[ -n "${!name-}" ]]; then
    printf '%s=%q\n' "$name" "${!name}"
  fi
}

if [[ "$REPO_ROOT" != /* || "$PROJECT_DIR" != /* ]]; then
  echo "AMT_REPO_ROOT and PROJECT_DIR must be absolute paths." >&2
  exit 2
fi
if [[ ! -x "$ROOT_PYTHON" ||
      ! -f "$VERIFY_RUN_MANIFEST" ||
      ! -f "$PINS_PATH" ]]; then
  echo "Root Python, run-manifest verifier, or separator pins are unavailable." >&2
  exit 2
fi
if [[ ! -f "$INPUT_AUDIO" ]]; then
  echo "Separator input audio not found: $INPUT_AUDIO" >&2
  exit 2
fi
validate_base_run_id "$VOCAL_BASE_RUN_ID"
validate_base_run_id "$MULTISTEM_BASE_RUN_ID"
if [[ "$VOCAL_BASE_RUN_ID" == "$MULTISTEM_BASE_RUN_ID" ]]; then
  echo "The two separator run IDs must be distinct." >&2
  exit 2
fi

run_manifest_is_valid() {
  local preset="$1"
  local run_id="$2"
  local validator_args=(
    --run-dir "$PROJECT_DIR/runs/$run_id"
    --worker separator
    --preset "$preset"
    --input "$INPUT_AUDIO"
    --pins "$PINS_PATH"
    --repo-root "$REPO_ROOT"
    --source "$PINS_PATH"
    --source "$REPO_ROOT/workers/separator/pyproject.toml"
    --source "$REPO_ROOT/workers/separator/uv.lock"
    --source "$REPO_ROOT/workers/separator/metrics.py"
    --source "$REPO_ROOT/workers/separator/run_baseline.py"
    --source "$VERIFY_RUN_MANIFEST"
    --source "$REPO_ROOT/slurm/16_separator_baseline.slurm"
    --require-output raw/stems/vocals.flac
    --quiet
  )
  case "$preset" in
    vocal_quality_a)
      validator_args+=(--require-output raw/stems/instrumental.flac)
      ;;
    multistem_quality_a)
      validator_args+=(
        --require-output raw/stems/drums.flac
        --require-output raw/stems/bass.flac
        --require-output raw/stems/other.flac
      )
      ;;
    *)
      echo "Unsupported separator preset in checkpoint resolver: $preset" >&2
      return 2
      ;;
  esac
  "$ROOT_PYTHON" "$VERIFY_RUN_MANIFEST" "${validator_args[@]}"
}

RESERVED_RUN_IDS=""
RESOLVED_RUN_ID=""
RESOLVED_RUN_SKIP=""

resolve_run_id() {
  local preset="$1"
  local base_run_id="$2"
  local attempt=0
  local candidate="$base_run_id"
  local candidate_dir

  while (( attempt <= 9999 )); do
    validate_run_id "$candidate"
    candidate_dir="$PROJECT_DIR/runs/$candidate"
    if [[ "|$RESERVED_RUN_IDS|" == *"|$candidate|"* ]]; then
      echo "Run ID candidate is already reserved in this job: $candidate" >&2
    elif [[ ! -e "$candidate_dir" && ! -L "$candidate_dir" ]]; then
      RESOLVED_RUN_ID="$candidate"
      RESOLVED_RUN_SKIP=0
      RESERVED_RUN_IDS="${RESERVED_RUN_IDS}|${candidate}"
      return 0
    elif run_manifest_is_valid "$preset" "$candidate"; then
      echo "Reusing verified immutable run; inference will be skipped: $candidate"
      RESOLVED_RUN_ID="$candidate"
      RESOLVED_RUN_SKIP=1
      RESERVED_RUN_IDS="${RESERVED_RUN_IDS}|${candidate}"
      return 0
    else
      echo "Preserving incomplete or invalid run and trying a new ID: $candidate" >&2
    fi
    attempt=$((attempt + 1))
    candidate="${base_run_id}-attempt-${attempt}"
  done
  echo "Could not allocate a free attempt ID for base run: $base_run_id" >&2
  exit 2
}

resolve_run_id vocal_quality_a "$VOCAL_BASE_RUN_ID"
VOCAL_RUN_ID="$RESOLVED_RUN_ID"
VOCAL_RUN_SKIP="$RESOLVED_RUN_SKIP"
resolve_run_id multistem_quality_a "$MULTISTEM_BASE_RUN_ID"
MULTISTEM_RUN_ID="$RESOLVED_RUN_ID"
MULTISTEM_RUN_SKIP="$RESOLVED_RUN_SKIP"

printf 'resolved_vocal_run_id=%q skip=%s\n' "$VOCAL_RUN_ID" "$VOCAL_RUN_SKIP"
printf 'resolved_multistem_run_id=%q skip=%s\n' \
  "$MULTISTEM_RUN_ID" "$MULTISTEM_RUN_SKIP"

if [[ "$VOCAL_RUN_SKIP" == 1 && "$MULTISTEM_RUN_SKIP" == 1 ]]; then
  echo "Both separator runs are complete and verified; nothing to run."
  exit 0
fi

: "${SEPARATOR_MODEL_DIR:?Export SEPARATOR_MODEL_DIR in persistent storage}"
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
if [[ ! -x "$WORKER_ENV/bin/python" ||
      ! -x "$WORKER_ENV/bin/audio-separator" ]]; then
  echo "Run slurm/15_separator_setup.slurm before separator inference." >&2
  exit 2
fi

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
for name in \
  SLURM_JOB_ID \
  SLURM_JOB_NAME \
  SLURM_JOB_ACCOUNT \
  SLURM_JOB_PARTITION \
  SLURM_CPUS_PER_TASK \
  SLURM_GPUS \
  CUDA_VISIBLE_DEVICES \
  AMT_REPO_ROOT \
  AMT_ROOT_PYTHON \
  PROJECT_DIR \
  SEPARATOR_ENV \
  SEPARATOR_MODEL_DIR \
  SEPARATOR_PINS \
  SEPARATOR_AUDIO \
  SEPARATOR_RUN_ID_PREFIX \
  SEPARATOR_VOCAL_RUN_ID \
  SEPARATOR_MULTISTEM_RUN_ID \
  FFMPEG_MODULE
do
  print_env_value "$name"
done
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
ffmpeg -version
ffprobe -version
"$ROOT_PYTHON" --version
"$WORKER_ENV/bin/python" -c \
  'import torch; print({"torch": torch.__version__, "cuda": torch.version.cuda, "available": torch.cuda.is_available(), "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None})'
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO_ROOT" rev-parse HEAD
  git -C "$REPO_ROOT" status --porcelain
else
  echo "Git metadata unavailable in the synced HYAK copy; runner records commit=null."
fi

run_separator() {
  local preset="$1"
  local run_id="$2"
  local runner_args=(
    --project "$PROJECT_DIR"
    --worker-env "$WORKER_ENV"
    --model-dir "$SEPARATOR_MODEL_DIR"
    --pins "$PINS_PATH"
    --run-id "$run_id"
    --preset "$preset"
    --audio "$INPUT_AUDIO"
  )
  srun "$ROOT_PYTHON" "$REPO_ROOT/workers/separator/run_baseline.py" \
    "${runner_args[@]}"
}

cd "$REPO_ROOT"
if [[ "$VOCAL_RUN_SKIP" == 0 ]]; then
  run_separator vocal_quality_a "$VOCAL_RUN_ID"
  run_manifest_is_valid vocal_quality_a "$VOCAL_RUN_ID"
fi
if [[ "$MULTISTEM_RUN_SKIP" == 0 ]]; then
  run_separator multistem_quality_a "$MULTISTEM_RUN_ID"
  run_manifest_is_valid multistem_quality_a "$MULTISTEM_RUN_ID"
fi
