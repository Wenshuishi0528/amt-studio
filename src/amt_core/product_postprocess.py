from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from typing import Any

from .events import NoteEvent


def _ordered(events: list[NoteEvent]) -> list[NoteEvent]:
    return sorted(
        events,
        key=lambda event: (
            event.onset_sec,
            event.offset_sec,
            event.pitch_midi,
            event.event_id,
        ),
    )


def _copy_event(
    event: NoteEvent,
    *,
    tags: list[str],
    extra: dict[str, Any],
) -> NoteEvent:
    return NoteEvent(
        event_id=event.event_id,
        track_id=event.track_id,
        instrument=event.instrument,
        onset_sec=event.onset_sec,
        offset_sec=event.offset_sec,
        pitch_midi=event.pitch_midi,
        quantized_pitch_midi=event.quantized_pitch_midi,
        velocity=event.velocity,
        confidence=event.confidence,
        is_main_melody_candidate=event.is_main_melody_candidate,
        source_run_id=event.source_run_id,
        source_model=event.source_model,
        source_event_ids=list(event.source_event_ids),
        tags=tags,
        extra=extra,
    )


def clean_trailing_fragments(
    events: list[NoteEvent],
    *,
    timeline_end: float,
    run_id: str,
    maximum_gap_sec: float = 0.03,
    short_duration_sec: float = 0.35,
) -> tuple[list[NoteEvent], dict[str, Any]]:
    """Derive conservative pitched-track tail sustains without changing input."""

    if not math.isfinite(timeline_end) or timeline_end <= 0:
        raise ValueError("timeline_end must be finite and positive")
    if not run_id:
        raise ValueError("run_id is required")
    instruments = {
        (event.instrument or "").lower()
        for event in events
        if event.instrument
    }
    if "drums" in instruments or any("drum" in value for value in instruments):
        return _clean_trailing_percussion_repeats(
            events,
            timeline_end=timeline_end,
            run_id=run_id,
        )

    groups: list[list[NoteEvent]] = []
    by_pitch: dict[float, list[NoteEvent]] = defaultdict(list)
    for event in events:
        if event.onset_sec < timeline_end:
            by_pitch[round(event.pitch_midi, 6)].append(event)
    for pitch_events in by_pitch.values():
        chain: list[NoteEvent] = []
        chain_end = -math.inf
        for event in _ordered(pitch_events):
            if chain and event.onset_sec > chain_end + maximum_gap_sec:
                if _is_trailing_fragment_chain(
                    chain,
                    timeline_end=timeline_end,
                    short_duration_sec=short_duration_sec,
                ):
                    groups.append(chain)
                chain = []
                chain_end = -math.inf
            chain.append(event)
            chain_end = max(chain_end, event.offset_sec)
        if _is_trailing_fragment_chain(
            chain,
            timeline_end=timeline_end,
            short_duration_sec=short_duration_sec,
        ):
            groups.append(chain)

    removed_ids = {
        event.event_id
        for group in groups
        for event in group
    }
    cleaned = [event for event in events if event.event_id not in removed_ids]
    for group in groups:
        first = group[0]
        source_ids = sorted(
            {
                source_id
                for event in group
                for source_id in [event.event_id, *event.source_event_ids]
            }
        )
        digest = hashlib.sha256("\n".join(source_ids).encode()).hexdigest()[:16]
        extra = dict(first.extra)
        extra["automatic_sustain_cleanup"] = {
            "run_id": run_id,
            "source_event_ids": source_ids,
            "source_overwritten": False,
            "owner_approved": False,
        }
        confidences = [event.confidence for event in group]
        confidence = (
            min(value for value in confidences if value is not None)
            if all(value is not None for value in confidences)
            else None
        )
        cleaned.append(
            NoteEvent(
                event_id=f"{run_id}:sustain-cleanup:{digest}",
                track_id=first.track_id,
                instrument=first.instrument,
                onset_sec=first.onset_sec,
                offset_sec=min(
                    timeline_end,
                    max(event.offset_sec for event in group),
                ),
                pitch_midi=first.pitch_midi,
                quantized_pitch_midi=first.quantized_pitch_midi,
                velocity=first.velocity,
                confidence=confidence,
                is_main_melody_candidate=first.is_main_melody_candidate,
                source_run_id=run_id,
                source_model="deterministic:trailing-sustain-cleanup",
                source_event_ids=source_ids,
                tags=sorted(
                    {
                        tag
                        for event in group
                        for tag in [*event.tags, "automatic-sustain-cleanup"]
                    }
                ),
                extra=extra,
            )
        )
    return _ordered(cleaned), {
        "decision": (
            "derived_trailing_sustain_cleanup"
            if groups
            else "no_conservative_tail_candidate"
        ),
        "group_count": len(groups),
        "fragment_count": sum(len(group) for group in groups),
        "merged_note_count": len(groups),
        "source_overwritten": False,
    }


def _clean_trailing_percussion_repeats(
    events: list[NoteEvent],
    *,
    timeline_end: float,
    run_id: str,
    maximum_onset_gap_sec: float = 0.5,
    short_duration_sec: float = 0.1,
) -> tuple[list[NoteEvent], dict[str, Any]]:
    groups: list[list[NoteEvent]] = []
    by_pitch: dict[float, list[NoteEvent]] = defaultdict(list)
    for event in events:
        if event.onset_sec < timeline_end:
            by_pitch[round(event.pitch_midi, 6)].append(event)
    for pitch_events in by_pitch.values():
        sequence: list[NoteEvent] = []
        for event in _ordered(pitch_events):
            if (
                sequence
                and event.onset_sec - sequence[-1].onset_sec
                > maximum_onset_gap_sec
            ):
                if _is_trailing_percussion_sequence(
                    sequence,
                    timeline_end=timeline_end,
                    short_duration_sec=short_duration_sec,
                ):
                    groups.append(sequence)
                sequence = []
            sequence.append(event)
        if _is_trailing_percussion_sequence(
            sequence,
            timeline_end=timeline_end,
            short_duration_sec=short_duration_sec,
        ):
            groups.append(sequence)

    removed_ids = {
        event.event_id
        for group in groups
        for event in group
    }
    cleaned = [event for event in events if event.event_id not in removed_ids]
    for group in groups:
        first = group[0]
        source_ids = sorted(
            {
                source_id
                for event in group
                for source_id in [event.event_id, *event.source_event_ids]
            }
        )
        digest = hashlib.sha256("\n".join(source_ids).encode()).hexdigest()[:16]
        extra = dict(first.extra)
        extra["automatic_percussion_repeat_cleanup"] = {
            "run_id": run_id,
            "source_event_ids": source_ids,
            "kept_as_single_hit": True,
            "source_overwritten": False,
            "accuracy_claimed": False,
        }
        cleaned.append(
            NoteEvent(
                event_id=f"{run_id}:percussion-cleanup:{digest}",
                track_id=first.track_id,
                instrument=first.instrument,
                onset_sec=first.onset_sec,
                offset_sec=first.offset_sec,
                pitch_midi=first.pitch_midi,
                quantized_pitch_midi=first.quantized_pitch_midi,
                velocity=first.velocity,
                confidence=(
                    min(event.confidence for event in group)
                    if all(event.confidence is not None for event in group)
                    else None
                ),
                is_main_melody_candidate=first.is_main_melody_candidate,
                source_run_id=run_id,
                source_model="deterministic:trailing-percussion-repeat-cleanup",
                source_event_ids=source_ids,
                tags=sorted(
                    {
                        tag
                        for event in group
                        for tag in [
                            *event.tags,
                            "automatic-percussion-repeat-cleanup",
                        ]
                    }
                ),
                extra=extra,
            )
        )
    return _ordered(cleaned), {
        "decision": (
            "derived_trailing_percussion_repeat_cleanup"
            if groups
            else "no_conservative_tail_candidate"
        ),
        "group_count": len(groups),
        "fragment_count": sum(len(group) for group in groups),
        "merged_note_count": len(groups),
        "source_overwritten": False,
    }


def _is_trailing_percussion_sequence(
    events: list[NoteEvent],
    *,
    timeline_end: float,
    short_duration_sec: float,
) -> bool:
    if len(events) < 5:
        return False
    first = events[0]
    last = events[-1]
    if (
        last.offset_sec < timeline_end - 0.5
        or first.onset_sec < timeline_end - 15
        or last.offset_sec - first.onset_sec < 1
    ):
        return False
    short_count = sum(
        event.offset_sec - event.onset_sec <= short_duration_sec
        for event in events
    )
    return short_count * 2 >= len(events)


def _is_trailing_fragment_chain(
    events: list[NoteEvent],
    *,
    timeline_end: float,
    short_duration_sec: float,
) -> bool:
    if len(events) < 4:
        return False
    first = events[0]
    last_offset = max(event.offset_sec for event in events)
    if (
        last_offset < timeline_end - 0.5
        or first.onset_sec < timeline_end - 30
        or last_offset - first.onset_sec < 2
    ):
        return False
    short_count = sum(
        event.offset_sec - event.onset_sec <= short_duration_sec
        for event in events
    )
    return short_count >= 3 and short_count * 2 >= len(events)


def soft_mask_melody_candidates(
    candidates: list[NoteEvent],
    accompaniment: list[NoteEvent],
    *,
    probe_id: str,
    shadow_threshold: float = 0.7,
) -> tuple[list[NoteEvent], dict[str, Any]]:
    """Remove strong accompaniment copies, then keep one non-overlapping path."""

    if not probe_id:
        raise ValueError("probe_id is required")
    if not 0 < shadow_threshold <= 1:
        raise ValueError("shadow_threshold must be in (0, 1]")
    accompaniment_by_pitch: dict[int, list[NoteEvent]] = defaultdict(list)
    for event in accompaniment:
        accompaniment_by_pitch[round(event.pitch_midi)].append(event)

    scored: list[tuple[NoteEvent, float]] = []
    shadowed_ids: list[str] = []
    for candidate in candidates:
        shadow = _accompaniment_shadow(
            candidate,
            accompaniment_by_pitch.get(round(candidate.pitch_midi), []),
        )
        if shadow >= shadow_threshold:
            shadowed_ids.append(candidate.event_id)
            continue
        scored.append((candidate, shadow))

    selected = _maximum_weight_monophonic_path(scored)
    filtered: list[NoteEvent] = []
    for event, shadow in selected:
        extra = dict(event.extra)
        extra["accompaniment_soft_mask"] = {
            "probe_id": probe_id,
            "shadow_score": round(shadow, 6),
            "shadow_threshold": shadow_threshold,
            "monophonic_path_selected": True,
            "accuracy_claimed": False,
        }
        filtered.append(
            _copy_event(
                event,
                tags=sorted({*event.tags, "accompaniment-soft-mask"}),
                extra=extra,
            )
        )
    return _ordered(filtered), {
        "schema_version": 1,
        "artifact_type": "amt-accompaniment-soft-mask-report",
        "probe_id": probe_id,
        "raw_candidate_count": len(candidates),
        "accompaniment_shadow_count": len(shadowed_ids),
        "monophonic_rejection_count": len(scored) - len(selected),
        "filtered_candidate_count": len(filtered),
        "shadow_threshold": shadow_threshold,
        "shadowed_event_ids": sorted(shadowed_ids),
        "accuracy_claimed": False,
        "source_overwritten": False,
    }


def _accompaniment_shadow(
    candidate: NoteEvent,
    accompaniment: list[NoteEvent],
) -> float:
    duration = max(0.02, candidate.offset_sec - candidate.onset_sec)
    score = 0.0
    for event in accompaniment:
        if abs(event.pitch_midi - candidate.pitch_midi) > 0.5:
            continue
        overlap = min(candidate.offset_sec, event.offset_sec) - max(
            candidate.onset_sec,
            event.onset_sec,
        )
        if overlap <= 0.03:
            continue
        overlap_score = min(1.0, overlap / duration)
        onset_score = max(
            0.0,
            1.0 - abs(event.onset_sec - candidate.onset_sec) / 0.08,
        )
        score = max(score, overlap_score, onset_score)
    return score


def _maximum_weight_monophonic_path(
    scored: list[tuple[NoteEvent, float]],
) -> list[tuple[NoteEvent, float]]:
    ordered = sorted(
        scored,
        key=lambda item: (
            item[0].offset_sec,
            item[0].onset_sec,
            item[0].pitch_midi,
            item[0].event_id,
        ),
    )
    if not ordered:
        return []
    best_scores = [0.0] * (len(ordered) + 1)
    choices: list[tuple[bool, int]] = [(False, 0)] * (len(ordered) + 1)
    for index, (event, shadow) in enumerate(ordered, start=1):
        predecessor = 0
        for earlier in range(index - 1, 0, -1):
            previous = ordered[earlier - 1][0]
            if previous.offset_sec <= event.onset_sec + 0.03:
                predecessor = earlier
                break
        duration = min(1.0, event.offset_sec - event.onset_sec)
        weight = 1.0 - shadow + duration * 0.25
        include = best_scores[predecessor] + weight
        exclude = best_scores[index - 1]
        if include > exclude:
            best_scores[index] = include
            choices[index] = (True, predecessor)
        else:
            best_scores[index] = exclude
            choices[index] = (False, index - 1)

    selected: list[tuple[NoteEvent, float]] = []
    cursor = len(ordered)
    while cursor > 0:
        take, previous = choices[cursor]
        if take:
            selected.append(ordered[cursor - 1])
        cursor = previous
    selected.reverse()
    return selected


def residual_melody_gaps(
    *,
    start_sec: float,
    end_sec: float,
    events: list[NoteEvent],
    minimum_gap_sec: float = 3.0,
) -> list[tuple[float, float]]:
    if (
        not math.isfinite(start_sec)
        or not math.isfinite(end_sec)
        or end_sec <= start_sec
        or minimum_gap_sec <= 0
    ):
        raise ValueError("invalid residual-gap bounds")
    occupied: list[tuple[float, float]] = []
    for event in _ordered(events):
        start = max(start_sec, event.onset_sec)
        end = min(end_sec, event.offset_sec)
        if end <= start:
            continue
        if occupied and start <= occupied[-1][1]:
            occupied[-1] = (occupied[-1][0], max(occupied[-1][1], end))
        else:
            occupied.append((start, end))
    gaps: list[tuple[float, float]] = []
    cursor = start_sec
    for start, end in occupied:
        if start - cursor >= minimum_gap_sec:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if end_sec - cursor >= minimum_gap_sec:
        gaps.append((cursor, end_sec))
    return gaps
