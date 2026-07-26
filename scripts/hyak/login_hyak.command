#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG="$ROOT/configs/local_hyak.json"
if [[ -n "${HYAK_HOST:-}" ]]; then
  HOST="$HYAK_HOST"
elif [[ -f "$CONFIG" && ! -L "$CONFIG" ]]; then
  HOST="$(/usr/bin/python3 - "$CONFIG" <<'PY'
import json
import sys

value = json.load(open(sys.argv[1], encoding="utf-8"))
host = value.get("host") if isinstance(value, dict) else None
if not isinstance(host, str) or not host:
    raise SystemExit("configs/local_hyak.json 缺少 host")
print(host)
PY
)"
else
  echo "尚未配置 Hyak。请先创建 configs/local_hyak.json。" >&2
  exit 2
fi
CONTROL_DIR="$(mktemp -d /tmp/amt-hyak-control.XXXXXX)"
CONTROL_PATH="$CONTROL_DIR/socket"

echo "正在连接 ${HOST}。密码和 Duo 只在这个 Terminal 输入，不会写入项目。"
echo "连接成功后可以关闭本窗口；控制连接会保留 12 小时。"
ssh -M -S "$CONTROL_PATH" -o ControlPersist=12h "$HOST"
