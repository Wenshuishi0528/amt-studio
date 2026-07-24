#!/bin/bash
#SBATCH --job-name=amt-muscriptor
#SBATCH --account=stf
#SBATCH --partition=gpu-l40
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --gpus=l40:1
#SBATCH --time=06:00:00
#SBATCH --output=/gscratch/stf/%u/amt-studio/logs/%x-%j.out
#SBATCH --error=/gscratch/stf/%u/amt-studio/logs/%x-%j.err
#SBATCH --export=ALL

set -euo pipefail

: "${PROJECT_DIR:?Export PROJECT_DIR to an initialized private project}"
PERSIST_ROOT="${HYAK_PERSIST_ROOT:-/gscratch/stf/$USER/amt-studio}"
WORKER_ENV="${MUSCRIPTOR_ENV:-$PERSIST_ROOT/envs/muscriptor}"
MODEL="${MUSCRIPTOR_MODEL:-large}"
RUN_ID="muscriptor-${MODEL}-${SLURM_JOB_ID}"
RUN_DIR="$PROJECT_DIR/runs/$RUN_ID"
AUDIO="$PROJECT_DIR/audio/canonical/mix.flac"

mkdir -p "$RUN_DIR/raw" "$RUN_DIR/normalized" "$RUN_DIR/logs"

if [[ ! -f "$AUDIO" ]]; then
  echo "Canonical audio not found: $AUDIO" >&2
  exit 2
fi
if [[ ! -x "$WORKER_ENV/bin/muscriptor" ]]; then
  echo "MuScriptor environment not found: $WORKER_ENV" >&2
  echo "Complete Task 002 installation before submitting this job." >&2
  exit 2
fi

{
  date --iso-8601=seconds
  hostname
  nvidia-smi
  "$WORKER_ENV/bin/python" --version
  "$WORKER_ENV/bin/muscriptor" --help | head -n 30
} > "$RUN_DIR/logs/environment.txt" 2>&1

set +e
srun "$WORKER_ENV/bin/muscriptor" transcribe "$AUDIO" \
  --model "$MODEL" \
  --beam-size 4 \
  --format jsonl \
  -o "$RUN_DIR/raw/events.native.jsonl" \
  > "$RUN_DIR/logs/transcribe-jsonl.stdout" \
  2> "$RUN_DIR/logs/transcribe-jsonl.stderr"
status_jsonl=$?

srun "$WORKER_ENV/bin/muscriptor" transcribe "$AUDIO" \
  --model "$MODEL" \
  --beam-size 4 \
  -o "$RUN_DIR/raw/full.mid" \
  > "$RUN_DIR/logs/transcribe-midi.stdout" \
  2> "$RUN_DIR/logs/transcribe-midi.stderr"
status_midi=$?
set -e

python3 - "$RUN_DIR" "$PROJECT_DIR" "$MODEL" "$status_jsonl" "$status_midi" <<'PY'
from __future__ import annotations
import hashlib
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

run_dir = Path(sys.argv[1])
project_dir = Path(sys.argv[2])
model = sys.argv[3]
status_jsonl = int(sys.argv[4])
status_midi = int(sys.argv[5])

def sha(path: Path):
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

outputs = []
for path in sorted((run_dir / 'raw').glob('*')):
    if path.is_file():
        outputs.append({
            'path': str(path.relative_to(run_dir)),
            'sha256': sha(path),
            'size': path.stat().st_size,
        })
manifest = {
    'schema_version': 1,
    'run_id': run_dir.name,
    'project_id': project_dir.name,
    'worker': 'muscriptor',
    'model': model,
    'started_at': None,
    'ended_at': datetime.now(timezone.utc).isoformat(),
    'status': 'succeeded' if status_jsonl == 0 and status_midi == 0 else 'failed',
    'command': ['see logs and Slurm script'],
    'inputs': [{
        'path': 'audio/canonical/mix.flac',
        'sha256': sha(project_dir / 'audio/canonical/mix.flac'),
    }],
    'outputs': outputs,
    'environment': {
        'hostname': platform.node(),
        'python': sys.version,
        'slurm_job_id': os.environ.get('SLURM_JOB_ID'),
        'cuda_visible_devices': os.environ.get('CUDA_VISIBLE_DEVICES'),
    },
    'model_provenance': {
        'package_version': None,
        'weight_sha256': None,
        'needs_completion': True,
    },
    'exit_codes': {'jsonl': status_jsonl, 'midi': status_midi},
}
(run_dir / 'run_manifest.json').write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + '\n',
    encoding='utf-8',
)
PY

if [[ "$status_jsonl" -ne 0 || "$status_midi" -ne 0 ]]; then
  echo "MuScriptor baseline failed; inspect $RUN_DIR/logs" >&2
  exit 1
fi

echo "Completed $RUN_DIR"
