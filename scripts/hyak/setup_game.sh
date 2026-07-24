#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ -z "${SLURM_JOB_ID:-}" || "$(hostname)" == klone-login* ]]; then
  echo "Run GAME setup through sbatch on a compute node, never on a login node." >&2
  exit 2
fi

: "${AMT_REPO_ROOT:?Export AMT_REPO_ROOT as the absolute repository path}"
: "${GAME_ASSET_ROOT:?Export GAME_ASSET_ROOT in private persistent storage}"

REPO_ROOT_RAW="$AMT_REPO_ROOT"
ASSET_ROOT_RAW="$GAME_ASSET_ROOT"
UV_BIN="${UV_BIN:-}"
GAME_PYTHON="${GAME_PYTHON:-3.12}"
ROOT_ENV_RAW="${AMT_ROOT_ENV:-$REPO_ROOT_RAW/.venv}"
WORKER_ENV_RAW="${GAME_ENV:-$REPO_ROOT_RAW/workers/game/.venv}"
SOURCE_DIR_RAW="${GAME_SOURCE_DIR:-$ASSET_ROOT_RAW/source}"
PROVENANCE_RAW="${GAME_MODEL_PROVENANCE:-$ASSET_ROOT_RAW/model-provenance.json}"
PINS_PATH_RAW="${GAME_PINS:-$REPO_ROOT_RAW/workers/game/pins.json}"
UV_CACHE_DIR_RAW="${UV_CACHE_DIR:-$ASSET_ROOT_RAW/uv-cache}"
UV_PYTHON_INSTALL_DIR_RAW="${UV_PYTHON_INSTALL_DIR:-$ASSET_ROOT_RAW/python}"
CUDA_MODULE="${CUDA_MODULE:-cuda/12.9.1}"
EXPECTED_COMMIT="475a8ee781fe8cca980b3b12fbe6c80c768a813a"
UPSTREAM_REPOSITORY="https://github.com/openvpi/GAME.git"

for path in "$REPO_ROOT_RAW" "$ASSET_ROOT_RAW" "$ROOT_ENV_RAW" "$WORKER_ENV_RAW" \
  "$SOURCE_DIR_RAW" "$PROVENANCE_RAW" "$PINS_PATH_RAW" "$UV_CACHE_DIR_RAW" \
  "$UV_PYTHON_INSTALL_DIR_RAW"; do
  if [[ "$path" != /* ]]; then
    echo "All GAME setup paths must be absolute: $path" >&2
    exit 2
  fi
done

PATH_CANONICALIZER="$(command -v python3 || true)"
if [[ -z "$PATH_CANONICALIZER" || ! -x "$PATH_CANONICALIZER" ]]; then
  echo "python3 is required to canonicalize GAME setup paths safely." >&2
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
ROOT_ENV="$(canonicalize_path "$ROOT_ENV_RAW")"
WORKER_ENV="$(canonicalize_path "$WORKER_ENV_RAW")"
SOURCE_DIR="$(canonicalize_path "$SOURCE_DIR_RAW")"
PROVENANCE="$(canonicalize_path "$PROVENANCE_RAW")"
PINS_PATH="$(canonicalize_path "$PINS_PATH_RAW")"
UV_CACHE_DIR="$(canonicalize_path "$UV_CACHE_DIR_RAW")"
UV_PYTHON_INSTALL_DIR="$(canonicalize_path "$UV_PYTHON_INSTALL_DIR_RAW")"
if [[ "$REPO_ROOT" == "/" ||
      "$ASSET_ROOT" == "/" ||
      "$ROOT_ENV" == "/" ||
      "$ROOT_ENV" == "$REPO_ROOT" ||
      "$WORKER_ENV" == "/" ||
      "$WORKER_ENV" == "$REPO_ROOT" ||
      "$ROOT_ENV" == "$WORKER_ENV" ]]; then
  echo "GAME repository, asset, and environment paths violate the safety boundary." >&2
  exit 2
fi
if ! path_is_within "$ROOT_ENV" "$REPO_ROOT"; then
  echo "AMT_ROOT_ENV must resolve inside the repository: $ROOT_ENV" >&2
  exit 2
fi
if ! path_is_within "$WORKER_ENV" "$REPO_ROOT/workers/game"; then
  echo "GAME_ENV must resolve inside workers/game: $WORKER_ENV" >&2
  exit 2
fi
if path_is_within "$ROOT_ENV" "$WORKER_ENV" ||
   path_is_within "$WORKER_ENV" "$ROOT_ENV"; then
  echo "Root and GAME worker environments must not contain one another." >&2
  exit 2
fi
if ! path_is_within "$SOURCE_DIR" "$ASSET_ROOT" ||
   ! path_is_within "$PROVENANCE" "$ASSET_ROOT" ||
   ! path_is_within "$UV_CACHE_DIR" "$ASSET_ROOT" ||
   ! path_is_within "$UV_PYTHON_INSTALL_DIR" "$ASSET_ROOT"; then
  echo "GAME source, provenance, uv cache, and Python store must stay under GAME_ASSET_ROOT." >&2
  exit 2
fi
if ! path_is_within "$PINS_PATH" "$REPO_ROOT/workers/game"; then
  echo "GAME_PINS must resolve inside workers/game: $PINS_PATH" >&2
  exit 2
fi
if [[ ! -d "$REPO_ROOT" || ! -f "$PINS_PATH" ]]; then
  echo "AMT repository or GAME pins are unavailable." >&2
  exit 2
fi
if [[ -z "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "uv not found; pass UV_BIN=/absolute/path/to/uv." >&2
  exit 2
fi

set +u
if ! type module >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source /etc/profile.d/lmod.sh
  module use /sw/klone /sw/contrib/modulefiles
fi
module --ignore_cache load "$CUDA_MODULE"
set -u

mkdir -p "$ASSET_ROOT" "$UV_CACHE_DIR" "$UV_PYTHON_INSTALL_DIR"
if [[ -e "$SOURCE_DIR" || -L "$SOURCE_DIR" ]]; then
  if [[ ! -d "$SOURCE_DIR/.git" ]]; then
    echo "Existing GAME_SOURCE_DIR is not a Git checkout: $SOURCE_DIR" >&2
    exit 2
  fi
else
  TEMP_ROOT="$(mktemp -d "$ASSET_ROOT/.game-source.XXXXXX")"
  trap 'rm -rf "$TEMP_ROOT"' EXIT
  git clone --filter=blob:none --no-checkout "$UPSTREAM_REPOSITORY" "$TEMP_ROOT/source"
  git -C "$TEMP_ROOT/source" checkout --detach "$EXPECTED_COMMIT"
  mv "$TEMP_ROOT/source" "$SOURCE_DIR"
  rmdir "$TEMP_ROOT"
  trap - EXIT
fi

ACTUAL_COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
if [[ "$ACTUAL_COMMIT" != "$EXPECTED_COMMIT" ]]; then
  echo "GAME source commit mismatch: $ACTUAL_COMMIT" >&2
  exit 2
fi
if [[ -n "$(git -C "$SOURCE_DIR" status --porcelain)" ]]; then
  echo "GAME source checkout must be clean." >&2
  exit 2
fi

cd "$REPO_ROOT"
ROOT_PYTHON="$ROOT_ENV/bin/python"
if [[ ! -x "$ROOT_PYTHON" ]]; then
  echo "Root project environment is unavailable; run the root uv sync before GAME setup." >&2
  exit 2
fi
UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" python install "$GAME_PYTHON"
UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" venv \
    --clear \
    --managed-python \
    --python "$GAME_PYTHON" \
    "$WORKER_ENV"
UV_PROJECT_ENVIRONMENT="$WORKER_ENV" \
  UV_CACHE_DIR="$UV_CACHE_DIR" \
  UV_PYTHON_INSTALL_DIR="$UV_PYTHON_INSTALL_DIR" \
  "$UV_BIN" sync \
    --project "$REPO_ROOT/workers/game" \
    --locked \
    --managed-python \
    --python "$GAME_PYTHON"

WORKER_PYTHON="$WORKER_ENV/bin/python"
if [[ ! -x "$ROOT_PYTHON" || ! -x "$WORKER_PYTHON" ]]; then
  echo "uv sync did not create the expected GAME environments." >&2
  exit 2
fi

nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
"$WORKER_PYTHON" - <<'PY'
import importlib.metadata
import json
import platform
import torch

available = bool(torch.cuda.is_available())
print(json.dumps({
    "python": platform.python_version(),
    "torch": torch.__version__,
    "lightning": importlib.metadata.version("lightning"),
    "cuda_available": available,
    "cuda_version": torch.version.cuda,
    "cuda_device": torch.cuda.get_device_name(0) if available else None,
}, indent=2, sort_keys=True))
if not available:
    raise SystemExit("CUDA is unavailable inside the GAME worker environment")
PY

(
  cd "$SOURCE_DIR"
  "$WORKER_PYTHON" - <<'PY'
import inference.callbacks
import inference.data
import training.augmentation

print({
    "game_inference_import_smoke": "passed",
    "modules": [
        inference.callbacks.__name__,
        inference.data.__name__,
        training.augmentation.__name__,
    ],
})
PY
)

"$ROOT_PYTHON" "$REPO_ROOT/workers/game/prepare_assets.py" \
  --source-dir "$SOURCE_DIR" \
  --asset-root "$ASSET_ROOT" \
  --pins "$PINS_PATH" \
  --output "$PROVENANCE"

echo "GAME setup completed on the Slurm compute node."
echo "Before inference, ensure pins.json expected_files matches the provenance exactly."
