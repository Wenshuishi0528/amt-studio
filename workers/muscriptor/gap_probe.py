from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.canonical import MeterPoint, TempoPoint
from amt_core.events import NoteEvent, read_jsonl, write_jsonl
from amt_core.midi import export_performance_midi
from amt_core.product_postprocess import (
    automatic_voice_candidate_admission,
    clean_trailing_fragments,
    residual_melody_gaps,
    soft_mask_melody_candidates,
)
from amt_core.project import load_project
from amt_core.utils import atomic_write_json, sha256_file
try:
    from workers.muscriptor import run_baseline
except ModuleNotFoundError:
    import run_baseline


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", re.ASCII)


class GapProbeError(RuntimeError):
    """Raised when a directed MuScriptor gap probe is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class TargetInterval:
    target_id: str
    start_sec: float
    end_sec: float
    expectation: str

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


@dataclass(frozen=True, slots=True)
class ProbeWindow:
    window_id: str
    clip_start_sec: float
    clip_end_sec: float
    targets: tuple[TargetInterval, ...]


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    probe_id: str
    source_bundle_id: str
    source_voice_track_id: str
    canonical_duration_sec: float
    context_sec: float
    windows: tuple[ProbeWindow, ...]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GapProbeError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GapProbeError(f"expected JSON object: {path}")
    return value


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GapProbeError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise GapProbeError(f"{label} must be finite")
    return result


def _safe_identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None or ".." in value:
        raise GapProbeError(f"{label} is not a safe identifier")
    return value


def load_spec(path: Path) -> ProbeSpec:
    value = _load_object(path)
    if value.get("schema_version") != 1:
        raise GapProbeError("unsupported gap probe schema_version")
    probe_id = _safe_identifier(value.get("probe_id"), label="probe_id")
    source_bundle_id = _safe_identifier(
        value.get("source_bundle_id"),
        label="source_bundle_id",
    )
    source_voice_track_id = _safe_identifier(
        value.get("source_voice_track_id"),
        label="source_voice_track_id",
    )
    duration = _finite_number(
        value.get("canonical_duration_sec"),
        label="canonical_duration_sec",
    )
    context = _finite_number(value.get("context_sec"), label="context_sec")
    if duration <= 0 or context < 0:
        raise GapProbeError("duration must be positive and context must be non-negative")
    raw_windows = value.get("windows")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise GapProbeError("windows must be a non-empty list")

    windows: list[ProbeWindow] = []
    target_ids: set[str] = set()
    window_ids: set[str] = set()
    all_targets: list[TargetInterval] = []
    for index, raw_window in enumerate(raw_windows):
        if not isinstance(raw_window, dict):
            raise GapProbeError(f"windows[{index}] must be an object")
        window_id = _safe_identifier(
            raw_window.get("window_id"),
            label=f"windows[{index}].window_id",
        )
        if window_id in window_ids:
            raise GapProbeError(f"duplicate window_id: {window_id}")
        window_ids.add(window_id)
        clip_start = _finite_number(
            raw_window.get("clip_start_sec"),
            label=f"{window_id}.clip_start_sec",
        )
        clip_end = _finite_number(
            raw_window.get("clip_end_sec"),
            label=f"{window_id}.clip_end_sec",
        )
        if clip_start < 0 or clip_end <= clip_start or clip_end > duration + 0.02:
            raise GapProbeError(f"invalid clip interval for {window_id}")
        raw_targets = raw_window.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise GapProbeError(f"{window_id} must contain at least one target")
        targets: list[TargetInterval] = []
        for target_index, raw_target in enumerate(raw_targets):
            if not isinstance(raw_target, dict):
                raise GapProbeError(f"{window_id}.targets[{target_index}] must be an object")
            target_id = _safe_identifier(
                raw_target.get("target_id"),
                label=f"{window_id}.targets[{target_index}].target_id",
            )
            if target_id in target_ids:
                raise GapProbeError(f"duplicate target_id: {target_id}")
            target_ids.add(target_id)
            start = _finite_number(
                raw_target.get("start_sec"),
                label=f"{target_id}.start_sec",
            )
            end = _finite_number(
                raw_target.get("end_sec"),
                label=f"{target_id}.end_sec",
            )
            expectation = raw_target.get("expectation")
            if not isinstance(expectation, str) or not expectation.strip():
                raise GapProbeError(f"{target_id}.expectation must be non-empty")
            if start < clip_start or end > clip_end or end <= start:
                raise GapProbeError(f"target {target_id} is outside its clip")
            target = TargetInterval(target_id, start, end, expectation.strip())
            targets.append(target)
            all_targets.append(target)
        windows.append(ProbeWindow(window_id, clip_start, clip_end, tuple(targets)))

    ordered_targets = sorted(all_targets, key=lambda item: (item.start_sec, item.end_sec))
    for previous, current in zip(ordered_targets, ordered_targets[1:], strict=False):
        if current.start_sec < previous.end_sec:
            raise GapProbeError(
                f"target intervals overlap: {previous.target_id} and {current.target_id}"
            )
    return ProbeSpec(
        probe_id=probe_id,
        source_bundle_id=source_bundle_id,
        source_voice_track_id=source_voice_track_id,
        canonical_duration_sec=duration,
        context_sec=context,
        windows=tuple(windows),
    )


def spec_as_dict(spec: ProbeSpec) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "probe_id": spec.probe_id,
        "source_bundle_id": spec.source_bundle_id,
        "source_voice_track_id": spec.source_voice_track_id,
        "canonical_duration_sec": spec.canonical_duration_sec,
        "context_sec": spec.context_sec,
        "windows": [
            {
                "window_id": window.window_id,
                "clip_start_sec": window.clip_start_sec,
                "clip_end_sec": window.clip_end_sec,
                "targets": [
                    {
                        "target_id": target.target_id,
                        "start_sec": target.start_sec,
                        "end_sec": target.end_sec,
                        "expectation": target.expectation,
                    }
                    for target in window.targets
                ],
            }
            for window in spec.windows
        ],
    }


def _resolve_inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise GapProbeError("artifact path must be non-empty")
    try:
        resolved = (root / relative).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise GapProbeError(f"artifact escapes the project: {relative}") from exc
    if not resolved.is_file():
        raise GapProbeError(f"artifact is not a file: {relative}")
    return resolved


def _source_context(
    project_dir: Path,
    spec: ProbeSpec,
) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    project = load_project(project_dir)
    canonical_record = project.get("canonical_audio")
    if not isinstance(canonical_record, dict):
        raise GapProbeError("project has no canonical audio record")
    canonical_audio = _resolve_inside(project_dir, canonical_record.get("path"))
    if sha256_file(canonical_audio) != canonical_record.get("sha256"):
        raise GapProbeError("canonical audio hash does not match project manifest")
    bundle_dir = project_dir / "exports" / spec.source_bundle_id
    canonical_project_path = _resolve_inside(bundle_dir, "canonical_project.json")
    canonical_project = _load_object(canonical_project_path)
    if (
        canonical_project.get("project_id") != project.get("project_id")
        or canonical_project.get("canonical_audio", {}).get("sha256")
        != canonical_record.get("sha256")
    ):
        raise GapProbeError("source bundle does not match the project or canonical audio")
    tracks = canonical_project.get("tracks")
    if not isinstance(tracks, list):
        raise GapProbeError("source bundle has no tracks")
    matches = [
        track
        for track in tracks
        if isinstance(track, dict) and track.get("track_id") == spec.source_voice_track_id
    ]
    if len(matches) != 1:
        raise GapProbeError("source voice track is missing or ambiguous")
    source_track = matches[0]
    source_voice = _resolve_inside(project_dir, source_track.get("source_events_path"))
    expected_hash = source_track.get("provenance", {}).get("normalized_artifact_sha256")
    if sha256_file(source_voice) != expected_hash:
        raise GapProbeError("source voice events hash does not match source bundle")
    return project, canonical_audio, source_voice, canonical_project


def _overlaps(event: NoteEvent, target: TargetInterval) -> bool:
    return event.offset_sec > target.start_sec and event.onset_sec < target.end_sec


def validate_empty_source_gaps(
    source_events: list[NoteEvent],
    spec: ProbeSpec,
) -> None:
    for window in spec.windows:
        for target in window.targets:
            count = sum(_overlaps(event, target) for event in source_events)
            if count:
                raise GapProbeError(
                    f"source voice is not empty in {target.target_id}: {count} overlapping notes"
                )


def plan_automatic_probe(
    project_dir: Path,
    *,
    probe_id: str,
    source_bundle_id: str,
    source_voice_track_id: str = "voice",
    minimum_gap_duration_sec: float = 8.0,
    context_sec: float = 4.0,
    maximum_target_duration_sec: float = 80.0,
    maximum_window_duration_sec: float = 90.0,
    maximum_targets: int = 8,
) -> ProbeSpec:
    project_dir = project_dir.expanduser().resolve()
    probe_id = _safe_identifier(probe_id, label="probe_id")
    source_bundle_id = _safe_identifier(
        source_bundle_id,
        label="source_bundle_id",
    )
    source_voice_track_id = _safe_identifier(
        source_voice_track_id,
        label="source_voice_track_id",
    )
    for label, value in (
        ("minimum_gap_duration_sec", minimum_gap_duration_sec),
        ("context_sec", context_sec),
        ("maximum_target_duration_sec", maximum_target_duration_sec),
        ("maximum_window_duration_sec", maximum_window_duration_sec),
    ):
        if not math.isfinite(value) or value <= 0:
            raise GapProbeError(f"{label} must be finite and positive")
    if maximum_targets < 1:
        raise GapProbeError("maximum_targets must be positive")

    project = load_project(project_dir)
    canonical_record = project.get("canonical_audio")
    if not isinstance(canonical_record, dict):
        raise GapProbeError("project has no canonical audio record")
    metadata = canonical_record.get("metadata")
    if not isinstance(metadata, dict):
        raise GapProbeError("canonical audio metadata is unavailable")
    duration = _finite_number(
        metadata.get("duration_sec"),
        label="canonical_audio.metadata.duration_sec",
    )
    if duration <= 0:
        raise GapProbeError("canonical audio duration must be positive")

    source_spec = ProbeSpec(
        probe_id=probe_id,
        source_bundle_id=source_bundle_id,
        source_voice_track_id=source_voice_track_id,
        canonical_duration_sec=duration,
        context_sec=context_sec,
        windows=(),
    )
    _project, _audio, source_voice_path, _canonical = _source_context(
        project_dir,
        source_spec,
    )
    source_events = read_jsonl(source_voice_path)
    if not source_events:
        return source_spec

    occupied: list[tuple[float, float]] = []
    for event in sorted(
        source_events,
        key=lambda item: (item.onset_sec, item.offset_sec, item.event_id),
    ):
        start = max(0.0, event.onset_sec)
        end = min(duration, event.offset_sec)
        if end <= start:
            continue
        if occupied and start <= occupied[-1][1]:
            occupied[-1] = (occupied[-1][0], max(occupied[-1][1], end))
        else:
            occupied.append((start, end))
    if not occupied:
        return source_spec

    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in occupied:
        if start - cursor >= minimum_gap_duration_sec:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if duration - cursor >= minimum_gap_duration_sec:
        gaps.append((cursor, duration))
    if not gaps:
        return source_spec

    ranked_gaps = sorted(
        gaps,
        key=lambda interval: (
            -(interval[1] - interval[0]),
            interval[0],
        ),
    )
    selected_targets: list[TargetInterval] = []
    for gap_start, gap_end in ranked_gaps:
        duration_sec = gap_end - gap_start
        part_count = max(1, math.ceil(duration_sec / maximum_target_duration_sec))
        part_duration = duration_sec / part_count
        for part_index in range(part_count):
            if len(selected_targets) >= maximum_targets:
                break
            start = gap_start + part_index * part_duration
            end = (
                gap_end
                if part_index == part_count - 1
                else gap_start + (part_index + 1) * part_duration
            )
            selected_targets.append(
                TargetInterval(
                    target_id="pending",
                    start_sec=round(start, 6),
                    end_sec=round(end, 6),
                    expectation="automatic long voice-gap recovery candidate",
                )
            )
        if len(selected_targets) >= maximum_targets:
            break
    selected_targets.sort(key=lambda item: (item.start_sec, item.end_sec))
    selected_targets = [
        TargetInterval(
            target_id=f"gap-{index:02d}",
            start_sec=target.start_sec,
            end_sec=target.end_sec,
            expectation=target.expectation,
        )
        for index, target in enumerate(selected_targets, start=1)
    ]

    grouped_targets: list[list[TargetInterval]] = []
    for target in selected_targets:
        if not grouped_targets:
            grouped_targets.append([target])
            continue
        current = grouped_targets[-1]
        combined_start = max(0.0, current[0].start_sec - context_sec)
        combined_end = min(duration, target.end_sec + context_sec)
        separation = target.start_sec - current[-1].end_sec
        if (
            separation <= context_sec * 2 + 8.0
            and combined_end - combined_start <= maximum_window_duration_sec
        ):
            current.append(target)
        else:
            grouped_targets.append([target])
    windows = tuple(
        ProbeWindow(
            window_id=f"window-{index:02d}",
            clip_start_sec=round(
                max(0.0, targets[0].start_sec - context_sec),
                6,
            ),
            clip_end_sec=round(
                min(duration, targets[-1].end_sec + context_sec),
                6,
            ),
            targets=tuple(targets),
        )
        for index, targets in enumerate(grouped_targets, start=1)
    )
    return ProbeSpec(
        probe_id=probe_id,
        source_bundle_id=source_bundle_id,
        source_voice_track_id=source_voice_track_id,
        canonical_duration_sec=duration,
        context_sec=context_sec,
        windows=windows,
    )


def shift_voice_candidates(
    events: list[NoteEvent],
    *,
    probe_id: str,
    window: ProbeWindow,
) -> list[NoteEvent]:
    shifted: list[NoteEvent] = []
    for event in events:
        if (event.instrument or "").lower() != "voice":
            continue
        original_onset = event.onset_sec + window.clip_start_sec
        original_offset = event.offset_sec + window.clip_start_sec
        matching = [
            target
            for target in window.targets
            if original_offset > target.start_sec and original_onset < target.end_sec
        ]
        if not matching:
            continue
        if len(matching) != 1:
            raise GapProbeError(f"candidate overlaps multiple targets: {event.event_id}")
        target = matching[0]
        clipped_onset = max(original_onset, target.start_sec)
        clipped_offset = min(original_offset, target.end_sec)
        if clipped_offset <= clipped_onset:
            continue
        extra = dict(event.extra)
        extra["gap_probe"] = {
            "probe_id": probe_id,
            "window_id": window.window_id,
            "target_id": target.target_id,
            "clip_start_sec": window.clip_start_sec,
            "clip_onset_sec": event.onset_sec,
            "clip_offset_sec": event.offset_sec,
            "source_event_id": event.event_id,
            "automatic_merge_performed": False,
        }
        shifted.append(
            NoteEvent(
                event_id=f"{probe_id}:{window.window_id}:{event.event_id}",
                track_id="muscriptor-gap:voice",
                instrument="voice",
                onset_sec=clipped_onset,
                offset_sec=clipped_offset,
                pitch_midi=event.pitch_midi,
                quantized_pitch_midi=event.quantized_pitch_midi,
                velocity=event.velocity,
                confidence=event.confidence,
                is_main_melody_candidate=True,
                source_run_id=event.source_run_id,
                source_model=event.source_model,
                source_event_ids=[*event.source_event_ids, event.event_id],
                tags=sorted(
                    {
                        *event.tags,
                        "candidate",
                        "directed-gap-probe",
                        target.target_id,
                    }
                ),
                extra=extra,
            )
        )
    return shifted


def shift_unconstrained_melody_candidates(
    events: list[NoteEvent],
    *,
    probe_id: str,
    window: ProbeWindow,
) -> list[NoteEvent]:
    """Relabel non-percussion fallback predictions as traceable melody candidates."""

    shifted: list[NoteEvent] = []
    for event in events:
        original_instrument = (event.instrument or "unknown").lower()
        if "drum" in original_instrument or original_instrument == "percussion":
            continue
        original_onset = event.onset_sec + window.clip_start_sec
        original_offset = event.offset_sec + window.clip_start_sec
        matching = [
            target
            for target in window.targets
            if original_offset > target.start_sec and original_onset < target.end_sec
        ]
        if len(matching) != 1:
            continue
        target = matching[0]
        clipped_onset = max(original_onset, target.start_sec)
        clipped_offset = min(original_offset, target.end_sec)
        if clipped_offset <= clipped_onset:
            continue
        extra = dict(event.extra)
        extra["residual_melody_fallback"] = {
            "probe_id": probe_id,
            "window_id": window.window_id,
            "target_id": target.target_id,
            "source_event_id": event.event_id,
            "original_predicted_instrument": original_instrument,
            "instrument_allowlist_used": False,
            "accuracy_claimed": False,
        }
        shifted.append(
            NoteEvent(
                event_id=f"{probe_id}:{window.window_id}:fallback:{event.event_id}",
                track_id="muscriptor-gap:voice",
                instrument="voice",
                onset_sec=clipped_onset,
                offset_sec=clipped_offset,
                pitch_midi=event.pitch_midi,
                quantized_pitch_midi=event.quantized_pitch_midi,
                velocity=event.velocity,
                confidence=event.confidence,
                is_main_melody_candidate=True,
                source_run_id=event.source_run_id,
                source_model=event.source_model,
                source_event_ids=sorted({*event.source_event_ids, event.event_id}),
                tags=sorted(
                    {
                        *event.tags,
                        "candidate",
                        "residual-melody-fallback",
                        target.target_id,
                    }
                ),
                extra=extra,
            )
        )
    return shifted


def load_accompaniment_events(
    project_dir: Path,
    source_canonical: dict[str, Any],
    *,
    source_track_id: str,
) -> list[NoteEvent]:
    """Load verified non-voice product tracks used only as a soft exclusion mask."""

    accompaniment: list[NoteEvent] = []
    for index, track in enumerate(source_canonical.get("tracks", []), start=1):
        if not isinstance(track, dict) or track.get("track_id") == source_track_id:
            continue
        if track.get("role") == "diagnostic_candidate":
            continue
        instrument = str(track.get("instrument") or "").lower()
        if instrument == "voice":
            continue
        track_id = _safe_identifier(
            track.get("track_id"),
            label=f"source accompaniment track {index}",
        )
        path = _resolve_inside(project_dir, track.get("source_events_path"))
        expected_hash = track.get("provenance", {}).get(
            "normalized_artifact_sha256"
        )
        if sha256_file(path) != expected_hash:
            raise GapProbeError(
                f"source accompaniment hash does not match: {track_id}"
            )
        accompaniment.extend(read_jsonl(path))
    return accompaniment


def plan_residual_fallback_windows(
    spec: ProbeSpec,
    candidates: list[NoteEvent],
    *,
    minimum_gap_sec: float = 3.0,
    maximum_windows: int = 16,
) -> tuple[ProbeWindow, ...]:
    """Plan one bounded unconstrained fallback pass over still-empty target spans."""

    windows: list[ProbeWindow] = []
    for source_window in spec.windows:
        for target in source_window.targets:
            target_events = [
                event
                for event in candidates
                if event.offset_sec > target.start_sec
                and event.onset_sec < target.end_sec
            ]
            for start, end in residual_melody_gaps(
                start_sec=target.start_sec,
                end_sec=target.end_sec,
                events=target_events,
                minimum_gap_sec=minimum_gap_sec,
            ):
                index = len(windows) + 1
                fallback_target = TargetInterval(
                    target_id=f"fallback-{index:02d}",
                    start_sec=round(start, 6),
                    end_sec=round(end, 6),
                    expectation="residual empty span after directed voice decode",
                )
                windows.append(
                    ProbeWindow(
                        window_id=f"fallback-window-{index:02d}",
                        clip_start_sec=round(
                            max(0.0, start - spec.context_sec),
                            6,
                        ),
                        clip_end_sec=round(
                            min(spec.canonical_duration_sec, end + spec.context_sec),
                            6,
                        ),
                        targets=(fallback_target,),
                    )
                )
                if len(windows) >= maximum_windows:
                    return tuple(windows)
    return tuple(windows)


def _union_duration(events: list[NoteEvent], target: TargetInterval) -> float:
    intervals = sorted(
        (
            max(target.start_sec, event.onset_sec),
            min(target.end_sec, event.offset_sec),
        )
        for event in events
        if _overlaps(event, target)
    )
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


def build_coverage_report(
    spec: ProbeSpec,
    candidates: list[NoteEvent],
) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    for window in spec.windows:
        for target in window.targets:
            notes = [event for event in candidates if _overlaps(event, target)]
            coverage = _union_duration(notes, target)
            pitches = [event.pitch_midi for event in notes]
            targets.append(
                {
                    "target_id": target.target_id,
                    "expectation": target.expectation,
                    "start_sec": target.start_sec,
                    "end_sec": target.end_sec,
                    "duration_sec": round(target.duration_sec, 6),
                    "candidate_note_count": len(notes),
                    "candidate_union_duration_sec": round(coverage, 6),
                    "candidate_time_coverage": round(
                        coverage / target.duration_sec,
                        6,
                    ),
                    "candidate_pitch_min": min(pitches) if pitches else None,
                    "candidate_pitch_max": max(pitches) if pitches else None,
                    "correct_recovered_note_count": None,
                    "false_positive_note_count": None,
                    "owner_review_required": True,
                }
            )
    return {
        "schema_version": 1,
        "artifact_type": "amt-muscriptor-gap-probe-report",
        "probe_id": spec.probe_id,
        "candidate_track_id": "voice_gap_candidate",
        "source_track_id": spec.source_voice_track_id,
        "automatic_merge_performed": False,
        "accuracy_claimed": False,
        "candidate_note_count": len(candidates),
        "targets": targets,
        "decision": "awaiting_owner_gap_review",
    }


def derive_owner_approved_voice(
    source_events: list[NoteEvent],
    candidates: list[NoteEvent],
    *,
    probe_id: str,
) -> list[NoteEvent]:
    enhanced: list[NoteEvent] = []
    for origin, events in (
        ("voice_raw", source_events),
        ("voice_gap_candidate", candidates),
    ):
        for event in events:
            if (event.instrument or "").lower() != "voice":
                raise GapProbeError(
                    f"{origin} contains a non-voice event: {event.event_id}"
                )
            extra = dict(event.extra)
            extra["owner_approved_voice_enhancement"] = {
                "probe_id": probe_id,
                "origin_track_id": origin,
                "source_event_id": event.event_id,
                "automatic_model_promotion": False,
                "owner_approved_derivation": True,
            }
            enhanced.append(
                NoteEvent(
                    event_id=(
                        f"{probe_id}:voice-enhanced:{origin}:{event.event_id}"
                    ),
                    track_id="derived:voice_enhanced",
                    instrument="voice",
                    onset_sec=event.onset_sec,
                    offset_sec=event.offset_sec,
                    pitch_midi=event.pitch_midi,
                    quantized_pitch_midi=event.quantized_pitch_midi,
                    velocity=event.velocity,
                    confidence=event.confidence,
                    is_main_melody_candidate=True,
                    source_run_id=probe_id,
                    source_model="deterministic:voice_raw+voice_gap_candidate",
                    source_event_ids=sorted(
                        {*event.source_event_ids, event.event_id}
                    ),
                    tags=sorted(
                        {
                            *event.tags,
                            "owner-approved",
                            "voice-enhanced",
                            origin,
                        }
                    ),
                    extra=extra,
                )
            )
    enhanced.sort(
        key=lambda event: (
            event.onset_sec,
            event.offset_sec,
            event.pitch_midi,
            event.event_id,
        )
    )
    if len({event.event_id for event in enhanced}) != len(enhanced):
        raise GapProbeError("owner-approved enhanced voice has duplicate event IDs")
    return enhanced


def derive_automatic_voice(
    source_events: list[NoteEvent],
    candidates: list[NoteEvent],
    *,
    probe_id: str,
) -> list[NoteEvent]:
    enhanced: list[NoteEvent] = []
    for origin, events in (
        ("voice_raw", source_events),
        ("voice_gap_candidate", candidates),
    ):
        for event in events:
            if (event.instrument or "").lower() != "voice":
                raise GapProbeError(
                    f"{origin} contains a non-voice event: {event.event_id}"
                )
            extra = dict(event.extra)
            extra["automatic_voice_enhancement"] = {
                "probe_id": probe_id,
                "origin_track_id": origin,
                "source_event_id": event.event_id,
                "automatic_gap_recovery": True,
                "automatic_model_promotion": False,
                "owner_approved_derivation": False,
            }
            enhanced.append(
                NoteEvent(
                    event_id=(
                        f"{probe_id}:voice-auto-enhanced:{origin}:{event.event_id}"
                    ),
                    track_id="derived:voice_auto_enhanced",
                    instrument="voice",
                    onset_sec=event.onset_sec,
                    offset_sec=event.offset_sec,
                    pitch_midi=event.pitch_midi,
                    quantized_pitch_midi=event.quantized_pitch_midi,
                    velocity=event.velocity,
                    confidence=event.confidence,
                    is_main_melody_candidate=True,
                    source_run_id=probe_id,
                    source_model=(
                        "deterministic:voice_raw+voice_gap_candidate:auto"
                    ),
                    source_event_ids=sorted(
                        {*event.source_event_ids, event.event_id}
                    ),
                    tags=sorted(
                        {
                            *event.tags,
                            "automatic-gap-recovery",
                            "voice-auto-enhanced",
                            origin,
                        }
                    ),
                    extra=extra,
                )
            )
    enhanced.sort(
        key=lambda event: (
            event.onset_sec,
            event.offset_sec,
            event.pitch_midi,
            event.event_id,
        )
    )
    if len({event.event_id for event in enhanced}) != len(enhanced):
        raise GapProbeError("automatic enhanced voice has duplicate event IDs")
    return enhanced


def _artifact_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "run_manifest.json":
            continue
        records.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def _run_checked(argv: list[str], *, stdout: Path | None = None, stderr: Path | None = None) -> None:
    stdout_handle = stdout.open("wb") if stdout else subprocess.DEVNULL
    stderr_handle = stderr.open("wb") if stderr else subprocess.PIPE
    try:
        result = subprocess.run(
            argv,
            check=False,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    finally:
        if stdout:
            stdout_handle.close()
        if stderr:
            stderr_handle.close()
    if result.returncode != 0:
        detail = ""
        if stderr is None and isinstance(result.stderr, bytes):
            detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GapProbeError(f"command failed ({result.returncode}): {argv[0]} {detail}")


def _clip_audio(
    canonical_audio: Path,
    destination: Path,
    *,
    start_sec: float,
    end_sec: float,
    ffmpeg: str,
) -> list[str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(canonical_audio),
        "-af",
        f"atrim=start={start_sec:.6f}:end={end_sec:.6f},asetpts=PTS-STARTPTS",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "flac",
        str(destination),
    ]
    _run_checked(argv)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise GapProbeError(f"ffmpeg did not create clip: {destination}")
    return argv


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve(strict=True).relative_to(root.resolve(strict=True)))
    except (OSError, ValueError) as exc:
        raise GapProbeError(f"output is outside project: {path}") from exc


def _rhythm_points(
    source_canonical: dict[str, Any],
) -> tuple[list[TempoPoint], list[MeterPoint]]:
    rhythm = source_canonical.get("rhythm")
    if not isinstance(rhythm, dict):
        raise GapProbeError("source canonical project has no rhythm map")
    tempo = []
    for index, row in enumerate(rhythm.get("tempo_map", [])):
        if not isinstance(row, dict):
            continue
        enriched = dict(row)
        enriched.setdefault("confidence", None)
        enriched.setdefault("uncertainty_bpm", None)
        enriched.setdefault(
            "source_event_ids",
            [f"source-canonical-tempo-{index}"],
        )
        enriched.setdefault("method", "source_canonical_legacy")
        tempo.append(TempoPoint.from_dict(enriched))
    meter = []
    for index, row in enumerate(rhythm.get("meter_map", [])):
        if not isinstance(row, dict):
            continue
        enriched = dict(row)
        enriched.setdefault("confidence", None)
        enriched.setdefault(
            "source_event_ids",
            [f"source-canonical-meter-{index}"],
        )
        enriched.setdefault("status", "defaulted")
        meter.append(MeterPoint.from_dict(enriched))
    if not tempo:
        tempo = [
            TempoPoint(
                time_sec=0.0,
                bpm=120.0,
                confidence=None,
                uncertainty_bpm=None,
                source_event_ids=("gap-probe-default-tempo",),
                method="gap_probe_default",
            )
        ]
    if not meter:
        meter = [
            MeterPoint(
                time_sec=0.0,
                numerator=4,
                denominator=4,
                confidence=None,
                source_event_ids=("gap-probe-default-meter",),
                status="defaulted",
            )
        ]
    return tempo, meter


def build_review_bundle(
    project_dir: Path,
    *,
    spec: ProbeSpec,
    source_voice_path: Path,
    source_canonical: dict[str, Any],
    source_events: list[NoteEvent],
    candidate_path: Path,
    candidates: list[NoteEvent],
    parent_manifest_path: Path,
    output_dir: Path,
    owner_approved_enhanced: bool = False,
) -> dict[str, Any]:
    if output_dir.exists() or output_dir.is_symlink():
        raise GapProbeError(f"review bundle already exists: {output_dir}")
    source_track = next(
        track
        for track in source_canonical["tracks"]
        if track["track_id"] == spec.source_voice_track_id
    )
    project = load_project(project_dir)
    canonical = project["canonical_audio"]
    tempo, meter = _rhythm_points(source_canonical)
    enhanced = (
        derive_owner_approved_voice(
            source_events,
            candidates,
            probe_id=spec.probe_id,
        )
        if owner_approved_enhanced
        else []
    )
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.",
        dir=output_dir.parent,
    ) as temporary_name:
        temporary = Path(temporary_name)
        enhanced_path = temporary / "tracks" / "voice_enhanced.jsonl"
        if enhanced:
            write_jsonl(enhanced_path, enhanced)
        midi_report = export_performance_midi(
            temporary / "performance.mid",
            {
                "voice_raw": source_events,
                "voice_gap_candidate": candidates,
            },
            tempo,
            meter,
        )
        parent_hash = sha256_file(parent_manifest_path)
        candidate_hash = sha256_file(candidate_path)
        tracks = [
            {
                "track_id": "voice_raw",
                "label": "voice raw（原始，不修改）",
                "role": "candidate",
                "instrument": "voice",
                "event_count": len(source_events),
                "source_events_path": _relative(source_voice_path, project_dir),
                "provenance": source_track["provenance"],
            },
            {
                "track_id": "voice_gap_candidate",
                "label": "voice gap candidate（仅补漏候选）",
                "role": "candidate",
                "instrument": "voice",
                "event_count": len(candidates),
                "source_events_path": _relative(candidate_path, project_dir),
                "provenance": {
                    "source_run_id": spec.probe_id,
                    "source_model": candidates[0].source_model
                    if candidates
                    else source_track["provenance"]["source_model"],
                    "run_manifest_sha256": parent_hash,
                    "normalized_artifact_sha256": candidate_hash,
                },
            },
        ]
        if enhanced:
            final_enhanced_path = (
                output_dir / "tracks" / "voice_enhanced.jsonl"
            ).resolve(strict=False)
            try:
                enhanced_relative = str(
                    final_enhanced_path.relative_to(
                        project_dir.resolve(strict=True)
                    )
                )
            except ValueError as exc:
                raise GapProbeError(
                    f"enhanced review track is outside project: {final_enhanced_path}"
                ) from exc
            tracks.append(
                {
                    "track_id": "voice_enhanced",
                    "label": "增强主唱（原始 + 已审核补漏）",
                    "role": "owner_approved_candidate",
                    "instrument": "voice",
                    "event_count": len(enhanced),
                    "source_events_path": enhanced_relative,
                    "provenance": {
                        "source_run_id": spec.probe_id,
                        "source_model": (
                            "deterministic:voice_raw+voice_gap_candidate"
                        ),
                        "run_manifest_sha256": parent_hash,
                        "normalized_artifact_sha256": sha256_file(
                            enhanced_path
                        ),
                    },
                }
            )
        canonical_project = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-project",
            "project_id": project["project_id"],
            "timeline_basis": "original_canonical_mix_seconds",
            "canonical_audio": canonical,
            "tracks": tracks,
            "rhythm": source_canonical["rhythm"],
            "exports": {
                "performance_midi": {
                    "path": "performance.mid",
                    "representation": "performance",
                    "report": midi_report,
                }
            },
            "claims": {
                "candidate_fusion_performed": False,
                "automatic_merge_performed": False,
                "preferred_candidate_selected": bool(enhanced),
                "accuracy_claimed": False,
                "owner_approved_derivation_performed": bool(enhanced),
            },
        }
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
            "tracks": [track["track_id"] for track in tracks],
            "outputs": outputs,
            "claims": canonical_project["claims"],
            "limitations": [
                "voice_gap_candidate is a same-model recovery probe, not a verified correction.",
                "The original voice_raw track remains separate and unchanged.",
                "No candidate fusion, automatic merge, or accuracy claim was performed.",
                (
                    "voice_enhanced is a deterministic owner-approved derivation."
                    if enhanced
                    else "Owner listening is required before accepting any recovered note."
                ),
            ],
        }
        atomic_write_json(temporary / "bundle_manifest.json", bundle_manifest)
        temporary.replace(output_dir)
    return bundle_manifest


def build_automatic_bundle(
    project_dir: Path,
    *,
    spec: ProbeSpec,
    source_voice_path: Path,
    source_canonical: dict[str, Any],
    source_events: list[NoteEvent],
    candidate_path: Path,
    candidates: list[NoteEvent],
    product_candidates: list[NoteEvent] | None = None,
    parent_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    source_voice_path = source_voice_path.expanduser().resolve()
    candidate_path = candidate_path.expanduser().resolve()
    parent_manifest_path = parent_manifest_path.expanduser().resolve()
    if output_dir.exists() or output_dir.is_symlink():
        raise GapProbeError(f"automatic bundle already exists: {output_dir}")
    source_tracks = source_canonical.get("tracks")
    if not isinstance(source_tracks, list):
        raise GapProbeError("source canonical project has no tracks")
    source_voice_tracks = [
        track
        for track in source_tracks
        if isinstance(track, dict)
        and track.get("track_id") == spec.source_voice_track_id
    ]
    if len(source_voice_tracks) != 1:
        raise GapProbeError("source voice track is missing or ambiguous")
    reserved = {"voice_raw", "voice_gap_candidate", "voice_auto_enhanced"}
    accompaniment = [
        track
        for track in source_tracks
        if isinstance(track, dict)
        and track.get("track_id") != spec.source_voice_track_id
    ]
    if any(track.get("track_id") in reserved for track in accompaniment):
        raise GapProbeError("source accompaniment collides with a voice variant")

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
    tempo, meter = _rhythm_points(source_canonical)
    admitted_candidates = (
        candidates if product_candidates is None else product_candidates
    )
    product_admission = automatic_voice_candidate_admission(
        source_note_count=len(source_events),
        candidate_note_count=len(candidates),
    )
    enhanced = derive_automatic_voice(
        source_events,
        admitted_candidates,
        probe_id=spec.probe_id,
    )
    parent_hash = sha256_file(parent_manifest_path)
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

        raw_path = tracks_dir / "voice_raw.jsonl"
        shutil.copy2(source_voice_path, raw_path)
        copied_candidate_path = tracks_dir / "voice_gap_candidate.jsonl"
        shutil.copy2(candidate_path, copied_candidate_path)
        enhanced_path = tracks_dir / "voice_auto_enhanced.jsonl"
        write_jsonl(enhanced_path, enhanced)

        source_voice_track = source_voice_tracks[0]
        track_records: list[dict[str, Any]] = [
            {
                "track_id": "voice_auto_enhanced",
                "label": "自动增强主旋律（Beta）",
                "role": "automatic_candidate",
                "instrument": "voice",
                "event_count": len(enhanced),
                "source_events_path": str(
                    (output_dir / "tracks" / enhanced_path.name).relative_to(
                        project_dir
                    )
                ),
                "provenance": {
                    "source_run_id": spec.probe_id,
                    "source_model": (
                        "deterministic:voice_raw+voice_gap_candidate:auto"
                    ),
                    "run_manifest_sha256": parent_hash,
                    "normalized_artifact_sha256": sha256_file(enhanced_path),
                },
            },
            {
                "track_id": "voice_raw",
                "label": "原始主唱候选",
                "role": "diagnostic_candidate",
                "instrument": "voice",
                "event_count": len(source_events),
                "source_events_path": str(
                    (output_dir / "tracks" / raw_path.name).relative_to(
                        project_dir
                    )
                ),
                "provenance": source_voice_track["provenance"],
            },
            {
                "track_id": "voice_gap_candidate",
                "label": "自动补漏候选（原始生成）",
                "role": "diagnostic_candidate",
                "instrument": "voice",
                "event_count": len(candidates),
                "source_events_path": str(
                    (
                        output_dir / "tracks" / copied_candidate_path.name
                    ).relative_to(project_dir)
                ),
                "provenance": {
                    "source_run_id": spec.probe_id,
                    "source_model": (
                        candidates[0].source_model
                        if candidates
                        else source_voice_track["provenance"]["source_model"]
                    ),
                    "run_manifest_sha256": parent_hash,
                    "normalized_artifact_sha256": sha256_file(
                        copied_candidate_path
                    ),
                },
            },
        ]
        midi_tracks: dict[str, list[NoteEvent]] = {
            "voice_auto_enhanced": enhanced,
        }
        for index, track in enumerate(accompaniment, start=1):
            track_id = _safe_identifier(
                track.get("track_id"),
                label=f"source accompaniment track {index}",
            )
            source_path = _resolve_inside(
                project_dir,
                track.get("source_events_path"),
            )
            expected_hash = track.get("provenance", {}).get(
                "normalized_artifact_sha256"
            )
            if sha256_file(source_path) != expected_hash:
                raise GapProbeError(
                    f"source accompaniment hash does not match: {track_id}"
                )
            copied_path = tracks_dir / f"{track_id}.jsonl"
            source_track_events = read_jsonl(source_path)
            cleaned_events = source_track_events
            cleanup = {
                "decision": "not_applicable",
                "group_count": 0,
                "fragment_count": 0,
                "merged_note_count": 0,
                "source_overwritten": False,
            }
            if timeline_end is not None:
                cleaned_events, cleanup = clean_trailing_fragments(
                    source_track_events,
                    timeline_end=timeline_end,
                    run_id=spec.probe_id,
                )
            if cleanup["group_count"]:
                raw_tracks_dir.mkdir(exist_ok=True)
                raw_copy = raw_tracks_dir / f"{track_id}.jsonl"
                shutil.copy2(source_path, raw_copy)
                cleanup["raw_source_path"] = str(
                    (output_dir / "raw_tracks" / raw_copy.name).relative_to(
                        project_dir
                    )
                )
                cleanup["raw_source_sha256"] = sha256_file(raw_copy)
                write_jsonl(copied_path, cleaned_events)
            else:
                shutil.copy2(source_path, copied_path)
            cleanup_records.append(
                {
                    "track_id": track_id,
                    "instrument": track.get("instrument"),
                    **cleanup,
                }
            )
            copied_track = dict(track)
            copied_track["source_events_path"] = str(
                (output_dir / "tracks" / copied_path.name).relative_to(
                    project_dir
                )
            )
            if cleanup["group_count"]:
                copied_track["event_count"] = len(cleaned_events)
                copied_track["source_provenance"] = track.get("provenance")
                copied_track["provenance"] = {
                    "source_run_id": spec.probe_id,
                    "source_model": "deterministic:trailing-sustain-cleanup",
                    "run_manifest_sha256": parent_hash,
                    "normalized_artifact_sha256": sha256_file(copied_path),
                }
            track_records.append(copied_track)
            midi_tracks[track_id] = cleaned_events

        melodic_track_count = sum(track_id != "drums" for track_id in midi_tracks)
        if melodic_track_count <= 15:
            midi_report = export_performance_midi(
                temporary / "performance.mid",
                midi_tracks,
                tempo,
                meter,
            )
        else:
            midi_report = {
                "status": "unavailable",
                "reason": (
                    "The automatic result has more than the 15 melodic "
                    "channels available in one General MIDI port."
                ),
                "track_count": len(midi_tracks),
                "note_count": sum(len(events) for events in midi_tracks.values()),
            }
        canonical_project = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-project",
            "project_id": project["project_id"],
            "timeline_basis": "original_canonical_mix_seconds",
            "canonical_audio": canonical,
            "worker_results": source_canonical.get("worker_results", []),
            "tracks": track_records,
            "main_melody_track_id": "voice_auto_enhanced",
            "rhythm": source_canonical["rhythm"],
            "exports": {
                "performance_midi": {
                    "path": (
                        "performance.mid"
                        if midi_report.get("status") != "unavailable"
                        else None
                    ),
                    "representation": "performance",
                    "report": midi_report,
                }
            },
            "claims": {
                "all_muscriptor_instruments_preserved": True,
                "automatic_gap_recovery_performed": bool(spec.windows),
                "automatic_merge_performed": bool(admitted_candidates),
                "automatic_candidate_admission": product_admission["decision"],
                "automatic_candidate_selection": "raw_generated",
                "preferred_candidate_selected": True,
                "accuracy_claimed": False,
                "owner_approved_derivation_performed": False,
                "automatic_model_promotion": False,
                "accompaniment_soft_mask_performed": True,
                "accompaniment_soft_mask_used_for_product": False,
                "automatic_trailing_sustain_cleanup_performed": any(
                    record["group_count"] for record in cleanup_records
                ),
                "automatic_trailing_sustain_cleanup_source_overwritten": False,
            },
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
            "tracks": [track["track_id"] for track in track_records],
            "outputs": outputs,
            "claims": canonical_project["claims"],
            "limitations": [
                "Automatic long-gap detection cannot prove that singing is present.",
                "voice_gap_candidate is a same-model recovery candidate, not a verified correction.",
                "voice_auto_enhanced uses the raw voice-constrained candidates selected by the owner.",
                "No song-length-blind candidate-count limit is applied to selected empty windows.",
                "Accompaniment-filtered and monophonic views remain diagnostic alternatives.",
                "The original voice and every MuScriptor accompaniment track remain preserved.",
                "Automatic sustain cleanup is conservative and excludes percussion from sustain merging.",
            ],
        }
        atomic_write_json(temporary / "bundle_manifest.json", bundle_manifest)
        temporary.replace(output_dir)
    return bundle_manifest


def _execution_source_record(
    *,
    automatic_enhanced: bool,
    execution_backend: str,
) -> dict[str, Any]:
    if execution_backend == "local":
        relative = Path("src/amt_core/private_beta.py")
    else:
        relative = Path(
            "slurm/40_private_beta_muscriptor.slurm"
            if automatic_enhanced
            else "slurm/41_muscriptor_gap_probe.slurm"
        )
    return {
        "path": str(relative),
        "sha256": sha256_file(run_baseline.REPO_ROOT / relative),
    }


def _directed_child_arguments(
    *,
    project_dir: Path,
    clip_path: Path,
    worker_env: Path,
    weight_provenance: Path,
    child_run_id: str,
    device: str,
    instrument: str | None,
) -> list[str]:
    arguments = [
        "--project",
        str(project_dir),
        "--audio",
        str(clip_path),
        "--worker-env",
        str(worker_env),
        "--weight-provenance",
        str(weight_provenance),
        "--run-id",
        child_run_id,
        "--beam-size",
        "4",
        "--device",
        device,
        "--prelude-forcing",
        "--skip-midi",
    ]
    if instrument is not None:
        arguments.extend(["--instruments", instrument])
    return arguments


def run_residual_fallbacks(
    *,
    project_dir: Path,
    canonical_audio: Path,
    run_dir: Path,
    probe_id: str,
    windows: tuple[ProbeWindow, ...],
    worker_env: Path,
    weight_provenance: Path,
    ffmpeg: str,
    device: str,
) -> tuple[list[NoteEvent], list[dict[str, Any]]]:
    """Run at most one unrestricted decode for each planned residual window."""

    fallback_candidates: list[NoteEvent] = []
    records: list[dict[str, Any]] = []
    clips_dir = run_dir / "clips"
    logs_dir = run_dir / "logs"
    for window in windows:
        clip_path = clips_dir / f"{window.window_id}.flac"
        command = _clip_audio(
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
                "fallback_pass": 1,
            },
        )
        child_run_id = f"{probe_id}-{window.window_id}"
        exit_code = run_baseline.main(
            _directed_child_arguments(
                project_dir=project_dir,
                clip_path=clip_path,
                worker_env=worker_env,
                weight_provenance=weight_provenance,
                child_run_id=child_run_id,
                device=device,
                instrument=None,
            )
        )
        child_dir = project_dir / "runs" / child_run_id
        child_manifest = child_dir / "run_manifest.json"
        if exit_code != 0 or not child_manifest.is_file():
            raise GapProbeError(
                f"MuScriptor residual fallback failed: {child_run_id}"
            )
        child_value = _load_object(child_manifest)
        if child_value.get("status") != "succeeded":
            raise GapProbeError(
                f"MuScriptor residual fallback did not succeed: {child_run_id}"
            )
        child_events = read_jsonl(child_dir / "normalized" / "events.jsonl")
        window_candidates = shift_unconstrained_melody_candidates(
            child_events,
            probe_id=probe_id,
            window=window,
        )
        fallback_candidates.extend(window_candidates)
        records.append(
            {
                "window_id": window.window_id,
                "run_id": child_run_id,
                "run_manifest_path": _relative(child_manifest, project_dir),
                "run_manifest_sha256": sha256_file(child_manifest),
                "clip_sha256": sha256_file(clip_path),
                "all_event_count": len(child_events),
                "fallback_candidate_count": len(window_candidates),
                "instrument_allowlist_used": False,
                "fallback_pass": 1,
            }
        )
    return fallback_candidates, records


def run_probe(
    project_dir: Path,
    config_path: Path,
    *,
    worker_env: Path,
    weight_provenance: Path,
    ffmpeg: str,
    output_dir: Path | None = None,
    automatic_enhanced: bool = False,
    device: str = "cuda",
    require_slurm: bool = True,
    execution_backend: str = "slurm",
) -> dict[str, Any]:
    if require_slurm and not os.environ.get("SLURM_JOB_ID"):
        raise GapProbeError("gap probe requires an active Slurm allocation")
    hostname = platform.node()
    if require_slurm and "login" in hostname:
        raise GapProbeError("refusing to run gap probe on a login node")
    if device not in {"cuda", "mps", "cpu", "auto"}:
        raise GapProbeError("unsupported MuScriptor device")
    if execution_backend not in {"slurm", "local"}:
        raise GapProbeError("unsupported execution backend")
    if require_slurm != (execution_backend == "slurm"):
        raise GapProbeError("execution backend does not match the Slurm requirement")
    project_dir = project_dir.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    worker_env = worker_env.expanduser().resolve()
    weight_provenance = weight_provenance.expanduser().resolve()
    spec = load_spec(config_path)
    project, canonical_audio, source_voice_path, source_canonical = _source_context(
        project_dir,
        spec,
    )
    source_events = read_jsonl(source_voice_path)
    validate_empty_source_gaps(source_events, spec)
    run_dir = project_dir / "runs" / spec.probe_id
    review_bundle = (
        output_dir.expanduser().resolve()
        if output_dir is not None
        else project_dir / "exports" / f"{spec.probe_id}-review"
    )
    try:
        review_bundle.relative_to(project_dir)
    except ValueError as exc:
        raise GapProbeError("output bundle must be inside the project") from exc
    if run_dir.exists() or run_dir.is_symlink():
        raise GapProbeError(f"probe run already exists: {run_dir}")
    if review_bundle.exists() or review_bundle.is_symlink():
        raise GapProbeError(f"review bundle already exists: {review_bundle}")
    clips_dir = run_dir / "clips"
    normalized_dir = run_dir / "normalized"
    logs_dir = run_dir / "logs"
    for directory in (clips_dir, normalized_dir, logs_dir):
        directory.mkdir(parents=True)
    request = {
        "schema_version": 1,
        "probe_id": spec.probe_id,
        "project_id": project["project_id"],
        "config_path": _relative(config_path, project_dir),
        "config_sha256": sha256_file(config_path),
        "canonical_audio": {
            "path": _relative(canonical_audio, project_dir),
            "sha256": sha256_file(canonical_audio),
        },
        "source_voice_events": {
            "path": _relative(source_voice_path, project_dir),
            "sha256": sha256_file(source_voice_path),
            "event_count": len(source_events),
        },
        "decoding": {
            "model": "MuScriptor/muscriptor-large",
            "beam_size": 4,
            "prelude_forcing": True,
            "skip_midi": True,
            "instrument_allowlist": ["voice"],
            "sampling": False,
            "device": device,
            "residual_fallback_max_passes": 0,
        },
        "execution_backend": execution_backend,
        "automatic_merge_performed": False,
    }
    atomic_write_json(run_dir / "request.json", request)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "amt-muscriptor-gap-probe-run",
        "probe_id": spec.probe_id,
        "project_id": project["project_id"],
        "status": "running",
        "started_at": _utc_now(),
        "ended_at": None,
        "hostname": hostname,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "execution_backend": execution_backend,
        "request_sha256": sha256_file(run_dir / "request.json"),
        "child_runs": [],
        "outputs": [],
        "code": {
            **run_baseline.git_state(run_baseline.REPO_ROOT),
            "source_files": [
                {
                    "path": "workers/muscriptor/gap_probe.py",
                    "sha256": sha256_file(Path(__file__).resolve()),
                },
                {
                    "path": "workers/muscriptor/run_baseline.py",
                    "sha256": sha256_file(Path(run_baseline.__file__).resolve()),
                },
                {
                    "path": "src/amt_core/product_postprocess.py",
                    "sha256": sha256_file(
                        run_baseline.REPO_ROOT
                        / "src"
                        / "amt_core"
                        / "product_postprocess.py"
                    ),
                },
                _execution_source_record(
                    automatic_enhanced=automatic_enhanced,
                    execution_backend=execution_backend,
                ),
            ],
        },
        "error": None,
    }
    atomic_write_json(run_dir / "run_manifest.json", manifest)
    raw_candidates: list[NoteEvent] = []
    candidates: list[NoteEvent] = []
    try:
        accompaniment_events = load_accompaniment_events(
            project_dir,
            source_canonical,
            source_track_id=spec.source_voice_track_id,
        )
        for window in spec.windows:
            clip_path = clips_dir / f"{window.window_id}.flac"
            command = _clip_audio(
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
                _directed_child_arguments(
                    project_dir=project_dir,
                    clip_path=clip_path,
                    worker_env=worker_env,
                    weight_provenance=weight_provenance,
                    child_run_id=child_run_id,
                    device=device,
                    instrument="voice",
                )
            )
            child_dir = project_dir / "runs" / child_run_id
            child_manifest = child_dir / "run_manifest.json"
            if exit_code != 0 or not child_manifest.is_file():
                raise GapProbeError(f"MuScriptor child run failed: {child_run_id}")
            child_value = _load_object(child_manifest)
            if child_value.get("status") != "succeeded":
                raise GapProbeError(f"MuScriptor child run did not succeed: {child_run_id}")
            child_events = read_jsonl(child_dir / "normalized" / "events.jsonl")
            window_candidates = shift_voice_candidates(
                child_events,
                probe_id=spec.probe_id,
                window=window,
            )
            raw_candidates.extend(window_candidates)
            manifest["child_runs"].append(
                {
                    "window_id": window.window_id,
                    "run_id": child_run_id,
                    "run_manifest_path": _relative(child_manifest, project_dir),
                    "run_manifest_sha256": sha256_file(child_manifest),
                    "clip_sha256": sha256_file(clip_path),
                    "all_event_count": len(child_events),
                    "voice_gap_candidate_count": len(window_candidates),
                }
            )
        raw_candidates.sort(
            key=lambda event: (event.onset_sec, event.pitch_midi, event.event_id)
        )
        write_jsonl(
            normalized_dir / "voice_gap_candidate.raw.jsonl",
            raw_candidates,
        )
        filtered_candidates, mask_report = soft_mask_melody_candidates(
            raw_candidates,
            accompaniment_events,
            probe_id=spec.probe_id,
        )
        fallback_candidates: list[NoteEvent] = []
        write_jsonl(
            normalized_dir / "voice_gap_fallback.raw.jsonl",
            fallback_candidates,
        )
        filtered_candidates.sort(
            key=lambda event: (event.onset_sec, event.pitch_midi, event.event_id)
        )
        write_jsonl(
            normalized_dir / "voice_gap_candidate.filtered.jsonl",
            filtered_candidates,
        )
        candidates = list(raw_candidates)
        candidate_path = normalized_dir / "voice_gap_candidate.jsonl"
        write_jsonl(candidate_path, candidates)
        report = build_coverage_report(spec, candidates)
        product_admission = automatic_voice_candidate_admission(
            source_note_count=len(source_events),
            candidate_note_count=len(candidates),
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
        manifest["product_admission"] = product_admission
        atomic_write_json(normalized_dir / "gap_report.json", report)
        manifest["status"] = "succeeded"
    except (GapProbeError, OSError, RuntimeError, ValueError) as exc:
        manifest["status"] = "failed"
        manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        manifest["ended_at"] = _utc_now()
        manifest["outputs"] = _artifact_records(run_dir)
        atomic_write_json(run_dir / "run_manifest.json", manifest)
    if manifest["status"] != "succeeded":
        return manifest
    try:
        bundle_builder = (
            build_automatic_bundle
            if automatic_enhanced
            else build_review_bundle
        )
        arguments: dict[str, Any] = {
            "spec": spec,
            "source_voice_path": source_voice_path,
            "source_canonical": source_canonical,
            "source_events": source_events,
            "candidate_path": normalized_dir / "voice_gap_candidate.jsonl",
            "candidates": candidates,
            "parent_manifest_path": run_dir / "run_manifest.json",
            "output_dir": review_bundle,
        }
        if automatic_enhanced:
            arguments["product_candidates"] = (
                candidates
                if product_admission["accepted_for_automatic_merge"]
                else []
            )
        bundle_builder(project_dir, **arguments)
    except (GapProbeError, OSError, RuntimeError, ValueError) as exc:
        manifest["status"] = "failed"
        manifest["ended_at"] = _utc_now()
        manifest["error"] = {
            "type": type(exc).__name__,
            "message": f"review bundle failed: {exc}",
        }
        atomic_write_json(run_dir / "run_manifest.json", manifest)
    return manifest


def run_automatic_probe(
    project_dir: Path,
    *,
    probe_id: str,
    source_bundle_id: str,
    output_bundle_id: str,
    worker_env: Path,
    weight_provenance: Path,
    ffmpeg: str,
    source_voice_track_id: str = "voice",
    device: str = "cuda",
    require_slurm: bool = True,
    execution_backend: str = "slurm",
) -> dict[str, Any]:
    if require_slurm and not os.environ.get("SLURM_JOB_ID"):
        raise GapProbeError("automatic gap recovery requires a Slurm allocation")
    hostname = platform.node()
    if require_slurm and "login" in hostname:
        raise GapProbeError("refusing automatic gap recovery on a login node")
    if device not in {"cuda", "mps", "cpu", "auto"}:
        raise GapProbeError("unsupported MuScriptor device")
    if execution_backend not in {"slurm", "local"}:
        raise GapProbeError("unsupported execution backend")
    if require_slurm != (execution_backend == "slurm"):
        raise GapProbeError("execution backend does not match the Slurm requirement")
    project_dir = project_dir.expanduser().resolve()
    probe_id = _safe_identifier(probe_id, label="probe_id")
    source_bundle_id = _safe_identifier(
        source_bundle_id,
        label="source_bundle_id",
    )
    output_bundle_id = _safe_identifier(
        output_bundle_id,
        label="output_bundle_id",
    )
    if source_bundle_id == output_bundle_id:
        raise GapProbeError("automatic output bundle must differ from source bundle")
    output_dir = project_dir / "exports" / output_bundle_id
    report_dir = project_dir / "reports" / probe_id
    if report_dir.exists() or report_dir.is_symlink():
        raise GapProbeError(f"automatic recovery report already exists: {report_dir}")
    report_dir.mkdir(parents=True)

    try:
        spec = plan_automatic_probe(
            project_dir,
            probe_id=probe_id,
            source_bundle_id=source_bundle_id,
            source_voice_track_id=source_voice_track_id,
        )
        plan_path = report_dir / "plan.json"
        atomic_write_json(plan_path, spec_as_dict(spec))
        if spec.windows:
            manifest = run_probe(
                project_dir,
                plan_path,
                worker_env=worker_env,
                weight_provenance=weight_provenance,
                ffmpeg=ffmpeg,
                output_dir=output_dir,
                automatic_enhanced=True,
                device=device,
                require_slurm=require_slurm,
                execution_backend=execution_backend,
            )
            if manifest["status"] != "succeeded":
                decision = "publish_raw_multitrack_fallback"
            elif not manifest.get("product_admission", {}).get(
                "accepted_for_automatic_merge",
                False,
            ):
                decision = "automatic_candidates_preserved_but_not_merged"
            else:
                decision = "automatic_gap_recovery_completed"
        else:
            project, _audio, source_voice_path, source_canonical = _source_context(
                project_dir,
                spec,
            )
            source_events = read_jsonl(source_voice_path)
            run_dir = project_dir / "runs" / probe_id
            if run_dir.exists() or run_dir.is_symlink():
                raise GapProbeError(f"automatic recovery run already exists: {run_dir}")
            normalized_dir = run_dir / "normalized"
            normalized_dir.mkdir(parents=True)
            candidate_path = normalized_dir / "voice_gap_candidate.jsonl"
            write_jsonl(candidate_path, [])
            atomic_write_json(
                normalized_dir / "gap_report.json",
                {
                    "schema_version": 1,
                    "artifact_type": "amt-muscriptor-gap-probe-report",
                    "probe_id": probe_id,
                    "candidate_track_id": "voice_gap_candidate",
                    "source_track_id": source_voice_track_id,
                    "automatic_merge_performed": False,
                    "accuracy_claimed": False,
                    "candidate_note_count": 0,
                    "targets": [],
                    "decision": "no_eligible_long_voice_gaps",
                },
            )
            manifest = {
                "schema_version": 1,
                "artifact_type": "amt-muscriptor-gap-probe-run",
                "probe_id": probe_id,
                "project_id": project["project_id"],
                "status": "succeeded",
                "started_at": _utc_now(),
                "ended_at": _utc_now(),
                "hostname": hostname,
                "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
                "execution_backend": execution_backend,
                "device": device,
                "request_sha256": sha256_file(plan_path),
                "child_runs": [],
                "outputs": _artifact_records(run_dir),
                "code": run_baseline.git_state(run_baseline.REPO_ROOT),
                "decision": "no_eligible_long_voice_gaps",
                "error": None,
            }
            atomic_write_json(run_dir / "run_manifest.json", manifest)
            build_automatic_bundle(
                project_dir,
                spec=spec,
                source_voice_path=source_voice_path,
                source_canonical=source_canonical,
                source_events=source_events,
                candidate_path=candidate_path,
                candidates=[],
                parent_manifest_path=run_dir / "run_manifest.json",
                output_dir=output_dir,
            )
            decision = "no_eligible_long_voice_gaps"
        report = {
            "schema_version": 1,
            "artifact_type": "amt-automatic-voice-gap-recovery",
            "probe_id": probe_id,
            "source_bundle_id": source_bundle_id,
            "output_bundle_id": output_bundle_id,
            "status": manifest["status"],
            "decision": decision,
            "window_count": len(spec.windows),
            "accuracy_claimed": False,
            "source_separation_used": False,
            "second_melody_model_used": False,
            "fallback_required": manifest["status"] != "succeeded",
        }
        atomic_write_json(report_dir / "automatic_recovery.json", report)
        return manifest
    except (GapProbeError, OSError, RuntimeError, ValueError) as exc:
        atomic_write_json(
            report_dir / "automatic_recovery.json",
            {
                "schema_version": 1,
                "artifact_type": "amt-automatic-voice-gap-recovery",
                "probe_id": probe_id,
                "source_bundle_id": source_bundle_id,
                "output_bundle_id": output_bundle_id,
                "status": "failed",
                "decision": "publish_raw_multitrack_fallback",
                "accuracy_claimed": False,
                "fallback_required": True,
                "error": {"type": type(exc).__name__, "message": str(exc)},
            },
        )
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run same-model MuScriptor probes only over frozen voice gaps."
    )
    parser.add_argument("--project", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", type=Path)
    source.add_argument("--auto-source-bundle")
    parser.add_argument("--probe-id")
    parser.add_argument("--output-bundle")
    parser.add_argument("--source-voice-track", default="voice")
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--weight-provenance", type=Path, required=True)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--allow-local",
        action="store_true",
        help="Allow the explicit local backend instead of requiring Slurm.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.auto_source_bundle is not None:
            if not args.probe_id or not args.output_bundle:
                raise GapProbeError(
                    "automatic recovery requires --probe-id and --output-bundle"
                )
            manifest = run_automatic_probe(
                args.project,
                probe_id=args.probe_id,
                source_bundle_id=args.auto_source_bundle,
                output_bundle_id=args.output_bundle,
                worker_env=args.worker_env,
                weight_provenance=args.weight_provenance,
                ffmpeg=args.ffmpeg,
                source_voice_track_id=args.source_voice_track,
                device=args.device,
                require_slurm=not args.allow_local,
                execution_backend="local" if args.allow_local else "slurm",
            )
        else:
            manifest = run_probe(
                args.project,
                args.config,
                worker_env=args.worker_env,
                weight_provenance=args.weight_provenance,
                ffmpeg=args.ffmpeg,
                device=args.device,
                require_slurm=not args.allow_local,
                execution_backend="local" if args.allow_local else "slurm",
            )
    except GapProbeError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
