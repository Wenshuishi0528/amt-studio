#!/usr/bin/env python3
"""Create and human-audit a provisional candidate-seeded reference set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from amt_core.benchmark import canonical_json_sha256
from amt_core.contracts import ContractValidationError, load_worker_result
from amt_core.evaluation import (
    AMBIGUITY_TAGS,
    CORRECTION_SESSION_SCHEMA,
    EvaluationError,
    ReferenceNote,
    note_sequence_fingerprint,
    read_reference_jsonl,
    summarize_correction_session,
    write_reference_jsonl,
)
from amt_core.events import EventValidationError, NoteEvent
from amt_core.utils import atomic_write_json, sha256_file


class SeededReferenceError(RuntimeError):
    """Raised when a seeded reference would be unauditable."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SeededReferenceError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise SeededReferenceError(f"{label} must be a JSON object")
    return value


def _pack(pack_dir: Path) -> tuple[Path, dict[str, Any]]:
    pack_dir = pack_dir.resolve(strict=True)
    manifest = _load_object(pack_dir / "benchmark_manifest.json", label="benchmark manifest")
    payload = manifest.get("freeze_payload")
    if (
        manifest.get("schema") != "amt-benchmark-pack/v1"
        or not isinstance(payload, dict)
        or canonical_json_sha256(payload) != manifest.get("benchmark_freeze_sha256")
    ):
        raise SeededReferenceError("benchmark freeze manifest is invalid or modified")
    if (pack_dir / "reference_seal.json").exists():
        raise SeededReferenceError("sealed references cannot be seeded or changed")
    return pack_dir, manifest


def _relative_file(pack_dir: Path, relative_value: Any, *, label: str) -> Path:
    if not isinstance(relative_value, str) or not relative_value or relative_value.startswith("/"):
        raise SeededReferenceError(f"{label} is not a safe relative path")
    relative = Path(relative_value)
    if ".." in relative.parts:
        raise SeededReferenceError(f"{label} is not a safe relative path")
    cursor = pack_dir
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise SeededReferenceError(f"{label} contains a symbolic link")
    path = cursor.resolve(strict=True)
    try:
        path.relative_to(pack_dir)
    except ValueError as exc:
        raise SeededReferenceError(f"{label} escapes the benchmark pack") from exc
    if not path.is_file():
        raise SeededReferenceError(f"{label} must be a regular non-symlink file")
    return path


def seed_references(pack_dir: Path, candidate_events_path: Path) -> dict[str, Any]:
    pack_dir, manifest = _pack(pack_dir)
    seed_manifest_path = pack_dir / "seed_manifest.json"
    if seed_manifest_path.exists():
        raise SeededReferenceError("seed manifest already exists")
    policy_path = pack_dir / "reference_seed_policy.json"
    policy = _load_object(policy_path, label="reference seed policy")
    if (
        policy.get("schema") != "amt-reference-seed-policy/v1"
        or policy.get("benchmark_freeze_sha256") != manifest["benchmark_freeze_sha256"]
        or policy.get("seed_method") != "candidate_corrected"
    ):
        raise SeededReferenceError("reference seed policy is invalid or mismatched")
    candidate_events_path = candidate_events_path.expanduser()
    if candidate_events_path.is_symlink():
        raise SeededReferenceError("candidate events cannot be a symbolic link")
    candidate_events_path = candidate_events_path.resolve(strict=True)
    if (
        not candidate_events_path.is_file()
        or candidate_events_path.name != "events.jsonl"
        or candidate_events_path.parent.name != "normalized"
    ):
        raise SeededReferenceError(
            "candidate must be a worker run normalized/events.jsonl"
        )
    try:
        worker_result = load_worker_result(candidate_events_path.parent.parent)
        expected_events_path = worker_result.output_path(
            "normalized/events.jsonl"
        ).resolve(strict=True)
        events = worker_result.read_note_events()
    except (ContractValidationError, EventValidationError, OSError) as exc:
        raise SeededReferenceError(f"candidate worker result is invalid: {exc}") from exc
    if expected_events_path != candidate_events_path:
        raise SeededReferenceError(
            "candidate path is not the recorded normalized worker output"
        )
    expected_run_id = policy.get("seed_candidate_run_id")
    payload = manifest["freeze_payload"]
    lineage = worker_result.manifest.get("input_lineage")
    if (
        worker_result.run_id != expected_run_id
        or worker_result.project_id != payload.get("project_id")
        or not isinstance(lineage, dict)
        or lineage.get("canonical_mix_sha256")
        != payload.get("canonical_audio_sha256")
        or not events
        or {event.source_run_id for event in events} != {expected_run_id}
    ):
        raise SeededReferenceError("candidate events do not match the frozen seed run")
    non_voice = sorted(
        {
            event.instrument
            for event in events
            if event.instrument not in {"voice", "vocals"}
        },
        key=str,
    )
    if non_voice:
        raise SeededReferenceError(f"seed candidate contains non-voice instruments: {non_voice}")

    pending: list[tuple[Path, list[ReferenceNote], str]] = []
    records: list[dict[str, Any]] = []
    seed_scoring_events: list[NoteEvent] = []
    for excerpt in payload["excerpts"]:
        excerpt_id = excerpt["excerpt_id"]
        reference_path = _relative_file(
            pack_dir,
            excerpt["reference_notes_path"],
            label=f"{excerpt_id} reference notes",
        )
        if reference_path.stat().st_size != 0:
            raise SeededReferenceError(f"{excerpt_id} reference file is not empty")
        start = excerpt["evaluation_start_sec"]
        end = excerpt["evaluation_end_sec"]
        audio_end = excerpt["audio_end_sec"]
        selected = [event for event in events if start <= event.onset_sec < end]
        seed_scoring_events.extend(selected)
        notes: list[ReferenceNote] = []
        for index, event in enumerate(selected, start=1):
            clipped = event.offset_sec > audio_end
            ambiguity = ("phrase_boundary", "source_identity") if clipped else ("source_identity",)
            notes.append(
                ReferenceNote(
                    reference_note_id=f"{excerpt_id}-seed-{index:04d}",
                    onset_sec=event.onset_sec,
                    offset_sec=min(event.offset_sec, audio_end),
                    pitch_midi=event.pitch_midi,
                    instrument="voice",
                    annotator_confidence=0.0,
                    ambiguity_tags=ambiguity,
                    comment=(
                        "Provisional candidate seed; not human-confirmed. "
                        f"Source event: {event.event_id}"
                    ),
                    offset_censored=clipped,
                )
            )
        pending.append((reference_path, notes, excerpt_id))

    for reference_path, notes, excerpt_id in pending:
        write_reference_jsonl(reference_path, notes)
        records.append(
            {
                "excerpt_id": excerpt_id,
                "reference_notes_path": str(reference_path.relative_to(pack_dir)),
                "reference_notes_sha256": sha256_file(reference_path),
                "provisional_note_count": len(notes),
            }
        )
    seed_manifest = {
        "schema": "amt-seeded-reference/v1",
        "status": "awaiting_human_correction",
        "benchmark_freeze_sha256": manifest["benchmark_freeze_sha256"],
        "seed_policy_path": "reference_seed_policy.json",
        "seed_policy_sha256": sha256_file(policy_path),
        "seed_candidate_label": policy["seed_candidate_label"],
        "seed_candidate_run_id": expected_run_id,
        "seed_candidate_worker": worker_result.worker,
        "seed_candidate_events_path": str(candidate_events_path),
        "seed_candidate_events_sha256": sha256_file(candidate_events_path),
        "seed_candidate_note_fingerprint_scope": (
            "frozen_evaluation_windows_onset_offset_pitch_instrument_v1"
        ),
        "seed_candidate_note_fingerprint_sha256": note_sequence_fingerprint(
            seed_scoring_events
        ),
        "seed_candidate_run_manifest_path": str(worker_result.manifest_path),
        "seed_candidate_run_manifest_sha256": sha256_file(
            worker_result.manifest_path
        ),
        "references": records,
        "claims": {
            "human_confirmed": False,
            "accuracy_claimed": False,
            "seed_candidate_eligible_for_primary_metrics": False,
        },
    }
    atomic_write_json(seed_manifest_path, seed_manifest)
    return seed_manifest


def _review_records(
    review: dict[str, Any],
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    if (
        review.get("schema") != "amt-seed-review/v1"
        or review.get("benchmark_freeze_sha256") != manifest["benchmark_freeze_sha256"]
        or review.get("reviewer") != "project_owner"
    ):
        raise SeededReferenceError("seed review identity or benchmark binding is invalid")
    records = review.get("excerpts")
    if not isinstance(records, list):
        raise SeededReferenceError("seed review excerpts must be an array")
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise SeededReferenceError("seed review excerpt must be an object")
        excerpt_id = record.get("excerpt_id")
        if not isinstance(excerpt_id, str) or not excerpt_id or excerpt_id in by_id:
            raise SeededReferenceError("seed review excerpt IDs must be unique")
        decision = record.get("decision")
        if decision not in {"accept_seed", "accept_empty", "needs_note_correction"}:
            raise SeededReferenceError(f"unsupported seed review decision: {decision!r}")
        if decision == "needs_note_correction":
            for field_name in (
                "corrected_reference_path",
                "correction_session_path",
            ):
                field_value = record.get(field_name)
                if not isinstance(field_value, str) or not field_value.strip():
                    raise SeededReferenceError(
                        f"{field_name} is required for note-level correction"
                    )
        else:
            playback_count = record.get("full_playback_count")
            if (
                isinstance(playback_count, bool)
                or not isinstance(playback_count, int)
                or playback_count < 1
            ):
                raise SeededReferenceError(
                    "full_playback_count must be a positive integer"
                )
            extra_time = record.get("additional_review_sec", 0)
            if (
                isinstance(extra_time, bool)
                or not isinstance(extra_time, (int, float))
                or extra_time < 0
            ):
                raise SeededReferenceError(
                    "additional_review_sec must be non-negative"
                )
            confidence = record.get("annotator_confidence")
            if (
                isinstance(confidence, bool)
                or not isinstance(confidence, (int, float))
                or not 0 < confidence <= 1
            ):
                raise SeededReferenceError(
                    "annotator_confidence must be in (0, 1]"
                )
            ambiguity = record.get("ambiguity_tags", [])
            if (
                not isinstance(ambiguity, list)
                or len(set(ambiguity)) != len(ambiguity)
                or set(ambiguity) - AMBIGUITY_TAGS
            ):
                raise SeededReferenceError("seed review ambiguity_tags are invalid")
        by_id[excerpt_id] = record
    expected_ids = {excerpt["excerpt_id"] for excerpt in manifest["freeze_payload"]["excerpts"]}
    if set(by_id) != expected_ids:
        raise SeededReferenceError("seed review must cover every frozen excerpt exactly once")
    return by_id


def _review_input_file(value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise SeededReferenceError(f"{label} path is required")
    requested = Path(value).expanduser()
    if requested.is_symlink():
        raise SeededReferenceError(f"{label} cannot be a symbolic link")
    try:
        path = requested.resolve(strict=True)
    except OSError as exc:
        raise SeededReferenceError(f"{label} is missing or unreadable") from exc
    if not path.is_file():
        raise SeededReferenceError(f"{label} must be a regular file")
    return path


def apply_human_review(pack_dir: Path, review_path: Path) -> dict[str, Any]:
    pack_dir, manifest = _pack(pack_dir)
    applied_path = pack_dir / "seed_review_manifest.json"
    if applied_path.exists():
        raise SeededReferenceError("seed review has already been applied")
    seed_manifest = _load_object(pack_dir / "seed_manifest.json", label="seed manifest")
    if (
        seed_manifest.get("schema") != "amt-seeded-reference/v1"
        or seed_manifest.get("benchmark_freeze_sha256")
        != manifest["benchmark_freeze_sha256"]
        or seed_manifest.get("status") != "awaiting_human_correction"
    ):
        raise SeededReferenceError("seed manifest is invalid or already reviewed")
    review_path = review_path.resolve(strict=True)
    review = _load_object(review_path, label="human seed review")
    review_by_id = _review_records(review, manifest)

    seed_records = {
        record["excerpt_id"]: record for record in seed_manifest["references"]
    }
    pending: list[
        tuple[
            Path,
            list[ReferenceNote],
            Path,
            dict[str, Any],
            dict[str, Any],
        ]
    ] = []
    result_records: list[dict[str, Any]] = []
    for excerpt in manifest["freeze_payload"]["excerpts"]:
        excerpt_id = excerpt["excerpt_id"]
        seed_record = seed_records.get(excerpt_id)
        if not isinstance(seed_record, dict):
            raise SeededReferenceError(f"seed manifest is missing {excerpt_id}")
        reference_path = _relative_file(
            pack_dir,
            seed_record["reference_notes_path"],
            label=f"{excerpt_id} seeded references",
        )
        if sha256_file(reference_path) != seed_record["reference_notes_sha256"]:
            raise SeededReferenceError(f"seeded references changed before review: {excerpt_id}")
        notes = read_reference_jsonl(reference_path)
        review_record = review_by_id[excerpt_id]
        correction_path = pack_dir / "corrections" / f"{excerpt_id}.json"
        duration = float(excerpt["duration_sec"])
        if review_record["decision"] == "needs_note_correction":
            corrected_source = _review_input_file(
                review_record["corrected_reference_path"],
                label=f"{excerpt_id} corrected reference",
            )
            correction_source = _review_input_file(
                review_record["correction_session_path"],
                label=f"{excerpt_id} correction session",
            )
            if corrected_source == reference_path:
                raise SeededReferenceError(
                    f"{excerpt_id} corrected reference must be a separate reviewed file"
                )
            try:
                confirmed = read_reference_jsonl(corrected_source)
                correction = _load_object(
                    correction_source,
                    label=f"{excerpt_id} correction session",
                )
                correction_summary = summarize_correction_session(correction)
            except (EvaluationError, OSError) as exc:
                raise SeededReferenceError(str(exc)) from exc
            if (
                correction_summary["review_granularity"] != "note_level_edit"
                or correction_summary["benchmark_freeze_sha256"]
                != manifest["benchmark_freeze_sha256"]
                or correction_summary["excerpt_id"] != excerpt_id
                or correction_summary["candidate_sha256"]
                != seed_manifest["seed_candidate_events_sha256"]
                or abs(correction_summary["audio_duration_sec"] - duration) > 1e-6
            ):
                raise SeededReferenceError(
                    f"{excerpt_id} note-level correction does not match the seed benchmark"
                )
            start = float(excerpt["evaluation_start_sec"])
            end = float(excerpt["evaluation_end_sec"])
            audio_end = float(excerpt["audio_end_sec"])
            if any(
                not start <= note.onset_sec < end
                or note.offset_sec > audio_end + 1e-9
                for note in confirmed
            ):
                raise SeededReferenceError(
                    f"{excerpt_id} corrected notes exceed the frozen excerpt"
                )
            seed_semantics = [
                (
                    note.onset_sec,
                    note.offset_sec,
                    note.pitch_midi,
                    note.instrument,
                    note.target_role,
                    note.evaluation_status,
                    note.offset_censored,
                )
                for note in notes
            ]
            corrected_semantics = [
                (
                    note.onset_sec,
                    note.offset_sec,
                    note.pitch_midi,
                    note.instrument,
                    note.target_role,
                    note.evaluation_status,
                    note.offset_censored,
                )
                for note in confirmed
            ]
            if seed_semantics == corrected_semantics:
                raise SeededReferenceError(
                    f"{excerpt_id} note-level correction did not change note semantics"
                )
            seed_ids = {note.reference_note_id for note in notes}
            corrected_ids = {note.reference_note_id for note in confirmed}
            for operation in correction.get("operations", []):
                if (
                    set(operation.get("source_note_ids", [])) - seed_ids
                    or set(operation.get("result_note_ids", [])) - corrected_ids
                ):
                    raise SeededReferenceError(
                        f"{excerpt_id} correction operation references unknown note IDs"
                    )
            evidence = {
                "decision": "note_correction_applied",
                "review_granularity": "note_level_edit",
                "corrected_reference_source_path": str(corrected_source),
                "corrected_reference_source_sha256": sha256_file(corrected_source),
                "correction_session_source_path": str(correction_source),
                "correction_session_source_sha256": sha256_file(correction_source),
            }
            pending.append(
                (
                    reference_path,
                    confirmed,
                    correction_path,
                    correction,
                    evidence,
                )
            )
            continue
        if review_record["decision"] == "accept_seed" and not notes:
            raise SeededReferenceError(f"{excerpt_id} cannot accept an empty seed")
        if review_record["decision"] == "accept_empty" and notes:
            raise SeededReferenceError(f"{excerpt_id} cannot accept_empty with seeded notes")
        ambiguity = tuple(review_record.get("ambiguity_tags", []))
        confirmed = [
            ReferenceNote(
                reference_note_id=note.reference_note_id,
                onset_sec=note.onset_sec,
                offset_sec=note.offset_sec,
                pitch_midi=note.pitch_midi,
                instrument=note.instrument,
                annotator_confidence=float(review_record["annotator_confidence"]),
                ambiguity_tags=tuple(
                    sorted(
                        set(ambiguity)
                        | (
                            {"phrase_boundary"}
                            if note.offset_censored
                            else set()
                        )
                    )
                ),
                comment=(
                    "Project owner accepted the candidate seed through "
                    "whole-excerpt aural comparison; no note-level edits were logged."
                ),
                offset_censored=note.offset_censored,
            )
            for note in notes
        ]
        total_review = (
            review_record["full_playback_count"] * duration
            + float(review_record.get("additional_review_sec", 0))
        )
        correction = {
            "schema": CORRECTION_SESSION_SCHEMA,
            "session_id": f"{excerpt_id}-whole-excerpt-review",
            "benchmark_freeze_sha256": manifest["benchmark_freeze_sha256"],
            "excerpt_id": excerpt_id,
            "candidate_sha256": seed_manifest["seed_candidate_events_sha256"],
            "audio_duration_sec": duration,
            "total_edit_time_sec": total_review,
            "review_granularity": "whole_excerpt_aural_comparison",
            "full_playback_count": review_record["full_playback_count"],
            "additional_review_sec": float(review_record.get("additional_review_sec", 0)),
            "decision": review_record["decision"],
            "operations": [],
        }
        pending.append(
            (
                reference_path,
                confirmed,
                correction_path,
                correction,
                {
                    "decision": correction["decision"],
                    "review_granularity": "whole_excerpt_aural_comparison",
                },
            )
        )

    for reference_path, confirmed, correction_path, correction, evidence in pending:
        write_reference_jsonl(reference_path, confirmed)
        atomic_write_json(correction_path, correction)
        result_records.append(
            {
                "excerpt_id": correction["excerpt_id"],
                **evidence,
                "reference_notes_sha256": sha256_file(reference_path),
                "reference_note_count": len(confirmed),
                "correction_session_path": str(correction_path.relative_to(pack_dir)),
                "correction_session_sha256": sha256_file(correction_path),
            }
        )
    applied = {
        "schema": "amt-seed-review-result/v1",
        "status": "human_review_applied_ready_to_seal",
        "benchmark_freeze_sha256": manifest["benchmark_freeze_sha256"],
        "review_path": str(review_path),
        "review_sha256": sha256_file(review_path),
        "seed_candidate_label": seed_manifest["seed_candidate_label"],
        "seed_candidate_events_sha256": seed_manifest["seed_candidate_events_sha256"],
        "review_granularity": (
            next(iter({record["review_granularity"] for record in result_records}))
            if len({record["review_granularity"] for record in result_records}) == 1
            else "mixed"
        ),
        "references": result_records,
        "limitations": [
            "The annotation seed is excluded from primary metrics.",
            "Whole-excerpt acceptance, when used, is less precise than note-by-note editing.",
        ],
    }
    atomic_write_json(applied_path, applied)
    return applied


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    seed = subparsers.add_parser("seed")
    seed.add_argument("--pack-dir", type=Path, required=True)
    seed.add_argument("--candidate-events", type=Path, required=True)
    review = subparsers.add_parser("apply-review")
    review.add_argument("--pack-dir", type=Path, required=True)
    review.add_argument("--review", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "seed":
        result = seed_references(args.pack_dir, args.candidate_events)
    else:
        result = apply_human_review(args.pack_dir, args.review)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
