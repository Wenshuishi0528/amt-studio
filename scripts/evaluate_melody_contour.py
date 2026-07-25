#!/usr/bin/env python3
"""Evaluate a pre-sealed blind candidate set against an external F0 contour."""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import csv
import json
import platform
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_benchmark import (
    BenchmarkEvaluationError,
    InputSnapshots,
    _git_state,
    _publish_new_directory,
    _snapshot_artifact,
    _track_input,
    _verified_candidate,
    _verify_input_snapshots,
)

from amt_core.benchmark import canonical_json_sha256
from amt_core.evaluation import (
    EvaluationError,
    evaluate_melody_frames,
    project_note_events_to_melody_frames,
)
from amt_core.utils import atomic_write_json, sha256_file


class MelodyContourEvaluationError(RuntimeError):
    """Raised when contour evidence or blind-evaluation lineage is invalid."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MelodyContourEvaluationError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MelodyContourEvaluationError(f"{label} must be a JSON object")
    return value


def read_melody_contour_csv(path: Path) -> tuple[list[float], list[float]]:
    """Read a two-column time/frequency contour without a header."""

    times: list[float] = []
    frequencies: list[float] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line_number, row in enumerate(csv.reader(handle), start=1):
                if not row or all(not value.strip() for value in row):
                    continue
                if len(row) != 2:
                    raise MelodyContourEvaluationError(
                        f"{path}:{line_number}: expected exactly two CSV columns"
                    )
                try:
                    time_sec = float(row[0])
                    frequency_hz = float(row[1])
                except ValueError as exc:
                    raise MelodyContourEvaluationError(
                        f"{path}:{line_number}: time and frequency must be numbers"
                    ) from exc
                if (
                    not (time_sec >= 0)
                    or not (frequency_hz >= 0)
                    or time_sec == float("inf")
                    or frequency_hz == float("inf")
                ):
                    raise MelodyContourEvaluationError(
                        f"{path}:{line_number}: values must be finite and non-negative"
                    )
                if times and time_sec <= times[-1]:
                    raise MelodyContourEvaluationError(
                        f"{path}:{line_number}: timestamps must be strictly increasing"
                    )
                times.append(time_sec)
                frequencies.append(frequency_hz)
    except OSError as exc:
        raise MelodyContourEvaluationError(f"Cannot read contour {path}: {exc}") from exc
    if not times:
        raise MelodyContourEvaluationError("reference contour must not be empty")
    return times, frequencies


def _excerpt_frames(
    times: list[float],
    frequencies: list[float],
    excerpts: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], list[float], list[float]]]:
    groups: list[tuple[dict[str, Any], list[float], list[float]]] = []
    for excerpt in excerpts:
        start = excerpt.get("evaluation_start_sec")
        end = excerpt.get("evaluation_end_sec")
        excerpt_id = excerpt.get("excerpt_id")
        if (
            isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or not isinstance(excerpt_id, str)
            or not excerpt_id
            or end <= start
        ):
            raise MelodyContourEvaluationError("benchmark excerpt bounds are invalid")
        indices = [
            index
            for index, time_sec in enumerate(times)
            if float(start) <= time_sec < float(end)
        ]
        if not indices:
            raise MelodyContourEvaluationError(
                f"reference contour has no frames in excerpt {excerpt_id}"
            )
        groups.append(
            (
                excerpt,
                [times[index] for index in indices],
                [frequencies[index] for index in indices],
            )
        )
    return groups


def _verified_pack(
    pack_dir: Path,
    input_snapshots: InputSnapshots,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = pack_dir / "benchmark_manifest.json"
    _track_input(input_snapshots, manifest_path, label="benchmark manifest")
    manifest = _load_object(manifest_path, label="benchmark manifest")
    payload = manifest.get("freeze_payload")
    if (
        manifest.get("schema") != "amt-benchmark-pack/v1"
        or not isinstance(payload, dict)
        or canonical_json_sha256(payload) != manifest.get("benchmark_freeze_sha256")
        or payload.get("split") != "blind_test"
    ):
        raise MelodyContourEvaluationError("blind benchmark freeze is invalid")
    excerpts = payload.get("excerpts")
    if not isinstance(excerpts, list) or not excerpts:
        raise MelodyContourEvaluationError("blind benchmark has no frozen excerpts")
    for excerpt in excerpts:
        if not isinstance(excerpt, dict) or not isinstance(excerpt.get("mix"), dict):
            raise MelodyContourEvaluationError("frozen excerpt mix record is invalid")
        mix = excerpt["mix"]
        relative_path = mix.get("path")
        expected_hash = mix.get("sha256")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or Path(relative_path).is_absolute()
            or ".." in Path(relative_path).parts
        ):
            raise MelodyContourEvaluationError("frozen excerpt mix path is unsafe")
        mix_path = (pack_dir / relative_path).resolve(strict=True)
        try:
            mix_path.relative_to(pack_dir)
        except ValueError as exc:
            raise MelodyContourEvaluationError(
                "frozen excerpt mix escapes the benchmark pack"
            ) from exc
        mix_snapshot = _track_input(
            input_snapshots,
            mix_path,
            label=f"{excerpt.get('excerpt_id')} frozen mix",
        )
        if mix_snapshot["sha256"] != expected_hash:
            raise MelodyContourEvaluationError("frozen excerpt mix SHA-256 changed")
    return manifest, payload


def _verify_project_reference_binding(
    pack_dir: Path,
    payload: dict[str, Any],
    selected_tracks: list[Any],
    input_snapshots: InputSnapshots,
    *,
    reference_sha256: str,
) -> None:
    project_dir = pack_dir.parent.parent
    project_manifest_path = project_dir / "manifest.json"
    _track_input(
        input_snapshots,
        project_manifest_path,
        label="project manifest",
    )
    project = _load_object(project_manifest_path, label="project manifest")
    canonical = project.get("canonical_audio")
    source = project.get("source")
    if (
        project.get("schema_version") != 1
        or project.get("project_id") != payload.get("project_id")
        or not isinstance(canonical, dict)
        or canonical.get("sha256") != payload.get("canonical_audio_sha256")
        or not isinstance(source, dict)
        or not any(
            isinstance(track, dict)
            and track.get("role") == "blind_test_vocal_melody"
            and track.get("melody1_sha256") == reference_sha256
            and track.get("mix_sha256") == source.get("sha256")
            for track in selected_tracks
        )
    ):
        raise MelodyContourEvaluationError(
            "external reference is not bound to the benchmark project source audio"
        )


def _portable_candidate_events_path(
    pack_dir: Path,
    record: dict[str, Any],
) -> Path:
    run_id = record.get("run_id")
    recorded_path = record.get("events_path")
    if (
        not isinstance(run_id, str)
        or not run_id
        or run_id in {".", ".."}
        or "/" in run_id
        or "\\" in run_id
        or not isinstance(recorded_path, str)
        or not recorded_path
        or "\\" in recorded_path
    ):
        raise MelodyContourEvaluationError("candidate path identity is invalid")
    expected_tail = ("runs", run_id, "normalized", "events.jsonl")
    if tuple(Path(recorded_path).parts[-4:]) != expected_tail:
        raise MelodyContourEvaluationError(
            f"{run_id}: sealed candidate path is not a standard worker output"
        )
    return pack_dir.parent.parent / Path(*expected_tail)


def _verified_candidate_records(
    pack_dir: Path,
    manifest: dict[str, Any],
    payload: dict[str, Any],
    input_snapshots: InputSnapshots,
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], list[Any]]]]:
    seal_path = pack_dir / "candidate_set_seal.json"
    _track_input(input_snapshots, seal_path, label="candidate set seal")
    seal = _load_object(seal_path, label="candidate set seal")
    freeze = seal.get("freeze_payload")
    if (
        seal.get("schema") != "amt-evaluation-candidate-set-seal/v1"
        or not isinstance(freeze, dict)
        or canonical_json_sha256(freeze) != seal.get("candidate_set_sha256")
        or freeze.get("benchmark_freeze_sha256")
        != manifest.get("benchmark_freeze_sha256")
        or freeze.get("split") != "blind_test"
    ):
        raise MelodyContourEvaluationError("blind candidate set seal is invalid")
    confirmation = freeze.get("confirmation")
    if (
        not isinstance(confirmation, dict)
        or confirmation.get("candidate_output_quality_uninspected_before_freeze") is not True
        or confirmation.get("candidate_selection_or_tuning_after_freeze_prohibited") is not True
    ):
        raise MelodyContourEvaluationError("blind candidate set confirmation is invalid")
    records = freeze.get("candidates")
    if not isinstance(records, list) or not records:
        raise MelodyContourEvaluationError("candidate set is empty")

    verified: list[tuple[dict[str, Any], list[Any]]] = []
    labels: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise MelodyContourEvaluationError("candidate record must be an object")
        label = record.get("label")
        if not isinstance(label, str) or not label or label in labels:
            raise MelodyContourEvaluationError("candidate labels must be unique")
        labels.add(label)
        candidate_path = _portable_candidate_events_path(pack_dir, record)
        try:
            path, result, events, events_hash = _verified_candidate(
                payload,
                label=label,
                raw_path=candidate_path,
                ineligible_candidate_hashes=set(),
                input_snapshots=input_snapshots,
            )
        except (BenchmarkEvaluationError, OSError, ValueError) as exc:
            raise MelodyContourEvaluationError(f"{label}: {exc}") from exc
        if (
            events_hash != record.get("events_sha256")
            or path != candidate_path.resolve(strict=True)
            or result.run_id != record.get("run_id")
            or result.worker != record.get("worker")
            or sha256_file(result.manifest_path) != record.get("run_manifest_sha256")
        ):
            raise MelodyContourEvaluationError(f"{label}: candidate seal binding failed")
        verified.append((record, events))
    return seal, verified


def evaluate_contour_candidate(
    events: list[Any],
    groups: list[tuple[dict[str, Any], list[float], list[float]]],
    *,
    instrument: str,
    cent_tolerance: float,
) -> dict[str, Any]:
    selected_times = [time for _excerpt, times, _reference in groups for time in times]
    selected_reference = [
        frequency for _excerpt, _times, reference in groups for frequency in reference
    ]
    estimate, projection = project_note_events_to_melody_frames(
        events,
        selected_times,
        instrument=instrument,
    )
    per_excerpt: list[dict[str, Any]] = []
    for excerpt, times, reference in groups:
        excerpt_estimate, excerpt_projection = project_note_events_to_melody_frames(
            events,
            times,
            instrument=instrument,
        )
        per_excerpt.append(
            {
                "excerpt_id": excerpt["excerpt_id"],
                "evaluation_start_sec": excerpt["evaluation_start_sec"],
                "evaluation_end_sec": excerpt["evaluation_end_sec"],
                "frame_metrics": evaluate_melody_frames(
                    reference,
                    excerpt_estimate,
                    cent_tolerance=cent_tolerance,
                ),
                "projection": excerpt_projection,
            }
        )
    return {
        "aggregate_frame_metrics": evaluate_melody_frames(
            selected_reference,
            estimate,
            cent_tolerance=cent_tolerance,
        ),
        "aggregate_projection": projection,
        "per_excerpt": per_excerpt,
    }


def evaluate_melody_contour(
    pack_dir: Path,
    reference_csv: Path,
    provenance_path: Path,
    output_dir: Path,
    *,
    expected_reference_sha256: str,
    instrument: str = "voice",
    cent_tolerance: float = 50.0,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    pack_dir = pack_dir.resolve(strict=True)
    reference_csv = reference_csv.resolve(strict=True)
    provenance_path = provenance_path.resolve(strict=True)
    if output_dir.exists() or output_dir.is_symlink():
        raise MelodyContourEvaluationError(f"output directory already exists: {output_dir}")
    input_snapshots: InputSnapshots = {}
    reference_snapshot = _track_input(
        input_snapshots,
        reference_csv,
        label="external melody contour",
    )
    actual_reference_hash = reference_snapshot["sha256"]
    if actual_reference_hash != expected_reference_sha256:
        raise MelodyContourEvaluationError("reference contour SHA-256 does not match")
    provenance_snapshot = _track_input(
        input_snapshots,
        provenance_path,
        label="private dataset provenance",
    )
    provenance = _load_object(provenance_path, label="dataset provenance")
    selected_tracks = provenance.get("selected_tracks")
    if (
        provenance.get("schema") != "amt-private-dataset-provenance/v1"
        or provenance.get("purpose") != "non-commercial research evaluation only"
        or not isinstance(selected_tracks, list)
        or not any(
            isinstance(track, dict)
            and track.get("melody1_sha256") == actual_reference_hash
            and track.get("role") == "blind_test_vocal_melody"
            for track in selected_tracks
        )
    ):
        raise MelodyContourEvaluationError(
            "reference contour is not approved by the private dataset provenance"
        )
    manifest, payload = _verified_pack(pack_dir, input_snapshots)
    seal, candidates = _verified_candidate_records(
        pack_dir,
        manifest,
        payload,
        input_snapshots,
    )
    _verify_project_reference_binding(
        pack_dir,
        payload,
        selected_tracks,
        input_snapshots,
        reference_sha256=actual_reference_hash,
    )
    times, reference = read_melody_contour_csv(reference_csv)
    excerpts = payload.get("excerpts")
    if not isinstance(excerpts, list) or not excerpts:
        raise MelodyContourEvaluationError("benchmark has no excerpts")
    groups = _excerpt_frames(times, reference, excerpts)
    selected_reference = [
        frequency for _excerpt, _times, values in groups for frequency in values
    ]
    if not any(frequency > 0 for frequency in selected_reference) or not any(
        frequency == 0 for frequency in selected_reference
    ):
        raise MelodyContourEvaluationError(
            "frozen excerpts must include reference-voiced and unvoiced frames"
        )

    candidate_reports: list[dict[str, Any]] = []
    try:
        for record, events in candidates:
            result = evaluate_contour_candidate(
                events,
                groups,
                instrument=instrument,
                cent_tolerance=cent_tolerance,
            )
            candidate_reports.append(
                {
                    "label": record["label"],
                    "worker": record["worker"],
                    "run_id": record["run_id"],
                    "events_sha256": record["events_sha256"],
                    **result,
                }
            )
    except EvaluationError as exc:
        raise MelodyContourEvaluationError(str(exc)) from exc

    leaderboard = sorted(
        (
            {
                "rank": 0,
                "label": candidate["label"],
                "overall_accuracy": candidate["aggregate_frame_metrics"][
                    "overall_accuracy"
                ],
                "raw_pitch_accuracy": candidate["aggregate_frame_metrics"][
                    "raw_pitch_accuracy"
                ],
                "raw_chroma_accuracy": candidate["aggregate_frame_metrics"][
                    "raw_chroma_accuracy"
                ],
                "voicing_recall": candidate["aggregate_frame_metrics"]["voicing_recall"],
                "voicing_false_alarm": candidate["aggregate_frame_metrics"][
                    "voicing_false_alarm"
                ],
            }
            for candidate in candidate_reports
        ),
        key=lambda row: (
            -float(row["overall_accuracy"]),
            -float(row["raw_pitch_accuracy"]),
            row["label"],
        ),
    )
    for rank, row in enumerate(leaderboard, start=1):
        row["rank"] = rank

    report = {
        "schema": "amt-external-melody-contour-evaluation/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "benchmark": {
            "benchmark_id": payload.get("benchmark_id"),
            "project_id": payload.get("project_id"),
            "split": payload.get("split"),
            "benchmark_freeze_sha256": manifest.get("benchmark_freeze_sha256"),
            "candidate_set_sha256": seal.get("candidate_set_sha256"),
            "candidate_output_quality_uninspected_before_freeze": True,
        },
        "reference": {
            "path": str(reference_csv),
            "sha256": actual_reference_hash,
            "provenance_path": str(provenance_path),
            "provenance_sha256": provenance_snapshot["sha256"],
            "total_frame_count": len(times),
            "selected_frame_count": sum(len(item[1]) for item in groups),
            "first_timestamp_sec": times[0],
            "last_timestamp_sec": times[-1],
            "license_boundary": "private non-commercial research evaluation only",
        },
        "policy": {
            "instrument_filter": instrument,
            "projection_rule": "highest_pitch_then_latest_onset_then_lexical_event_id",
            "cent_tolerance": cent_tolerance,
            "candidate_selection_after_blind_scoring_prohibited": True,
            "owner_listening_percentages_used_as_formal_accuracy": False,
        },
        "leaderboard": leaderboard,
        "candidates": candidate_reports,
        "claims": {
            "formal_frame_metrics_available": True,
            "professionally_annotated_reference_used": True,
            "commercial_use_authorized": False,
            "dataset_redistribution_authorized": False,
        },
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
    )
    try:
        atomic_write_json(temporary / "report.json", report)
        readme = (
            "# External melody-contour evaluation\n\n"
            "This directory scores the candidate set that was sealed before output "
            "inspection against the private MedleyDB Melody 1 contour. The downloaded "
            "audio and annotations remain outside Git and are restricted to "
            "non-commercial research evaluation.\n"
        )
        (temporary / "README.md").write_text(readme, encoding="utf-8")
        source_paths = [
            Path(__file__).resolve(),
            REPO_ROOT / "src" / "amt_core" / "benchmark.py",
            REPO_ROOT / "src" / "amt_core" / "contracts.py",
            REPO_ROOT / "src" / "amt_core" / "evaluation.py",
            REPO_ROOT / "src" / "amt_core" / "events.py",
            REPO_ROOT / "src" / "amt_core" / "utils.py",
            REPO_ROOT / "scripts" / "evaluate_benchmark.py",
        ]
        run_manifest = {
            "schema": "amt-external-melody-contour-evaluation-run/v1",
            "run_id": f"{payload['benchmark_id']}-melody-contour-evaluation",
            "project_id": payload["project_id"],
            "worker": "evaluation",
            "status": "succeeded",
            "started_at": started_at,
            "ended_at": datetime.now(UTC).isoformat(),
            "command": [
                sys.executable,
                str(Path(__file__).resolve()),
                "--pack-dir",
                str(pack_dir),
                "--reference-csv",
                str(reference_csv),
                "--reference-sha256",
                expected_reference_sha256,
                "--provenance",
                str(provenance_path),
                "--output-dir",
                str(output_dir),
                "--instrument",
                instrument,
                "--cent-tolerance",
                str(cent_tolerance),
            ],
            "configuration": {
                "instrument_filter": instrument,
                "cent_tolerance": cent_tolerance,
                "projection_rule": report["policy"]["projection_rule"],
            },
            "inputs": [
                _snapshot_artifact(input_snapshots[path])
                for path in sorted(input_snapshots, key=str)
            ],
            "outputs": [
                {
                    "path": path.name,
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in sorted(temporary.iterdir())
                if path.is_file() and path.name != "run_manifest.json"
            ],
            "environment": {
                "hostname": platform.node(),
                "device": "cpu",
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "code": {
                **_git_state(REPO_ROOT),
                "source_files": [
                    {
                        "path": str(path.relative_to(REPO_ROOT)),
                        "sha256": sha256_file(path),
                    }
                    for path in source_paths
                ],
            },
            "benchmark": report["benchmark"],
            "reference": report["reference"],
            "claims": report["claims"],
        }
        atomic_write_json(temporary / "run_manifest.json", run_manifest)
        _verify_input_snapshots(input_snapshots)
        _publish_new_directory(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--reference-csv", type=Path, required=True)
    parser.add_argument("--reference-sha256", required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--instrument", default="voice")
    parser.add_argument("--cent-tolerance", type=float, default=50.0)
    args = parser.parse_args()
    report = evaluate_melody_contour(
        args.pack_dir,
        args.reference_csv,
        args.provenance,
        args.output_dir,
        expected_reference_sha256=args.reference_sha256,
        instrument=args.instrument,
        cent_tolerance=args.cent_tolerance,
    )
    print(json.dumps(report["leaderboard"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
