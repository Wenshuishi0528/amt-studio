#!/bin/bash
#SBATCH --job-name=amt-game-vocal
#SBATCH --account=gpu-l40-stf
#SBATCH --partition=gpu-l40
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --gpus=l40:1
#SBATCH --time=01:00:00
#SBATCH --export=ALL

set -euo pipefail
umask 077

: "${AMT_REPO_ROOT:?Missing AMT_REPO_ROOT}"
: "${PROJECT_DIR:?Missing PROJECT_DIR}"
: "${SEPARATOR_MODEL_DIR:?Missing SEPARATOR_MODEL_DIR}"
: "${GAME_MODEL_PROVENANCE:?Missing GAME_MODEL_PROVENANCE}"
: "${SEPARATOR_VOCAL_RUN_ID:?Missing SEPARATOR_VOCAL_RUN_ID}"
: "${GAME_RUN_ID:?Missing GAME_RUN_ID}"
: "${AMT_BUNDLE_ID:?Missing AMT_BUNDLE_ID}"

case "$(hostname)" in
  *-login*|klone-login*)
    echo "Refusing to run source separation or GAME on a login node." >&2
    exit 2
    ;;
esac

ROOT_PYTHON="${AMT_ROOT_PYTHON:-$AMT_REPO_ROOT/.venv/bin/python}"
SEPARATOR_ENV="${SEPARATOR_ENV:-$AMT_REPO_ROOT/workers/separator/.venv}"
GAME_ENV="${GAME_ENV:-$AMT_REPO_ROOT/workers/game/.venv}"
BEAT_THIS_ENV="${BEAT_THIS_ENV:-$AMT_REPO_ROOT/workers/beat_this/.venv}"
BEAT_THIS_PINS="${BEAT_THIS_PINS:-$AMT_REPO_ROOT/workers/beat_this/pins.json}"
BEAT_THIS_CHECKPOINT="${BEAT_THIS_CHECKPOINT:-$(dirname "$AMT_REPO_ROOT")/models/beat-this/final0.ckpt}"
CANONICAL_AUDIO="$PROJECT_DIR/audio/canonical/mix.flac"
SEPARATOR_RUN_DIR="$PROJECT_DIR/runs/$SEPARATOR_VOCAL_RUN_ID"
VOCAL_STEM="$SEPARATOR_RUN_DIR/raw/stems/vocals.flac"
GAME_RUN_DIR="$PROJECT_DIR/runs/$GAME_RUN_ID"
RHYTHM_RUN_ID="${BEAT_THIS_RUN_ID:-${GAME_RUN_ID}-rhythm}"
RHYTHM_RUN_DIR="$PROJECT_DIR/runs/$RHYTHM_RUN_ID"
BUNDLE_DIR="$PROJECT_DIR/exports/$AMT_BUNDLE_ID"

for path in \
  "$AMT_REPO_ROOT" \
  "$PROJECT_DIR" \
  "$SEPARATOR_MODEL_DIR" \
  "$GAME_MODEL_PROVENANCE" \
  "$ROOT_PYTHON" \
  "$SEPARATOR_ENV" \
  "$GAME_ENV"
do
  if [[ "$path" != /* ]]; then
    echo "GAME product paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" ||
      ! -x "$SEPARATOR_ENV/bin/python" ||
      ! -x "$GAME_ENV/bin/python" ||
      ! -f "$CANONICAL_AUDIO" ||
      ! -d "$SEPARATOR_MODEL_DIR" ||
      ! -f "$GAME_MODEL_PROVENANCE" ]]; then
  echo "GAME, separator, canonical audio, or private model assets are unavailable." >&2
  exit 2
fi

set +u
if ! command -v module >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source /etc/profile.d/lmod.sh
  module use /sw/klone /sw/contrib/modulefiles
fi
module --ignore_cache load "${AMT_FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"
set -u
FFPROBE="$(command -v ffprobe)"

cd "$AMT_REPO_ROOT"
hostname
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader
echo "GAME official weights are CC-BY-NC-SA-4.0; this route is private non-commercial research."

srun "$ROOT_PYTHON" workers/separator/run_baseline.py \
  --project "$PROJECT_DIR" \
  --worker-env "$SEPARATOR_ENV" \
  --model-dir "$SEPARATOR_MODEL_DIR" \
  --pins "$AMT_REPO_ROOT/workers/separator/pins.json" \
  --run-id "$SEPARATOR_VOCAL_RUN_ID" \
  --preset vocal_quality_a \
  --audio "$CANONICAL_AUDIO"

if [[ ! -f "$VOCAL_STEM" ]]; then
  echo "Separator finished without the required vocal stem: $VOCAL_STEM" >&2
  exit 2
fi

srun "$ROOT_PYTHON" workers/game/run_baseline.py \
  --project "$PROJECT_DIR" \
  --audio "$VOCAL_STEM" \
  --worker-env "$GAME_ENV" \
  --model-provenance "$GAME_MODEL_PROVENANCE" \
  --pins "$AMT_REPO_ROOT/workers/game/pins.json" \
  --run-id "$GAME_RUN_ID" \
  --seed 3407 \
  --ffprobe "$FFPROBE" \
  --require-cuda

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
  echo "Beat analysis failed; GAME MIDI will use the explicit default grid." >&2
fi

"$ROOT_PYTHON" -m amt_core.cli build-game-vocal \
  "$PROJECT_DIR" \
  --run "$GAME_RUN_DIR" \
  "${RHYTHM_BUNDLE_ARGS[@]}" \
  --output "$BUNDLE_DIR"
