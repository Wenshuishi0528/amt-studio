from __future__ import annotations

import argparse
import json
from pathlib import Path

from workers.muscriptor.targeted_gap_recovery import (
    TargetedGapRecoveryError,
    build_recovery_stage_comparison_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build three independently playable diagnostic tracks from one "
            "completed targeted gap-recovery run."
        )
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-bundle", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = build_recovery_stage_comparison_bundle(
            args.project,
            recovery_run_id=args.run_id,
            output_bundle_id=args.output_bundle,
        )
    except (OSError, RuntimeError, ValueError, TargetedGapRecoveryError) as exc:
        print(
            json.dumps(
                {"status": "failed", "error": str(exc)},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 1
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
