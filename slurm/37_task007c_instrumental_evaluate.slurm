#!/bin/bash
#SBATCH --job-name=amt-t007c-eval
#SBATCH --account=stf
#SBATCH --partition=ckpt
#SBATCH --qos=ckpt
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --requeue
#SBATCH --signal=B:TERM@120
#SBATCH --output=slurm-%x-%j.out
#SBATCH --error=slurm-%x-%j.err
#SBATCH --export=ALL

set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Submit with sbatch; do not score the development benchmark on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export the absolute Hyak repository path}"
: "${AMT_DATASET_ROOT:?Export the absolute private MedleyDB sample root}"
: "${PROJECT_DIR:?Export the absolute private Task 007C project path}"
: "${BASIC_PITCH_RUN_ID:?Export the completed fixed Basic Pitch run ID}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
REFERENCE="$AMT_DATASET_ROOT/MedleyDB_sample/Annotations/Melody_Annotations/MELODY1/Phoenix_ScotchMorris_MELODY1.csv"
PROVENANCE="$AMT_DATASET_ROOT/source_provenance.json"
PACK="$PROJECT_DIR/annotations/reference-task007c-phoenix-development-v1"
CANDIDATE="$PROJECT_DIR/runs/$BASIC_PITCH_RUN_ID/normalized/events.jsonl"
REPORT_DIR="$PROJECT_DIR/reports/instrumental-development-task007c-v1"
DECISION="$PROJECT_DIR/reports/instrumental-development-task007c-decision-v2.json"
EXPECTED_REFERENCE_SHA="c1cb36655177b353e81d11778b755d92263e4f6b53070659c4d1e3dd8b34f508"

for path in "$ROOT_PYTHON" "$REFERENCE" "$PROVENANCE" "$PACK/benchmark_manifest.json" "$CANDIDATE"; do
  if [[ ! -f "$path" ]]; then
    echo "Required Task 007C evaluation input is unavailable: $path" >&2
    exit 2
  fi
done
if [[ -e "$DECISION" || -L "$DECISION" ]]; then
  echo "Refusing to replace completed immutable Task 007C decision evidence." >&2
  exit 2
fi

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "slurm_job_id=$SLURM_JOB_ID"
echo "basic_pitch_run_id=$BASIC_PITCH_RUN_ID"

cd "$REPO_ROOT"
if [[ ! -e "$PACK/candidate_set_seal.json" && ! -L "$PACK/candidate_set_seal.json" ]]; then
  "$ROOT_PYTHON" scripts/freeze_evaluation_candidates.py \
    --pack-dir "$PACK" \
    --candidate "basic-pitch-direct-mix=$CANDIDATE" \
    --confirm-output-quality-uninspected
fi

if [[ ! -e "$REPORT_DIR" && ! -L "$REPORT_DIR" ]]; then
  "$ROOT_PYTHON" scripts/evaluate_melody_contour.py \
    --pack-dir "$PACK" \
    --reference-csv "$REFERENCE" \
    --reference-sha256 "$EXPECTED_REFERENCE_SHA" \
    --reference-role development_instrumental_melody \
    --provenance "$PROVENANCE" \
    --output-dir "$REPORT_DIR" \
    --instrument other \
    --cent-tolerance 50
elif [[ ! -f "$REPORT_DIR/report.json" || ! -f "$REPORT_DIR/run_manifest.json" ]]; then
  echo "Existing Task 007C report directory is incomplete." >&2
  exit 2
fi

"$ROOT_PYTHON" scripts/assess_instrumental_dev_probe.py \
  --pack-dir "$PACK" \
  --report "$REPORT_DIR/report.json" \
  --run-manifest "$REPORT_DIR/run_manifest.json" \
  --output "$DECISION"
