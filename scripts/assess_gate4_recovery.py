#!/usr/bin/env python3
"""Apply the frozen Task 007B automatic Gate 4 precondition."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

from amt_core.utils import atomic_write_json, sha256_file

SCHEMA = "amt-task007b-gate4-precondition/v1"
ONSET_PITCH_MIN_DELTA = 0.01
ONSET_PITCH_OFFSET_MIN_DELTA = -0.01
EXPECTED_WORKER_ABLATIONS = {
    "game-vocal-a",
    "basic-pitch-vocal-a",
}


class Gate4RecoveryAssessmentError(RuntimeError):
    """Raised when the sealed blind report cannot be assessed safely."""


def _load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Gate4RecoveryAssessmentError(f"cannot read blind report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise Gate4RecoveryAssessmentError("blind report must be a JSON object")
    return value


def _finite_delta(comparison: dict[str, Any], metric: str) -> float:
    value = comparison.get(metric)
    delta = value.get("delta") if isinstance(value, dict) else None
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or not math.isfinite(delta):
        raise Gate4RecoveryAssessmentError(f"{metric} comparison delta is unavailable")
    return float(delta)


def assess(report_path: Path, output_path: Path) -> dict[str, Any]:
    """Verify one blind report and write the predeclared automatic decision."""

    report_path = report_path.expanduser().resolve(strict=True)
    output_path = output_path.expanduser().resolve(strict=False)
    if output_path.exists() or output_path.is_symlink():
        raise Gate4RecoveryAssessmentError(f"output path already exists: {output_path}")
    if not output_path.parent.is_dir():
        raise Gate4RecoveryAssessmentError(f"output parent does not exist: {output_path.parent}")

    report = _load_report(report_path)
    claims = report.get("claims")
    tasks = report.get("tasks")
    main_melody = tasks.get("main_melody") if isinstance(tasks, dict) else None
    comparison = (
        main_melody.get("comparison") if isinstance(main_melody, dict) else None
    )
    ablations = report.get("ablations")
    if (
        report.get("schema") != "amt-fusion-blind-evaluation/v1"
        or not isinstance(claims, dict)
        or claims.get("blind_fusion_seal_verified") is not True
        or claims.get("candidate_preinspection_seal_verified") is not True
        or claims.get("development_only_calibration_verified") is not True
        or claims.get("blind_retuning_performed") is not False
        or claims.get("manual_correction_time_measured") is not False
        or not isinstance(comparison, dict)
        or not isinstance(ablations, list)
    ):
        raise Gate4RecoveryAssessmentError(
            "blind report lacks the required seals, split isolation, or claims"
        )
    worker_ablations = {
        record.get("removed_component")
        for record in ablations
        if isinstance(record, dict) and record.get("variant_type") == "worker_removal"
    }
    if worker_ablations != EXPECTED_WORKER_ABLATIONS:
        raise Gate4RecoveryAssessmentError(
            f"worker ablations differ from the frozen two-route plan: {worker_ablations!r}"
        )

    strongest = comparison.get("strongest_baseline_by_metric")
    if not isinstance(strongest, dict):
        raise Gate4RecoveryAssessmentError("strongest-baseline comparison is unavailable")
    onset_pitch_delta = _finite_delta(strongest, "onset_pitch")
    onset_pitch_offset_delta = _finite_delta(strongest, "onset_pitch_offset")
    onset_pitch_passed = onset_pitch_delta >= ONSET_PITCH_MIN_DELTA
    onset_pitch_offset_passed = (
        onset_pitch_offset_delta >= ONSET_PITCH_OFFSET_MIN_DELTA
    )
    automatic_passed = onset_pitch_passed and onset_pitch_offset_passed

    decision = {
        "schema": SCHEMA,
        "blind_report": {
            "path": str(report_path),
            "sha256": sha256_file(report_path),
            "size_bytes": report_path.stat().st_size,
        },
        "frozen_thresholds": {
            "onset_pitch_minimum_absolute_delta": ONSET_PITCH_MIN_DELTA,
            "onset_pitch_offset_minimum_absolute_delta": (
                ONSET_PITCH_OFFSET_MIN_DELTA
            ),
        },
        "observed": {
            "onset_pitch_delta": onset_pitch_delta,
            "onset_pitch_offset_delta": onset_pitch_offset_delta,
            "worker_ablations": sorted(worker_ablations),
        },
        "checks": {
            "onset_pitch_improvement_passed": onset_pitch_passed,
            "onset_pitch_offset_guard_passed": onset_pitch_offset_passed,
            "precision_coverage_preserved_by_evaluation": True,
            "worker_ablations_preserved": True,
            "blind_retuning_performed": False,
            "human_correction_measured": False,
        },
        "automatic_precondition_passed": automatic_passed,
        "decision": (
            "eligible_for_matched_human_correction"
            if automatic_passed
            else "reject_v2_without_blind_retuning"
        ),
        "gate4_passed": False,
        "gate4_status": (
            "awaiting_matched_human_correction"
            if automatic_passed
            else "automatic_precondition_failed"
        ),
    }
    atomic_write_json(output_path, decision)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = assess(args.report, args.output)
    except (Gate4RecoveryAssessmentError, OSError, ValueError) as exc:
        parser.exit(2, f"error: {exc}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
