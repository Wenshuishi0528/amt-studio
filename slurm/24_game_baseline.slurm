#!/bin/bash
#SBATCH --job-name=amt-game-baseline
#SBATCH --account=stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt-gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --gpus=a40:1
#SBATCH --time=03:00:00
#SBATCH --requeue
#SBATCH --signal=B:TERM@120
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Submit this script with sbatch; do not run GAME inference on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${PROJECT_DIR:?Export PROJECT_DIR as the initialized private project}"
: "${GAME_AUDIO:?Export GAME_AUDIO as the selected vocal stem}"
: "${GAME_MODEL_PROVENANCE:?Export GAME_MODEL_PROVENANCE in persistent storage}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
WORKER_ENV="${GAME_ENV:-$REPO_ROOT/workers/game/.venv}"
PINS_PATH="${GAME_PINS:-$REPO_ROOT/workers/game/pins.json}"
RUN_BASE="${GAME_RUN_ID:-game-task004-medium-${SLURM_JOB_ID}}"
SEED="${GAME_SEED:-3407}"
VERIFY_RUN_MANIFEST="$REPO_ROOT/scripts/verify_run_manifest.py"
FFMPEG_MODULE="${FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"

validate_run_id() {
  local run_id="$1"
  if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ||
        "$run_id" == *".."* ||
        ${#run_id} -gt 180 ]]; then
    echo "Unsafe GAME run ID: $run_id" >&2
    exit 2
  fi
}

for path in "$REPO_ROOT" "$PROJECT_DIR" "$GAME_AUDIO" "$GAME_MODEL_PROVENANCE" \
  "$ROOT_PYTHON" "$WORKER_ENV" "$PINS_PATH" "$VERIFY_RUN_MANIFEST"; do
  if [[ "$path" != /* ]]; then
    echo "All GAME baseline paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" ||
      ! -x "$WORKER_ENV/bin/python" ||
      ! -f "$GAME_AUDIO" ||
      ! -f "$GAME_MODEL_PROVENANCE" ||
      ! -f "$PINS_PATH" ||
      ! -f "$VERIFY_RUN_MANIFEST" ]]; then
  echo "GAME environment, input, provenance, pins, or verifier is unavailable." >&2
  exit 2
fi
if [[ ! "$SEED" =~ ^[0-9]+$ ]]; then
  echo "GAME_SEED must be a non-negative integer." >&2
  exit 2
fi
validate_run_id "$RUN_BASE"

OUTPUT_STEM="$(basename "$GAME_AUDIO")"
OUTPUT_STEM="${OUTPUT_STEM%.*}"
PINS_SHA="$("$ROOT_PYTHON" - "$PINS_PATH" <<'PY'
import hashlib
import pathlib
import sys
print(hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest())
PY
)"
CANONICAL_MIX="$PROJECT_DIR/audio/canonical/mix.flac"
PARENT_RUN_DIR="$(dirname "$(dirname "$(dirname "$GAME_AUDIO")")")"
PARENT_MANIFEST="$PARENT_RUN_DIR/run_manifest.json"
if [[ ! -f "$CANONICAL_MIX" || ! -f "$PARENT_MANIFEST" ]]; then
  echo "Canonical mix or parent separator manifest is unavailable." >&2
  exit 2
fi
read -r CANONICAL_SHA PARENT_MANIFEST_SHA < <(
  "$ROOT_PYTHON" - "$CANONICAL_MIX" "$PARENT_MANIFEST" <<'PY'
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
    --worker game \
    --input "$GAME_AUDIO" \
    --repo-root "$REPO_ROOT" \
    --source "$PINS_PATH" \
    --source "$GAME_MODEL_PROVENANCE" \
    --source "$REPO_ROOT/workers/game/pyproject.toml" \
    --source "$REPO_ROOT/workers/game/uv.lock" \
    --source "$REPO_ROOT/workers/game/normalize.py" \
    --source "$REPO_ROOT/workers/game/prepare_assets.py" \
    --source "$REPO_ROOT/workers/game/seeded_infer.py" \
    --source "$REPO_ROOT/workers/game/run_baseline.py" \
    --source "$REPO_ROOT/src/amt_core/events.py" \
    --source "$REPO_ROOT/src/amt_core/utils.py" \
    --source "$VERIFY_RUN_MANIFEST" \
    --source "$REPO_ROOT/slurm/24_game_baseline.slurm" \
    --expect-field "code.pins_sha256=\"$PINS_SHA\"" \
    --expect-field 'code.upstream_commit="475a8ee781fe8cca980b3b12fbe6c80c768a813a"' \
    --expect-field 'model="GAME-1.0-medium"' \
    --expect-field 'input_lineage.kind="separator_vocal_stem"' \
    --expect-field "input_lineage.canonical_mix_sha256=\"$CANONICAL_SHA\"" \
    --expect-field "input_lineage.parent_manifest_sha256=\"$PARENT_MANIFEST_SHA\"" \
    --expect-field 'decoding.language="ja"' \
    --expect-field decoding.batch_size=4 \
    --expect-field decoding.num_workers=0 \
    --expect-field decoding.seg_threshold=0.2 \
    --expect-field decoding.seg_radius=0.02 \
    --expect-field decoding.t0=0.0 \
    --expect-field decoding.nsteps=8 \
    --expect-field decoding.est_threshold=0.2 \
    --expect-field decoding.tempo_bpm=120 \
    --expect-field 'decoding.pitch_format="number"' \
    --expect-field decoding.round_pitch=false \
    --expect-field "decoding.seed=$SEED" \
    --expect-field 'environment.torch="2.8.0+cu129"' \
    --expect-field 'environment.lightning="2.6.1"' \
    --expect-field environment.cuda_available=true \
    --expect-field 'environment.cuda_version="12.9"' \
    --require-output "raw/native/$OUTPUT_STEM.csv" \
    --require-output "raw/native/$OUTPUT_STEM.txt" \
    --require-output "raw/native/$OUTPUT_STEM.mid" \
    --require-output normalized/events.jsonl \
    --require-output normalized/summary.json \
    --quiet
}

RUN_ID="$RUN_BASE"
ATTEMPT=0
while [[ -e "$PROJECT_DIR/runs/$RUN_ID" || -L "$PROJECT_DIR/runs/$RUN_ID" ]]; do
  if run_manifest_is_valid "$RUN_ID"; then
    echo "Reusing verified immutable GAME run: $RUN_ID"
    exit 0
  fi
  ATTEMPT=$((ATTEMPT + 1))
  if (( ATTEMPT > 9999 )); then
    echo "Could not allocate a GAME attempt run ID." >&2
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
echo "game_seed=$SEED"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
"$WORKER_ENV/bin/python" -c \
  'import torch; print({"torch": torch.__version__, "cuda": torch.version.cuda, "available": torch.cuda.is_available(), "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None})'
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO_ROOT" rev-parse HEAD
  git -C "$REPO_ROOT" status --porcelain
fi

cd "$REPO_ROOT"
srun "$ROOT_PYTHON" "$REPO_ROOT/workers/game/run_baseline.py" \
  --project "$PROJECT_DIR" \
  --audio "$GAME_AUDIO" \
  --worker-env "$WORKER_ENV" \
  --model-provenance "$GAME_MODEL_PROVENANCE" \
  --pins "$PINS_PATH" \
  --run-id "$RUN_ID" \
  --seed "$SEED" \
  --ffprobe "$(command -v ffprobe)" \
  --require-cuda
run_manifest_is_valid "$RUN_ID"
echo "game_run_id=$RUN_ID"
