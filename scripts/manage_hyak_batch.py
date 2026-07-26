#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
from pathlib import Path

from amt_core.batch import (
    BatchInterrupted,
    BatchValidationError,
    freeze_batch_spec,
    prune_batch_cache,
    run_batch_row,
    summarize_batch,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage content-addressed Hyak batch runs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze", help="Hash a batch spec into a frozen manifest.")
    freeze.add_argument("--spec", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)

    run = subparsers.add_parser("run-row", help="Run one frozen manifest row.")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--row-index", type=int, required=True)
    run.add_argument("--cache-root", type=Path, required=True)
    run.add_argument("--selected-root", type=Path, required=True)
    run.add_argument("--index-root", type=Path, required=True)
    run.add_argument("--repo-root", type=Path, required=True)
    run.add_argument("--python", type=Path, required=True)
    run.add_argument("--allow-local", action="store_true")

    summarize = subparsers.add_parser(
        "summarize",
        help="Write the central experiment index and resource/failure summary.",
    )
    summarize.add_argument("--manifest", type=Path, required=True)
    summarize.add_argument("--cache-root", type=Path, required=True)
    summarize.add_argument("--selected-root", type=Path, required=True)
    summarize.add_argument("--index-root", type=Path, required=True)

    prune = subparsers.add_parser("prune", help="Apply the frozen cache retention policy.")
    prune.add_argument("--manifest", type=Path, required=True)
    prune.add_argument("--cache-root", type=Path, required=True)
    prune.add_argument("--selected-root", type=Path, required=True)
    prune.add_argument("--index-root", type=Path, required=True)
    prune.add_argument("--apply", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        if args.command == "freeze":
            slurm_step_id = os.environ.get("SLURM_STEP_ID")
            if shutil.which("sbatch") is not None and (
                not os.environ.get("SLURM_JOB_ID")
                or not slurm_step_id
                or slurm_step_id in {"batch", "extern"}
            ):
                raise BatchValidationError(
                    "freeze on Hyak requires an active Slurm compute step"
                )
            manifest = freeze_batch_spec(args.spec, args.output)
            print(
                json.dumps(
                    {
                        "status": "frozen",
                        "batch_id": manifest["batch_id"],
                        "row_count": len(manifest["rows"]),
                        "output": str(args.output.expanduser().resolve()),
                    },
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "run-row":
            status = run_batch_row(
                manifest_path=args.manifest,
                row_index=args.row_index,
                cache_root=args.cache_root,
                selected_root=args.selected_root,
                index_root=args.index_root,
                repo_root=args.repo_root,
                python_path=args.python,
                allow_local=args.allow_local,
            )
            print(json.dumps({"status": status, "row_index": args.row_index}, sort_keys=True))
            return 0
        if args.command == "summarize":
            index, resources = summarize_batch(
                manifest_path=args.manifest,
                cache_root=args.cache_root,
                selected_root=args.selected_root,
                index_root=args.index_root,
            )
            print(
                json.dumps(
                    {
                        "status": "summarized",
                        "status_counts": index["status_counts"],
                        "failure_rate": resources["failure_rate"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        report = prune_batch_cache(
            manifest_path=args.manifest,
            cache_root=args.cache_root,
            selected_root=args.selected_root,
            index_root=args.index_root,
            apply=args.apply,
        )
        print(json.dumps(report, sort_keys=True))
        return 0
    except BatchInterrupted as exc:
        print(json.dumps({"status": "interrupted", "error": str(exc)}, sort_keys=True))
        return 75
    except (BatchValidationError, OSError, RuntimeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
