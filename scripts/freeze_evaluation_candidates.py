#!/usr/bin/env python3
"""Freeze a candidate set before inspecting blind-test output quality."""

from __future__ import annotations

# ruff: noqa: E402, I001
import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from amt_core.benchmark import canonical_json_sha256
from amt_core.utils import atomic_write_json, sha256_file
from scripts.evaluate_benchmark import (
    BenchmarkEvaluationError,
    _candidate,
    _verified_candidate,
)


class CandidateSetFreezeError(RuntimeError):
    """Raised when a blind candidate set cannot be frozen safely."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CandidateSetFreezeError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CandidateSetFreezeError(f"{label} must be a JSON object")
    return value


def freeze_candidate_set(
    pack_dir: Path,
    candidates: list[tuple[str, Path]],
    *,
    output_quality_uninspected: bool,
) -> dict[str, Any]:
    if not output_quality_uninspected:
        raise CandidateSetFreezeError(
            "explicit confirmation that candidate output quality is uninspected is required"
        )
    pack_dir = pack_dir.resolve(strict=True)
    seal_path = pack_dir / "candidate_set_seal.json"
    if seal_path.exists() or seal_path.is_symlink():
        raise CandidateSetFreezeError("candidate set seal already exists")
    benchmark = _load_object(
        pack_dir / "benchmark_manifest.json",
        label="benchmark manifest",
    )
    payload = benchmark.get("freeze_payload")
    if (
        benchmark.get("schema") != "amt-benchmark-pack/v1"
        or not isinstance(payload, dict)
        or canonical_json_sha256(payload)
        != benchmark.get("benchmark_freeze_sha256")
    ):
        raise CandidateSetFreezeError("benchmark freeze manifest is invalid or modified")
    if not candidates:
        raise CandidateSetFreezeError("at least one candidate is required")
    labels = [label for label, _path in candidates]
    if len(set(labels)) != len(labels):
        raise CandidateSetFreezeError("candidate labels must be unique")

    records: list[dict[str, Any]] = []
    paths: set[Path] = set()
    try:
        for label, path in candidates:
            (
                verified_path,
                result,
                _events,
                events_sha256,
            ) = _verified_candidate(
                payload,
                label=label,
                raw_path=path,
                ineligible_candidate_hashes=set(),
            )
            if verified_path in paths:
                raise CandidateSetFreezeError("candidate paths must be unique")
            paths.add(verified_path)
            records.append(
                {
                    "label": label,
                    "run_id": result.run_id,
                    "worker": result.worker,
                    "events_path": str(verified_path),
                    "events_sha256": events_sha256,
                    "run_manifest_path": str(result.manifest_path),
                    "run_manifest_sha256": sha256_file(result.manifest_path),
                }
            )
    except BenchmarkEvaluationError as exc:
        raise CandidateSetFreezeError(str(exc)) from exc

    freeze_payload = {
        "schema": "amt-evaluation-candidate-set/v1",
        "benchmark_freeze_sha256": benchmark["benchmark_freeze_sha256"],
        "split": payload.get("split"),
        "frozen_at": datetime.now(UTC).isoformat(),
        "candidates": records,
        "confirmation": {
            "candidate_output_quality_uninspected_before_freeze": True,
            "candidate_selection_or_tuning_after_freeze_prohibited": (
                payload.get("split") == "blind_test"
            ),
        },
    }
    seal = {
        "schema": "amt-evaluation-candidate-set-seal/v1",
        "freeze_payload": freeze_payload,
        "candidate_set_sha256": canonical_json_sha256(freeze_payload),
        "claims": {
            "blind_result_eligible": payload.get("split") == "blind_test",
            "quality_inspection_recorded_by_this_tool": False,
        },
    }
    atomic_write_json(seal_path, seal)
    return seal


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument(
        "--confirm-output-quality-uninspected",
        action="store_true",
        help="Required acknowledgement before freezing a blind candidate set.",
    )
    args = parser.parse_args()
    seal = freeze_candidate_set(
        args.pack_dir,
        [_candidate(value) for value in args.candidate],
        output_quality_uninspected=args.confirm_output_quality_uninspected,
    )
    print(json.dumps(seal, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
