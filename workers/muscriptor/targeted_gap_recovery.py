from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import tempfile
from pathlib import Path
from typing import Any

from amt_core.events import NoteEvent, read_jsonl, write_jsonl
from amt_core.midi import export_performance_midi
from amt_core.product_postprocess import (
    automatic_voice_candidate_admission,
    clean_trailing_fragments,
    soft_mask_melody_candidates,
)
from amt_core.project import load_project
from amt_core.utils import atomic_write_json, sha256_file
from workers.muscriptor import gap_probe, run_baseline


class TargetedGapRecoveryError(RuntimeError):
    """Raised when a user-selected gap recovery request is unsafe or incomplete."""


RECOVERY_STAGE_TRACKS = (
    (
        "gap_raw_candidate",
        "补漏 1/3 · 原始生成",
        "raw_generated",
    ),
    (
        "gap_accompaniment_filtered",
        "补漏 2/3 · 伴奏过滤后",
        "accompaniment_filtered",
    ),
    (
        "gap_monophonic_candidate",
        "补漏 3/3 · 单旋律约束后",
        "monophonic_constrained",
    ),
)


def _target_instrument(
    source_canonical: dict[str, Any],
    source_track_id: str,
) -> tuple[dict[str, Any], str]:
    matches = [
        track
        for track in source_canonical.get("tracks", [])
        if isinstance(track, dict) and track.get("track_id") == source_track_id
    ]
    if len(matches) != 1:
        raise TargetedGapRecoveryError("source track is missing or ambiguous")
    track = matches[0]
    instrument = track.get("instrument")
    if not isinstance(instrument, str) or not instrument:
        raise TargetedGapRecoveryError(
            "the selected track has no instrument label for directed recovery"
        )
    return track, instrument.lower()


def plan_selected_gaps(
    project_dir: Path,
    *,
    probe_id: str,
    source_bundle_id: str,
    source_track_id: str,
    intervals: list[tuple[float, float]],
    context_sec: float = 4.0,
    maximum_target_duration_sec: float = 80.0,
    maximum_targets: int = 16,
) -> gap_probe.ProbeSpec:
    project_dir = project_dir.expanduser().resolve()
    probe_id = gap_probe._safe_identifier(probe_id, label="probe_id")
    source_bundle_id = gap_probe._safe_identifier(
        source_bundle_id,
        label="source_bundle_id",
    )
    source_track_id = gap_probe._safe_identifier(
        source_track_id,
        label="source_track_id",
    )
    if not math.isfinite(context_sec) or context_sec < 0:
        raise TargetedGapRecoveryError("context_sec must be finite and non-negative")
    if (
        not math.isfinite(maximum_target_duration_sec)
        or maximum_target_duration_sec <= 0
    ):
        raise TargetedGapRecoveryError(
            "maximum_target_duration_sec must be finite and positive"
        )
    if not intervals:
        raise TargetedGapRecoveryError("at least one gap must be selected")

    project = load_project(project_dir)
    metadata = project.get("canonical_audio", {}).get("metadata")
    if not isinstance(metadata, dict):
        raise TargetedGapRecoveryError("canonical audio metadata is unavailable")
    duration = gap_probe._finite_number(
        metadata.get("duration_sec"),
        label="canonical_audio.metadata.duration_sec",
    )
    if duration <= 0:
        raise TargetedGapRecoveryError("canonical audio duration must be positive")

    ordered = sorted(intervals)
    previous_end = -1.0
    targets: list[gap_probe.TargetInterval] = []
    for interval_index, (start_value, end_value) in enumerate(ordered, start=1):
        start = float(start_value)
        end = float(end_value)
        if (
            not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or end <= start
            or end > duration + 0.02
        ):
            raise TargetedGapRecoveryError(
                f"selected gap {interval_index} is outside the song timeline"
            )
        if start < previous_end:
            raise TargetedGapRecoveryError("selected gaps must not overlap")
        previous_end = end
        boundary_inset = min(0.001, (end - start) / 1000)
        start += boundary_inset
        end -= boundary_inset
        part_count = max(
            1,
            math.ceil((end - start) / maximum_target_duration_sec),
        )
        part_duration = (end - start) / part_count
        for part_index in range(part_count):
            part_start = start + part_index * part_duration
            part_end = (
                end
                if part_index == part_count - 1
                else start + (part_index + 1) * part_duration
            )
            targets.append(
                gap_probe.TargetInterval(
                    target_id=f"gap-{len(targets) + 1:02d}",
                    start_sec=round(part_start, 6),
                    end_sec=round(part_end, 6),
                    expectation="user-selected empty-track recovery candidate",
                )
            )
    if len(targets) > maximum_targets:
        raise TargetedGapRecoveryError(
            f"one recovery job supports at most {maximum_targets} target windows"
        )

    windows = tuple(
        gap_probe.ProbeWindow(
            window_id=f"window-{index:02d}",
            clip_start_sec=round(max(0.0, target.start_sec - context_sec), 6),
            clip_end_sec=round(min(duration, target.end_sec + context_sec), 6),
            targets=(target,),
        )
        for index, target in enumerate(targets, start=1)
    )
    spec = gap_probe.ProbeSpec(
        probe_id=probe_id,
        source_bundle_id=source_bundle_id,
        source_voice_track_id=source_track_id,
        canonical_duration_sec=duration,
        context_sec=context_sec,
        windows=windows,
    )
    _project, _audio, source_path, source_canonical = gap_probe._source_context(
        project_dir,
        spec,
    )
    _target_instrument(source_canonical, source_track_id)
    gap_probe.validate_empty_source_gaps(read_jsonl(source_path), spec)
    return spec


def shift_target_candidates(
    events: list[NoteEvent],
    *,
    probe_id: str,
    window: gap_probe.ProbeWindow,
    source_track_id: str,
    instrument: str,
    main_melody: bool,
) -> list[NoteEvent]:
    shifted: list[NoteEvent] = []
    normalized_instrument = instrument.lower()
    for event in events:
        if (event.instrument or "").lower() != normalized_instrument:
            continue
        original_onset = event.onset_sec + window.clip_start_sec
        original_offset = event.offset_sec + window.clip_start_sec
        matching = [
            target
            for target in window.targets
            if original_offset > target.start_sec
            and original_onset < target.end_sec
        ]
        if not matching:
            continue
        if len(matching) != 1:
            raise TargetedGapRecoveryError(
                f"candidate overlaps multiple targets: {event.event_id}"
            )
        target = matching[0]
        clipped_onset = max(original_onset, target.start_sec)
        clipped_offset = min(original_offset, target.end_sec)
        if clipped_offset <= clipped_onset:
            continue
        extra = dict(event.extra)
        extra["targeted_gap_recovery"] = {
            "probe_id": probe_id,
            "source_track_id": source_track_id,
            "window_id": window.window_id,
            "target_id": target.target_id,
            "clip_start_sec": window.clip_start_sec,
            "clip_onset_sec": event.onset_sec,
            "clip_offset_sec": event.offset_sec,
            "source_event_id": event.event_id,
            "automatic_accuracy_claimed": False,
        }
        shifted.append(
            NoteEvent(
                event_id=f"{probe_id}:{window.window_id}:{event.event_id}",
                track_id=f"targeted-gap:{source_track_id}",
                instrument=instrument,
                onset_sec=clipped_onset,
                offset_sec=clipped_offset,
                pitch_midi=event.pitch_midi,
                quantized_pitch_midi=event.quantized_pitch_midi,
                velocity=event.velocity,
                confidence=event.confidence,
                is_main_melody_candidate=main_melody,
                source_run_id=event.source_run_id,
                source_model=event.source_model,
                source_event_ids=sorted(
                    {*event.source_event_ids, event.event_id}
                ),
                tags=sorted(
                    {
                        *event.tags,
                        "candidate",
                        "targeted-gap-recovery",
                        target.target_id,
                    }
                ),
                extra=extra,
            )
        )
    return shifted


def _coverage_report(
    spec: gap_probe.ProbeSpec,
    candidates: list[NoteEvent],
) -> dict[str, Any]:
    targets = []
    for window in spec.windows:
        target = window.targets[0]
        notes = [
            event
            for event in candidates
            if event.offset_sec > target.start_sec
            and event.onset_sec < target.end_sec
        ]
        targets.append(
            {
                "target_id": target.target_id,
                "start_sec": target.start_sec,
                "end_sec": target.end_sec,
                "duration_sec": round(target.duration_sec, 6),
                "candidate_note_count": len(notes),
                "owner_review_required": True,
            }
        )
    return {
        "schema_version": 1,
        "artifact_type": "amt-targeted-gap-recovery-report",
        "probe_id": spec.probe_id,
        "source_bundle_id": spec.source_bundle_id,
        "source_track_id": spec.source_voice_track_id,
        "candidate_note_count": len(candidates),
        "targets": targets,
        "accuracy_claimed": False,
        "decision": "awaiting_owner_review",
    }


def _copy_track(
    project_dir: Path,
    output_dir: Path,
    tracks_dir: Path,
    track: dict[str, Any],
    *,
    index: int,
) -> tuple[dict[str, Any], list[NoteEvent]]:
    track_id = gap_probe._safe_identifier(
        track.get("track_id"),
        label=f"source track {index}",
    )
    source_path = gap_probe._resolve_inside(
        project_dir,
        track.get("source_events_path"),
    )
    expected_hash = track.get("provenance", {}).get(
        "normalized_artifact_sha256"
    )
    if sha256_file(source_path) != expected_hash:
        raise TargetedGapRecoveryError(
            f"source track hash does not match: {track_id}"
        )
    destination = tracks_dir / f"{track_id}.jsonl"
    shutil.copy2(source_path, destination)
    copied = dict(track)
    copied["source_events_path"] = str(
        (output_dir / "tracks" / destination.name).relative_to(project_dir)
    )
    return copied, read_jsonl(destination)


def build_recovery_bundle(
    project_dir: Path,
    *,
    spec: gap_probe.ProbeSpec,
    source_canonical: dict[str, Any],
    source_events: list[NoteEvent],
    candidates: list[NoteEvent],
    run_manifest_path: Path,
    output_dir: Path,
    product_candidates: list[NoteEvent] | None = None,
    product_admission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    run_manifest_path = run_manifest_path.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().resolve(strict=False)
    if output_dir.exists() or output_dir.is_symlink():
        raise TargetedGapRecoveryError(
            f"recovery bundle already exists: {output_dir}"
        )
    source_tracks = source_canonical.get("tracks")
    if not isinstance(source_tracks, list) or not source_tracks:
        raise TargetedGapRecoveryError("source bundle has no tracks")
    source_track, instrument = _target_instrument(
        source_canonical,
        spec.source_voice_track_id,
    )
    project = load_project(project_dir)
    canonical = project["canonical_audio"]
    metadata = canonical.get("metadata")
    timeline_end = (
        float(metadata["duration_sec"])
        if isinstance(metadata, dict)
        and isinstance(metadata.get("duration_sec"), (int, float))
        and not isinstance(metadata.get("duration_sec"), bool)
        and float(metadata["duration_sec"]) > 0
        else None
    )
    tempo, meter = gap_probe._rhythm_points(source_canonical)
    admitted_candidates = (
        candidates if product_candidates is None else product_candidates
    )
    merged = [*source_events, *admitted_candidates]
    merged.sort(
        key=lambda event: (
            event.onset_sec,
            event.offset_sec,
            event.pitch_midi,
            event.event_id,
        )
    )
    if len({event.event_id for event in merged}) != len(merged):
        raise TargetedGapRecoveryError("recovered track has duplicate event IDs")

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.",
        dir=output_dir.parent,
    ) as temporary_name:
        temporary = Path(temporary_name)
        tracks_dir = temporary / "tracks"
        tracks_dir.mkdir()
        raw_tracks_dir = temporary / "raw_tracks"
        cleanup_records: list[dict[str, Any]] = []
        records: list[dict[str, Any]] = []
        midi_tracks: dict[str, list[NoteEvent]] = {}
        parent_hash = sha256_file(run_manifest_path)
        for index, track in enumerate(source_tracks, start=1):
            if not isinstance(track, dict):
                raise TargetedGapRecoveryError("source track record is malformed")
            track_id = track.get("track_id")
            if track_id == spec.source_voice_track_id:
                destination = tracks_dir / f"{track_id}.jsonl"
                write_jsonl(destination, merged)
                record = dict(track)
                record["label"] = f"{track.get('label', track_id)} · 所选空缺重算"
                record["event_count"] = len(merged)
                record["source_events_path"] = str(
                    (output_dir / "tracks" / destination.name).relative_to(
                        project_dir
                    )
                )
                candidate_model = (
                    admitted_candidates[0].source_model
                    if admitted_candidates
                    else "no-candidate"
                )
                record["provenance"] = {
                    "source_run_id": spec.probe_id,
                    "source_model": (
                        f"deterministic:{track_id}+targeted-gap:"
                        f"{candidate_model}"
                    ),
                    "run_manifest_sha256": parent_hash,
                    "normalized_artifact_sha256": sha256_file(destination),
                }
                events = merged
            else:
                record, events = _copy_track(
                    project_dir,
                    output_dir,
                    tracks_dir,
                    track,
                    index=index,
                )
                destination = tracks_dir / f"{track_id}.jsonl"
            cleanup = {
                "decision": "not_applicable",
                "group_count": 0,
                "fragment_count": 0,
                "merged_note_count": 0,
                "source_overwritten": False,
            }
            record_instrument = str(record.get("instrument") or "").lower()
            if timeline_end is not None and record_instrument != "voice":
                cleaned_events, cleanup = clean_trailing_fragments(
                    events,
                    timeline_end=timeline_end,
                    run_id=spec.probe_id,
                )
                if cleanup["group_count"]:
                    raw_tracks_dir.mkdir(exist_ok=True)
                    raw_copy = raw_tracks_dir / f"{track_id}.jsonl"
                    shutil.copy2(destination, raw_copy)
                    write_jsonl(destination, cleaned_events)
                    record["source_provenance"] = record.get("provenance")
                    record["event_count"] = len(cleaned_events)
                    record["provenance"] = {
                        "source_run_id": spec.probe_id,
                        "source_model": "deterministic:trailing-sustain-cleanup",
                        "run_manifest_sha256": parent_hash,
                        "normalized_artifact_sha256": sha256_file(destination),
                    }
                    cleanup["raw_source_path"] = str(
                        (output_dir / "raw_tracks" / raw_copy.name).relative_to(
                            project_dir
                        )
                    )
                    cleanup["raw_source_sha256"] = sha256_file(raw_copy)
                    events = cleaned_events
            cleanup_records.append(
                {
                    "track_id": track_id,
                    "instrument": record.get("instrument"),
                    **cleanup,
                }
            )
            records.append(record)
            if record.get("role") != "diagnostic_candidate":
                midi_tracks[str(track_id)] = events

        if candidates and not admitted_candidates:
            existing_track_ids = {
                str(record.get("track_id")) for record in records
            }
            diagnostic_track_id = "target_gap_candidate"
            suffix = 2
            while diagnostic_track_id in existing_track_ids:
                diagnostic_track_id = f"target_gap_candidate_{suffix}"
                suffix += 1
            diagnostic_path = tracks_dir / f"{diagnostic_track_id}.jsonl"
            write_jsonl(diagnostic_path, candidates)
            records.append(
                {
                    "track_id": diagnostic_track_id,
                    "label": "补漏候选（未自动合入）",
                    "role": "diagnostic_candidate",
                    "instrument": instrument,
                    "event_count": len(candidates),
                    "source_events_path": str(
                        (
                            output_dir
                            / "tracks"
                            / diagnostic_path.name
                        ).relative_to(project_dir)
                    ),
                    "provenance": {
                        "source_run_id": spec.probe_id,
                        "source_model": candidates[0].source_model,
                        "run_manifest_sha256": parent_hash,
                        "normalized_artifact_sha256": sha256_file(
                            diagnostic_path
                        ),
                    },
                }
            )

        melodic_count = sum(track_id != "drums" for track_id in midi_tracks)
        if melodic_count <= 15:
            midi_report = export_performance_midi(
                temporary / "performance.mid",
                midi_tracks,
                tempo,
                meter,
            )
            performance_path: str | None = "performance.mid"
        else:
            midi_report = {
                "status": "unavailable",
                "reason": "more than 15 melodic tracks require multiple MIDI ports",
                "track_count": len(midi_tracks),
                "note_count": sum(len(events) for events in midi_tracks.values()),
            }
            performance_path = None

        claims = dict(source_canonical.get("claims", {}))
        claims.update(
            {
                "targeted_gap_recovery_performed": True,
                "targeted_source_bundle_id": spec.source_bundle_id,
                "targeted_source_track_id": spec.source_voice_track_id,
                "selected_gap_count": len(spec.windows),
                "recovered_candidate_note_count": len(candidates),
                "merged_recovered_candidate_note_count": len(
                    admitted_candidates
                ),
                "automatic_merge_performed": bool(admitted_candidates),
                "automatic_candidate_admission": (
                    product_admission["decision"]
                    if product_admission is not None
                    else "not_recorded"
                ),
                "accuracy_claimed": False,
                "source_bundle_overwritten": False,
                "accompaniment_soft_mask_performed": instrument == "voice",
                "accompaniment_soft_mask_used_for_product": False,
                "automatic_candidate_selection": "raw_generated",
                "automatic_trailing_sustain_cleanup_performed": any(
                    record["group_count"] for record in cleanup_records
                ),
                "automatic_trailing_sustain_cleanup_source_overwritten": False,
            }
        )
        canonical_project = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-project",
            "project_id": project["project_id"],
            "timeline_basis": "original_canonical_mix_seconds",
            "canonical_audio": canonical,
            "worker_results": source_canonical.get("worker_results", []),
            "tracks": records,
            "main_melody_track_id": source_canonical.get(
                "main_melody_track_id"
            ),
            "rhythm": source_canonical["rhythm"],
            "exports": {
                "performance_midi": {
                    "path": performance_path,
                    "representation": "performance",
                    "report": midi_report,
                }
            },
            "claims": claims,
        }
        reports_dir = temporary / "reports"
        reports_dir.mkdir()
        atomic_write_json(
            reports_dir / "trailing_sustain_cleanup.json",
            {
                "schema_version": 1,
                "artifact_type": "amt-trailing-sustain-cleanup-report",
                "timeline_end_sec": timeline_end,
                "tracks": cleanup_records,
                "accuracy_claimed": False,
                "source_overwritten": False,
            },
        )
        atomic_write_json(temporary / "canonical_project.json", canonical_project)
        outputs = [
            {
                "path": str(path.relative_to(temporary)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(temporary.rglob("*"))
            if path.is_file()
        ]
        bundle_manifest = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-bundle",
            "status": "succeeded",
            "project_id": project["project_id"],
            "canonical_audio_sha256": canonical["sha256"],
            "bundle_id": output_dir.name,
            "tracks": [record["track_id"] for record in records],
            "outputs": outputs,
            "claims": claims,
            "limitations": [
                (
                    f"Only user-selected empty spans of {spec.source_voice_track_id} "
                    "were rerun; the source bundle remains unchanged."
                ),
                (
                    f"Recovered {instrument} notes are same-model candidates and "
                    "require listening review."
                ),
                "An empty selected span may be intentional silence.",
                "Selected voice gaps use the owner-selected raw voice-constrained candidates.",
                "No song-length-blind candidate-count limit is applied to selected empty windows.",
                "Accompaniment-filtered and monophonic views remain diagnostic alternatives.",
                "Automatic sustain cleanup is conservative and excludes percussion from sustain merging.",
                "No accuracy claim or owner approval is inferred.",
            ],
        }
        atomic_write_json(temporary / "bundle_manifest.json", bundle_manifest)
        temporary.replace(output_dir)
    return bundle_manifest


def reconstruct_recovery_stages(
    raw_candidates: list[NoteEvent],
    constrained_candidates: list[NoteEvent],
    mask_report: dict[str, Any],
) -> tuple[list[NoteEvent], list[NoteEvent], list[NoteEvent]]:
    """Reconstruct the three saved candidate stages without rerunning a model."""

    raw_ids = [event.event_id for event in raw_candidates]
    constrained_ids = [event.event_id for event in constrained_candidates]
    if len(set(raw_ids)) != len(raw_ids):
        raise TargetedGapRecoveryError("raw recovery candidates contain duplicate IDs")
    if len(set(constrained_ids)) != len(constrained_ids):
        raise TargetedGapRecoveryError(
            "constrained recovery candidates contain duplicate IDs"
        )
    shadowed_value = mask_report.get("shadowed_event_ids")
    if not isinstance(shadowed_value, list) or not all(
        isinstance(event_id, str) and event_id for event_id in shadowed_value
    ):
        raise TargetedGapRecoveryError(
            "recovery report has no valid accompaniment shadow IDs"
        )
    shadowed_ids = set(shadowed_value)
    raw_id_set = set(raw_ids)
    if not shadowed_ids.issubset(raw_id_set):
        raise TargetedGapRecoveryError(
            "recovery report references unknown accompaniment shadow IDs"
        )
    accompaniment_filtered = [
        event for event in raw_candidates if event.event_id not in shadowed_ids
    ]
    accompaniment_ids = {event.event_id for event in accompaniment_filtered}
    if not set(constrained_ids).issubset(accompaniment_ids):
        raise TargetedGapRecoveryError(
            "monophonic candidates are not a subset of accompaniment-filtered candidates"
        )

    expected = {
        "raw": mask_report.get("raw_candidate_count"),
        "shadowed": mask_report.get("accompaniment_shadow_count"),
        "monophonic_rejected": mask_report.get("monophonic_rejection_count"),
        "constrained": mask_report.get("filtered_candidate_count"),
    }
    actual = {
        "raw": len(raw_candidates),
        "shadowed": len(shadowed_ids),
        "monophonic_rejected": (
            len(accompaniment_filtered) - len(constrained_candidates)
        ),
        "constrained": len(constrained_candidates),
    }
    if expected != actual:
        raise TargetedGapRecoveryError(
            f"saved recovery stage counts do not match the report: {actual!r}"
        )
    return (
        list(raw_candidates),
        accompaniment_filtered,
        list(constrained_candidates),
    )


def _diagnostic_stage_event(
    event: NoteEvent,
    *,
    recovery_run_id: str,
    track_id: str,
    stage: str,
) -> NoteEvent:
    extra = dict(event.extra)
    extra["gap_recovery_stage_comparison"] = {
        "stage": stage,
        "source_event_id": event.event_id,
        "source_run_id": event.source_run_id,
        "source_model": event.source_model,
        "diagnostic_only": True,
        "accuracy_claimed": False,
    }
    return NoteEvent(
        event_id=f"{track_id}:{event.event_id}",
        track_id=track_id,
        instrument=event.instrument,
        onset_sec=event.onset_sec,
        offset_sec=event.offset_sec,
        pitch_midi=event.pitch_midi,
        quantized_pitch_midi=event.quantized_pitch_midi,
        velocity=event.velocity,
        confidence=event.confidence,
        is_main_melody_candidate=event.is_main_melody_candidate,
        source_run_id=recovery_run_id,
        source_model=f"deterministic:gap-recovery-stage:{stage}",
        source_event_ids=sorted({*event.source_event_ids, event.event_id}),
        tags=sorted(
            {
                *event.tags,
                "diagnostic-only",
                "gap-recovery-stage-comparison",
                stage,
            }
        ),
        extra=extra,
    )


def _comparison_output_records(root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": str(path.relative_to(root)),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name != "bundle_manifest.json"
    ]


def build_recovery_stage_comparison_bundle(
    project_dir: Path,
    *,
    recovery_run_id: str,
    output_bundle_id: str,
) -> dict[str, Any]:
    """Materialize three independently playable stages from a completed run."""

    project_dir = project_dir.expanduser().resolve()
    recovery_run_id = gap_probe._safe_identifier(
        recovery_run_id,
        label="recovery_run_id",
    )
    output_bundle_id = gap_probe._safe_identifier(
        output_bundle_id,
        label="output_bundle_id",
    )
    run_dir = project_dir / "runs" / recovery_run_id
    run_manifest_path = run_dir / "run_manifest.json"
    request_path = run_dir / "request.json"
    report_path = run_dir / "normalized" / "recovery_report.json"
    raw_path = run_dir / "normalized" / "target_gap_candidates.raw.jsonl"
    filtered_path = (
        run_dir / "normalized" / "target_gap_candidates.filtered.jsonl"
    )
    constrained_path = (
        filtered_path
        if filtered_path.is_file()
        else run_dir / "normalized" / "target_gap_candidates.jsonl"
    )
    for required in (
        run_manifest_path,
        request_path,
        report_path,
        raw_path,
        constrained_path,
    ):
        if not required.is_file():
            raise TargetedGapRecoveryError(
                f"completed recovery artifact is missing: {required.name}"
            )

    run_manifest = gap_probe._load_object(run_manifest_path)
    if (
        run_manifest.get("status") != "succeeded"
        or run_manifest.get("probe_id") != recovery_run_id
    ):
        raise TargetedGapRecoveryError("recovery run is not a matching success")
    request = gap_probe._load_object(request_path)
    config_path = gap_probe._resolve_inside(
        project_dir,
        request.get("config_path"),
    )
    if sha256_file(config_path) != request.get("config_sha256"):
        raise TargetedGapRecoveryError("recovery request config hash does not match")
    spec = gap_probe.load_spec(config_path)
    if spec.probe_id != recovery_run_id:
        raise TargetedGapRecoveryError("recovery request belongs to another run")
    project, canonical_audio, _source_path, source_canonical = (
        gap_probe._source_context(project_dir, spec)
    )
    if sha256_file(canonical_audio) != request.get("canonical_audio_sha256"):
        raise TargetedGapRecoveryError("recovery run belongs to another audio file")
    source_track, instrument = _target_instrument(
        source_canonical,
        spec.source_voice_track_id,
    )
    if instrument != "voice":
        raise TargetedGapRecoveryError(
            "three-stage melody comparison requires a voice recovery run"
        )

    report = gap_probe._load_object(report_path)
    mask_report = report.get("accompaniment_soft_mask")
    if not isinstance(mask_report, dict):
        raise TargetedGapRecoveryError(
            "recovery report has no accompaniment soft-mask evidence"
        )
    raw, accompaniment_filtered, constrained = reconstruct_recovery_stages(
        read_jsonl(raw_path),
        read_jsonl(constrained_path),
        mask_report,
    )
    stage_sources = (raw, accompaniment_filtered, constrained)
    output_dir = project_dir / "exports" / output_bundle_id
    if output_dir.exists() or output_dir.is_symlink():
        raise TargetedGapRecoveryError(
            f"comparison bundle already exists: {output_dir}"
        )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    tempo, meter = gap_probe._rhythm_points(source_canonical)
    parent_hash = sha256_file(run_manifest_path)

    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.",
        dir=output_dir.parent,
    ) as temporary_name:
        temporary = Path(temporary_name)
        tracks_dir = temporary / "tracks"
        tracks_dir.mkdir()
        track_records: list[dict[str, Any]] = []
        stage_reports: dict[str, Any] = {}
        for (track_id, label, stage), source_events in zip(
            RECOVERY_STAGE_TRACKS,
            stage_sources,
            strict=True,
        ):
            events = [
                _diagnostic_stage_event(
                    event,
                    recovery_run_id=recovery_run_id,
                    track_id=track_id,
                    stage=stage,
                )
                for event in source_events
            ]
            track_path = tracks_dir / f"{track_id}.jsonl"
            write_jsonl(track_path, events)
            midi_path = temporary / f"{track_id}.mid"
            midi_report = export_performance_midi(
                midi_path,
                {track_id: events},
                tempo,
                meter,
            )
            stage_reports[track_id] = {
                "stage": stage,
                "event_count": len(events),
                "midi_path": midi_path.name,
                "midi_report": midi_report,
            }
            track_records.append(
                {
                    "track_id": track_id,
                    "label": f"{label}（{len(events)}）",
                    "role": "diagnostic_candidate",
                    "instrument": source_track.get("instrument"),
                    "event_count": len(events),
                    "source_events_path": str(
                        (
                            output_dir / "tracks" / track_path.name
                        ).relative_to(project_dir)
                    ),
                    "provenance": {
                        "source_run_id": recovery_run_id,
                        "source_model": (
                            f"deterministic:gap-recovery-stage:{stage}"
                        ),
                        "run_manifest_sha256": parent_hash,
                        "normalized_artifact_sha256": sha256_file(track_path),
                    },
                }
            )

        comparison_report = {
            "schema_version": 1,
            "artifact_type": "amt-gap-recovery-stage-comparison",
            "project_id": project["project_id"],
            "source_bundle_id": spec.source_bundle_id,
            "source_track_id": spec.source_voice_track_id,
            "source_recovery_run_id": recovery_run_id,
            "raw_candidate_count": len(raw),
            "accompaniment_shadow_count": len(raw) - len(accompaniment_filtered),
            "accompaniment_filtered_count": len(accompaniment_filtered),
            "monophonic_rejection_count": (
                len(accompaniment_filtered) - len(constrained)
            ),
            "monophonic_constrained_count": len(constrained),
            "tracks": stage_reports,
            "model_rerun": False,
            "diagnostic_only": True,
            "accuracy_claimed": False,
            "source_overwritten": False,
        }
        reports_dir = temporary / "reports"
        reports_dir.mkdir()
        atomic_write_json(
            reports_dir / "stage_comparison.json",
            comparison_report,
        )
        claims = {
            "diagnostic_gap_recovery_stage_comparison": True,
            "targeted_source_bundle_id": spec.source_bundle_id,
            "targeted_source_track_id": spec.source_voice_track_id,
            "source_recovery_run_id": recovery_run_id,
            "automatic_candidate_admission": "rejected_excessive_voice_growth",
            "model_rerun": False,
            "accuracy_claimed": False,
            "source_bundle_overwritten": False,
        }
        canonical_project = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-project",
            "project_id": project["project_id"],
            "timeline_basis": "original_canonical_mix_seconds",
            "canonical_audio": source_canonical["canonical_audio"],
            "worker_results": source_canonical.get("worker_results", []),
            "tracks": track_records,
            "main_melody_track_id": "gap_monophonic_candidate",
            "rhythm": source_canonical["rhythm"],
            "exports": {
                "diagnostic_stage_midi": stage_reports,
            },
            "claims": claims,
        }
        atomic_write_json(temporary / "canonical_project.json", canonical_project)
        bundle_manifest = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-bundle",
            "status": "succeeded",
            "project_id": project["project_id"],
            "canonical_audio_sha256": project["canonical_audio"]["sha256"],
            "bundle_id": output_bundle_id,
            "tracks": [record["track_id"] for record in track_records],
            "outputs": _comparison_output_records(temporary),
            "claims": claims,
            "limitations": [
                "This bundle compares three deterministic views of one completed recovery run.",
                "No model was rerun and the source or product melody was not overwritten.",
                "The three tracks are diagnostic alternatives and must not be stacked as an arrangement.",
                "No transcription accuracy or owner preference is inferred.",
            ],
        }
        atomic_write_json(temporary / "bundle_manifest.json", bundle_manifest)
        temporary.replace(output_dir)
    return bundle_manifest


def run_selected_recovery(
    project_dir: Path,
    config_path: Path,
    *,
    output_bundle_id: str,
    worker_env: Path,
    weight_provenance: Path,
    ffmpeg: str,
    device: str = "cuda",
    require_slurm: bool = True,
    execution_backend: str = "slurm",
) -> dict[str, Any]:
    if require_slurm and not os.environ.get("SLURM_JOB_ID"):
        raise TargetedGapRecoveryError(
            "targeted gap recovery requires an active Slurm allocation"
        )
    hostname = platform.node()
    if require_slurm and "login" in hostname:
        raise TargetedGapRecoveryError(
            "refusing targeted recovery on a login node"
        )
    if device not in {"cuda", "mps", "cpu", "auto"}:
        raise TargetedGapRecoveryError("unsupported MuScriptor device")
    if execution_backend not in {"slurm", "local"}:
        raise TargetedGapRecoveryError("unsupported execution backend")
    if require_slurm != (execution_backend == "slurm"):
        raise TargetedGapRecoveryError(
            "execution backend does not match the Slurm requirement"
        )

    project_dir = project_dir.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    output_bundle_id = gap_probe._safe_identifier(
        output_bundle_id,
        label="output_bundle_id",
    )
    spec = gap_probe.load_spec(config_path)
    project, canonical_audio, source_path, source_canonical = (
        gap_probe._source_context(project_dir, spec)
    )
    source_track, instrument = _target_instrument(
        source_canonical,
        spec.source_voice_track_id,
    )
    main_melody = (
        source_canonical.get("main_melody_track_id")
        == spec.source_voice_track_id
        or instrument == "voice"
    )
    accompaniment_events = (
        gap_probe.load_accompaniment_events(
            project_dir,
            source_canonical,
            source_track_id=spec.source_voice_track_id,
        )
        if main_melody
        else []
    )
    source_events = read_jsonl(source_path)
    gap_probe.validate_empty_source_gaps(source_events, spec)
    run_dir = project_dir / "runs" / spec.probe_id
    output_dir = project_dir / "exports" / output_bundle_id
    if run_dir.exists() or run_dir.is_symlink():
        raise TargetedGapRecoveryError(f"recovery run already exists: {run_dir}")
    if output_dir.exists() or output_dir.is_symlink():
        raise TargetedGapRecoveryError(
            f"recovery bundle already exists: {output_dir}"
        )
    clips_dir = run_dir / "clips"
    normalized_dir = run_dir / "normalized"
    logs_dir = run_dir / "logs"
    for directory in (clips_dir, normalized_dir, logs_dir):
        directory.mkdir(parents=True)

    request = {
        "schema_version": 1,
        "artifact_type": "amt-targeted-gap-recovery-request",
        "probe_id": spec.probe_id,
        "project_id": project["project_id"],
        "source_bundle_id": spec.source_bundle_id,
        "source_track_id": spec.source_voice_track_id,
        "source_instrument": instrument,
        "instrument_allowlist": [instrument],
        "accompaniment_soft_mask": main_melody,
        "residual_fallback_max_passes": 0,
        "config_path": gap_probe._relative(config_path, project_dir),
        "config_sha256": sha256_file(config_path),
        "canonical_audio_sha256": sha256_file(canonical_audio),
        "selected_gap_count": len(spec.windows),
        "device": device,
        "execution_backend": execution_backend,
        "source_bundle_overwritten": False,
    }
    atomic_write_json(run_dir / "request.json", request)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "amt-targeted-gap-recovery-run",
        "probe_id": spec.probe_id,
        "project_id": project["project_id"],
        "status": "running",
        "started_at": gap_probe._utc_now(),
        "ended_at": None,
        "hostname": hostname,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "execution_backend": execution_backend,
        "request_sha256": sha256_file(run_dir / "request.json"),
        "child_runs": [],
        "outputs": [],
        "error": None,
    }
    atomic_write_json(run_dir / "run_manifest.json", manifest)
    raw_candidates: list[NoteEvent] = []
    candidates: list[NoteEvent] = []
    try:
        for window in spec.windows:
            clip_path = clips_dir / f"{window.window_id}.flac"
            command = gap_probe._clip_audio(
                canonical_audio,
                clip_path,
                start_sec=window.clip_start_sec,
                end_sec=window.clip_end_sec,
                ffmpeg=ffmpeg,
            )
            atomic_write_json(
                logs_dir / f"{window.window_id}-clip.json",
                {
                    "argv": command,
                    "sha256": sha256_file(clip_path),
                    "clip_start_sec": window.clip_start_sec,
                    "clip_end_sec": window.clip_end_sec,
                },
            )
            child_run_id = f"{spec.probe_id}-{window.window_id}"
            exit_code = run_baseline.main(
                gap_probe._directed_child_arguments(
                    project_dir=project_dir,
                    clip_path=clip_path,
                    worker_env=worker_env,
                    weight_provenance=weight_provenance,
                    child_run_id=child_run_id,
                    device=device,
                    instrument=instrument,
                )
            )
            child_dir = project_dir / "runs" / child_run_id
            child_manifest = child_dir / "run_manifest.json"
            if exit_code != 0 or not child_manifest.is_file():
                raise TargetedGapRecoveryError(
                    f"MuScriptor child run failed: {child_run_id}"
                )
            child_value = gap_probe._load_object(child_manifest)
            if child_value.get("status") != "succeeded":
                raise TargetedGapRecoveryError(
                    f"MuScriptor child run did not succeed: {child_run_id}"
                )
            child_events = read_jsonl(
                child_dir / "normalized" / "events.jsonl"
            )
            window_candidates = shift_target_candidates(
                child_events,
                probe_id=spec.probe_id,
                window=window,
                source_track_id=spec.source_voice_track_id,
                instrument=instrument,
                main_melody=(
                    source_canonical.get("main_melody_track_id")
                    == spec.source_voice_track_id
                    or source_track.get("instrument") == "voice"
                ),
            )
            raw_candidates.extend(window_candidates)
            manifest["child_runs"].append(
                {
                    "window_id": window.window_id,
                    "run_id": child_run_id,
                    "run_manifest_path": gap_probe._relative(
                        child_manifest,
                        project_dir,
                    ),
                    "run_manifest_sha256": sha256_file(child_manifest),
                    "clip_sha256": sha256_file(clip_path),
                    "all_event_count": len(child_events),
                    "target_candidate_count": len(window_candidates),
                }
            )
        raw_candidates.sort(
            key=lambda event: (
                event.onset_sec,
                event.pitch_midi,
                event.event_id,
            )
        )
        write_jsonl(
            normalized_dir / "target_gap_candidates.raw.jsonl",
            raw_candidates,
        )
        fallback_candidates: list[NoteEvent] = []
        mask_report: dict[str, Any] | None = None
        filtered_candidates: list[NoteEvent] = []
        if main_melody:
            filtered_candidates, mask_report = soft_mask_melody_candidates(
                raw_candidates,
                accompaniment_events,
                probe_id=spec.probe_id,
            )
        write_jsonl(
            normalized_dir / "target_gap_fallback.raw.jsonl",
            fallback_candidates,
        )
        filtered_candidates.sort(
            key=lambda event: (
                event.onset_sec,
                event.pitch_midi,
                event.event_id,
            )
        )
        write_jsonl(
            normalized_dir / "target_gap_candidates.filtered.jsonl",
            filtered_candidates,
        )
        candidates = list(raw_candidates)
        write_jsonl(normalized_dir / "target_gap_candidates.jsonl", candidates)
        report = _coverage_report(spec, candidates)
        product_admission = (
            automatic_voice_candidate_admission(
                source_note_count=len(source_events),
                candidate_note_count=len(candidates),
            )
            if main_melody
            else {
                "decision": "not_applicable_to_accompaniment",
                "accepted_for_automatic_merge": True,
                "candidate_preserved_for_diagnosis": True,
                "accuracy_claimed": False,
            }
        )
        report["raw_directed_candidate_note_count"] = len(raw_candidates)
        report["raw_fallback_candidate_note_count"] = len(fallback_candidates)
        report["residual_fallback_window_count"] = 0
        report["residual_fallback_max_passes"] = 0
        report["accompaniment_soft_mask"] = mask_report
        report["product_candidate_selection"] = "raw_generated"
        report["diagnostic_filtered_candidate_note_count"] = len(
            filtered_candidates
        )
        report["product_admission"] = product_admission
        atomic_write_json(
            normalized_dir / "recovery_report.json",
            report,
        )
        manifest["status"] = "succeeded"
    except (
        TargetedGapRecoveryError,
        gap_probe.GapProbeError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        manifest["status"] = "failed"
        manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        manifest["ended_at"] = gap_probe._utc_now()
        manifest["outputs"] = gap_probe._artifact_records(run_dir)
        atomic_write_json(run_dir / "run_manifest.json", manifest)
    if manifest["status"] != "succeeded":
        return manifest
    try:
        build_recovery_bundle(
            project_dir,
            spec=spec,
            source_canonical=source_canonical,
            source_events=source_events,
            candidates=candidates,
            product_candidates=(
                candidates
                if product_admission["accepted_for_automatic_merge"]
                else []
            ),
            product_admission=product_admission,
            run_manifest_path=run_dir / "run_manifest.json",
            output_dir=output_dir,
        )
    except (
        TargetedGapRecoveryError,
        gap_probe.GapProbeError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        manifest["status"] = "failed"
        manifest["ended_at"] = gap_probe._utc_now()
        manifest["error"] = {
            "type": type(exc).__name__,
            "message": f"recovery bundle failed: {exc}",
        }
        atomic_write_json(run_dir / "run_manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Rerun MuScriptor over user-selected empty spans of one track."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-bundle", required=True)
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--weight-provenance", type=Path, required=True)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--allow-local", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = run_selected_recovery(
            args.project,
            args.config,
            output_bundle_id=args.output_bundle,
            worker_env=args.worker_env,
            weight_provenance=args.weight_provenance,
            ffmpeg=args.ffmpeg,
            device=args.device,
            require_slurm=not args.allow_local,
            execution_backend="local" if args.allow_local else "slurm",
        )
    except (
        TargetedGapRecoveryError,
        gap_probe.GapProbeError,
        OSError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0 if manifest.get("status") == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
