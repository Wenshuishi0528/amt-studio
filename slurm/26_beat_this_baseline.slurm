#!/bin/bash
#SBATCH --job-name=amt-beat-baseline
#SBATCH --account=stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt-gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --gpus=a40:1
#SBATCH --time=01:00:00
#SBATCH --requeue
#SBATCH --signal=B:TERM@120
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Submit this script with sbatch; do not run Beat This on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${PROJECT_DIR:?Export PROJECT_DIR as the initialized private project}"
: "${BEAT_THIS_CHECKPOINT:?Export BEAT_THIS_CHECKPOINT in persistent storage}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
WORKER_ENV="${BEAT_THIS_ENV:-$REPO_ROOT/workers/beat_this/.venv}"
PINS_PATH="${BEAT_THIS_PINS:-$REPO_ROOT/workers/beat_this/pins.json}"
RUN_BASE="${BEAT_THIS_RUN_ID:-beat-this-task005-final0-${SLURM_JOB_ID}}"
VERIFY_RUN_MANIFEST="$REPO_ROOT/scripts/verify_run_manifest.py"
FFMPEG_MODULE="${FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"

validate_run_id() {
  local run_id="$1"
  if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ||
        "$run_id" == *".."* ||
        ${#run_id} -gt 180 ]]; then
    echo "Unsafe Beat This run ID: $run_id" >&2
    exit 2
  fi
}
for path in "$REPO_ROOT" "$PROJECT_DIR" "$BEAT_THIS_CHECKPOINT" "$ROOT_PYTHON" \
  "$WORKER_ENV" "$PINS_PATH" "$VERIFY_RUN_MANIFEST"; do
  if [[ "$path" != /* ]]; then
    echo "All Beat This baseline paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" ||
      ! -x "$WORKER_ENV/bin/python" ||
      ! -f "$BEAT_THIS_CHECKPOINT" ||
      ! -f "$PINS_PATH" ||
      ! -f "$VERIFY_RUN_MANIFEST" ]]; then
  echo "Beat This environment, checkpoint, pins, or verifier is unavailable." >&2
  exit 2
fi
validate_run_id "$RUN_BASE"

CANONICAL_MIX="$PROJECT_DIR/audio/canonical/mix.flac"
if [[ ! -f "$CANONICAL_MIX" ]]; then
  echo "Canonical mix is unavailable." >&2
  exit 2
fi
read -r CANONICAL_SHA PINS_SHA < <(
  "$ROOT_PYTHON" - "$CANONICAL_MIX" "$PINS_PATH" <<'PY'
import hashlib
import pathlib
import sys

print(*(hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest() for path in sys.argv[1:]))
PY
)

run_manifest_is_valid() {
  local run_id="$1"
  "$ROOT_PYTHON" "$VERIFY_RUN_MANIFEST" \
    --run-dir "$PROJECT_DIR/runs/$run_id" \
    --worker beat_this \
    --input "$CANONICAL_MIX" \
    --pins "$PINS_PATH" \
    --repo-root "$REPO_ROOT" \
    --source "$PINS_PATH" \
    --source "$REPO_ROOT/workers/beat_this/pyproject.toml" \
    --source "$REPO_ROOT/workers/beat_this/uv.lock" \
    --source "$REPO_ROOT/workers/beat_this/normalize.py" \
    --source "$REPO_ROOT/workers/beat_this/run_baseline.py" \
    --source "$REPO_ROOT/src/amt_core/canonical.py" \
    --source "$REPO_ROOT/src/amt_core/contracts.py" \
    --source "$REPO_ROOT/src/amt_core/utils.py" \
    --source "$VERIFY_RUN_MANIFEST" \
    --source "$REPO_ROOT/slurm/26_beat_this_baseline.slurm" \
    --expect-field 'contract_version="amt-worker-result/v1"' \
    --expect-field "code.pins_sha256=\"$PINS_SHA\"" \
    --expect-field "input_lineage.canonical_mix_sha256=\"$CANONICAL_SHA\"" \
    --expect-field 'configuration.checkpoint="final0"' \
    --expect-field configuration.dbn=false \
    --expect-field configuration.float16=false \
    --expect-field configuration.activations=true \
    --expect-field 'configuration.postprocessor="minimal"' \
    --expect-field configuration.frame_rate_hz=50 \
    --expect-field 'environment.beat_this="1.1.0"' \
    --expect-field 'environment.torch="2.8.0+cu129"' \
    --expect-field 'environment.torchaudio="2.8.0+cu129"' \
    --expect-field 'environment.soundfile="0.13.1"' \
    --expect-field environment.cuda_available=true \
    --require-output raw/native/mix.beats \
    --require-output raw/native/mix.npy \
    --require-output normalized/rhythm.json \
    --require-output normalized/summary.json \
    --quiet
}

RUN_ID="$RUN_BASE"
ATTEMPT=0
while [[ -e "$PROJECT_DIR/runs/$RUN_ID" || -L "$PROJECT_DIR/runs/$RUN_ID" ]]; do
  if run_manifest_is_valid "$RUN_ID"; then
    echo "Reusing verified immutable Beat This run: $RUN_ID"
    exit 0
  fi
  ATTEMPT=$((ATTEMPT + 1))
  if (( ATTEMPT > 9999 )); then
    echo "Could not allocate a Beat This attempt run ID." >&2
    exit 2
  fi
  RUN_ID="${RUN_BASE}-attempt-${ATTEMPT}"
  validate_run_id "$RUN_ID"
done

set +u
if ! type module >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source /etc/profile.d/lmod.sh
  module use /sw/klone /sw/contrib/modulefiles
fi
module --ignore_cache load "$FFMPEG_MODULE"
set -u
if ! command -v ffprobe >/dev/null; then
  echo "Pinned FFmpeg module did not provide ffprobe." >&2
  exit 2
fi

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "resolved_run_id=$RUN_ID"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO_ROOT" rev-parse HEAD
  git -C "$REPO_ROOT" status --porcelain
fi

cd "$REPO_ROOT"
srun "$ROOT_PYTHON" "$REPO_ROOT/workers/beat_this/run_baseline.py" \
  --project "$PROJECT_DIR" \
  --worker-env "$WORKER_ENV" \
  --checkpoint "$BEAT_THIS_CHECKPOINT" \
  --pins "$PINS_PATH" \
  --run-id "$RUN_ID" \
  --ffprobe "$(command -v ffprobe)" \
  --require-cuda
run_manifest_is_valid "$RUN_ID"
echo "beat_this_run_id=$RUN_ID"
