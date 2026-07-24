#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UV_BIN="${UV_BIN:-}"

if [[ -z "$UV_BIN" ]]; then
  UV_BIN="$(command -v uv || true)"
fi
if [[ -z "$UV_BIN" || ! -x "$UV_BIN" ]]; then
  echo "uv not found. Install the pinned project uv tool in persistent storage" >&2
  echo "and rerun with UV_BIN=/absolute/path/to/uv." >&2
  exit 2
fi

cd "$ROOT"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$ROOT/.uv-cache}"
"$UV_BIN" sync --locked
"$UV_BIN" sync --project workers/muscriptor --locked

ROOT_PYTHON="$ROOT/.venv/bin/python"
WORKER_PYTHON="$ROOT/workers/muscriptor/.venv/bin/python"

"$ROOT_PYTHON" --version
"$WORKER_PYTHON" - <<'PY'
import importlib.metadata
import json
import platform
import torch

print(json.dumps({
    "python": platform.python_version(),
    "machine": platform.machine(),
    "muscriptor": importlib.metadata.version("muscriptor"),
    "torch": torch.__version__,
    "mps_available": bool(torch.backends.mps.is_available()),
    "cuda_available": bool(torch.cuda.is_available()),
    "cuda_version": torch.version.cuda,
}, indent=2))
PY

echo "MuScriptor environment setup complete."
echo "No model inference was run."
