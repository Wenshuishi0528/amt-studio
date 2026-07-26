#!/usr/bin/env python3
"""Evaluate a sealed candidate set against dual human note annotations."""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import csv
import json
import math
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
from amt_core.evaluation import EvaluationConfig, EvaluationError, ReferenceNote, evaluate_notes
from amt_core.events import NoteEvent
from amt_core.utils import atomic_write_json, sha256_file


class ExternalNoteEvaluationError(RuntimeError):
    """Raised when an external note benchmark cannot be scored safely."""


NOTE_BOUNDARY_TOLERANCE_SEC = 0.005


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ExternalNoteEvaluationError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ExternalNoteEvaluationError(f"{label} must be a JSON object")
    return value


def read_external_note_csv(
    path: Path,
    *,
    excerpt_id: str,
    annotator: str,
    start_sec: float,
    duration_sec: float,
) -> list[ReferenceNote]:
    """Read onset-Hz-duration rows and map them to canonical project time."""

    notes: list[ReferenceNote] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line_number, row in enumerate(csv.reader(handle), start=1):
                if not row or all(not value.strip() for value in row):
                    continue
                if len(row) != 3:
                    raise ExternalNoteEvaluationError(
                        f"{path}:{line_number}: expected onset, pitch Hz, duration"
                    )
                try:
                    local_onset = float(row[0])
                    frequency_hz = float(row[1])
                    note_duration = float(row[2])
                except ValueError as exc:
                    raise ExternalNoteEvaluationError(
                        f"{path}:{line_number}: note fields must be numeric"
                    ) from exc
                if (
                    not math.isfinite(local_onset)
                    or not math.isfinite(frequency_hz)
                    or not math.isfinite(note_duration)
                    or local_onset < 0
                    or frequency_hz <= 0
                    or note_duration <= 0
                    # Vocadito decimal note timestamps can end a few PCM
                    # frames beyond the WAV boundary. Preserve the official
                    # reference and allow the same fixed 5 ms drift as freeze.
                    or local_onset + note_duration
                    > duration_sec + NOTE_BOUNDARY_TOLERANCE_SEC
                ):
                    raise ExternalNoteEvaluationError(
                        f"{path}:{line_number}: note values exceed the frozen excerpt"
                    )
                pitch_midi = 69.0 + 12.0 * math.log2(frequency_hz / 440.0)
                note = ReferenceNote(
                    reference_note_id=(
                        f"{excerpt_id}:{annotator}:{line_number:05d}"
                    ),
                    onset_sec=start_sec + local_onset,
                    offset_sec=start_sec + local_onset + note_duration,
                    pitch_midi=pitch_midi,
                    instrument="voice",
                    annotator_confidence=0.0,
                    comment=(
                        "Imported trained-musician external annotation; source "
                        "does not provide per-note confidence."
                    ),
                )
                note.validate()
                notes.append(note)
    except OSError as exc:
        raise ExternalNoteEvaluationError(f"Cannot read note annotation {path}: {exc}") from exc
    if not notes:
        raise ExternalNoteEvaluationError(f"note annotation is empty: {path}")
    return notes


def _verified_benchmark(
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
        or payload.get("schema") != "amt-external-note-benchmark-manifest/v1"
        or payload.get("split") != "blind_test"
        or payload.get("prior_system_exposure") is not False
    ):
        raise ExternalNoteEvaluationError("external blind benchmark freeze is invalid")
    reference_policy = payload.get("reference_policy")
    if (
        not isinstance(reference_policy, dict)
        or reference_policy.get("annotators") != ["a1", "a2"]
        or reference_policy.get("report_each_annotator") is not True
        or reference_policy.get("aggregate_policy")
        != "per_track_max_onset_pitch_offset_f1"
        or reference_policy.get("aggregate_policy_fixed_before_candidate_inference")
        is not True
    ):
        raise ExternalNoteEvaluationError("dual-annotator policy is invalid")
    return manifest, payload


def _validate_candidate_count(records: object, minimum_candidates: int) -> list[Any]:
    if (
        isinstance(minimum_candidates, bool)
        or not isinstance(minimum_candidates, int)
        or minimum_candidates < 2
    ):
        raise ExternalNoteEvaluationError("minimum candidate count must be an integer of at least 2")
    if not isinstance(records, list) or len(records) < minimum_candidates:
        raise ExternalNoteEvaluationError(
            f"at least {minimum_candidates} sealed candidates are required"
        )
    return records


def _verified_candidate_set(
    pack_dir: Path,
    manifest: dict[str, Any],
    payload: dict[str, Any],
    input_snapshots: InputSnapshots,
    *,
    minimum_candidates: int = 3,
) -> tuple[dict[str, Any], list[tuple[dict[str, Any], list[NoteEvent]]]]:
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
        raise ExternalNoteEvaluationError("candidate set seal is invalid")
    confirmation = freeze.get("confirmation")
    if (
        not isinstance(confirmation, dict)
        or confirmation.get("candidate_output_quality_uninspected_before_freeze") is not True
        or confirmation.get("candidate_selection_or_tuning_after_freeze_prohibited") is not True
    ):
        raise ExternalNoteEvaluationError("candidate preinspection confirmation is invalid")
    records = _validate_candidate_count(
        freeze.get("candidates"),
        minimum_candidates,
    )

    verified: list[tuple[dict[str, Any], list[NoteEvent]]] = []
    labels: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ExternalNoteEvaluationError("candidate record must be an object")
        label = record.get("label")
        if not isinstance(label, str) or not label or label in labels:
            raise ExternalNoteEvaluationError("candidate labels must be unique")
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
            raise ExternalNoteEvaluationError(f"{label}: {exc}") from exc
        if (
            path != candidate_path.resolve(strict=True)
            or events_hash != record.get("events_sha256")
            or result.run_id != record.get("run_id")
            or result.worker != record.get("worker")
            or sha256_file(result.manifest_path) != record.get("run_manifest_sha256")
        ):
            raise ExternalNoteEvaluationError(f"{label}: candidate seal binding failed")
        verified.append((record, events))
    return seal, verified


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
        raise ExternalNoteEvaluationError("candidate path identity is invalid")
    expected_tail = ("runs", run_id, "normalized", "events.jsonl")
    if tuple(Path(recorded_path).parts[-4:]) != expected_tail:
        raise ExternalNoteEvaluationError(
            f"{run_id}: sealed candidate path is not a standard worker output"
        )
    return pack_dir.parent.parent / Path(*expected_tail)


def _external_reference_records(
    payload: dict[str, Any],
    selection: dict[str, Any],
    concatenation: dict[str, Any],
) -> None:
    if (
        selection.get("schema") != "amt-external-note-selection/v1"
        or selection.get("selection_before_candidate_inference") is not True
        or selection.get("candidate_output_inspected") is not False
        or selection.get("split") != "blind_test"
        or concatenation.get("schema") != "amt-external-note-concatenation/v1"
        or concatenation.get("created_before_candidate_inference") is not True
    ):
        raise ExternalNoteEvaluationError("external reference manifests are invalid")
    excerpts = payload.get("excerpts")
    selected_tracks = selection.get("tracks")
    concatenated_tracks = concatenation.get("tracks")
    if (
        not isinstance(excerpts, list)
        or not isinstance(selected_tracks, list)
        or not isinstance(concatenated_tracks, list)
        or not excerpts
    ):
        raise ExternalNoteEvaluationError("external reference track records are missing")

    def unique_records(
        records: list[Any],
        key: str,
        *,
        label: str,
    ) -> dict[Any, dict[str, Any]]:
        result: dict[Any, dict[str, Any]] = {}
        for record in records:
            if not isinstance(record, dict):
                raise ExternalNoteEvaluationError(f"{label} record must be an object")
            identifier = record.get(key)
            if (
                isinstance(identifier, bool)
                or not isinstance(identifier, (int, str))
                or identifier in result
            ):
                raise ExternalNoteEvaluationError(
                    f"{label} {key} values must be present and unique"
                )
            result[identifier] = record
        return result

    excerpt_by_id = unique_records(excerpts, "excerpt_id", label="benchmark excerpt")
    selection_by_track = unique_records(
        selected_tracks,
        "track_id",
        label="selection track",
    )
    concatenation_by_excerpt = unique_records(
        concatenated_tracks,
        "excerpt_id",
        label="concatenation track",
    )
    excerpt_track_ids = {record.get("track_id") for record in excerpts}
    if (
        set(excerpt_by_id) != set(concatenation_by_excerpt)
        or excerpt_track_ids != set(selection_by_track)
        or len(excerpt_track_ids) != len(excerpts)
    ):
        raise ExternalNoteEvaluationError(
            "benchmark excerpts do not exactly match selected and concatenated tracks"
        )

    for excerpt_id, excerpt in excerpt_by_id.items():
        track_id = excerpt.get("track_id")
        selected = selection_by_track[track_id]
        concatenated = concatenation_by_excerpt[excerpt_id]
        exact_fields = (
            ("track_id", track_id),
            ("singer_id", excerpt.get("singer_group_id")),
            ("language", excerpt.get("language")),
            ("average_midi_pitch", excerpt.get("average_midi_pitch")),
            ("audio_sha256", excerpt.get("source_audio_sha256")),
        )
        if any(
            selected.get(field) != expected
            or concatenated.get(field) != expected
            for field, expected in exact_fields
        ):
            raise ExternalNoteEvaluationError(
                f"{excerpt_id}: selected source track identity does not match benchmark"
            )
        for field, expected in (
            ("start_sec", excerpt.get("evaluation_start_sec")),
            ("end_sec", excerpt.get("evaluation_end_sec")),
            ("duration_sec", excerpt.get("duration_sec")),
        ):
            observed = concatenated.get(field)
            if (
                isinstance(observed, bool)
                or not isinstance(observed, (int, float))
                or isinstance(expected, bool)
                or not isinstance(expected, (int, float))
                or not math.isclose(
                    float(observed),
                    float(expected),
                    rel_tol=0.0,
                    abs_tol=1e-6,
                )
            ):
                raise ExternalNoteEvaluationError(
                    f"{excerpt_id}: concatenation timing does not match benchmark"
                )
        benchmark_references = excerpt.get("note_references")
        concatenated_references = concatenated.get("note_references")
        if not isinstance(benchmark_references, dict) or not isinstance(
            concatenated_references,
            dict,
        ):
            raise ExternalNoteEvaluationError(
                f"{excerpt_id}: note reference records are missing"
            )
        for annotator in ("a1", "a2"):
            benchmark_reference = benchmark_references.get(annotator)
            concatenated_reference = concatenated_references.get(annotator)
            if (
                not isinstance(benchmark_reference, dict)
                or not isinstance(concatenated_reference, dict)
                or benchmark_reference.get("sha256")
                != selected.get(f"notes_{annotator}_sha256")
                or benchmark_reference.get("note_count")
                != selected.get(f"notes_{annotator}_count")
                or benchmark_reference.get("sha256")
                != concatenated_reference.get("sha256")
                or benchmark_reference.get("note_count")
                != concatenated_reference.get("note_count")
            ):
                raise ExternalNoteEvaluationError(
                    f"{excerpt_id}: {annotator} annotation is not bound to its source track"
                )


def _voice_events_in_window(
    events: list[NoteEvent],
    *,
    start_sec: float,
    end_sec: float,
) -> list[NoteEvent]:
    selected = [
        event
        for event in events
        if event.instrument == "voice" and start_sec <= event.onset_sec < end_sec
    ]
    identifiers = [event.event_id for event in selected]
    if len(set(identifiers)) != len(identifiers):
        raise ExternalNoteEvaluationError("candidate contains duplicate voice event IDs")
    return selected


def _metric_row(
    candidate: str,
    excerpt_id: str,
    annotator: str,
    metric_name: str,
    metric: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidate": candidate,
        "excerpt_id": excerpt_id,
        "annotator": annotator,
        "metric": metric_name,
        "precision": metric.get("precision"),
        "recall": metric.get("recall"),
        "f1": metric.get("f1"),
        "matches": metric.get("matches"),
        "reference_count": metric.get("reference_count"),
        "estimate_count": metric.get("estimate_count"),
    }


def _correction_proxy(
    report: dict[str, Any],
    *,
    duration_sec: float,
) -> dict[str, Any]:
    primary = report["primary"]
    onset = primary["onset_only"]
    onset_pitch = primary["onset_pitch"]
    full = primary["onset_pitch_offset"]
    reference_count = full["reference_count"]
    estimate_count = full["estimate_count"]
    discrepancy = max(reference_count, estimate_count) - full["matches"]
    return {
        "schema": "amt-automated-correction-proxy/v1",
        "audio_duration_sec": duration_sec,
        "note_object_discrepancy_count": discrepancy,
        "note_object_discrepancy_per_minute": (
            discrepancy / duration_sec * 60.0 if duration_sec else None
        ),
        "unmatched_reference_after_onset": reference_count - onset["matches"],
        "unmatched_estimate_after_onset": estimate_count - onset["matches"],
        "onset_matched_pitch_mismatch": onset["matches"] - onset_pitch["matches"],
        "onset_pitch_matched_offset_mismatch": (
            onset_pitch["matches"] - full["matches"]
        ),
        "manual_edit_time_measured": False,
        "interpretation": (
            "Automated note-object discrepancy proxy; split or merge operations "
            "can change several note objects, so this is not an edit-action lower "
            "bound and is not a substitute for timed human correction."
        ),
    }


def _mean(values: list[float | None]) -> float | None:
    defined = [float(value) for value in values if value is not None]
    return sum(defined) / len(defined) if defined else None


def evaluate_external_notes(
    pack_dir: Path,
    output_dir: Path,
    *,
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    config = config or EvaluationConfig()
    config.validate()
    pack_dir = pack_dir.resolve(strict=True)
    if output_dir.exists() or output_dir.is_symlink():
        raise ExternalNoteEvaluationError(f"output directory already exists: {output_dir}")
    input_snapshots: InputSnapshots = {}
    manifest, payload = _verified_benchmark(pack_dir, input_snapshots)
    seal, candidates = _verified_candidate_set(
        pack_dir,
        manifest,
        payload,
        input_snapshots,
    )

    project_dir = pack_dir.parent.parent
    project_manifest_path = project_dir / "manifest.json"
    _track_input(input_snapshots, project_manifest_path, label="project manifest")
    project = _load_object(project_manifest_path, label="project manifest")
    canonical = project.get("canonical_audio")
    concatenation = payload.get("concatenation_manifest")
    selection = payload.get("selection_manifest")
    if (
        project.get("schema_version") != 1
        or project.get("project_id") != payload.get("project_id")
        or not isinstance(canonical, dict)
        or canonical.get("sha256") != payload.get("canonical_audio_sha256")
        or not isinstance(concatenation, dict)
        or not isinstance(selection, dict)
    ):
        raise ExternalNoteEvaluationError("project and benchmark lineage do not match")
    external_manifests: dict[str, dict[str, Any]] = {}
    for label, record in (
        ("concatenation manifest", concatenation),
        ("selection manifest", selection),
    ):
        path = Path(str(record.get("path"))).resolve(strict=True)
        snapshot = _track_input(input_snapshots, path, label=label)
        if snapshot["sha256"] != record.get("sha256"):
            raise ExternalNoteEvaluationError(f"{label} SHA-256 changed")
        external_manifests[label] = _load_object(path, label=label)
    _external_reference_records(
        payload,
        external_manifests["selection manifest"],
        external_manifests["concatenation manifest"],
    )
    concatenation_audio = external_manifests["concatenation manifest"].get(
        "concatenated_audio"
    )
    if (
        not isinstance(concatenation_audio, dict)
        or not isinstance(project.get("source"), dict)
        or project["source"].get("sha256") != concatenation_audio.get("sha256")
    ):
        raise ExternalNoteEvaluationError(
            "project source is not bound to the frozen concatenation"
        )

    excerpts = payload.get("excerpts")
    if not isinstance(excerpts, list) or len(excerpts) < 3:
        raise ExternalNoteEvaluationError("external note benchmark has too few excerpts")
    reference_sets: dict[str, dict[str, list[ReferenceNote]]] = {}
    total_duration_sec = 0.0
    for excerpt in excerpts:
        if not isinstance(excerpt, dict):
            raise ExternalNoteEvaluationError("excerpt must be an object")
        excerpt_id = excerpt.get("excerpt_id")
        start = excerpt.get("evaluation_start_sec")
        end = excerpt.get("evaluation_end_sec")
        duration = excerpt.get("duration_sec")
        references = excerpt.get("note_references")
        if (
            not isinstance(excerpt_id, str)
            or isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or abs((float(end) - float(start)) - float(duration)) > 1e-6
            or not isinstance(references, dict)
        ):
            raise ExternalNoteEvaluationError("excerpt bounds or references are invalid")
        total_duration_sec += float(duration)
        reference_sets[excerpt_id] = {}
        for annotator in ("a1", "a2"):
            record = references.get(annotator)
            if not isinstance(record, dict):
                raise ExternalNoteEvaluationError("annotator reference record is missing")
            path = Path(str(record.get("path"))).resolve(strict=True)
            snapshot = _track_input(
                input_snapshots,
                path,
                label=f"{excerpt_id} {annotator} note reference",
            )
            if snapshot["sha256"] != record.get("sha256"):
                raise ExternalNoteEvaluationError("note reference SHA-256 changed")
            notes = read_external_note_csv(
                path,
                excerpt_id=excerpt_id,
                annotator=annotator,
                start_sec=float(start),
                duration_sec=float(duration),
            )
            if len(notes) != record.get("note_count"):
                raise ExternalNoteEvaluationError("note reference count changed")
            reference_sets[excerpt_id][annotator] = notes

    candidate_reports: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    correction_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    for candidate_record, all_events in candidates:
        label = candidate_record["label"]
        per_excerpt: list[dict[str, Any]] = []
        aggregate_references = {"a1": [], "a2": []}
        aggregate_estimates: list[NoteEvent] = []
        for excerpt in excerpts:
            excerpt_id = excerpt["excerpt_id"]
            start = float(excerpt["evaluation_start_sec"])
            end = float(excerpt["evaluation_end_sec"])
            duration = float(excerpt["duration_sec"])
            estimates = _voice_events_in_window(
                all_events,
                start_sec=start,
                end_sec=end,
            )
            aggregate_estimates.extend(estimates)
            annotator_reports: dict[str, dict[str, Any]] = {}
            for annotator in ("a1", "a2"):
                references = reference_sets[excerpt_id][annotator]
                aggregate_references[annotator].extend(references)
                try:
                    note_report = evaluate_notes(references, estimates, config)
                except EvaluationError as exc:
                    raise ExternalNoteEvaluationError(str(exc)) from exc
                annotator_reports[annotator] = note_report
                for metric_name in (
                    "onset_only",
                    "onset_pitch",
                    "onset_pitch_offset",
                    "onset_chroma",
                ):
                    metric_rows.append(
                        _metric_row(
                            label,
                            excerpt_id,
                            annotator,
                            metric_name,
                            note_report["primary"][metric_name],
                        )
                    )
                proxy = _correction_proxy(note_report, duration_sec=duration)
                correction_rows.append(
                    {
                        "candidate": label,
                        "excerpt_id": excerpt_id,
                        "annotator": annotator,
                        **proxy,
                    }
                )
                for category in (
                    "unmatched_reference_after_onset",
                    "unmatched_estimate_after_onset",
                    "onset_matched_pitch_mismatch",
                    "onset_pitch_matched_offset_mismatch",
                ):
                    error_rows.append(
                        {
                            "candidate": label,
                            "excerpt_id": excerpt_id,
                            "annotator": annotator,
                            "category": category,
                            "count": proxy[category],
                        }
                    )
            selected_annotator = max(
                ("a1", "a2"),
                key=lambda annotator, reports=annotator_reports: (
                    reports[annotator]["primary"]["onset_pitch_offset"]["f1"],
                    reports[annotator]["primary"]["onset_pitch"]["f1"],
                    annotator == "a1",
                ),
            )
            per_excerpt.append(
                {
                    "excerpt_id": excerpt_id,
                    "track_id": excerpt.get("track_id"),
                    "singer_group_id": excerpt.get("singer_group_id"),
                    "language": excerpt.get("language"),
                    "duration_sec": duration,
                    "estimate_note_count": len(estimates),
                    "annotators": annotator_reports,
                    "predeclared_amax_annotator": selected_annotator,
                    "predeclared_amax_metrics": annotator_reports[selected_annotator],
                }
            )

        aggregate: dict[str, dict[str, Any]] = {}
        for annotator in ("a1", "a2"):
            aggregate[annotator] = evaluate_notes(
                aggregate_references[annotator],
                aggregate_estimates,
                config,
            )
        macro_amax = {
            metric_name: {
                field: _mean(
                    [
                        excerpt["predeclared_amax_metrics"]["primary"][metric_name][
                            field
                        ]
                        for excerpt in per_excerpt
                    ]
                )
                for field in ("precision", "recall", "f1")
            }
            for metric_name in (
                "onset_only",
                "onset_pitch",
                "onset_pitch_offset",
                "onset_chroma",
            )
        }
        amax_discrepancy = sum(
            _correction_proxy(
                excerpt["predeclared_amax_metrics"],
                duration_sec=excerpt["duration_sec"],
            )["note_object_discrepancy_count"]
            for excerpt in per_excerpt
        )
        candidate_reports.append(
            {
                "label": label,
                "worker": candidate_record["worker"],
                "run_id": candidate_record["run_id"],
                "events_sha256": candidate_record["events_sha256"],
                "eligible_voice_event_count": len(aggregate_estimates),
                "aggregate_by_annotator": aggregate,
                "macro_amax": macro_amax,
                "amax_note_object_discrepancy_count": amax_discrepancy,
                "amax_note_object_discrepancy_per_minute": (
                    amax_discrepancy / total_duration_sec * 60.0
                ),
                "manual_edit_time_measured": False,
                "per_excerpt": per_excerpt,
            }
        )

    leaderboard = sorted(
        (
            {
                "rank": 0,
                "label": candidate["label"],
                "macro_amax_onset_pitch_offset_f1": candidate["macro_amax"][
                    "onset_pitch_offset"
                ]["f1"],
                "macro_amax_onset_pitch_f1": candidate["macro_amax"]["onset_pitch"][
                    "f1"
                ],
                "note_object_discrepancy_per_minute": candidate[
                    "amax_note_object_discrepancy_per_minute"
                ],
            }
            for candidate in candidate_reports
        ),
        key=lambda row: (
            -float(row["macro_amax_onset_pitch_offset_f1"]),
            -float(row["macro_amax_onset_pitch_f1"]),
            row["label"],
        ),
    )
    for rank, row in enumerate(leaderboard, start=1):
        row["rank"] = rank

    report = {
        "schema": "amt-external-dual-note-evaluation/v1",
        "created_at": datetime.now(UTC).isoformat(),
        "benchmark": {
            "benchmark_id": payload.get("benchmark_id"),
            "project_id": payload.get("project_id"),
            "split": payload.get("split"),
            "benchmark_freeze_sha256": manifest.get("benchmark_freeze_sha256"),
            "candidate_set_sha256": seal.get("candidate_set_sha256"),
            "excerpt_count": len(excerpts),
            "evaluated_audio_duration_sec": total_duration_sec,
        },
        "metric_config": config.to_dict(),
        "reference_policy": payload["reference_policy"],
        "annotator_confidence_policy": {
            "source_per_note_confidence_available": False,
            "internal_unavailable_sentinel": 0.0,
            "confidence_secondary_metrics_used": False,
        },
        "leaderboard": leaderboard,
        "candidates": candidate_reports,
        "listening_impressions": {
            "used_for_metrics": False,
            "owner_percentages_are_formal_accuracy": False,
        },
        "claims": {
            "human_note_references_verified": True,
            "two_annotators_reported_separately": True,
            "blind_candidate_set_verified": True,
            "manual_correction_time_measured": False,
            "automated_correction_proxy_available": True,
            "fusion_tuning_authorized": False,
        },
    }

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
    )
    try:
        atomic_write_json(temporary / "report.json", report)
        _write_csv(
            temporary / "metrics_by_track.csv",
            metric_rows,
            [
                "candidate",
                "excerpt_id",
                "annotator",
                "metric",
                "precision",
                "recall",
                "f1",
                "matches",
                "reference_count",
                "estimate_count",
            ],
        )
        _write_csv(
            temporary / "correction_proxy.csv",
            correction_rows,
            [
                "candidate",
                "excerpt_id",
                "annotator",
                "schema",
                "audio_duration_sec",
                "note_object_discrepancy_count",
                "note_object_discrepancy_per_minute",
                "unmatched_reference_after_onset",
                "unmatched_estimate_after_onset",
                "onset_matched_pitch_mismatch",
                "onset_pitch_matched_offset_mismatch",
                "manual_edit_time_measured",
                "interpretation",
            ],
        )
        _write_csv(
            temporary / "error_taxonomy.csv",
            error_rows,
            ["candidate", "excerpt_id", "annotator", "category", "count"],
        )
        _write_csv(
            temporary / "precision_coverage.csv",
            [
                {
                    "candidate": candidate["label"],
                    "status": "unavailable_no_candidate_confidence",
                }
                for candidate in candidate_reports
            ],
            ["candidate", "status"],
        )
        (temporary / "README.md").write_text(
            "# External dual-annotator note evaluation\n\n"
            "Each trained-musician annotation is reported separately. The Amax "
            "summary follows the benchmark's predeclared per-track maximum "
            "onset+pitch+offset F1 policy. Note-object discrepancy counts are "
            "automated burden proxies, not edit-action lower bounds; no human "
            "correction time was measured.\n",
            encoding="utf-8",
        )
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
            "schema_version": 1,
            "artifact_type": "amt-external-note-evaluation-run",
            "run_id": f"{payload['benchmark_id']}-dual-note-evaluation",
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
                "--output-dir",
                str(output_dir),
            ],
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
            "claims": report["claims"],
        }
        atomic_write_json(temporary / "run_manifest.json", run_manifest)
        _verify_input_snapshots(input_snapshots)
        _publish_new_directory(temporary, output_dir)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return report


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_external_notes(args.pack_dir, args.output_dir)
    print(json.dumps(report["leaderboard"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
