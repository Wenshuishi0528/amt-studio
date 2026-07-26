#!/usr/bin/env python3
"""Apply the frozen Task 007C development stop rule to one contour report."""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.benchmark import canonical_json_sha256
from amt_core.utils import atomic_write_json, sha256_file

EXPECTED_BENCHMARK = "medleydb-phoenix-task007c-development-v1"
EXPECTED_PROJECT = "medleydb-phoenix-scotch-morris"
EXPECTED_REFERENCE_ROLE = "development_instrumental_melody"
EXPECTED_REFERENCE_SHA256 = "c1cb36655177b353e81d11778b755d92263e4f6b53070659c4d1e3dd8b34f508"
EXPECTED_INSTRUMENT = "other"
EXPECTED_CANDIDATE = "basic-pitch-direct-mix"
EXPECTED_PROJECTION = "highest_pitch_then_latest_onset_then_lexical_event_id"
EXPECTED_CENT_TOLERANCE = 50.0
THRESHOLDS = {
    "minimum_raw_pitch_accuracy": 0.70,
    "minimum_overall_accuracy": 0.70,
    "maximum_voicing_false_alarm": 0.25,
}


class InstrumentalProbeAssessmentError(RuntimeError):
    """Raised when Task 007C evidence cannot be assessed safely."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstrumentalProbeAssessmentError(
            f"Cannot read {label} {path}: {exc}"
        ) from exc
    if not isinstance(value, dict):
        raise InstrumentalProbeAssessmentError(f"{label} must be an object")
    return value


def _metric(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InstrumentalProbeAssessmentError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 0 <= number <= 1:
        raise InstrumentalProbeAssessmentError(f"{label} must be finite and in [0, 1]")
    return number


def _artifact(path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    if not resolved.is_file() or resolved.is_symlink():
        raise InstrumentalProbeAssessmentError(f"evidence must be a regular file: {path}")
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _require_manifest_artifact(
    records: Any,
    artifact: dict[str, Any],
    *,
    label: str,
) -> None:
    if not isinstance(records, list):
        raise InstrumentalProbeAssessmentError("evaluation run inputs are invalid")
    matches = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("sha256") == artifact["sha256"]
        and record.get("size_bytes") == artifact["size_bytes"]
    ]
    if len(matches) != 1:
        raise InstrumentalProbeAssessmentError(
            f"evaluation run does not bind exactly one {label}"
        )


def _verify_frozen_evidence(
    *,
    pack_dir: Path,
    report_path: Path,
    run_manifest_path: Path,
    report: dict[str, Any],
) -> dict[str, Any]:
    pack_dir = pack_dir.resolve(strict=True)
    report_path = report_path.resolve(strict=True)
    run_manifest_path = run_manifest_path.resolve(strict=True)
    if (
        not pack_dir.is_dir()
        or pack_dir.name != "reference-task007c-phoenix-development-v1"
        or report_path.name != "report.json"
        or run_manifest_path.name != "run_manifest.json"
        or report_path.parent != run_manifest_path.parent
    ):
        raise InstrumentalProbeAssessmentError("Task 007C evidence paths are invalid")

    project_dir = pack_dir.parent.parent
    benchmark_path = pack_dir / "benchmark_manifest.json"
    seal_path = pack_dir / "candidate_set_seal.json"
    benchmark_artifact = _artifact(benchmark_path)
    seal_artifact = _artifact(seal_path)
    report_artifact = _artifact(report_path)
    benchmark_manifest = _load_object(benchmark_path, label="benchmark manifest")
    benchmark_payload = benchmark_manifest.get("freeze_payload")
    if (
        benchmark_manifest.get("schema") != "amt-benchmark-pack/v1"
        or not isinstance(benchmark_payload, dict)
        or canonical_json_sha256(benchmark_payload)
        != benchmark_manifest.get("benchmark_freeze_sha256")
        or benchmark_payload.get("benchmark_id") != EXPECTED_BENCHMARK
        or benchmark_payload.get("project_id") != EXPECTED_PROJECT
        or benchmark_payload.get("split") != "development"
    ):
        raise InstrumentalProbeAssessmentError("Task 007C benchmark freeze is invalid")

    seal = _load_object(seal_path, label="candidate-set seal")
    seal_payload = seal.get("freeze_payload")
    sealed_candidates = (
        seal_payload.get("candidates") if isinstance(seal_payload, dict) else None
    )
    if (
        seal.get("schema") != "amt-evaluation-candidate-set-seal/v1"
        or not isinstance(seal_payload, dict)
        or canonical_json_sha256(seal_payload) != seal.get("candidate_set_sha256")
        or seal_payload.get("benchmark_freeze_sha256")
        != benchmark_manifest.get("benchmark_freeze_sha256")
        or seal_payload.get("split") != "development"
        or not isinstance(sealed_candidates, list)
        or len(sealed_candidates) != 1
    ):
        raise InstrumentalProbeAssessmentError("Task 007C candidate-set seal is invalid")
    sealed_candidate = sealed_candidates[0]
    confirmation = seal_payload.get("confirmation")
    if (
        not isinstance(sealed_candidate, dict)
        or sealed_candidate.get("label") != EXPECTED_CANDIDATE
        or sealed_candidate.get("worker") != "basic_pitch"
        or not isinstance(confirmation, dict)
        or confirmation.get("candidate_output_quality_uninspected_before_freeze")
        is not True
    ):
        raise InstrumentalProbeAssessmentError("fixed sealed Basic Pitch candidate is invalid")

    report_benchmark = report.get("benchmark")
    if (
        not isinstance(report_benchmark, dict)
        or report_benchmark.get("benchmark_id") != EXPECTED_BENCHMARK
        or report_benchmark.get("project_id") != EXPECTED_PROJECT
        or report_benchmark.get("split") != "development"
        or report_benchmark.get("benchmark_freeze_sha256")
        != benchmark_manifest.get("benchmark_freeze_sha256")
        or report_benchmark.get("candidate_set_sha256")
        != seal.get("candidate_set_sha256")
        or report_benchmark.get("candidate_output_quality_uninspected_before_freeze")
        is not True
    ):
        raise InstrumentalProbeAssessmentError(
            "report does not bind the frozen benchmark and candidate set"
        )

    run_id = sealed_candidate.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise InstrumentalProbeAssessmentError("sealed candidate run ID is invalid")
    candidate_events = project_dir / "runs" / run_id / "normalized" / "events.jsonl"
    candidate_manifest = project_dir / "runs" / run_id / "run_manifest.json"
    candidate_events_artifact = _artifact(candidate_events)
    candidate_manifest_artifact = _artifact(candidate_manifest)
    if (
        candidate_events_artifact["sha256"] != sealed_candidate.get("events_sha256")
        or candidate_manifest_artifact["sha256"]
        != sealed_candidate.get("run_manifest_sha256")
    ):
        raise InstrumentalProbeAssessmentError("sealed candidate artifacts changed")

    run_manifest = _load_object(run_manifest_path, label="evaluation run manifest")
    expected_configuration = {
        "cent_tolerance": EXPECTED_CENT_TOLERANCE,
        "instrument_filter": EXPECTED_INSTRUMENT,
        "projection_rule": EXPECTED_PROJECTION,
        "reference_role": EXPECTED_REFERENCE_ROLE,
    }
    outputs = run_manifest.get("outputs")
    report_outputs = (
        [
            record
            for record in outputs
            if isinstance(record, dict) and record.get("path") == "report.json"
        ]
        if isinstance(outputs, list)
        else []
    )
    if (
        run_manifest.get("schema")
        != "amt-external-melody-contour-evaluation-run/v1"
        or run_manifest.get("status") != "succeeded"
        or run_manifest.get("project_id") != EXPECTED_PROJECT
        or run_manifest.get("configuration") != expected_configuration
        or run_manifest.get("benchmark") != report.get("benchmark")
        or run_manifest.get("reference") != report.get("reference")
        or len(report_outputs) != 1
        or report_outputs[0].get("sha256") != report_artifact["sha256"]
        or report_outputs[0].get("size_bytes") != report_artifact["size_bytes"]
    ):
        raise InstrumentalProbeAssessmentError(
            "evaluation run manifest does not authenticate the report and frozen policy"
        )
    inputs = run_manifest.get("inputs")
    for artifact, label in (
        (benchmark_artifact, "benchmark manifest"),
        (seal_artifact, "candidate-set seal"),
        (candidate_events_artifact, "candidate events"),
        (candidate_manifest_artifact, "candidate run manifest"),
    ):
        _require_manifest_artifact(inputs, artifact, label=label)

    reference = report.get("reference")
    candidates = report.get("candidates")
    candidate = candidates[0] if isinstance(candidates, list) and len(candidates) == 1 else None
    metrics = candidate.get("aggregate_frame_metrics") if isinstance(candidate, dict) else None
    projection = candidate.get("aggregate_projection") if isinstance(candidate, dict) else None
    if (
        not isinstance(reference, dict)
        or reference.get("sha256") != EXPECTED_REFERENCE_SHA256
        or not isinstance(candidate, dict)
        or candidate.get("run_id") != run_id
        or candidate.get("events_sha256") != candidate_events_artifact["sha256"]
        or not isinstance(metrics, dict)
        or metrics.get("cent_tolerance") != EXPECTED_CENT_TOLERANCE
        or not isinstance(projection, dict)
        or projection.get("instrument_filter") != EXPECTED_INSTRUMENT
        or projection.get("overlap_rule") != EXPECTED_PROJECTION
    ):
        raise InstrumentalProbeAssessmentError(
            "report does not match the sealed candidate, reference, or projection"
        )

    return {
        "benchmark_manifest": benchmark_artifact,
        "candidate_set_seal": seal_artifact,
        "candidate_events": candidate_events_artifact,
        "candidate_run_manifest": candidate_manifest_artifact,
        "evaluation_run_manifest": _artifact(run_manifest_path),
    }


def assess_report(
    report_path: Path,
    output_path: Path,
    *,
    pack_dir: Path,
    run_manifest_path: Path,
) -> dict[str, Any]:
    report_path = report_path.resolve(strict=True)
    if output_path.exists() or output_path.is_symlink():
        raise InstrumentalProbeAssessmentError(
            f"refusing to replace assessment output: {output_path}"
        )
    report = _load_object(report_path, label="evaluation report")
    verified_evidence = _verify_frozen_evidence(
        pack_dir=pack_dir,
        report_path=report_path,
        run_manifest_path=run_manifest_path,
        report=report,
    )
    benchmark = report.get("benchmark")
    policy = report.get("policy")
    candidates = report.get("candidates")
    if (
        report.get("schema") != "amt-external-melody-contour-evaluation/v1"
        or not isinstance(benchmark, dict)
        or benchmark.get("benchmark_id") != EXPECTED_BENCHMARK
        or benchmark.get("split") != "development"
        or not isinstance(policy, dict)
        or policy.get("reference_role") != EXPECTED_REFERENCE_ROLE
        or policy.get("instrument_filter") != EXPECTED_INSTRUMENT
        or policy.get("projection_rule") != EXPECTED_PROJECTION
        or policy.get("cent_tolerance") != EXPECTED_CENT_TOLERANCE
        or policy.get("candidate_selection_after_scoring_prohibited") is not False
        or policy.get("owner_listening_percentages_used_as_formal_accuracy") is not False
        or not isinstance(candidates, list)
        or len(candidates) != 1
    ):
        raise InstrumentalProbeAssessmentError(
            "report identity, development split, or frozen policy is invalid"
        )
    candidate = candidates[0]
    metrics = candidate.get("aggregate_frame_metrics") if isinstance(candidate, dict) else None
    if (
        not isinstance(candidate, dict)
        or candidate.get("label") != EXPECTED_CANDIDATE
        or candidate.get("worker") != "basic_pitch"
        or not isinstance(metrics, dict)
    ):
        raise InstrumentalProbeAssessmentError("fixed Basic Pitch candidate is missing")

    raw_pitch_accuracy = _metric(
        metrics.get("raw_pitch_accuracy"),
        label="raw_pitch_accuracy",
    )
    overall_accuracy = _metric(
        metrics.get("overall_accuracy"),
        label="overall_accuracy",
    )
    voicing_false_alarm = _metric(
        metrics.get("voicing_false_alarm"),
        label="voicing_false_alarm",
    )
    checks = {
        "raw_pitch_accuracy": {
            "value": raw_pitch_accuracy,
            "operator": ">=",
            "threshold": THRESHOLDS["minimum_raw_pitch_accuracy"],
            "passed": raw_pitch_accuracy >= THRESHOLDS["minimum_raw_pitch_accuracy"],
        },
        "overall_accuracy": {
            "value": overall_accuracy,
            "operator": ">=",
            "threshold": THRESHOLDS["minimum_overall_accuracy"],
            "passed": overall_accuracy >= THRESHOLDS["minimum_overall_accuracy"],
        },
        "voicing_false_alarm": {
            "value": voicing_false_alarm,
            "operator": "<=",
            "threshold": THRESHOLDS["maximum_voicing_false_alarm"],
            "passed": voicing_false_alarm <= THRESHOLDS["maximum_voicing_false_alarm"],
        },
    }
    passed = all(check["passed"] for check in checks.values())
    decision = {
        "schema": "amt-instrumental-development-decision/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "task": "007C",
        "benchmark_id": EXPECTED_BENCHMARK,
        "split": "development",
        "candidate": EXPECTED_CANDIDATE,
        "report": {
            "path": str(report_path),
            "sha256": sha256_file(report_path),
        },
        "code": {
            "path": "scripts/assess_instrumental_dev_probe.py",
            "sha256": sha256_file(Path(__file__).resolve()),
        },
        "verified_evidence": verified_evidence,
        "checks": checks,
        "all_conditions_passed": passed,
        "decision": (
            "advance_to_new_artist_disjoint_instrumental_blind"
            if passed
            else "reject_direct_mix_instrumental_route_for_v1"
        ),
        "scope": {
            "gate4_passed": False,
            "production_route_authorized": False,
            "phoenix_is_blind": False,
            "phoenix_retuning_authorized": False,
            "task009b2b_authorized": False,
            "task010_authorized": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output_path, decision)
    return decision


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--run-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    decision = assess_report(
        args.report,
        args.output,
        pack_dir=args.pack_dir,
        run_manifest_path=args.run_manifest,
    )
    print(json.dumps(decision, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
