#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Separator setup must run inside a Slurm GPU allocation, not on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${SEPARATOR_MODEL_DIR:?Export SEPARATOR_MODEL_DIR in persistent storage}"
: "${SEPARATOR_MODEL_PROVENANCE:?Export SEPARATOR_MODEL_PROVENANCE as an output JSON path}"

REPO_ROOT_RAW="$AMT_REPO_ROOT"
ROOT_ENV_RAW="${AMT_ROOT_ENV:-$REPO_ROOT_RAW/.venv}"
WORKER_ENV_RAW="${SEPARATOR_ENV:-$REPO_ROOT_RAW/workers/separator/.venv}"
for env_path in "$REPO_ROOT_RAW" "$ROOT_ENV_RAW" "$WORKER_ENV_RAW"; do
  if [[ "$env_path" != /* ]]; then
    echo "Repository and environment paths must be absolute: $env_path" >&2
    exit 2
  fi
done

PATH_CANONICALIZER="$(command -v python3 || true)"
if [[ -z "$PATH_CANONICALIZER" || ! -x "$PATH_CANONICALIZER" ]]; then
  echo "python3 is required to canonicalize environment paths safely." >&2
  exit 2
fi
canonicalize_path() {
  "$PATH_CANONICALIZER" - "$1" <<'PY'
import os
import sys

print(os.path.realpath(os.path.abspath(sys.argv[1])))
PY
}

REPO_ROOT="$(canonicalize_path "$REPO_ROOT_RAW")"
ROOT_ENV="$(canonicalize_path "$ROOT_ENV_RAW")"
WORKER_ENV="$(canonicalize_path "$WORKER_ENV_RAW")"
if [[ "$ROOT_ENV" == "$WORKER_ENV" ]]; then
  echo "AMT_ROOT_ENV and SEPARATOR_ENV resolve to the same environment: $ROOT_ENV" >&2
  exit 2
fi
if [[ "$REPO_ROOT" == "/" ]]; then
  echo "AMT_REPO_ROOT must not resolve to the filesystem root." >&2
  exit 2
fi
if [[ "$ROOT_ENV" == "/" ||
      "$ROOT_ENV" == "$REPO_ROOT" ||
      "$WORKER_ENV" == "/" ||
      "$WORKER_ENV" == "$REPO_ROOT" ]]; then
  echo "Root and separator environments must be safe paths distinct from the repository root." >&2
  exit 2
fi
path_is_within() {
  local child="$1"
  local parent="$2"
  [[ "$child" == "$parent"/* ]]
}
if ! path_is_within "$ROOT_ENV" "$REPO_ROOT"; then
  echo "AMT_ROOT_ENV must resolve inside the repository: $ROOT_ENV" >&2
  exit 2
fi
if ! path_is_within "$WORKER_ENV" "$REPO_ROOT/workers/separator"; then
  echo "SEPARATOR_ENV must resolve inside the separator worker directory: $WORKER_ENV" >&2
  exit 2
fi
if path_is_within "$ROOT_ENV" "$WORKER_ENV" ||
   path_is_within "$WORKER_ENV" "$ROOT_ENV"; then
  echo "Root and separator environments must not contain one another." >&2
  exit 2
fi

UV_BIN="${UV_BIN:-}"
UV_CACHE_DIR="${UV_CACHE_DIR:-$REPO_ROOT/.uv-cache}"
UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$REPO_ROOT/.uv-python}"
SEPARATOR_PYTHON="${SEPARATOR_PYTHON:-3.12}"
FFMPEG_MODULE="${FFMPEG_MODULE:-weirdlab/ffmpeg/8.1}"

if [[ -z "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "uv not found; export UV_BIN as the absolute path to the approved uv binary." >&2
  exit 2
fi
set +u
if ! type module >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source /etc/profile.d/lmod.sh
  module use /sw/klone /sw/contrib/modulefiles
fi
module --ignore_cache load "$FFMPEG_MODULE"
set -u
if ! command -v ffmpeg >/dev/null || ! command -v ffprobe >/dev/null; then
  echo "Pinned FFmpeg module did not provide ffmpeg and ffprobe: $FFMPEG_MODULE" >&2
  exit 2
fi
if [[ ! -f "$REPO_ROOT/pyproject.toml" ||
      ! -f "$REPO_ROOT/uv.lock" ||
      ! -f "$REPO_ROOT/workers/separator/pyproject.toml" ||
      ! -f "$REPO_ROOT/workers/separator/uv.lock" ]]; then
  echo "Repository or locked separator project is incomplete: $REPO_ROOT" >&2
  exit 2
fi

mkdir -p \
  "$ROOT_ENV" \
  "$WORKER_ENV" \
  "$UV_CACHE_DIR" \
  "$UV_PYTHON_INSTALL_DIR" \
  "$SEPARATOR_MODEL_DIR" \
  "$(dirname "$SEPARATOR_MODEL_PROVENANCE")"
chmod 700 \
  "$ROOT_ENV" \
  "$WORKER_ENV" \
  "$UV_CACHE_DIR" \
  "$UV_PYTHON_INSTALL_DIR" \
  "$SEPARATOR_MODEL_DIR" \
  "$(dirname "$SEPARATOR_MODEL_PROVENANCE")"

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
  SLURM_GPUS \
  CUDA_VISIBLE_DEVICES \
  AMT_REPO_ROOT \
  AMT_ROOT_ENV \
  SEPARATOR_ENV \
  SEPARATOR_MODEL_DIR \
  SEPARATOR_MODEL_PROVENANCE \
  UV_BIN \
  UV_CACHE_DIR \
  UV_PYTHON_INSTALL_DIR \
  SEPARATOR_PYTHON \
  FFMPEG_MODULE
do
  print_env_value "$name"
done
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
ffmpeg -version
ffprobe -version

cd "$REPO_ROOT"
UV_PROJECT_ENVIRONMENT="$ROOT_ENV" \
  UV_CACHE_DIR="$UV_CACHE_DIR" \
  "$UV_BIN" sync \
    --project "$REPO_ROOT" \
    --locked \
    --python "$SEPARATOR_PYTHON"
UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" python install "$SEPARATOR_PYTHON"
UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" venv \
    --clear \
    --managed-python \
    --python "$SEPARATOR_PYTHON" \
    "$WORKER_ENV"
UV_PROJECT_ENVIRONMENT="$WORKER_ENV" \
  UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" sync \
    --project "$REPO_ROOT/workers/separator" \
    --locked \
    --managed-python \
    --python "$SEPARATOR_PYTHON"

ROOT_PYTHON="$ROOT_ENV/bin/python"
WORKER_PYTHON="$WORKER_ENV/bin/python"
if [[ ! -x "$ROOT_PYTHON" || ! -x "$WORKER_PYTHON" ]]; then
  echo "uv sync did not create the expected isolated Python environments." >&2
  exit 2
fi

"$ROOT_PYTHON" --version
"$WORKER_PYTHON" - <<'PY'
import importlib.metadata
import json
import platform

import onnxruntime as ort
import torch

cuda_available = bool(torch.cuda.is_available())
print(json.dumps({
    "python": platform.python_version(),
    "machine": platform.machine(),
    "audio_separator": importlib.metadata.version("audio-separator"),
    "numpy": importlib.metadata.version("numpy"),
    "numba": importlib.metadata.version("numba"),
    "onnxruntime": importlib.metadata.version("onnxruntime"),
    "onnxruntime_providers": ort.get_available_providers(),
    "torch": torch.__version__,
    "cuda_available": cuda_available,
    "cuda_version": torch.version.cuda,
    "cuda_device_count": torch.cuda.device_count(),
    "cuda_device_name": torch.cuda.get_device_name(0) if cuda_available else None,
}, indent=2, sort_keys=True))
if not cuda_available:
    raise SystemExit("CUDA is unavailable inside the separator worker environment")
PY

"$ROOT_PYTHON" "$REPO_ROOT/workers/separator/fetch_models.py" \
  --worker-env "$WORKER_ENV" \
  --model-dir "$SEPARATOR_MODEL_DIR" \
  --output "$SEPARATOR_MODEL_PROVENANCE"

echo "Separator environment and model download completed on the Slurm compute node."
echo "Review the provenance JSON and pin every model-file hash before inference."
