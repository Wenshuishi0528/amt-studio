#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Basic Pitch setup must run inside a Slurm CPU allocation, not on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"

REPO_ROOT_RAW="$AMT_REPO_ROOT"
ROOT_ENV_RAW="${AMT_ROOT_ENV:-$REPO_ROOT_RAW/.venv}"
WORKER_ENV_RAW="${BASIC_PITCH_ENV:-$REPO_ROOT_RAW/workers/basic_pitch/.venv}"
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
  echo "AMT_ROOT_ENV and BASIC_PITCH_ENV resolve to the same environment." >&2
  exit 2
fi
if [[ "$REPO_ROOT" == "/" ||
      "$ROOT_ENV" == "/" ||
      "$ROOT_ENV" == "$REPO_ROOT" ||
      "$WORKER_ENV" == "/" ||
      "$WORKER_ENV" == "$REPO_ROOT" ]]; then
  echo "Repository and environment paths do not satisfy the safety boundary." >&2
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
if ! path_is_within "$WORKER_ENV" "$REPO_ROOT/workers/basic_pitch"; then
  echo "BASIC_PITCH_ENV must resolve inside workers/basic_pitch: $WORKER_ENV" >&2
  exit 2
fi
if path_is_within "$ROOT_ENV" "$WORKER_ENV" ||
   path_is_within "$WORKER_ENV" "$ROOT_ENV"; then
  echo "Root and Basic Pitch environments must not contain one another." >&2
  exit 2
fi

UV_BIN="${UV_BIN:-}"
UV_CACHE_DIR="${UV_CACHE_DIR:-$REPO_ROOT/.uv-cache}"
UV_PYTHON_INSTALL_DIR="${UV_PYTHON_INSTALL_DIR:-$REPO_ROOT/.uv-python}"
ROOT_PYTHON_VERSION="${AMT_ROOT_PYTHON_VERSION:-3.12}"
BASIC_PITCH_PYTHON="${BASIC_PITCH_PYTHON:-3.10}"
PINS_PATH="${BASIC_PITCH_PINS:-$REPO_ROOT/workers/basic_pitch/pins.json}"

if [[ -z "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "uv not found; export UV_BIN as the absolute path to the approved uv binary." >&2
  exit 2
fi
if [[ ! -f "$REPO_ROOT/pyproject.toml" ||
      ! -f "$REPO_ROOT/uv.lock" ||
      ! -f "$REPO_ROOT/workers/basic_pitch/pyproject.toml" ||
      ! -f "$REPO_ROOT/workers/basic_pitch/uv.lock" ||
      ! -f "$PINS_PATH" ]]; then
  echo "Repository or locked Basic Pitch project is incomplete: $REPO_ROOT" >&2
  exit 2
fi

mkdir -p "$ROOT_ENV" "$WORKER_ENV" "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"
chmod 700 "$ROOT_ENV" "$WORKER_ENV" "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"

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
  AMT_ROOT_ENV \
  AMT_ROOT_PYTHON_VERSION \
  BASIC_PITCH_ENV \
  BASIC_PITCH_PYTHON \
  BASIC_PITCH_PINS \
  UV_BIN \
  UV_CACHE_DIR \
  UV_PYTHON_INSTALL_DIR
do
  print_env_value "$name"
done

cd "$REPO_ROOT"
UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" python install "$ROOT_PYTHON_VERSION" "$BASIC_PITCH_PYTHON"
UV_PROJECT_ENVIRONMENT="$ROOT_ENV" \
  UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" sync \
    --project "$REPO_ROOT" \
    --locked \
    --managed-python \
    --python "$ROOT_PYTHON_VERSION"
UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" venv \
    --clear \
    --managed-python \
    --python "$BASIC_PITCH_PYTHON" \
    "$WORKER_ENV"
UV_PROJECT_ENVIRONMENT="$WORKER_ENV" \
  UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" sync \
    --project "$REPO_ROOT/workers/basic_pitch" \
    --locked \
    --managed-python \
    --python "$BASIC_PITCH_PYTHON"

ROOT_PYTHON="$ROOT_ENV/bin/python"
WORKER_PYTHON="$WORKER_ENV/bin/python"
if [[ ! -x "$ROOT_PYTHON" ||
      ! -x "$WORKER_PYTHON" ||
      ! -x "$WORKER_ENV/bin/basic-pitch" ]]; then
  echo "uv sync did not create the expected isolated Python environments." >&2
  exit 2
fi

"$ROOT_PYTHON" --version
"$WORKER_PYTHON" - "$PINS_PATH" <<'PY'
import hashlib
import importlib.metadata
import json
import pathlib
import platform
import sys

import onnxruntime as ort
import pkg_resources
from basic_pitch import FilenameSuffix, build_icassp_2022_model_path
from basic_pitch.inference import Model

pins = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
model_path = pathlib.Path(
    build_icassp_2022_model_path(FilenameSuffix.onnx)
).resolve()
model = Model(model_path)
model_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
result = {
    "python": platform.python_version(),
    "machine": platform.machine(),
    "basic_pitch": importlib.metadata.version("basic-pitch"),
    "numpy": importlib.metadata.version("numpy"),
    "onnxruntime": importlib.metadata.version("onnxruntime"),
    "setuptools": importlib.metadata.version("setuptools"),
    "pkg_resources": pkg_resources.__file__,
    "available_providers": ort.get_available_providers(),
    "model_type": model.model_type.name,
    "model_path": str(model_path),
    "model_session_providers": model.model.get_providers(),
    "model_sha256": model_hash,
    "model_size_bytes": model_path.stat().st_size,
}
print(json.dumps(result, indent=2, sort_keys=True))
if result["python"].split(".")[:2] != ["3", "10"]:
    raise SystemExit("Basic Pitch worker is not using Python 3.10")
if result["basic_pitch"] != pins["package"]["version"]:
    raise SystemExit("Basic Pitch package version does not match pins.json")
if result["numpy"] != pins["runtime"]["numpy"]:
    raise SystemExit("NumPy version does not match pins.json")
if result["onnxruntime"] != pins["runtime"]["onnxruntime"]:
    raise SystemExit("ONNX Runtime version does not match pins.json")
if result["setuptools"] != pins["runtime"]["setuptools"]:
    raise SystemExit("setuptools version does not match pins.json")
if result["model_type"] != "ONNX":
    raise SystemExit("Basic Pitch did not load the ONNX serialization")
if result["model_session_providers"] != [pins["runtime"]["onnxruntime_provider"]]:
    raise SystemExit("Basic Pitch ONNX session is not CPU-only")
if result["model_sha256"] != pins["model"]["sha256"]:
    raise SystemExit("Bundled Basic Pitch ONNX hash does not match pins.json")
if result["model_size_bytes"] != pins["model"]["size_bytes"]:
    raise SystemExit("Bundled Basic Pitch ONNX size does not match pins.json")
PY

echo "Basic Pitch environment setup and bundled-model verification completed."
echo "No audio inference was run."
