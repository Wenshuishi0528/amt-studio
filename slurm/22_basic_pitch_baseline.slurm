#!/bin/bash
#SBATCH --job-name=amt-basic-pitch
#SBATCH --account=stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=03:00:00
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
: "${BASIC_PITCH_AUDIO:?Export BASIC_PITCH_AUDIO as a selected vocal stem or the exact canonical mix}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
WORKER_ENV="${BASIC_PITCH_ENV:-$REPO_ROOT/workers/basic_pitch/.venv}"
PINS_PATH="${BASIC_PITCH_PINS:-$REPO_ROOT/workers/basic_pitch/pins.json}"
INPUT_AUDIO="$BASIC_PITCH_AUDIO"
BASE_RUN_ID="${BASIC_PITCH_RUN_ID:-basic-pitch-onnx-${SLURM_JOB_ID}}"
VERIFY_RUN_MANIFEST="$REPO_ROOT/scripts/verify_run_manifest.py"

validate_run_id() {
  local run_id="$1"
  if [[ ! "$run_id" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ||
        "$run_id" == *".."* ||
        ${#run_id} -gt 128 ]]; then
    echo "Unsafe run ID: $run_id" >&2
    exit 2
  fi
}

if [[ "$REPO_ROOT" != /* ||
      "$PROJECT_DIR" != /* ||
      "$INPUT_AUDIO" != /* ]]; then
  echo "AMT_REPO_ROOT, PROJECT_DIR, and BASIC_PITCH_AUDIO must be absolute." >&2
  exit 2
fi
if [[ ! -x "$ROOT_PYTHON" ||
      ! -f "$VERIFY_RUN_MANIFEST" ||
      ! -f "$PINS_PATH" ||
      ! -f "$INPUT_AUDIO" ]]; then
  echo "Root Python, verifier, pins, or Basic Pitch input is unavailable." >&2
  exit 2
fi
validate_run_id "$BASE_RUN_ID"
if [[ ${#BASE_RUN_ID} -gt 110 ]]; then
  echo "Base run ID is too long to add a safe attempt suffix: $BASE_RUN_ID" >&2
  exit 2
fi

NATIVE_PREFIX="$("$ROOT_PYTHON" - "$INPUT_AUDIO" <<'PY'
import pathlib
import sys

stem = pathlib.Path(sys.argv[1]).stem
if (
    not stem
    or stem in {".", ".."}
    or "/" in stem
    or any(ord(character) < 32 or ord(character) == 127 for character in stem)
):
    raise SystemExit("Unsafe Basic Pitch native output prefix")
print(f"{stem}_basic_pitch")
PY
)"
CANONICAL_MIX="$PROJECT_DIR/audio/canonical/mix.flac"
if [[ ! -f "$CANONICAL_MIX" ]]; then
  echo "Canonical mix is unavailable." >&2
  exit 2
fi
read -r INPUT_KIND CANONICAL_SHA PARENT_MANIFEST_SHA < <(
  "$ROOT_PYTHON" - "$CANONICAL_MIX" "$INPUT_AUDIO" <<'PY'
import hashlib
import pathlib
import sys

canonical = pathlib.Path(sys.argv[1]).resolve(strict=True)
audio = pathlib.Path(sys.argv[2]).resolve(strict=True)
canonical_sha = hashlib.sha256(canonical.read_bytes()).hexdigest()
if audio == canonical:
    print("direct_canonical_mix", canonical_sha, "-")
else:
    try:
        relative = audio.relative_to(canonical.parents[2] / "runs")
    except ValueError as exc:
        raise SystemExit("Basic Pitch input is neither canonical mix nor project run audio") from exc
    if (
        len(relative.parts) != 4
        or relative.parts[1:3] != ("raw", "stems")
        or pathlib.Path(relative.parts[3]).stem != "vocals"
    ):
        raise SystemExit("Basic Pitch non-mix input must be a separator vocals stem")
    parent_manifest = canonical.parents[2] / "runs" / relative.parts[0] / "run_manifest.json"
    if not parent_manifest.is_file():
        raise SystemExit("Parent separator manifest is unavailable")
    parent_sha = hashlib.sha256(parent_manifest.read_bytes()).hexdigest()
    print("separator_vocal_stem", canonical_sha, parent_sha)
PY
)

run_manifest_is_valid() {
  local run_id="$1"
  local verify_args=(
    --run-dir "$PROJECT_DIR/runs/$run_id" \
    --worker basic_pitch \
    --input "$INPUT_AUDIO" \
    --repo-root "$REPO_ROOT" \
    --source "$PINS_PATH" \
    --source "$REPO_ROOT/workers/basic_pitch/pyproject.toml" \
    --source "$REPO_ROOT/workers/basic_pitch/uv.lock" \
    --source "$REPO_ROOT/workers/basic_pitch/normalize.py" \
    --source "$REPO_ROOT/workers/basic_pitch/run_baseline.py" \
    --source "$REPO_ROOT/src/amt_core/events.py" \
    --source "$REPO_ROOT/src/amt_core/utils.py" \
    --source "$VERIFY_RUN_MANIFEST" \
    --source "$REPO_ROOT/slurm/22_basic_pitch_baseline.slurm" \
    --expect-field 'model="basic-pitch-icassp-2022-onnx"' \
    --expect-field 'model_provenance.serialization="onnx"' \
    --expect-field 'model_provenance.onnxruntime_provider="CPUExecutionProvider"' \
    --expect-field "input_lineage.kind=\"$INPUT_KIND\"" \
    --expect-field "input_lineage.canonical_mix_sha256=\"$CANONICAL_SHA\"" \
    --expect-field decoding.onset_threshold=0.5 \
    --expect-field decoding.frame_threshold=0.3 \
    --expect-field decoding.minimum_note_length_ms=127.7 \
    --expect-field decoding.minimum_frequency_hz=null \
    --expect-field decoding.maximum_frequency_hz=null \
    --expect-field decoding.multiple_pitch_bends=false \
    --expect-field decoding.melodia_trick=true \
    --expect-field decoding.midi_tempo_bpm=120.0 \
    --expect-field 'environment.model_type="ONNX"' \
    --expect-field 'environment.model_session_providers=["CPUExecutionProvider"]' \
    --require-output "raw/native/${NATIVE_PREFIX}.mid" \
    --require-output "raw/native/${NATIVE_PREFIX}.npz" \
    --require-output "raw/native/${NATIVE_PREFIX}.csv" \
    --require-output normalized/events.jsonl \
    --require-output normalized/summary.json \
    --quiet
  )
  if [[ "$INPUT_KIND" == "separator_vocal_stem" ]]; then
    verify_args+=(
      --expect-field "input_lineage.parent_manifest_sha256=\"$PARENT_MANIFEST_SHA\""
    )
  fi
  "$ROOT_PYTHON" "$VERIFY_RUN_MANIFEST" "${verify_args[@]}"
}

RUN_ID="$BASE_RUN_ID"
RUN_SKIP=0
attempt=0
while (( attempt <= 9999 )); do
  validate_run_id "$RUN_ID"
  RUN_DIR="$PROJECT_DIR/runs/$RUN_ID"
  if [[ ! -e "$RUN_DIR" && ! -L "$RUN_DIR" ]]; then
    break
  fi
  if run_manifest_is_valid "$RUN_ID"; then
    echo "Reusing verified immutable run; inference will be skipped: $RUN_ID"
    RUN_SKIP=1
    break
  fi
  echo "Preserving incomplete or invalid run and trying a new ID: $RUN_ID" >&2
  attempt=$((attempt + 1))
  RUN_ID="${BASE_RUN_ID}-attempt-${attempt}"
done
if (( attempt > 9999 )); then
  echo "Could not allocate a free attempt ID for base run: $BASE_RUN_ID" >&2
  exit 2
fi
if [[ "$RUN_SKIP" == 1 ]]; then
  exit 0
fi

if [[ ! -x "$WORKER_ENV/bin/python" ||
      ! -x "$WORKER_ENV/bin/basic-pitch" ]]; then
  echo "Run slurm/21_basic_pitch_setup.slurm before Basic Pitch inference." >&2
  exit 2
fi

print_env_value() {
  local name="$1"
  if [[ -n "${!name-}" ]]; then
    printf '%s=%q\n' "$name" "${!name}"
  fi
}

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
for name in \
  SLURM_JOB_ID \
  SLURM_JOB_NAME \
  SLURM_JOB_ACCOUNT \
  SLURM_JOB_PARTITION \
  SLURM_CPUS_PER_TASK \
  AMT_REPO_ROOT \
  AMT_ROOT_PYTHON \
  PROJECT_DIR \
  BASIC_PITCH_ENV \
  BASIC_PITCH_PINS \
  BASIC_PITCH_AUDIO \
  BASIC_PITCH_RUN_ID
do
  print_env_value "$name"
done
"$ROOT_PYTHON" --version
"$WORKER_ENV/bin/python" - <<'PY'
import importlib.metadata
import json
import platform

import onnxruntime as ort

print(json.dumps({
    "python": platform.python_version(),
    "basic_pitch": importlib.metadata.version("basic-pitch"),
    "numpy": importlib.metadata.version("numpy"),
    "onnxruntime": importlib.metadata.version("onnxruntime"),
    "setuptools": importlib.metadata.version("setuptools"),
    "available_providers": ort.get_available_providers(),
}, sort_keys=True))
PY
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO_ROOT" rev-parse HEAD
  git -C "$REPO_ROOT" status --porcelain
else
  echo "Git metadata unavailable in the synced HYAK copy; runner records commit=null."
fi

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-${SLURM_CPUS_PER_TASK:-1}}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-${SLURM_CPUS_PER_TASK:-1}}"
cd "$REPO_ROOT"
srun "$ROOT_PYTHON" "$REPO_ROOT/workers/basic_pitch/run_baseline.py" \
  --project "$PROJECT_DIR" \
  --audio "$INPUT_AUDIO" \
  --worker-env "$WORKER_ENV" \
  --pins "$PINS_PATH" \
  --run-id "$RUN_ID"
run_manifest_is_valid "$RUN_ID"
