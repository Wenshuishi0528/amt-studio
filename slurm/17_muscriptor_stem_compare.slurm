#!/bin/bash
#SBATCH --job-name=amt-muscriptor-stem-compare
#SBATCH --account=stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt-gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
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
: "${MUSCRIPTOR_WEIGHT_PROVENANCE:?Export the pinned MuScriptor provenance JSON path}"
: "${DIRECT_MIX_AUDIO:?Export DIRECT_MIX_AUDIO as the canonical mix path}"
: "${VOCAL_A_AUDIO:?Export VOCAL_A_AUDIO as the first separator vocal stem}"
: "${VOCAL_B_AUDIO:?Export VOCAL_B_AUDIO as the second separator vocal stem}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
WORKER_ENV="${MUSCRIPTOR_ENV:-$REPO_ROOT/workers/muscriptor/.venv}"
PINS_PATH="${MUSCRIPTOR_PINS:-$REPO_ROOT/workers/muscriptor/pins.json}"
RUN_PREFIX="${MUSCRIPTOR_COMPARE_RUN_ID_PREFIX:-muscriptor-voice-beam4-${SLURM_JOB_ID}}"
DIRECT_BASE_RUN_ID="${MUSCRIPTOR_DIRECT_RUN_ID:-${RUN_PREFIX}-direct}"
VOCAL_A_BASE_RUN_ID="${MUSCRIPTOR_VOCAL_A_RUN_ID:-${RUN_PREFIX}-vocal-a}"
VOCAL_B_BASE_RUN_ID="${MUSCRIPTOR_VOCAL_B_RUN_ID:-${RUN_PREFIX}-vocal-b}"
COMPARISON_REPORT_BASE="${MUSCRIPTOR_COMPARE_REPORT:-$PROJECT_DIR/reports/${RUN_PREFIX}-comparison.json}"
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
      ! -f "$PINS_PATH" ||
      ! -f "$MUSCRIPTOR_WEIGHT_PROVENANCE" ]]; then
  echo "Root Python, verifier, pins, or model provenance is unavailable." >&2
  exit 2
fi
for audio_path in "$DIRECT_MIX_AUDIO" "$VOCAL_A_AUDIO" "$VOCAL_B_AUDIO"; do
  if [[ ! -f "$audio_path" ]]; then
    echo "Comparison input audio not found: $audio_path" >&2
    exit 2
  fi
done
case "${MUSCRIPTOR_DTYPE:-}" in
  "")
    EXPECTED_DTYPE_JSON=null
    ;;
  float16|float32|bfloat16)
    EXPECTED_DTYPE_JSON="\"${MUSCRIPTOR_DTYPE}\""
    ;;
  *)
    echo "Unsupported MUSCRIPTOR_DTYPE: ${MUSCRIPTOR_DTYPE}" >&2
    exit 2
    ;;
esac
validate_base_run_id "$DIRECT_BASE_RUN_ID"
validate_base_run_id "$VOCAL_A_BASE_RUN_ID"
validate_base_run_id "$VOCAL_B_BASE_RUN_ID"
if [[ "$DIRECT_BASE_RUN_ID" == "$VOCAL_A_BASE_RUN_ID" ||
      "$DIRECT_BASE_RUN_ID" == "$VOCAL_B_BASE_RUN_ID" ||
      "$VOCAL_A_BASE_RUN_ID" == "$VOCAL_B_BASE_RUN_ID" ]]; then
  echo "All three MuScriptor comparison run IDs must be distinct." >&2
  exit 2
fi

run_manifest_is_valid() {
  local run_id="$1"
  local audio_path="$2"
  "$ROOT_PYTHON" "$VERIFY_RUN_MANIFEST" \
    --run-dir "$PROJECT_DIR/runs/$run_id" \
    --worker muscriptor \
    --input "$audio_path" \
    --pins "$PINS_PATH" \
    --model-provenance "$MUSCRIPTOR_WEIGHT_PROVENANCE" \
    --repo-root "$REPO_ROOT" \
    --source "$PINS_PATH" \
    --source "$REPO_ROOT/workers/muscriptor/pyproject.toml" \
    --source "$REPO_ROOT/workers/muscriptor/uv.lock" \
    --source "$REPO_ROOT/workers/muscriptor/normalize.py" \
    --source "$REPO_ROOT/workers/muscriptor/run_baseline.py" \
    --source "$VERIFY_RUN_MANIFEST" \
    --source "$REPO_ROOT/slurm/17_muscriptor_stem_compare.slurm" \
    --expect-field decoding.beam_size=4 \
    --expect-field 'decoding.instruments=["voice"]' \
    --expect-field decoding.prelude_forcing=true \
    --expect-field decoding.sampling=false \
    --expect-field decoding.cfg_coef=1.0 \
    --expect-field "decoding.dtype=$EXPECTED_DTYPE_JSON" \
    --expect-field 'decoding.device="cuda"' \
    --expect-field decoding.skip_midi=true \
    --require-output normalized/events.jsonl \
    --require-output normalized/summary.json \
    --quiet
}

RESERVED_RUN_IDS=""
RESOLVED_RUN_ID=""
RESOLVED_RUN_SKIP=""

resolve_run_id() {
  local base_run_id="$1"
  local audio_path="$2"
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
    elif run_manifest_is_valid "$candidate" "$audio_path"; then
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

resolve_run_id "$DIRECT_BASE_RUN_ID" "$DIRECT_MIX_AUDIO"
DIRECT_RUN_ID="$RESOLVED_RUN_ID"
DIRECT_RUN_SKIP="$RESOLVED_RUN_SKIP"
resolve_run_id "$VOCAL_A_BASE_RUN_ID" "$VOCAL_A_AUDIO"
VOCAL_A_RUN_ID="$RESOLVED_RUN_ID"
VOCAL_A_RUN_SKIP="$RESOLVED_RUN_SKIP"
resolve_run_id "$VOCAL_B_BASE_RUN_ID" "$VOCAL_B_AUDIO"
VOCAL_B_RUN_ID="$RESOLVED_RUN_ID"
VOCAL_B_RUN_SKIP="$RESOLVED_RUN_SKIP"

if [[ "$DIRECT_RUN_ID" == "$VOCAL_A_RUN_ID" ||
      "$DIRECT_RUN_ID" == "$VOCAL_B_RUN_ID" ||
      "$VOCAL_A_RUN_ID" == "$VOCAL_B_RUN_ID" ]]; then
  echo "Resolved MuScriptor run IDs unexpectedly collide." >&2
  exit 2
fi

validate_report_path() {
  local report_path="$1"
  "$ROOT_PYTHON" - "$PROJECT_DIR/reports" "$report_path" <<'PY'
import pathlib
import sys

report_root = pathlib.Path(sys.argv[1]).expanduser().resolve(strict=False)
report = pathlib.Path(sys.argv[2]).expanduser()
if not report.is_absolute():
    raise SystemExit(1)
if any(ord(character) < 32 or ord(character) == 127 for character in report.name):
    raise SystemExit(1)
try:
    report.parent.resolve(strict=False).relative_to(report_root)
except ValueError:
    raise SystemExit(1)
if report.parent.resolve(strict=False) == report_root and report.name not in {"", ".", ".."}:
    raise SystemExit(0)
raise SystemExit(1)
PY
}

if ! validate_report_path "$COMPARISON_REPORT_BASE"; then
  echo "MUSCRIPTOR_COMPARE_REPORT must be a safe path directly under " \
    "$PROJECT_DIR/reports: $COMPARISON_REPORT_BASE" >&2
  exit 2
fi

comparison_report_matches() {
  local report_path="$1"
  "$ROOT_PYTHON" - \
    "$report_path" \
    "$REPO_ROOT" \
    "$PROJECT_DIR" \
    "$DIRECT_RUN_ID" \
    "$VOCAL_A_RUN_ID" \
    "$VOCAL_B_RUN_ID" <<'PY'
from datetime import datetime
import json
import pathlib
import sys

repo_root = pathlib.Path(sys.argv[2]).resolve()
sys.path.insert(0, str(repo_root))

from workers.separator.compare_amt import ComparisonError, compare_runs


report_path = pathlib.Path(sys.argv[1])
project_dir = pathlib.Path(sys.argv[3]).resolve()
run_ids = dict(zip(("direct", "vocal_a", "vocal_b"), sys.argv[4:], strict=True))
run_dirs = {
    name: (project_dir / "runs" / run_id).resolve()
    for name, run_id in run_ids.items()
}
try:
    if report_path.is_symlink() or not report_path.is_file():
        raise ValueError("report path is missing, not a file, or a symbolic link")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError("report root is not a JSON object")
    generated_at = report.get("generated_at")
    if not isinstance(generated_at, str):
        raise ValueError("generated_at is missing or not a string")
    parsed_generated_at = datetime.fromisoformat(generated_at)
    if (
        parsed_generated_at.tzinfo is None
        or parsed_generated_at.utcoffset() is None
    ):
        raise ValueError("generated_at has no UTC offset")

    expected_report = compare_runs(run_dirs)
    if set(report) != set(expected_report):
        raise ValueError("report field set is incomplete or unsupported")
    for key, expected_value in expected_report.items():
        if key != "generated_at" and report.get(key) != expected_value:
            raise ValueError(f"report field does not match current runs: {key}")
except (
    ComparisonError,
    OSError,
    UnicodeDecodeError,
    json.JSONDecodeError,
    KeyError,
    TypeError,
    ValueError,
) as exc:
    print(f"comparison report validation failed: {exc}", file=sys.stderr)
    raise SystemExit(1)
PY
}

report_attempt_path() {
  local base_path="$1"
  local attempt="$2"
  local directory="${base_path%/*}"
  local filename="${base_path##*/}"
  if [[ "$filename" == *.json ]]; then
    printf '%s/%s-attempt-%d.json\n' \
      "$directory" "${filename%.json}" "$attempt"
  else
    printf '%s/%s-attempt-%d\n' "$directory" "$filename" "$attempt"
  fi
}

COMPARISON_REPORT=""
COMPARISON_REPORT_SKIP=""
resolve_comparison_report() {
  local attempt=0
  local candidate="$COMPARISON_REPORT_BASE"

  while (( attempt <= 9999 )); do
    if ! validate_report_path "$candidate"; then
      echo "Unsafe comparison report attempt path: $candidate" >&2
      exit 2
    fi
    if [[ ! -e "$candidate" && ! -L "$candidate" ]]; then
      COMPARISON_REPORT="$candidate"
      COMPARISON_REPORT_SKIP=0
      return 0
    elif comparison_report_matches "$candidate"; then
      echo "Reusing verified comparison report; comparison will be skipped: $candidate"
      COMPARISON_REPORT="$candidate"
      COMPARISON_REPORT_SKIP=1
      return 0
    else
      echo "Preserving mismatched or invalid report and trying a new path: " \
        "$candidate" >&2
    fi
    attempt=$((attempt + 1))
    candidate="$(report_attempt_path "$COMPARISON_REPORT_BASE" "$attempt")"
  done
  echo "Could not allocate a free attempt path for comparison report." >&2
  exit 2
}

resolve_comparison_report

printf 'resolved_direct_run_id=%q skip=%s\n' "$DIRECT_RUN_ID" "$DIRECT_RUN_SKIP"
printf 'resolved_vocal_a_run_id=%q skip=%s\n' "$VOCAL_A_RUN_ID" "$VOCAL_A_RUN_SKIP"
printf 'resolved_vocal_b_run_id=%q skip=%s\n' "$VOCAL_B_RUN_ID" "$VOCAL_B_RUN_SKIP"
printf 'resolved_comparison_report=%q skip=%s\n' \
  "$COMPARISON_REPORT" "$COMPARISON_REPORT_SKIP"

if [[ "$DIRECT_RUN_SKIP" == 1 &&
      "$VOCAL_A_RUN_SKIP" == 1 &&
      "$VOCAL_B_RUN_SKIP" == 1 &&
      "$COMPARISON_REPORT_SKIP" == 1 ]]; then
  echo "All MuScriptor runs and their comparison report are complete and verified."
  exit 0
fi

RUN_INFERENCE=0
if [[ "$DIRECT_RUN_SKIP" == 0 ||
      "$VOCAL_A_RUN_SKIP" == 0 ||
      "$VOCAL_B_RUN_SKIP" == 0 ]]; then
  RUN_INFERENCE=1
fi

if [[ "$RUN_INFERENCE" == 1 ]]; then
  if [[ ! -x "$WORKER_ENV/bin/muscriptor" ]]; then
    echo "MuScriptor worker environment is incomplete." >&2
    exit 2
  fi
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
  MUSCRIPTOR_ENV \
  MUSCRIPTOR_WEIGHT_PROVENANCE \
  MUSCRIPTOR_PINS \
  MUSCRIPTOR_DTYPE \
  DIRECT_MIX_AUDIO \
  VOCAL_A_AUDIO \
  VOCAL_B_AUDIO \
  MUSCRIPTOR_COMPARE_RUN_ID_PREFIX \
  MUSCRIPTOR_DIRECT_RUN_ID \
  MUSCRIPTOR_VOCAL_A_RUN_ID \
  MUSCRIPTOR_VOCAL_B_RUN_ID \
  MUSCRIPTOR_COMPARE_REPORT
do
  print_env_value "$name"
done
"$ROOT_PYTHON" --version
if [[ "$RUN_INFERENCE" == 1 ]]; then
  nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
  "$WORKER_ENV/bin/python" -c \
    'import torch; print({"torch": torch.__version__, "cuda": torch.version.cuda, "available": torch.cuda.is_available(), "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None})'
fi
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  git -C "$REPO_ROOT" rev-parse HEAD
  git -C "$REPO_ROOT" status --porcelain
else
  echo "Git metadata unavailable in the synced HYAK copy; runner records commit=null."
fi

run_muscriptor() {
  local audio_path="$1"
  local run_id="$2"
  local runner_args=(
    --project "$PROJECT_DIR"
    --audio "$audio_path"
    --worker-env "$WORKER_ENV"
    --weight-provenance "$MUSCRIPTOR_WEIGHT_PROVENANCE"
    --pins "$PINS_PATH"
    --run-id "$run_id"
    --beam-size 4
    --device cuda
    --instruments voice
    --skip-midi
    --prelude-forcing
  )
  if [[ -n "${MUSCRIPTOR_DTYPE:-}" ]]; then
    runner_args+=(--dtype "$MUSCRIPTOR_DTYPE")
  fi
  srun "$ROOT_PYTHON" "$REPO_ROOT/workers/muscriptor/run_baseline.py" \
    "${runner_args[@]}"
}

cd "$REPO_ROOT"
if [[ "$DIRECT_RUN_SKIP" == 0 ]]; then
  run_muscriptor "$DIRECT_MIX_AUDIO" "$DIRECT_RUN_ID"
  run_manifest_is_valid "$DIRECT_RUN_ID" "$DIRECT_MIX_AUDIO"
fi
if [[ "$VOCAL_A_RUN_SKIP" == 0 ]]; then
  run_muscriptor "$VOCAL_A_AUDIO" "$VOCAL_A_RUN_ID"
  run_manifest_is_valid "$VOCAL_A_RUN_ID" "$VOCAL_A_AUDIO"
fi
if [[ "$VOCAL_B_RUN_SKIP" == 0 ]]; then
  run_muscriptor "$VOCAL_B_AUDIO" "$VOCAL_B_RUN_ID"
  run_manifest_is_valid "$VOCAL_B_RUN_ID" "$VOCAL_B_AUDIO"
fi

if [[ "$COMPARISON_REPORT_SKIP" == 0 ]]; then
  if [[ -e "$COMPARISON_REPORT" || -L "$COMPARISON_REPORT" ]]; then
    echo "Refusing to overwrite comparison report: $COMPARISON_REPORT" >&2
    exit 2
  fi
  mkdir -p "$(dirname "$COMPARISON_REPORT")"
  srun "$ROOT_PYTHON" "$REPO_ROOT/workers/separator/compare_amt.py" \
    --run "direct=$PROJECT_DIR/runs/$DIRECT_RUN_ID" \
    --run "vocal_a=$PROJECT_DIR/runs/$VOCAL_A_RUN_ID" \
    --run "vocal_b=$PROJECT_DIR/runs/$VOCAL_B_RUN_ID" \
    --output "$COMPARISON_REPORT"
  if ! comparison_report_matches "$COMPARISON_REPORT"; then
    echo "AMT comparison report failed integrity validation: $COMPARISON_REPORT" >&2
    exit 1
  fi
fi
printf 'amt_comparison_report=%q\n' "$COMPARISON_REPORT"
