#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Run Beat This setup through sbatch on a compute node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${BEAT_THIS_ASSET_ROOT:?Export BEAT_THIS_ASSET_ROOT in persistent storage}"

REPO_ROOT_RAW="$AMT_REPO_ROOT"
ASSET_ROOT_RAW="$BEAT_THIS_ASSET_ROOT"
WORKER_ENV_RAW="${BEAT_THIS_ENV:-$REPO_ROOT_RAW/workers/beat_this/.venv}"
PINS_PATH_RAW="${BEAT_THIS_PINS:-$REPO_ROOT_RAW/workers/beat_this/pins.json}"
CHECKPOINT_RAW="${BEAT_THIS_CHECKPOINT:-$ASSET_ROOT_RAW/final0.ckpt}"
UV_CACHE_DIR_RAW="${UV_CACHE_DIR:-$ASSET_ROOT_RAW/uv-cache}"
UV_PYTHON_INSTALL_DIR_RAW="${UV_PYTHON_INSTALL_DIR:-$ASSET_ROOT_RAW/python}"
ROOT_ENV_RAW="${AMT_ROOT_ENV:-$REPO_ROOT_RAW/.venv}"
BEAT_THIS_PYTHON="${BEAT_THIS_PYTHON:-3.12}"
CUDA_MODULE="${CUDA_MODULE:-cuda/12.9.1}"
UV_BIN="${UV_BIN:-}"

for path in "$REPO_ROOT_RAW" "$ASSET_ROOT_RAW" "$WORKER_ENV_RAW" "$PINS_PATH_RAW" \
  "$CHECKPOINT_RAW" "$UV_CACHE_DIR_RAW" "$UV_PYTHON_INSTALL_DIR_RAW" "$ROOT_ENV_RAW"; do
  if [[ "$path" != /* ]]; then
    echo "All Beat This setup paths must be absolute: $path" >&2
    exit 2
  fi
done

PATH_CANONICALIZER="$(command -v python3 || true)"
if [[ -z "$PATH_CANONICALIZER" || ! -x "$PATH_CANONICALIZER" ]]; then
  echo "python3 is required to canonicalize setup paths." >&2
  exit 2
fi
canonicalize_path() {
  "$PATH_CANONICALIZER" - "$1" <<'PY'
import os
import sys

print(os.path.realpath(os.path.abspath(sys.argv[1])))
PY
}
path_is_within() {
  local child="$1"
  local parent="$2"
  [[ "$child" == "$parent"/* ]]
}

REPO_ROOT="$(canonicalize_path "$REPO_ROOT_RAW")"
ASSET_ROOT="$(canonicalize_path "$ASSET_ROOT_RAW")"
WORKER_ENV="$(canonicalize_path "$WORKER_ENV_RAW")"
PINS_PATH="$(canonicalize_path "$PINS_PATH_RAW")"
CHECKPOINT="$(canonicalize_path "$CHECKPOINT_RAW")"
UV_CACHE_DIR="$(canonicalize_path "$UV_CACHE_DIR_RAW")"
UV_PYTHON_INSTALL_DIR="$(canonicalize_path "$UV_PYTHON_INSTALL_DIR_RAW")"
ROOT_ENV="$(canonicalize_path "$ROOT_ENV_RAW")"

if [[ "$REPO_ROOT" == "/" ||
      "$ASSET_ROOT" == "/" ||
      "$WORKER_ENV" == "/" ||
      "$WORKER_ENV" == "$REPO_ROOT" ||
      "$ROOT_ENV" == "/" ||
      "$ROOT_ENV" == "$REPO_ROOT" ||
      "$WORKER_ENV" == "$ROOT_ENV" ]]; then
  echo "Beat This setup paths violate the safety boundary." >&2
  exit 2
fi
if ! path_is_within "$WORKER_ENV" "$REPO_ROOT/workers/beat_this"; then
  echo "BEAT_THIS_ENV must resolve inside workers/beat_this." >&2
  exit 2
fi
if ! path_is_within "$ROOT_ENV" "$REPO_ROOT"; then
  echo "AMT_ROOT_ENV must resolve inside the repository." >&2
  exit 2
fi
if path_is_within "$WORKER_ENV" "$ROOT_ENV" ||
   path_is_within "$ROOT_ENV" "$WORKER_ENV"; then
  echo "Root and Beat This environments must not contain one another." >&2
  exit 2
fi
for path in "$CHECKPOINT" "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"; do
  if ! path_is_within "$path" "$ASSET_ROOT"; then
    echo "Checkpoint and uv stores must stay under BEAT_THIS_ASSET_ROOT." >&2
    exit 2
  fi
done
if ! path_is_within "$PINS_PATH" "$REPO_ROOT/workers/beat_this"; then
  echo "BEAT_THIS_PINS must stay inside workers/beat_this." >&2
  exit 2
fi
if [[ ! -d "$REPO_ROOT" || ! -f "$PINS_PATH" ]]; then
  echo "AMT repository or Beat This pins are unavailable." >&2
  exit 2
fi
if [[ -z "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "uv not found; pass UV_BIN=/absolute/path/to/uv." >&2
  exit 2
fi

read -r CHECKPOINT_URL EXPECTED_SHA EXPECTED_SIZE < <(
  "$PATH_CANONICALIZER" - "$PINS_PATH" <<'PY'
import json
import pathlib
import sys

pins = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
model = pins["model"]
print(model["url"], model["sha256"], model["size_bytes"])
PY
)
verify_checkpoint() {
  "$PATH_CANONICALIZER" - "$1" "$EXPECTED_SHA" "$EXPECTED_SIZE" <<'PY'
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
expected_hash = sys.argv[2]
expected_size = int(sys.argv[3])
if not path.is_file() or path.is_symlink() or path.stat().st_size != expected_size:
    raise SystemExit(1)
digest = hashlib.sha256(path.read_bytes()).hexdigest()
raise SystemExit(0 if digest == expected_hash else 1)
PY
}

set +u
if ! type module >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source /etc/profile.d/lmod.sh
  module use /sw/klone /sw/contrib/modulefiles
fi
module --ignore_cache load "$CUDA_MODULE"
set -u

mkdir -p "$ASSET_ROOT" "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"
if [[ -e "$CHECKPOINT" || -L "$CHECKPOINT" ]]; then
  if ! verify_checkpoint "$CHECKPOINT"; then
    echo "Existing Beat This checkpoint is invalid; refusing to overwrite it." >&2
    exit 2
  fi
else
  TEMP_CHECKPOINT="$(mktemp "$ASSET_ROOT/.final0.ckpt.XXXXXX")"
  trap 'rm -f "$TEMP_CHECKPOINT"' EXIT
  "$PATH_CANONICALIZER" - "$CHECKPOINT_URL" "$TEMP_CHECKPOINT" <<'PY'
import pathlib
import sys
import urllib.request

with urllib.request.urlopen(sys.argv[1]) as response:
    with pathlib.Path(sys.argv[2]).open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
PY
  if ! verify_checkpoint "$TEMP_CHECKPOINT"; then
    echo "Downloaded Beat This checkpoint failed hash or size validation." >&2
    exit 2
  fi
  mv "$TEMP_CHECKPOINT" "$CHECKPOINT"
  trap - EXIT
fi

ROOT_PYTHON="$ROOT_ENV/bin/python"
if [[ ! -x "$ROOT_PYTHON" ]]; then
  echo "Root project environment is unavailable." >&2
  exit 2
fi
UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" python install "$BEAT_THIS_PYTHON"
UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" venv \
    --clear \
    --managed-python \
    --python "$BEAT_THIS_PYTHON" \
    "$WORKER_ENV"
UV_PROJECT_ENVIRONMENT="$WORKER_ENV" \
  UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" sync \
    --project "$REPO_ROOT/workers/beat_this" \
    --locked \
    --managed-python \
    --python "$BEAT_THIS_PYTHON"

nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
"$WORKER_ENV/bin/python" - "$CHECKPOINT" <<'PY'
import importlib.metadata
import json
import sys

import torch
import torchaudio
from beat_this.inference import load_checkpoint

checkpoint = load_checkpoint(sys.argv[1], "cpu")
diagnostics = {
    "beat_this": importlib.metadata.version("beat-this"),
    "torch": torch.__version__,
    "torchaudio": torchaudio.__version__,
    "soundfile": importlib.metadata.version("soundfile"),
    "cuda_available": torch.cuda.is_available(),
    "cuda_version": torch.version.cuda,
    "cuda_device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
    "checkpoint_keys": sorted(checkpoint),
}
print(json.dumps(diagnostics, indent=2, sort_keys=True))
if not diagnostics["cuda_available"]:
    raise SystemExit("CUDA is unavailable inside the Beat This worker environment")
PY

echo "Beat This setup completed on the Slurm compute node."
