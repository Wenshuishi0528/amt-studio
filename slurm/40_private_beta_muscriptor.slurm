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
RAW_BUNDLE_ID="${AMT_BUNDLE_ID}-raw"
RAW_BUNDLE_DIR="$PROJECT_DIR/exports/$RAW_BUNDLE_ID"
AUTO_GAP_PROBE_ID="${MUSCRIPTOR_RUN_ID}-auto-gap"
RHYTHM_RUN_ID="${BEAT_THIS_RUN_ID:-${MUSCRIPTOR_RUN_ID}-rhythm}"
RHYTHM_RUN_DIR="$PROJECT_DIR/runs/$RHYTHM_RUN_ID"
BEAT_THIS_ENV="${BEAT_THIS_ENV:-$AMT_REPO_ROOT/workers/beat_this/.venv}"
BEAT_THIS_PINS="${BEAT_THIS_PINS:-$AMT_REPO_ROOT/workers/beat_this/pins.json}"
BEAT_THIS_CHECKPOINT="${BEAT_THIS_CHECKPOINT:-$(dirname "$AMT_REPO_ROOT")/models/beat-this/final0.ckpt}"

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

if ! command -v ffmpeg >/dev/null 2>&1; then
  set +u
  module load "${AMT_FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"
  set -u
fi
FFMPEG="$(command -v ffmpeg)"
FFPROBE="$(command -v ffprobe)"

RHYTHM_BUNDLE_ARGS=()
if srun "$ROOT_PYTHON" workers/beat_this/run_baseline.py \
  --project "$PROJECT_DIR" \
  --worker-env "$BEAT_THIS_ENV" \
  --checkpoint "$BEAT_THIS_CHECKPOINT" \
  --pins "$BEAT_THIS_PINS" \
  --run-id "$RHYTHM_RUN_ID" \
  --ffprobe "$FFPROBE" \
  --require-cuda; then
  RHYTHM_BUNDLE_ARGS=(--beat-run "$RHYTHM_RUN_DIR")
else
  echo "Beat analysis failed; continuing with the explicit default MIDI grid." >&2
fi

"$ROOT_PYTHON" -m amt_core.cli build-muscriptor-multitrack \
  "$PROJECT_DIR" \
  --run "$RUN_DIR" \
  "${RHYTHM_BUNDLE_ARGS[@]}" \
  --output "$RAW_BUNDLE_DIR"

if srun "$ROOT_PYTHON" workers/muscriptor/gap_probe.py \
  --project "$PROJECT_DIR" \
  --auto-source-bundle "$RAW_BUNDLE_ID" \
  --probe-id "$AUTO_GAP_PROBE_ID" \
  --output-bundle "$AMT_BUNDLE_ID" \
  --source-voice-track voice \
  --worker-env "$WORKER_ENV" \
  --weight-provenance "$MUSCRIPTOR_WEIGHT_PROVENANCE" \
  --ffmpeg "$FFMPEG"; then
  echo "Automatic same-model voice-gap recovery finished."
else
  echo "Automatic voice-gap recovery failed; publishing raw multitrack fallback." >&2
  "$ROOT_PYTHON" -m amt_core.cli build-muscriptor-multitrack \
    "$PROJECT_DIR" \
    --run "$RUN_DIR" \
    "${RHYTHM_BUNDLE_ARGS[@]}" \
    --output "$BUNDLE_DIR"
fi
