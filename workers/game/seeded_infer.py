from __future__ import annotations

import argparse
import os
import random
import runpy
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed GAME's stochastic D3PM path before invoking upstream infer.py."
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--infer-script", type=Path, required=True)
    parser.add_argument("upstream_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    infer_script = args.infer_script.expanduser().resolve(strict=True)
    upstream_args = list(args.upstream_args)
    if upstream_args[:1] == ["--"]:
        upstream_args = upstream_args[1:]
    if not upstream_args:
        raise ValueError("At least one upstream infer.py argument is required")
    if args.seed < 0:
        raise ValueError("--seed must be non-negative")

    expected_hash_seed = str(args.seed)
    current_hash_seed = os.environ.get("PYTHONHASHSEED")
    if current_hash_seed != expected_hash_seed:
        raise RuntimeError(
            "PYTHONHASHSEED must be set by the parent process before Python starts: "
            f"expected {expected_hash_seed!r}, got {current_hash_seed!r}"
        )

    import numpy
    import torch

    random.seed(args.seed)
    numpy.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True

    source_dir = infer_script.parent
    sys.path.insert(0, str(source_dir))
    sys.argv = [str(infer_script), *upstream_args]
    previous_cwd = Path.cwd()
    try:
        os.chdir(source_dir)
        runpy.run_path(str(infer_script), run_name="__main__")
    finally:
        os.chdir(previous_cwd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
