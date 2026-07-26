#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dependency-light Task008 batch smoke worker.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkpoint-dir", type=Path)
    parser.add_argument("--interrupt-once", action="store_true")
    parser.add_argument("--record-input-name", action="store_true")
    parser.add_argument("--environment-key")
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.interrupt_once:
        if args.checkpoint_dir is None:
            raise SystemExit("--interrupt-once requires --checkpoint-dir")
        args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
        marker = args.checkpoint_dir / "interrupted-once"
        if not marker.exists():
            marker.write_text("resume-safe checkpoint\n", encoding="utf-8")
            return 75

    payload = {
        "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "configuration": json.loads(args.configuration.read_text(encoding="utf-8")),
        "model_sha256": hashlib.sha256(args.model.read_bytes()).hexdigest(),
    }
    if args.record_input_name:
        payload["input_name"] = args.input.name
    if args.environment_key:
        payload["environment_value"] = os.environ.get(args.environment_key)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
