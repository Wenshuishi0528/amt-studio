#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

missing=0
for tool in git ffmpeg ffprobe uv; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "Missing required tool: $tool" >&2
    missing=1
  fi
done

if [[ "$missing" -ne 0 ]]; then
  cat >&2 <<'EOF'
Install missing tools on macOS with Homebrew, for example:
  brew install git ffmpeg uv
Then rerun this script.
EOF
  exit 2
fi

python_version="$(uv run --python 3.12 python -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
echo "Using Python $python_version"

uv sync
uv run python -m unittest discover -s tests -v
uv run amt doctor

cat <<'EOF'
Mac bootstrap complete.
Next:
  mkdir -p data/private/inbox projects/private
  cp "/path/to/song.mp3" data/private/inbox/
  uv run amt init-project "data/private/inbox/song.mp3" --output "projects/private/song"
EOF
