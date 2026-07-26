#!/bin/bash
#SBATCH --job-name=amt-t007b-voc-candidates
#SBATCH --account=ckpt-stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt-gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gpus=a40:1
#SBATCH --time=04:00:00
#SBATCH --requeue
#SBATCH --signal=B:TERM@120
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Submit with sbatch; do not execute candidate inference on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${TASK007B_DATA_ROOT:?Export the persistent Task 007B artifact root}"
: "${TASK007_PROJECTS_ROOT:?Export the persistent private projects root}"
: "${SEPARATOR_MODEL_DIR:?Export the pinned separator model directory}"
: "${GAME_MODEL_PROVENANCE:?Export the pinned GAME model provenance JSON}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
LOG_DIR="$TASK007B_DATA_ROOT/logs/candidates/${SLURM_JOB_ID}"
DEVELOPMENT_PROJECT="$TASK007_PROJECTS_ROOT/vocadito-task007b-development-v2"
BLIND_PROJECT="$TASK007_PROJECTS_ROOT/vocadito-task007b-blind-v2"
BLIND_PACK="$BLIND_PROJECT/annotations/external-note-task007b-blind-v2"

for path in \
  "$REPO_ROOT" \
  "$ROOT_PYTHON" \
  "$TASK007B_DATA_ROOT" \
  "$TASK007_PROJECTS_ROOT" \
  "$SEPARATOR_MODEL_DIR" \
  "$GAME_MODEL_PROVENANCE"
do
  if [[ "$path" != /* ]]; then
    echo "All Task 007B candidate paths must be absolute: $path" >&2
    exit 2
  fi
done
if [[ ! -x "$ROOT_PYTHON" ||
      ! -d "$SEPARATOR_MODEL_DIR" ||
      ! -f "$GAME_MODEL_PROVENANCE" ||
      ! -f "$DEVELOPMENT_PROJECT/manifest.json" ||
      ! -f "$BLIND_PROJECT/manifest.json" ||
      ! -f "$BLIND_PACK/benchmark_manifest.json" ]]; then
  echo "Preparation output, model assets, or root Python is unavailable." >&2
  exit 2
fi

mkdir -p "$LOG_DIR"
exec > >(tee "$LOG_DIR/stdout.log") 2> >(tee "$LOG_DIR/stderr.log" >&2)

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "SLURM_JOB_ID=$SLURM_JOB_ID"
echo "SLURM_JOB_PARTITION=${SLURM_JOB_PARTITION:-}"
echo "SLURM_GPUS=${SLURM_GPUS:-}"
echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES:-}"
printf 'AMT_REPO_ROOT=%q\n' "$REPO_ROOT"
printf 'TASK007B_DATA_ROOT=%q\n' "$TASK007B_DATA_ROOT"
printf 'TASK007_PROJECTS_ROOT=%q\n' "$TASK007_PROJECTS_ROOT"
"$ROOT_PYTHON" --version
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
git -C "$REPO_ROOT" rev-parse HEAD
git -C "$REPO_ROOT" status --porcelain

export AMT_REPO_ROOT="$REPO_ROOT"
export AMT_ROOT_PYTHON="$ROOT_PYTHON"

run_split_candidates() {
  local split_name="$1"
  local run_token="$2"
  local project="$3"
  local pack="$4"
  local seal_after="$5"
  local separator_vocal_run="separator-t007b-voc-${run_token}-vocal-a"
  local separator_multistem_run="separator-t007b-voc-${run_token}-multistem-a"
  local vocal_a="$project/runs/$separator_vocal_run/raw/stems/vocals.flac"
  local game_run="game-t007b-voc-${run_token}-medium"
  local basic_pitch_run="basic-pitch-t007b-voc-${run_token}-onnx"

  echo "candidate_split=$split_name"
  export PROJECT_DIR="$project"
  export SEPARATOR_VOCAL_RUN_ID="$separator_vocal_run"
  export SEPARATOR_MULTISTEM_RUN_ID="$separator_multistem_run"
  bash "$REPO_ROOT/slurm/16_separator_baseline.slurm"

  export GAME_AUDIO="$vocal_a"
  export GAME_RUN_ID="$game_run"
  export GAME_SEED="3407"
  bash "$REPO_ROOT/slurm/24_game_baseline.slurm"

  export BASIC_PITCH_AUDIO="$vocal_a"
  export BASIC_PITCH_RUN_ID="$basic_pitch_run"
  bash "$REPO_ROOT/slurm/22_basic_pitch_baseline.slurm"

  if [[ "$seal_after" == "yes" ]]; then
    "$ROOT_PYTHON" "$REPO_ROOT/scripts/freeze_evaluation_candidates.py" \
      --pack-dir "$pack" \
      --candidate "game-vocal-a=$project/runs/$game_run/normalized/events.jsonl" \
      --candidate \
      "basic-pitch-vocal-a=$project/runs/$basic_pitch_run/normalized/events.jsonl" \
      --confirm-output-quality-uninspected
  fi
}

validate_existing_blind_seal() {
  "$ROOT_PYTHON" - "$BLIND_PACK" <<'PY'
import pathlib
import sys

from scripts.evaluate_external_notes import (
    _verified_benchmark,
    _verified_candidate_set,
)

pack = pathlib.Path(sys.argv[1]).resolve(strict=True)
snapshots = {}
manifest, payload = _verified_benchmark(pack, snapshots)
_seal, candidates = _verified_candidate_set(
    pack,
    manifest,
    payload,
    snapshots,
)
expected = {
    "game-vocal-a": ("game-t007b-voc-blind-medium", "game"),
    "basic-pitch-vocal-a": ("basic-pitch-t007b-voc-blind-onnx", "basic_pitch"),
}
observed = {
    record["label"]: (record["run_id"], record["worker"])
    for record, _events in candidates
}
if observed != expected:
    raise SystemExit(f"sealed candidate identity mismatch: {observed!r}")
print("Existing Task 007B blind candidate set is hash-verified and will be reused.")
PY
}

cd "$REPO_ROOT"
run_split_candidates \
  development dev "$DEVELOPMENT_PROJECT" \
  "$DEVELOPMENT_PROJECT/annotations/external-note-task007b-development-v2" no
if [[ -e "$BLIND_PACK/candidate_set_seal.json" ||
      -L "$BLIND_PACK/candidate_set_seal.json" ]]; then
  validate_existing_blind_seal
else
  run_split_candidates blind_test blind "$BLIND_PROJECT" "$BLIND_PACK" yes
fi
