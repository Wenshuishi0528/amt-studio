#!/bin/bash
#SBATCH --job-name=amt-t007c-prepare
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
  echo "Submit with sbatch; do not canonicalize or render excerpts on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export the absolute Hyak repository path}"
: "${AMT_DATASET_ROOT:?Export the absolute private MedleyDB sample root}"
: "${PROJECT_DIR:?Export the absolute private Task 007C project path}"

REPO_ROOT="$AMT_REPO_ROOT"
ROOT_PYTHON="${AMT_ROOT_PYTHON:-$REPO_ROOT/.venv/bin/python}"
SOURCE_AUDIO="$AMT_DATASET_ROOT/MedleyDB_sample/Audio/Phoenix_ScotchMorris/Phoenix_ScotchMorris_MIX.wav"
REFERENCE="$AMT_DATASET_ROOT/MedleyDB_sample/Annotations/Melody_Annotations/MELODY1/Phoenix_ScotchMorris_MELODY1.csv"
PROVENANCE="$AMT_DATASET_ROOT/source_provenance.json"
SPEC="$REPO_ROOT/configs/task007c/phoenix_instrumental_development.json"
PACK="$PROJECT_DIR/annotations/reference-task007c-phoenix-development-v1"

EXPECTED_MIX_SHA="0abff2045127295b46849d7cb14614ec5d6cc2e7737c47bfd59577c103b3f41c"
EXPECTED_REFERENCE_SHA="c1cb36655177b353e81d11778b755d92263e4f6b53070659c4d1e3dd8b34f508"

if [[ "$REPO_ROOT" != /* || "$AMT_DATASET_ROOT" != /* || "$PROJECT_DIR" != /* ]]; then
  echo "Task 007C paths must be absolute." >&2
  exit 2
fi
if [[ "$(basename "$PROJECT_DIR")" != "medleydb-phoenix-scotch-morris" ]]; then
  echo "PROJECT_DIR must use the frozen Task 007C project identity." >&2
  exit 2
fi
for path in "$ROOT_PYTHON" "$SOURCE_AUDIO" "$REFERENCE" "$PROVENANCE" "$SPEC"; do
  if [[ ! -f "$path" ]]; then
    echo "Required Task 007C input is unavailable: $path" >&2
    exit 2
  fi
done

"$ROOT_PYTHON" - "$SOURCE_AUDIO" "$REFERENCE" "$PROVENANCE" <<'PY'
import hashlib
import json
import pathlib
import sys

mix, reference, provenance_path = map(pathlib.Path, sys.argv[1:])
expected_mix = "0abff2045127295b46849d7cb14614ec5d6cc2e7737c47bfd59577c103b3f41c"
expected_reference = "c1cb36655177b353e81d11778b755d92263e4f6b53070659c4d1e3dd8b34f508"
digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
if digest(mix) != expected_mix or digest(reference) != expected_reference:
    raise SystemExit("Task 007C MedleyDB mix or Melody 1 hash changed")
provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
tracks = provenance.get("selected_tracks", [])
if not any(
    isinstance(track, dict)
    and track.get("track_id") == "Phoenix_ScotchMorris"
    and track.get("role") == "development_instrumental_melody"
    and track.get("mix_sha256") == expected_mix
    and track.get("melody1_sha256") == expected_reference
    for track in tracks
):
    raise SystemExit("Task 007C development provenance is missing or changed")
PY

set +u
if ! type module >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source /etc/profile.d/lmod.sh
  module use /sw/klone /sw/contrib/modulefiles
fi
module --ignore_cache load weirdlab/ffmpeg/8.1
set -u

echo "timestamp=$(date --iso-8601=seconds)"
echo "hostname=$(hostname)"
echo "slurm_job_id=$SLURM_JOB_ID"
echo "source_mix_sha256=$EXPECTED_MIX_SHA"
echo "reference_sha256=$EXPECTED_REFERENCE_SHA"
command -v ffmpeg
command -v ffprobe

if [[ ! -e "$PROJECT_DIR" && ! -L "$PROJECT_DIR" ]]; then
  "$REPO_ROOT/.venv/bin/amt" init-project \
    "$SOURCE_AUDIO" \
    --output "$PROJECT_DIR" \
    --title "MedleyDB Sample - Phoenix Scotch Morris" \
    --reference-original
else
  "$ROOT_PYTHON" - "$PROJECT_DIR/manifest.json" "$EXPECTED_MIX_SHA" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if (
    manifest.get("project_id") != "medleydb-phoenix-scotch-morris"
    or manifest.get("source", {}).get("sha256") != sys.argv[2]
):
    raise SystemExit("Existing Task 007C project identity or source hash changed")
PY
fi

if [[ ! -e "$PACK" && ! -L "$PACK" ]]; then
  cd "$REPO_ROOT"
  "$ROOT_PYTHON" scripts/create_reference_pack.py \
    --project-dir "$PROJECT_DIR" \
    --spec "$SPEC" \
    --output-dir "$PACK" \
    --ffmpeg "$(command -v ffmpeg)" \
    --context-sec 0
else
  "$ROOT_PYTHON" - "$PACK/benchmark_manifest.json" <<'PY'
import json
import pathlib
import sys

manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
payload = manifest.get("freeze_payload", {})
if (
    payload.get("benchmark_id") != "medleydb-phoenix-task007c-development-v1"
    or payload.get("split") != "development"
    or len(payload.get("excerpts", [])) != 6
):
    raise SystemExit("Existing Task 007C benchmark pack identity changed")
PY
fi

"$REPO_ROOT/.venv/bin/amt" show "$PROJECT_DIR"
