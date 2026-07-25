#!/usr/bin/env python3
"""Evaluate canonical note candidates against a sealed reference benchmark."""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.benchmark import canonical_json_sha256
from amt_core.contracts import ContractValidationError, WorkerResultV1, load_worker_result
from amt_core.evaluation import (
    EvaluationConfig,
    EvaluationError,
    ReferenceNote,
    evaluate_notes,
    note_sequence_fingerprint,
    read_reference_jsonl,
    summarize_correction_session,
)
from amt_core.events import EventValidationError, NoteEvent
from amt_core.utils import atomic_write_json, sha256_file


class BenchmarkEvaluationError(RuntimeError):
    """Raised when an evaluation would not be auditable."""


InputSnapshots = dict[Path, dict[str, Any]]


def _capture_input_snapshot(path: Path, *, label: str) -> dict[str, Any]:
    requested = path.expanduser()
    if requested.is_symlink():
        raise BenchmarkEvaluationError(f"{label} must not be a symbolic link")
    try:
        resolved = requested.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise BenchmarkEvaluationError(f"{label} is missing or unreadable: {path}") from exc
    if not resolved.is_file():
        raise BenchmarkEvaluationError(f"{label} is not a regular file: {resolved}")
    size_before = resolved.stat().st_size
    digest = sha256_file(resolved)
    size_after = resolved.stat().st_size
    if size_before != size_after:
        raise BenchmarkEvaluationError(f"{label} changed while it was being hashed")
    return {
        "path": str(resolved),
        "sha256": digest,
        "size_bytes": size_after,
        "label": label,
    }


def _track_input(
    snapshots: InputSnapshots,
    path: Path,
    *,
    label: str,
) -> dict[str, Any]:
    current = _capture_input_snapshot(path, label=label)
    resolved = Path(current["path"])
    previous = snapshots.get(resolved)
    if previous is not None:
        if (
            current["sha256"] != previous["sha256"]
            or current["size_bytes"] != previous["size_bytes"]
        ):
            raise BenchmarkEvaluationError(
                f"{label} changed during benchmark evaluation: {resolved}"
            )
        return previous
    snapshots[resolved] = current
    return current


def _verify_input_snapshot(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    current = _capture_input_snapshot(path, label=record["label"])
    if (
        current["sha256"] != record["sha256"]
        or current["size_bytes"] != record["size_bytes"]
    ):
        raise BenchmarkEvaluationError(
            f"{record['label']} changed during benchmark evaluation: {path}"
        )


def _verify_input_snapshots(snapshots: InputSnapshots) -> None:
    for path in sorted(snapshots, key=str):
        _verify_input_snapshot(snapshots[path])


def _snapshot_artifact(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": record["path"],
        "sha256": record["sha256"],
        "size_bytes": record["size_bytes"],
    }


def _publish_new_directory(stage: Path, output_dir: Path) -> None:
    if os.path.lexists(output_dir):
        raise BenchmarkEvaluationError(
            f"output directory appeared during evaluation: {output_dir}"
        )
    try:
        output_dir.mkdir()
    except FileExistsError as exc:
        raise BenchmarkEvaluationError(
            f"output directory appeared during evaluation: {output_dir}"
        ) from exc

    created: list[Path] = []
    try:
        for source in sorted(stage.iterdir()):
            if source.is_symlink() or not source.is_file():
                raise BenchmarkEvaluationError(
                    f"staged evaluation output is not a regular file: {source}"
                )
            destination = output_dir / source.name
            with source.open("rb") as input_handle, destination.open("xb") as output_handle:
                created.append(destination)
                shutil.copyfileobj(input_handle, output_handle)
            if (
                destination.stat().st_size != source.stat().st_size
                or sha256_file(destination) != sha256_file(source)
            ):
                raise BenchmarkEvaluationError(
                    f"published evaluation output does not match staging: {destination}"
                )
    except BaseException:
        for destination in reversed(created):
            destination.unlink(missing_ok=True)
        with suppress(OSError):
            output_dir.rmdir()
        raise
    shutil.rmtree(stage)


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkEvaluationError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BenchmarkEvaluationError(f"{label} must be a JSON object")
    return value


def _relative_file(pack_dir: Path, value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/"):
        raise BenchmarkEvaluationError(f"{label} is not a safe relative path")
    relative = Path(value)
    if ".." in relative.parts:
        raise BenchmarkEvaluationError(f"{label} is not a safe relative path")
    path = (pack_dir / relative).resolve(strict=True)
    try:
        path.relative_to(pack_dir.resolve(strict=True))
    except ValueError as exc:
        raise BenchmarkEvaluationError(f"{label} escapes the benchmark pack") from exc
    if not path.is_file() or path.is_symlink():
        raise BenchmarkEvaluationError(f"{label} must be a regular non-symlink file")
    return path


def _verify_frozen_mix(
    pack_dir: Path,
    excerpt: dict[str, Any],
    *,
    excerpt_id: str,
    input_snapshots: InputSnapshots,
) -> None:
    mix = excerpt.get("mix")
    if not isinstance(mix, dict):
        raise BenchmarkEvaluationError(f"{excerpt_id} has no frozen mix record")
    path = _relative_file(
        pack_dir,
        mix.get("path"),
        label=f"{excerpt_id} frozen mix",
    )
    snapshot = _track_input(
        input_snapshots,
        path,
        label=f"{excerpt_id} frozen mix",
    )
    expected_size = mix.get("size_bytes")
    expected_hash = mix.get("sha256")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
        or snapshot["size_bytes"] != expected_size
        or snapshot["sha256"] != expected_hash
    ):
        raise BenchmarkEvaluationError(f"frozen mix changed: {excerpt_id}")


def _verified_pack(
    pack_dir: Path,
    *,
    input_snapshots: InputSnapshots,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest_path = pack_dir / "benchmark_manifest.json"
    _track_input(input_snapshots, manifest_path, label="benchmark manifest")
    manifest = _load_object(manifest_path, label="benchmark manifest")
    _verify_input_snapshot(input_snapshots[manifest_path.resolve(strict=True)])
    payload = manifest.get("freeze_payload")
    if (
        manifest.get("schema") != "amt-benchmark-pack/v1"
        or not isinstance(payload, dict)
        or canonical_json_sha256(payload) != manifest.get("benchmark_freeze_sha256")
    ):
        raise BenchmarkEvaluationError("benchmark freeze manifest is invalid or modified")
    seal_path = pack_dir / "reference_seal.json"
    _track_input(input_snapshots, seal_path, label="reference seal")
    seal = _load_object(seal_path, label="reference seal")
    _verify_input_snapshot(input_snapshots[seal_path.resolve(strict=True)])
    seal_hash = seal.get("reference_seal_sha256")
    seal_payload = {
        key: value
        for key, value in seal.items()
        if key not in {"reference_seal_sha256", "claims"}
    }
    if (
        seal.get("schema") != "amt-reference-seal/v1"
        or seal.get("benchmark_freeze_sha256") != manifest["benchmark_freeze_sha256"]
        or canonical_json_sha256(seal_payload) != seal_hash
    ):
        raise BenchmarkEvaluationError("reference seal is invalid or belongs to another pack")
    references = seal.get("references")
    if not isinstance(references, list):
        raise BenchmarkEvaluationError("reference seal has no reference list")
    annotation_seed = seal.get("annotation_seed")
    if seal.get("creation_method") == "candidate_corrected":
        if not isinstance(annotation_seed, dict):
            raise BenchmarkEvaluationError(
                "candidate-corrected seal has no immutable annotation seed binding"
            )
        for path_key, hash_key, label in (
            (
                "seed_manifest_path",
                "seed_manifest_sha256",
                "annotation seed manifest",
            ),
            (
                "seed_review_manifest_path",
                "seed_review_manifest_sha256",
                "annotation seed review manifest",
            ),
        ):
            try:
                bound_path = _relative_file(
                    pack_dir,
                    annotation_seed.get(path_key),
                    label=label,
                )
            except (OSError, ValueError) as exc:
                raise BenchmarkEvaluationError(
                    f"sealed {label} is missing or unsafe"
                ) from exc
            bound_snapshot = _track_input(
                input_snapshots,
                bound_path,
                label=label,
            )
            if bound_snapshot["sha256"] != annotation_seed.get(hash_key):
                raise BenchmarkEvaluationError(f"sealed {label} changed")
        candidate_hash = annotation_seed.get("candidate_events_sha256")
        candidate_fingerprint = annotation_seed.get(
            "candidate_note_fingerprint_sha256"
        )
        if (
            annotation_seed.get("candidate_note_fingerprint_scope")
            != "frozen_evaluation_windows_onset_offset_pitch_instrument_v1"
        ):
            raise BenchmarkEvaluationError(
                "annotation seed note fingerprint scope is invalid"
            )
        for value, label in (
            (candidate_hash, "candidate hash"),
            (candidate_fingerprint, "note fingerprint"),
        ):
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(
                    character not in "0123456789abcdef"
                    for character in value
                )
            ):
                raise BenchmarkEvaluationError(
                    f"annotation seed {label} is invalid"
                )
    elif annotation_seed is not None:
        raise BenchmarkEvaluationError(
            "from-scratch seal must not contain an annotation seed"
        )
    by_excerpt = {record.get("excerpt_id"): record for record in references}
    for excerpt in payload.get("excerpts", []):
        excerpt_id = excerpt.get("excerpt_id")
        if not isinstance(excerpt_id, str) or not excerpt_id:
            raise BenchmarkEvaluationError("benchmark excerpt_id is missing")
        _verify_frozen_mix(
            pack_dir,
            excerpt,
            excerpt_id=excerpt_id,
            input_snapshots=input_snapshots,
        )
        record = by_excerpt.get(excerpt_id)
        if not isinstance(record, dict):
            raise BenchmarkEvaluationError(f"reference seal is missing {excerpt_id}")
        reference_path = _relative_file(
            pack_dir,
            record.get("reference_notes_path"),
            label=f"{excerpt_id} reference",
        )
        annotation_path = _relative_file(
            pack_dir,
            record.get("annotation_plan_path"),
            label=f"{excerpt_id} annotation plan",
        )
        reference_snapshot = _track_input(
            input_snapshots,
            reference_path,
            label=f"{excerpt_id} reference",
        )
        annotation_snapshot = _track_input(
            input_snapshots,
            annotation_path,
            label=f"{excerpt_id} annotation plan",
        )
        if (
            reference_snapshot["sha256"] != record.get("reference_notes_sha256")
            or annotation_snapshot["sha256"] != record.get("annotation_plan_sha256")
        ):
            raise BenchmarkEvaluationError(f"sealed reference changed: {excerpt_id}")
        annotation = _load_object(annotation_path, label=f"{excerpt_id} annotation plan")
        _verify_input_snapshot(annotation_snapshot)
        if annotation.get("schema") != "amt-annotation-plan/v1":
            raise BenchmarkEvaluationError(f"annotation plan is invalid: {excerpt_id}")
        correction_record = record.get("correction_session")
        if correction_record is not None:
            if not isinstance(correction_record, dict):
                raise BenchmarkEvaluationError(
                    f"correction record is invalid: {excerpt_id}"
                )
            correction_path = _relative_file(
                pack_dir,
                correction_record.get("path"),
                label=f"{excerpt_id} correction session",
            )
            correction_snapshot = _track_input(
                input_snapshots,
                correction_path,
                label=f"{excerpt_id} correction session",
            )
            if correction_snapshot["sha256"] != correction_record.get("sha256"):
                raise BenchmarkEvaluationError(
                    f"sealed correction session changed: {excerpt_id}"
                )
            try:
                correction_summary = summarize_correction_session(
                    _load_object(
                        correction_path,
                        label=f"{excerpt_id} correction session",
                    )
                )
            except EvaluationError as exc:
                raise BenchmarkEvaluationError(f"{excerpt_id}: {exc}") from exc
            _verify_input_snapshot(correction_snapshot)
            if (
                correction_summary != correction_record.get("summary")
                or correction_summary["benchmark_freeze_sha256"]
                != manifest["benchmark_freeze_sha256"]
                or correction_summary["excerpt_id"] != excerpt_id
                or abs(
                    correction_summary["audio_duration_sec"]
                    - float(excerpt["duration_sec"])
                )
                > 1e-6
            ):
                raise BenchmarkEvaluationError(
                    f"sealed correction session does not match benchmark: {excerpt_id}"
                )
        elif seal.get("creation_method") == "candidate_corrected":
            raise BenchmarkEvaluationError(
                f"candidate-corrected seal is missing correction session: {excerpt_id}"
            )
    return manifest, seal


def _candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise BenchmarkEvaluationError("candidate must be LABEL=EVENTS_JSONL")
    label, path = value.split("=", 1)
    if (
        not label
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in label)
        or not path
    ):
        raise BenchmarkEvaluationError("candidate label or path is invalid")
    return label, Path(path).expanduser()


def _verified_candidate_set(
    pack_dir: Path,
    manifest: dict[str, Any],
    payload: dict[str, Any],
    *,
    candidate_labels: set[str],
    annotation_seed: dict[str, Any] | None,
    input_snapshots: InputSnapshots,
) -> tuple[
    dict[str, dict[str, Any]],
    str,
    dict[str, Any] | None,
] | None:
    if payload.get("split") != "blind_test":
        return None
    try:
        seal_path = _relative_file(
            pack_dir,
            "candidate_set_seal.json",
            label="blind candidate set seal",
        )
    except (OSError, ValueError) as exc:
        raise BenchmarkEvaluationError(
            "blind evaluation requires a candidate set sealed before output "
            "quality inspection"
        ) from exc
    seal_snapshot = _track_input(
        input_snapshots,
        seal_path,
        label="blind candidate set seal",
    )
    seal = _load_object(seal_path, label="blind candidate set seal")
    _verify_input_snapshot(seal_snapshot)
    freeze_payload = seal.get("freeze_payload")
    if (
        seal.get("schema") != "amt-evaluation-candidate-set-seal/v1"
        or not isinstance(freeze_payload, dict)
        or canonical_json_sha256(freeze_payload)
        != seal.get("candidate_set_sha256")
        or freeze_payload.get("schema") != "amt-evaluation-candidate-set/v1"
        or freeze_payload.get("benchmark_freeze_sha256")
        != manifest["benchmark_freeze_sha256"]
        or freeze_payload.get("split") != "blind_test"
    ):
        raise BenchmarkEvaluationError("blind candidate set seal is invalid")
    confirmation = freeze_payload.get("confirmation")
    if (
        not isinstance(confirmation, dict)
        or confirmation.get(
            "candidate_output_quality_uninspected_before_freeze"
        )
        is not True
        or confirmation.get(
            "candidate_selection_or_tuning_after_freeze_prohibited"
        )
        is not True
    ):
        raise BenchmarkEvaluationError(
            "blind candidate set lacks the required pre-inspection confirmation"
        )
    records = freeze_payload.get("candidates")
    if not isinstance(records, list) or not records:
        raise BenchmarkEvaluationError("blind candidate set is empty")
    by_label: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise BenchmarkEvaluationError("blind candidate record is invalid")
        label = record.get("label")
        if not isinstance(label, str) or not label or label in by_label:
            raise BenchmarkEvaluationError(
                "blind candidate labels must be non-empty and unique"
            )
        by_label[label] = record

    excluded_seed: dict[str, Any] | None = None
    expected_labels = set(by_label)
    if annotation_seed is not None:
        seed_identity = {
            "run_id": annotation_seed.get("candidate_run_id"),
            "worker": annotation_seed.get("candidate_worker"),
            "events_sha256": annotation_seed.get("candidate_events_sha256"),
            "run_manifest_sha256": annotation_seed.get(
                "candidate_run_manifest_sha256"
            ),
        }
        matching_seed_records = [
            (label, record)
            for label, record in by_label.items()
            if all(record.get(key) == value for key, value in seed_identity.items())
        ]
        if len(matching_seed_records) != 1:
            raise BenchmarkEvaluationError(
                "candidate-corrected blind evaluation requires the annotation "
                "seed to match exactly one sealed candidate"
            )
        seed_label, seed_record = matching_seed_records[0]
        expected_labels.remove(seed_label)
        excluded_seed = {
            "label": seed_label,
            "run_id": seed_record["run_id"],
            "worker": seed_record["worker"],
            "events_sha256": seed_record["events_sha256"],
            "run_manifest_sha256": seed_record["run_manifest_sha256"],
            "reason": "candidate_used_to_create_reference",
        }

    if expected_labels != candidate_labels:
        raise BenchmarkEvaluationError(
            "evaluated candidates do not exactly match the sealed blind set "
            "after excluding its reference-bound annotation seed"
        )
    return by_label, seal["candidate_set_sha256"], excluded_seed


def _pool_references(
    pack_dir: Path,
    payload: dict[str, Any],
    *,
    target_role: str,
    input_snapshots: InputSnapshots,
) -> list[ReferenceNote]:
    references: list[ReferenceNote] = []
    for excerpt in payload["excerpts"]:
        path = _relative_file(
            pack_dir,
            excerpt["reference_notes_path"],
            label=f"{excerpt['excerpt_id']} reference",
        )
        notes = read_reference_jsonl(path)
        _verify_input_snapshot(input_snapshots[path.resolve(strict=True)])
        start = excerpt["evaluation_start_sec"]
        end = excerpt["evaluation_end_sec"]
        references.extend(
            note
            for note in notes
            if start <= note.onset_sec < end and note.target_role == target_role
        )
    return references


def _pool_estimates(events: list[NoteEvent], payload: dict[str, Any]) -> list[NoteEvent]:
    windows = [
        (excerpt["evaluation_start_sec"], excerpt["evaluation_end_sec"])
        for excerpt in payload["excerpts"]
    ]
    return [
        event
        for event in events
        if any(start <= event.onset_sec < end for start, end in windows)
    ]


def _select_target_events(
    events: list[NoteEvent],
    *,
    target_role: str,
) -> list[NoteEvent]:
    forbidden_tags = {"annotation-only", "not-evaluation-candidate"}
    if any(forbidden_tags.intersection(event.tags) for event in events):
        raise BenchmarkEvaluationError(
            "annotation-only or explicitly ineligible events cannot be scored"
        )
    if target_role == "main_melody":
        selected = [event for event in events if event.is_main_melody_candidate]
        if not selected:
            track_ids = {event.track_id for event in events}
            instruments = {event.instrument for event in events}
            if len(track_ids) == 1 and instruments == {"voice"}:
                selected = events
            else:
                raise BenchmarkEvaluationError(
                    "main_melody evaluation requires one explicitly flagged "
                    "melody track, or one voice-only candidate track"
                )
    elif target_role == "drums":
        selected = [event for event in events if event.instrument == "drums"]
    elif target_role == "bass":
        selected = [
            event
            for event in events
            if event.instrument in {"bass", "acoustic_bass", "electric_bass"}
        ]
    else:
        selected = [
            event
            for event in events
            if event.instrument
            not in {
                "voice",
                "drums",
                "bass",
                "acoustic_bass",
                "electric_bass",
            }
        ]
    if not selected:
        raise BenchmarkEvaluationError(
            f"candidate contains no events for target_role={target_role!r}"
        )
    track_ids = {event.track_id for event in selected}
    if len(track_ids) != 1:
        raise BenchmarkEvaluationError(
            f"target_role={target_role!r} resolves to multiple tracks: "
            f"{sorted(track_ids)}"
        )
    return selected


def _verified_candidate(
    payload: dict[str, Any],
    *,
    label: str,
    raw_path: Path,
    ineligible_candidate_hashes: set[str],
    input_snapshots: InputSnapshots | None = None,
) -> tuple[Path, WorkerResultV1, list[NoteEvent], str]:
    requested = raw_path.expanduser()
    if requested.is_symlink():
        raise BenchmarkEvaluationError(f"{label}: candidate must not be a symlink")
    try:
        path = requested.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise BenchmarkEvaluationError(f"{label}: candidate is missing") from exc
    if not path.is_file() or path.name != "events.jsonl" or path.parent.name != "normalized":
        raise BenchmarkEvaluationError(
            f"{label}: candidate must be a worker run normalized/events.jsonl"
        )
    run_dir = path.parent.parent
    manifest_path = run_dir / "run_manifest.json"
    events_snapshot = (
        _track_input(input_snapshots, path, label=f"{label} candidate events")
        if input_snapshots is not None
        else None
    )
    manifest_snapshot = (
        _track_input(
            input_snapshots,
            manifest_path,
            label=f"{label} candidate run manifest",
        )
        if input_snapshots is not None
        else None
    )
    try:
        result = load_worker_result(run_dir)
        expected_path = result.output_path("normalized/events.jsonl").resolve(strict=True)
        events = result.read_note_events()
    except (ContractValidationError, EventValidationError, OSError) as exc:
        raise BenchmarkEvaluationError(
            f"{label}: candidate worker result is invalid: {exc}"
        ) from exc
    if expected_path != path:
        raise BenchmarkEvaluationError(
            f"{label}: candidate path is not the recorded normalized worker output"
        )
    if result.project_id != payload.get("project_id"):
        raise BenchmarkEvaluationError(f"{label}: candidate belongs to another project")
    lineage = result.manifest.get("input_lineage")
    if (
        not isinstance(lineage, dict)
        or lineage.get("canonical_mix_sha256")
        != payload.get("canonical_audio_sha256")
    ):
        raise BenchmarkEvaluationError(
            f"{label}: candidate is not bound to the benchmark canonical mix"
        )
    if any(event.source_run_id != result.run_id for event in events):
        raise BenchmarkEvaluationError(
            f"{label}: event source_run_id does not match its worker run"
        )
    if events_snapshot is not None and manifest_snapshot is not None:
        _verify_input_snapshot(events_snapshot)
        _verify_input_snapshot(manifest_snapshot)
        candidate_hash = events_snapshot["sha256"]
    else:
        candidate_hash = sha256_file(path)
    if candidate_hash in ineligible_candidate_hashes:
        raise BenchmarkEvaluationError(
            f"{label}: the annotation seed is ineligible for primary metrics"
        )
    return path, result, events, candidate_hash


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _artifact_record(path: Path, *, base: Path | None = None) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(base)) if base is not None else str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _git_state(repo_root: Path) -> dict[str, Any]:
    commit = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return {
        "commit": commit.stdout.strip() if commit.returncode == 0 else None,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def evaluate_benchmark(
    pack_dir: Path,
    candidates: list[tuple[str, Path]],
    output_dir: Path,
    *,
    correction_logs: list[Path] | None = None,
    target_role: str = "main_melody",
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    pack_dir = pack_dir.resolve(strict=True)
    input_snapshots: InputSnapshots = {}
    manifest, seal = _verified_pack(
        pack_dir,
        input_snapshots=input_snapshots,
    )
    payload = manifest["freeze_payload"]
    if not candidates:
        raise BenchmarkEvaluationError("at least one candidate is required")
    if target_role not in {"main_melody", "drums", "bass", "harmonic"}:
        raise BenchmarkEvaluationError(f"unsupported target_role: {target_role}")
    labels = [label for label, _path in candidates]
    if len(set(labels)) != len(labels):
        raise BenchmarkEvaluationError("candidate labels must be unique")
    if output_dir.exists() or output_dir.is_symlink():
        raise BenchmarkEvaluationError(f"output directory already exists: {output_dir}")
    annotation_seed = seal.get("annotation_seed")
    verified_candidate_set = _verified_candidate_set(
        pack_dir,
        manifest,
        payload,
        candidate_labels=set(labels),
        annotation_seed=(
            annotation_seed if isinstance(annotation_seed, dict) else None
        ),
        input_snapshots=input_snapshots,
    )
    try:
        references = _pool_references(
            pack_dir,
            payload,
            target_role=target_role,
            input_snapshots=input_snapshots,
        )
    except (OSError, EvaluationError) as exc:
        raise BenchmarkEvaluationError(str(exc)) from exc
    if not references:
        raise BenchmarkEvaluationError("sealed benchmark contains no reference notes")

    candidate_reports: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    coverage_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    candidate_hashes: set[str] = set()
    candidate_paths: set[Path] = set()
    config = EvaluationConfig()
    ineligible_candidate_hashes = (
        {annotation_seed["candidate_events_sha256"]}
        if isinstance(annotation_seed, dict)
        else set()
    )
    ineligible_note_fingerprints = (
        {annotation_seed["candidate_note_fingerprint_sha256"]}
        if isinstance(annotation_seed, dict)
        else set()
    )
    for label, raw_path in candidates:
        try:
            path, result, all_events, candidate_hash = _verified_candidate(
                payload,
                label=label,
                raw_path=raw_path,
                ineligible_candidate_hashes=ineligible_candidate_hashes,
                input_snapshots=input_snapshots,
            )
            target_events = _select_target_events(
                all_events,
                target_role=target_role,
            )
            estimates = _pool_estimates(target_events, payload)
            if note_sequence_fingerprint(estimates) in ineligible_note_fingerprints:
                raise BenchmarkEvaluationError(
                    f"{label}: a semantic copy of the annotation seed within "
                    "the scored windows is ineligible for primary metrics"
                )
            metrics = evaluate_notes(references, estimates, config)
        except (OSError, EventValidationError, EvaluationError) as exc:
            raise BenchmarkEvaluationError(f"{label}: {exc}") from exc
        if path in candidate_paths:
            raise BenchmarkEvaluationError("candidate paths must be unique")
        if verified_candidate_set is not None:
            (
                frozen_candidates,
                _candidate_set_sha256,
                _excluded_seed,
            ) = verified_candidate_set
            frozen = frozen_candidates[label]
            candidate_manifest_snapshot = input_snapshots[
                result.manifest_path.resolve(strict=True)
            ]
            if (
                frozen.get("run_id") != result.run_id
                or frozen.get("worker") != result.worker
                or frozen.get("events_sha256") != candidate_hash
                or frozen.get("run_manifest_sha256")
                != candidate_manifest_snapshot["sha256"]
            ):
                raise BenchmarkEvaluationError(
                    f"{label}: candidate does not match the sealed blind set"
                )
        candidate_paths.add(path)
        candidate_hashes.add(candidate_hash)
        candidate_manifest_snapshot = input_snapshots[
            result.manifest_path.resolve(strict=True)
        ]
        candidate_reports.append(
            {
                "label": label,
                "events_path": str(path),
                "events_sha256": candidate_hash,
                "run_id": result.run_id,
                "worker": result.worker,
                "run_manifest_path": str(result.manifest_path),
                "run_manifest_sha256": candidate_manifest_snapshot["sha256"],
                "target_track_id": next(iter({event.track_id for event in target_events})),
                "target_event_count": len(target_events),
                "pooled_estimate_count": len(estimates),
                "metrics": metrics,
            }
        )
        primary = metrics["primary"]
        for metric_name in ("onset_only", "onset_pitch", "onset_pitch_offset", "onset_chroma"):
            metric = primary[metric_name]
            metric_rows.append(
                {
                    "candidate": label,
                    "metric": metric_name,
                    "precision": metric["precision"],
                    "recall": metric["recall"],
                    "f1": metric["f1"],
                    "matches": metric["matches"],
                    "reference_count": metric["reference_count"],
                    "estimate_count": metric["estimate_count"],
                }
            )
        for coverage in metrics["confidence_coverage"]:
            note_metric = coverage["onset_pitch"]
            coverage_rows.append(
                {
                    "candidate": label,
                    "status": metrics["confidence_coverage_status"],
                    "threshold": coverage["threshold"],
                    "estimate_retention": coverage["estimate_retention"],
                    "precision": note_metric["precision"],
                    "recall_reference_coverage": note_metric["recall"],
                    "f1": note_metric["f1"],
                    "estimates_missing_confidence": coverage["estimates_missing_confidence"],
                }
            )
        error_counts = {
            "missed_reference": (
                primary["onset_pitch"]["reference_count"] - primary["onset_pitch"]["matches"]
            ),
            "extra_estimate": (
                primary["onset_pitch"]["estimate_count"] - primary["onset_pitch"]["matches"]
            ),
            "onset_matched_pitch_mismatch": (
                primary["onset_only"]["matches"] - primary["onset_pitch"]["matches"]
            ),
            "onset_pitch_matched_offset_mismatch": (
                primary["onset_pitch"]["matches"]
                - primary["onset_pitch_offset"]["matches"]
            ),
            "octave_error": primary["octave_error"]["errors"],
        }
        for category, count in error_counts.items():
            error_rows.append({"candidate": label, "category": category, "count": count})

    sealed_correction_logs = [
        _relative_file(
            pack_dir,
            record["correction_session"]["path"],
            label=f"{record['excerpt_id']} correction session",
        )
        for record in seal["references"]
        if record.get("correction_session") is not None
    ]
    all_correction_logs: list[tuple[Path, bool]] = []
    seen_correction_logs: set[Path] = set()
    sealed_paths = {path.resolve(strict=True) for path in sealed_correction_logs}
    for path in [*sealed_correction_logs, *(correction_logs or [])]:
        resolved = path.resolve(strict=True)
        if resolved not in seen_correction_logs:
            seen_correction_logs.add(resolved)
            all_correction_logs.append((resolved, resolved in sealed_paths))
    correction_rows: list[dict[str, Any]] = []
    known_excerpt_ids = {
        excerpt["excerpt_id"] for excerpt in payload["excerpts"]
    }
    excerpt_duration_by_id = {
        excerpt["excerpt_id"]: float(excerpt["duration_sec"])
        for excerpt in payload["excerpts"]
    }
    for path, sealed_reference_log in all_correction_logs:
        correction_snapshot = _track_input(
            input_snapshots,
            path,
            label=(
                "sealed correction session"
                if sealed_reference_log
                else "supplemental correction log"
            ),
        )
        try:
            summary = summarize_correction_session(
                _load_object(path, label="correction log")
            )
        except EvaluationError as exc:
            raise BenchmarkEvaluationError(f"{path}: {exc}") from exc
        _verify_input_snapshot(correction_snapshot)
        if (
            summary["benchmark_freeze_sha256"]
            != manifest["benchmark_freeze_sha256"]
            or summary["excerpt_id"] not in known_excerpt_ids
            or abs(
                summary["audio_duration_sec"]
                - excerpt_duration_by_id.get(summary["excerpt_id"], -1)
            )
            > 1e-6
        ):
            raise BenchmarkEvaluationError(
                f"{path}: correction log does not belong to this benchmark"
            )
        if not sealed_reference_log and summary["candidate_sha256"] not in candidate_hashes:
            raise BenchmarkEvaluationError(
                f"{path}: supplemental correction log is not bound to an "
                "evaluated candidate"
            )
        correction_rows.append(
            {
                **summary,
                "correction_log_path": str(path),
                "correction_log_sha256": correction_snapshot["sha256"],
                "sealed_reference_log": sealed_reference_log,
            }
        )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
    )
    try:
        report = {
            "schema": "amt-benchmark-evaluation/v1",
            "created_at": datetime.now(UTC).isoformat(),
            "benchmark": {
                "benchmark_id": payload["benchmark_id"],
                "split": payload["split"],
                "benchmark_freeze_sha256": manifest["benchmark_freeze_sha256"],
                "reference_seal_sha256": seal["reference_seal_sha256"],
                "reference_note_count": len(references),
                "target_role": target_role,
                "candidate_set_sha256": (
                    verified_candidate_set[1]
                    if verified_candidate_set is not None
                    else None
                ),
                "excluded_sealed_annotation_seed": (
                    verified_candidate_set[2]
                    if verified_candidate_set is not None
                    else None
                ),
            },
            "metric_config": config.to_dict(),
            "measured_results": candidate_reports,
            "listening_impressions": {
                "status": "not_recorded_by_evaluator",
                "notes": [],
            },
            "correction_effort": correction_rows,
            "claims": {
                "human_reference_verified": True,
                "blind_test_result": verified_candidate_set is not None,
                "fusion_tuning_authorized": payload["split"] == "development",
            },
        }
        atomic_write_json(temporary / "evaluation_report.json", report)
        _write_csv(
            temporary / "metrics_by_track.csv",
            [
                "candidate",
                "metric",
                "precision",
                "recall",
                "f1",
                "matches",
                "reference_count",
                "estimate_count",
            ],
            metric_rows,
        )
        _write_csv(
            temporary / "precision_coverage.csv",
            [
                "candidate",
                "status",
                "threshold",
                "estimate_retention",
                "precision",
                "recall_reference_coverage",
                "f1",
                "estimates_missing_confidence",
            ],
            coverage_rows,
        )
        _write_csv(
            temporary / "error_taxonomy.csv",
            ["candidate", "category", "count"],
            error_rows,
        )
        _write_csv(
            temporary / "correction_time.csv",
            [
                "schema",
                "session_id",
                "benchmark_freeze_sha256",
                "excerpt_id",
                "candidate_sha256",
                "audio_duration_sec",
                "review_granularity",
                "full_playback_count",
                "additional_review_sec",
                "decision",
                "operation_count",
                "action_counts",
                "total_edit_time_sec",
                "operation_time_sec",
                "unattributed_review_time_sec",
                "corrections_per_minute_audio",
                "edit_seconds_per_minute_audio",
                "correction_log_path",
                "correction_log_sha256",
                "sealed_reference_log",
            ],
            correction_rows,
        )
        repo_root = Path(__file__).resolve().parents[1]
        source_paths = [
            Path(__file__).resolve(),
            repo_root / "src" / "amt_core" / "benchmark.py",
            repo_root / "src" / "amt_core" / "contracts.py",
            repo_root / "src" / "amt_core" / "evaluation.py",
            repo_root / "src" / "amt_core" / "events.py",
        ]
        logical_command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--pack-dir",
            str(pack_dir),
        ]
        for label, path in candidates:
            logical_command.extend(["--candidate", f"{label}={path.resolve(strict=True)}"])
        for path in correction_logs or []:
            logical_command.extend(["--correction-log", str(path.resolve(strict=True))])
        logical_command.extend(
            [
                "--target-role",
                target_role,
                "--output-dir",
                str(output_dir),
            ]
        )
        run_manifest = {
            "schema_version": 1,
            "artifact_type": "amt-evaluation-run",
            "run_id": f"{payload['benchmark_id']}-{target_role}-evaluation",
            "project_id": payload["project_id"],
            "worker": "evaluation",
            "status": "succeeded",
            "started_at": started_at,
            "ended_at": datetime.now(UTC).isoformat(),
            "command": logical_command,
            "inputs": [
                _snapshot_artifact(input_snapshots[path])
                for path in sorted(input_snapshots, key=str)
            ],
            "outputs": [
                _artifact_record(path, base=temporary)
                for path in sorted(temporary.iterdir())
                if path.is_file() and path.name != "run_manifest.json"
            ],
            "environment": {
                "hostname": platform.node(),
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "code": {
                **_git_state(repo_root),
                "source_files": [
                    {
                        "path": str(path.relative_to(repo_root)),
                        "sha256": sha256_file(path),
                    }
                    for path in source_paths
                ],
            },
            "benchmark": {
                "benchmark_freeze_sha256": manifest["benchmark_freeze_sha256"],
                "reference_seal_sha256": seal["reference_seal_sha256"],
                "split": payload["split"],
                "target_role": target_role,
                "candidate_set_sha256": (
                    verified_candidate_set[1]
                    if verified_candidate_set is not None
                    else None
                ),
                "excluded_sealed_annotation_seed": (
                    verified_candidate_set[2]
                    if verified_candidate_set is not None
                    else None
                ),
            },
            "claims": report["claims"],
        }
        atomic_write_json(temporary / "run_manifest.json", run_manifest)
        _verify_input_snapshots(input_snapshots)
        _publish_new_directory(temporary, output_dir)
        return report
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--correction-log", action="append", type=Path, default=[])
    parser.add_argument(
        "--target-role",
        choices=("main_melody", "drums", "bass", "harmonic"),
        default="main_melody",
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    report = evaluate_benchmark(
        args.pack_dir,
        [_candidate(value) for value in args.candidate],
        args.output_dir,
        correction_logs=args.correction_log,
        target_role=args.target_role,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
