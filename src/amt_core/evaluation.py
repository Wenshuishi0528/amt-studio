from __future__ import annotations

import hashlib
import heapq
import json
import math
import statistics
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .events import NoteEvent

REFERENCE_NOTE_SCHEMA = "amt-reference-note/v1"
CORRECTION_SESSION_SCHEMA = "amt-correction-session/v1"
AMBIGUITY_TAGS = {
    "harmony_overlap",
    "ornament",
    "pitch_center",
    "phrase_boundary",
    "source_identity",
    "timing",
    "weak_audibility",
}
CORRECTION_ACTIONS = {
    "add",
    "delete",
    "merge",
    "pitch",
    "reassign_instrument",
    "resize_offset",
    "shift_onset",
    "split",
}


class EvaluationError(ValueError):
    """Raised when reference annotations or evaluation inputs are invalid."""


def note_sequence_fingerprint(events: Iterable[NoteEvent]) -> str:
    """Hash only note semantics used by onset/pitch/offset/instrument scoring."""

    records: list[dict[str, Any]] = []
    for event in events:
        event.validate()
        records.append(
            {
                "onset_sec": round(float(event.onset_sec), 9),
                "offset_sec": round(float(event.offset_sec), 9),
                "pitch_midi": round(float(event.pitch_midi), 6),
                "instrument": event.instrument,
            }
        )
    records.sort(
        key=lambda record: (
            record["onset_sec"],
            record["offset_sec"],
            record["pitch_midi"],
            str(record["instrument"]),
        )
    )
    payload = json.dumps(
        {
            "schema": "amt-note-sequence-fingerprint/v1",
            "notes": records,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def project_note_events_to_melody_frames(
    events: Iterable[NoteEvent],
    frame_times_sec: Iterable[float],
    *,
    instrument: str = "voice",
) -> tuple[list[float], dict[str, Any]]:
    """Project note events to one deterministic predominant-melody contour.

    Only events with the exact requested instrument are eligible. When eligible
    events overlap, the highest pitch is selected, followed by the latest onset
    and then lexical event ID. The rule is fixed and reference-independent.
    """

    if not isinstance(instrument, str) or not instrument:
        raise EvaluationError("instrument must be a non-empty string")
    times = [
        _finite_number(value, label="frame time", minimum=0)
        for value in frame_times_sec
    ]
    if not times:
        raise EvaluationError("frame_times_sec must not be empty")
    if any(
        current <= previous
        for previous, current in zip(times, times[1:], strict=False)
    ):
        raise EvaluationError("frame_times_sec must be strictly increasing")

    materialized = list(events)
    for event in materialized:
        event.validate()
    selected = [event for event in materialized if event.instrument == instrument]
    selected_ids = [event.event_id for event in selected]
    if len(set(selected_ids)) != len(selected_ids):
        raise EvaluationError("eligible note events contain duplicate event_id values")
    eligible = sorted(
        selected,
        key=lambda event: (event.onset_sec, event.offset_sec, event.event_id),
    )
    active: dict[str, NoteEvent] = {}
    offset_heap: list[tuple[float, str]] = []
    pitch_heap: list[tuple[float, float, str]] = []
    event_index = 0
    overlap_frame_count = 0
    maximum_active_event_count = 0
    frequencies: list[float] = []

    for frame_time in times:
        while (
            event_index < len(eligible)
            and eligible[event_index].onset_sec <= frame_time
        ):
            event = eligible[event_index]
            active[event.event_id] = event
            heapq.heappush(offset_heap, (event.offset_sec, event.event_id))
            heapq.heappush(
                pitch_heap,
                (-event.pitch_midi, -event.onset_sec, event.event_id),
            )
            event_index += 1
        while offset_heap and offset_heap[0][0] <= frame_time:
            _offset, event_id = heapq.heappop(offset_heap)
            active.pop(event_id, None)
        while pitch_heap and pitch_heap[0][2] not in active:
            heapq.heappop(pitch_heap)

        active_count = len(active)
        maximum_active_event_count = max(maximum_active_event_count, active_count)
        if active_count > 1:
            overlap_frame_count += 1
        if not pitch_heap:
            frequencies.append(0.0)
            continue
        pitch_midi = -pitch_heap[0][0]
        frequencies.append(440.0 * (2.0 ** ((pitch_midi - 69.0) / 12.0)))

    return frequencies, {
        "schema": "amt-note-to-melody-projection/v1",
        "instrument_filter": instrument,
        "overlap_rule": "highest_pitch_then_latest_onset_then_lexical_event_id",
        "input_event_count": len(materialized),
        "eligible_event_count": len(eligible),
        "excluded_event_count": len(materialized) - len(eligible),
        "frame_count": len(times),
        "overlap_frame_count": overlap_frame_count,
        "overlap_frame_fraction": overlap_frame_count / len(times),
        "maximum_active_event_count": maximum_active_event_count,
    }


def _finite_number(value: Any, *, label: str, minimum: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvaluationError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise EvaluationError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise EvaluationError(f"{label} must be at least {minimum}")
    return number


def _unit_interval(value: Any, *, label: str) -> float:
    number = _finite_number(value, label=label, minimum=0)
    if number > 1:
        raise EvaluationError(f"{label} must be in [0, 1]")
    return number


@dataclass(frozen=True, slots=True)
class ReferenceNote:
    reference_note_id: str
    onset_sec: float
    offset_sec: float
    pitch_midi: float
    instrument: str
    annotator_confidence: float
    ambiguity_tags: tuple[str, ...] = ()
    evaluation_status: str = "include"
    exclusion_reason: str | None = None
    comment: str | None = None
    offset_censored: bool = False
    target_role: str = "main_melody"
    schema: str = REFERENCE_NOTE_SCHEMA

    @classmethod
    def from_dict(cls, value: Any) -> ReferenceNote:
        if not isinstance(value, dict):
            raise EvaluationError("reference note must be an object")
        ambiguity = value.get("ambiguity_tags", [])
        if not isinstance(ambiguity, list):
            raise EvaluationError("ambiguity_tags must be an array")
        note = cls(
            schema=value.get("schema"),
            reference_note_id=value.get("reference_note_id"),
            onset_sec=_finite_number(value.get("onset_sec"), label="onset_sec", minimum=0),
            offset_sec=_finite_number(value.get("offset_sec"), label="offset_sec", minimum=0),
            pitch_midi=_finite_number(value.get("pitch_midi"), label="pitch_midi"),
            instrument=value.get("instrument"),
            target_role=value.get("target_role", "main_melody"),
            annotator_confidence=_unit_interval(
                value.get("annotator_confidence"),
                label="annotator_confidence",
            ),
            ambiguity_tags=tuple(ambiguity),
            evaluation_status=value.get("evaluation_status", "include"),
            exclusion_reason=value.get("exclusion_reason"),
            comment=value.get("comment"),
            offset_censored=value.get("offset_censored", False),
        )
        note.validate()
        return note

    def validate(self) -> None:
        if self.schema != REFERENCE_NOTE_SCHEMA:
            raise EvaluationError(f"unsupported reference note schema: {self.schema!r}")
        if not isinstance(self.reference_note_id, str) or not self.reference_note_id:
            raise EvaluationError("reference_note_id is required")
        onset = _finite_number(self.onset_sec, label="onset_sec", minimum=0)
        offset = _finite_number(self.offset_sec, label="offset_sec", minimum=0)
        if offset <= onset:
            raise EvaluationError("offset_sec must be greater than onset_sec")
        pitch = _finite_number(self.pitch_midi, label="pitch_midi")
        if not 0 <= pitch <= 127:
            raise EvaluationError("pitch_midi must be in [0, 127]")
        if not isinstance(self.instrument, str) or not self.instrument:
            raise EvaluationError("instrument is required")
        if self.target_role not in {"main_melody", "drums", "bass", "harmonic"}:
            raise EvaluationError(f"unsupported target_role: {self.target_role!r}")
        _unit_interval(self.annotator_confidence, label="annotator_confidence")
        if len(set(self.ambiguity_tags)) != len(self.ambiguity_tags):
            raise EvaluationError("ambiguity_tags must be unique")
        unknown = sorted(set(self.ambiguity_tags) - AMBIGUITY_TAGS)
        if unknown:
            raise EvaluationError(f"unsupported ambiguity_tags: {unknown}")
        if self.evaluation_status not in {"include", "exclude"}:
            raise EvaluationError("evaluation_status must be include or exclude")
        if self.evaluation_status == "exclude" and not self.exclusion_reason:
            raise EvaluationError("excluded reference notes require exclusion_reason")
        if self.evaluation_status == "include" and self.exclusion_reason is not None:
            raise EvaluationError("included reference notes cannot have exclusion_reason")
        if self.comment is not None and not isinstance(self.comment, str):
            raise EvaluationError("comment must be a string or null")
        if not isinstance(self.offset_censored, bool):
            raise EvaluationError("offset_censored must be boolean")
        if self.offset_censored and "phrase_boundary" not in self.ambiguity_tags:
            raise EvaluationError(
                "offset-censored notes require phrase_boundary ambiguity"
            )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema,
            "reference_note_id": self.reference_note_id,
            "onset_sec": self.onset_sec,
            "offset_sec": self.offset_sec,
            "pitch_midi": self.pitch_midi,
            "instrument": self.instrument,
            "target_role": self.target_role,
            "annotator_confidence": self.annotator_confidence,
            "ambiguity_tags": list(self.ambiguity_tags),
            "evaluation_status": self.evaluation_status,
            "exclusion_reason": self.exclusion_reason,
            "comment": self.comment,
            "offset_censored": self.offset_censored,
        }


@dataclass(frozen=True, slots=True)
class EvaluationConfig:
    onset_tolerance_sec: float = 0.05
    pitch_tolerance_cents: float = 50.0
    offset_ratio: float = 0.2
    offset_min_tolerance_sec: float = 0.05
    high_reference_confidence: float = 0.8
    confidence_thresholds: tuple[float, ...] = (0.25, 0.5, 0.75, 0.9)

    def validate(self) -> None:
        for label, value in (
            ("onset_tolerance_sec", self.onset_tolerance_sec),
            ("pitch_tolerance_cents", self.pitch_tolerance_cents),
            ("offset_ratio", self.offset_ratio),
            ("offset_min_tolerance_sec", self.offset_min_tolerance_sec),
        ):
            if _finite_number(value, label=label) <= 0:
                raise EvaluationError(f"{label} must be positive")
        _unit_interval(
            self.high_reference_confidence,
            label="high_reference_confidence",
        )
        if tuple(sorted(set(self.confidence_thresholds))) != self.confidence_thresholds:
            raise EvaluationError("confidence_thresholds must be unique and increasing")
        for threshold in self.confidence_thresholds:
            _unit_interval(threshold, label="confidence threshold")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "onset_tolerance_sec": self.onset_tolerance_sec,
            "pitch_tolerance_cents": self.pitch_tolerance_cents,
            "offset_ratio": self.offset_ratio,
            "offset_min_tolerance_sec": self.offset_min_tolerance_sec,
            "high_reference_confidence": self.high_reference_confidence,
            "confidence_thresholds": list(self.confidence_thresholds),
            "threshold_comparison": "inclusive",
        }


def read_reference_jsonl(path: Path) -> list[ReferenceNote]:
    notes: list[ReferenceNote] = []
    identifiers: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                note = ReferenceNote.from_dict(json.loads(line))
            except (json.JSONDecodeError, EvaluationError, TypeError) as exc:
                raise EvaluationError(f"{path}:{line_number}: {exc}") from exc
            if note.reference_note_id in identifiers:
                raise EvaluationError(
                    f"{path}:{line_number}: duplicate reference_note_id "
                    f"{note.reference_note_id!r}"
                )
            identifiers.add(note.reference_note_id)
            notes.append(note)
    return notes


def write_reference_jsonl(path: Path, notes: Iterable[ReferenceNote]) -> None:
    materialized = list(notes)
    identifiers = [note.reference_note_id for note in materialized]
    if len(set(identifiers)) != len(identifiers):
        raise EvaluationError("reference_note_id values must be unique")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for note in materialized:
            handle.write(json.dumps(note.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    temporary.replace(path)


def _chroma_distance_midi(first: float, second: float) -> float:
    difference = (first - second + 6.0) % 12.0 - 6.0
    return abs(difference)


def _within_tolerance(distance: float, tolerance: float) -> bool:
    return distance <= tolerance + 1e-12


def _maximum_matching(
    references: list[ReferenceNote],
    estimates: list[NoteEvent],
    compatible: Callable[[ReferenceNote, NoteEvent], bool],
    cost: Callable[[ReferenceNote, NoteEvent], tuple[float, ...]],
) -> list[tuple[int, int]]:
    if not references or not estimates:
        return []

    sample_cost = cost(references[0], estimates[0])
    zero = tuple(0.0 for _ in sample_cost)

    def add_cost(
        first: tuple[float, ...],
        second: tuple[float, ...],
    ) -> tuple[float, ...]:
        return tuple(left + right for left, right in zip(first, second, strict=True))

    def negate_cost(value: tuple[float, ...]) -> tuple[float, ...]:
        return tuple(-part for part in value)

    source = 0
    reference_base = 1
    estimate_base = reference_base + len(references)
    sink = estimate_base + len(estimates)
    node_count = sink + 1
    graph: list[list[list[Any]]] = [[] for _ in range(node_count)]
    candidate_edges: list[tuple[int, int, list[Any]]] = []

    def add_edge(
        start: int,
        end: int,
        capacity: int,
        edge_cost: tuple[float, ...],
    ) -> list[Any]:
        forward: list[Any] = [end, len(graph[end]), capacity, edge_cost]
        reverse: list[Any] = [
            start,
            len(graph[start]),
            0,
            negate_cost(edge_cost),
        ]
        graph[start].append(forward)
        graph[end].append(reverse)
        return forward

    for reference_index in range(len(references)):
        add_edge(source, reference_base + reference_index, 1, zero)
    for estimate_index in range(len(estimates)):
        add_edge(estimate_base + estimate_index, sink, 1, zero)
    for reference_index, reference in enumerate(references):
        for estimate_index, estimate in enumerate(estimates):
            if not compatible(reference, estimate):
                continue
            edge = add_edge(
                reference_base + reference_index,
                estimate_base + estimate_index,
                1,
                cost(reference, estimate),
            )
            candidate_edges.append((reference_index, estimate_index, edge))

    # Successive shortest augmenting paths on the residual graph produce a
    # maximum-cardinality matching with globally minimum lexicographic cost.
    # Bellman-Ford is deliberate: reverse residual edges have negative costs.
    while True:
        distances: list[tuple[float, ...] | None] = [None] * node_count
        previous: list[tuple[int, int] | None] = [None] * node_count
        distances[source] = zero
        for _ in range(node_count - 1):
            changed = False
            for start in range(node_count):
                if distances[start] is None:
                    continue
                for edge_index, edge in enumerate(graph[start]):
                    end, _reverse, capacity, edge_cost = edge
                    if capacity <= 0:
                        continue
                    candidate_distance = add_cost(distances[start], edge_cost)
                    if distances[end] is None or candidate_distance < distances[end]:
                        distances[end] = candidate_distance
                        previous[end] = (start, edge_index)
                        changed = True
            if not changed:
                break
        if previous[sink] is None:
            break
        node = sink
        while node != source:
            prior = previous[node]
            if prior is None:
                raise EvaluationError("matching residual path is incomplete")
            start, edge_index = prior
            edge = graph[start][edge_index]
            edge[2] -= 1
            graph[node][edge[1]][2] += 1
            node = start

    return sorted(
        (reference_index, estimate_index)
        for reference_index, estimate_index, edge in candidate_edges
        if edge[2] == 0
    )


def _prf(match_count: int, reference_count: int, estimate_count: int) -> dict[str, Any]:
    if reference_count == 0 and estimate_count == 0:
        precision = recall = 1.0
    else:
        precision = match_count / estimate_count if estimate_count else 0.0
        recall = match_count / reference_count if reference_count else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "matches": match_count,
        "reference_count": reference_count,
        "estimate_count": estimate_count,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _note_matches(
    references: list[ReferenceNote],
    estimates: list[NoteEvent],
    config: EvaluationConfig,
    *,
    require_pitch: bool,
    chroma_only: bool = False,
    require_offset: bool = False,
) -> list[tuple[int, int]]:
    def compatible(reference: ReferenceNote, estimate: NoteEvent) -> bool:
        if not _within_tolerance(
            abs(reference.onset_sec - estimate.onset_sec),
            config.onset_tolerance_sec,
        ):
            return False
        if require_pitch:
            pitch_distance = (
                _chroma_distance_midi(reference.pitch_midi, estimate.pitch_midi)
                if chroma_only
                else abs(reference.pitch_midi - estimate.pitch_midi)
            )
            if not _within_tolerance(
                pitch_distance * 100,
                config.pitch_tolerance_cents,
            ):
                return False
        if require_offset:
            if reference.offset_censored:
                return True
            tolerance = max(
                config.offset_min_tolerance_sec,
                config.offset_ratio * (reference.offset_sec - reference.onset_sec),
            )
            if not _within_tolerance(
                abs(reference.offset_sec - estimate.offset_sec),
                tolerance,
            ):
                return False
        return True

    def cost(reference: ReferenceNote, estimate: NoteEvent) -> tuple[float, ...]:
        pitch_distance = (
            _chroma_distance_midi(reference.pitch_midi, estimate.pitch_midi)
            if chroma_only
            else abs(reference.pitch_midi - estimate.pitch_midi)
        )
        return (
            abs(reference.onset_sec - estimate.onset_sec),
            pitch_distance,
            (
                0.0
                if reference.offset_censored
                else abs(reference.offset_sec - estimate.offset_sec)
            ),
        )

    return _maximum_matching(references, estimates, compatible, cost)


def _primary_metrics(
    references: list[ReferenceNote],
    estimates: list[NoteEvent],
    config: EvaluationConfig,
) -> dict[str, Any]:
    onset = _note_matches(
        references,
        estimates,
        config,
        require_pitch=False,
    )
    onset_pitch = _note_matches(
        references,
        estimates,
        config,
        require_pitch=True,
    )
    onset_pitch_offset = _note_matches(
        references,
        estimates,
        config,
        require_pitch=True,
        require_offset=True,
    )
    onset_chroma = _note_matches(
        references,
        estimates,
        config,
        require_pitch=True,
        chroma_only=True,
    )
    octave_errors = sum(
        abs(references[reference_index].pitch_midi - estimates[estimate_index].pitch_midi)
        * 100
        > config.pitch_tolerance_cents
        for reference_index, estimate_index in onset_chroma
    )
    instrument_pairs = [
        (references[reference_index].instrument, estimates[estimate_index].instrument)
        for reference_index, estimate_index in onset_pitch
        if references[reference_index].instrument and estimates[estimate_index].instrument
    ]
    instrument_correct = sum(reference == estimate for reference, estimate in instrument_pairs)
    return {
        "onset_only": _prf(len(onset), len(references), len(estimates)),
        "onset_pitch": _prf(len(onset_pitch), len(references), len(estimates)),
        "onset_pitch_offset": _prf(
            len(onset_pitch_offset),
            len(references),
            len(estimates),
        ),
        "offset_censored_reference_count": sum(
            reference.offset_censored for reference in references
        ),
        "onset_chroma": _prf(len(onset_chroma), len(references), len(estimates)),
        "octave_error": {
            "errors": octave_errors,
            "onset_chroma_matches": len(onset_chroma),
            "rate": octave_errors / len(onset_chroma) if onset_chroma else None,
            "denominator_definition": "onset_and_chroma_matched_pairs",
        },
        "instrument_assignment": {
            "correct": instrument_correct,
            "eligible_matches": len(instrument_pairs),
            "accuracy": instrument_correct / len(instrument_pairs)
            if instrument_pairs
            else None,
        },
    }


def evaluate_notes(
    references: Iterable[ReferenceNote],
    estimates: Iterable[NoteEvent],
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    config = config or EvaluationConfig()
    config.validate()
    all_references = list(references)
    all_estimates = list(estimates)
    for reference in all_references:
        reference.validate()
    for estimate in all_estimates:
        estimate.validate()

    included = [note for note in all_references if note.evaluation_status == "include"]
    excluded = [note for note in all_references if note.evaluation_status == "exclude"]
    high_agreement = [
        note
        for note in included
        if note.annotator_confidence >= config.high_reference_confidence
        and not note.ambiguity_tags
    ]
    confidence_available = [
        estimate for estimate in all_estimates if estimate.confidence is not None
    ]
    confidence_coverage: list[dict[str, Any]] = []
    if confidence_available:
        for threshold in config.confidence_thresholds:
            selected = [
                estimate
                for estimate in confidence_available
                if estimate.confidence is not None and estimate.confidence >= threshold
            ]
            confidence_coverage.append(
                {
                    "threshold": threshold,
                    "estimate_retention": len(selected) / len(all_estimates)
                    if all_estimates
                    else 0.0,
                    "estimates_retained": len(selected),
                    "estimates_total": len(all_estimates),
                    "estimates_missing_confidence": len(all_estimates)
                    - len(confidence_available),
                    "onset_pitch": _primary_metrics(included, selected, config)["onset_pitch"],
                }
            )

    omitted_from_secondary = [
        note for note in included if note not in high_agreement
    ]
    omitted_matches = _note_matches(
        omitted_from_secondary,
        all_estimates,
        config,
        require_pitch=True,
    )
    omitted_estimate_indexes = {
        estimate_index for _reference_index, estimate_index in omitted_matches
    }
    secondary_estimates = [
        estimate
        for index, estimate in enumerate(all_estimates)
        if index not in omitted_estimate_indexes
    ]

    return {
        "schema": "amt-note-evaluation/v1",
        "metric_definitions": {
            **config.to_dict(),
            "pitch_unit": "midi_semitones_with_100_cents_per_semitone",
            "offset_tolerance": "max(offset_min_tolerance_sec, offset_ratio * reference_duration)",
            "offset_censoring": (
                "offset_censored references require onset+pitch but do not "
                "test offset"
            ),
            "matching": "maximum_cardinality_one_to_one",
            "primary_reference_policy": "all_included_human_confirmed_notes",
            "secondary_reference_policy": (
                "included_notes_without_ambiguity_tags_at_or_above_"
                f"{config.high_reference_confidence}_annotator_confidence; "
                "estimates matched to omitted included references are masked"
            ),
            "confidence_coverage": (
                "estimate_retention_is_fraction_of_all_estimates; recall is reference coverage"
            ),
        },
        "reference_summary": {
            "total": len(all_references),
            "included": len(included),
            "excluded": len(excluded),
            "high_agreement": len(high_agreement),
            "ambiguity_tag_counts": dict(
                sorted(Counter(tag for note in included for tag in note.ambiguity_tags).items())
            ),
        },
        "estimate_summary": {
            "total": len(all_estimates),
            "confidence_available": len(confidence_available),
            "confidence_missing": len(all_estimates) - len(confidence_available),
        },
        "primary": _primary_metrics(included, all_estimates, config),
        "high_agreement_secondary": _primary_metrics(
            high_agreement,
            secondary_estimates,
            config,
        ),
        "confidence_coverage_status": (
            "available"
            if confidence_available
            else "unavailable_no_candidate_confidence"
        ),
        "confidence_coverage": confidence_coverage,
    }


def evaluate_timed_events(
    reference_times: Iterable[float],
    estimate_times: Iterable[float],
    *,
    tolerance_sec: float = 0.07,
) -> dict[str, Any]:
    tolerance = _finite_number(tolerance_sec, label="tolerance_sec")
    if tolerance <= 0:
        raise EvaluationError("tolerance_sec must be positive")
    references = sorted(
        _finite_number(value, label="reference event time", minimum=0)
        for value in reference_times
    )
    estimates = sorted(
        _finite_number(value, label="estimate event time", minimum=0)
        for value in estimate_times
    )
    reference_index = 0
    estimate_index = 0
    matches = 0
    absolute_errors: list[float] = []
    while reference_index < len(references) and estimate_index < len(estimates):
        delta = estimates[estimate_index] - references[reference_index]
        if _within_tolerance(abs(delta), tolerance):
            matches += 1
            absolute_errors.append(abs(delta))
            reference_index += 1
            estimate_index += 1
        elif estimates[estimate_index] < references[reference_index] - tolerance:
            estimate_index += 1
        else:
            reference_index += 1
    return {
        "schema": "amt-timed-event-evaluation/v1",
        "tolerance_sec": tolerance,
        "threshold_comparison": "inclusive",
        **_prf(matches, len(references), len(estimates)),
        "mean_absolute_error_sec": (
            sum(absolute_errors) / len(absolute_errors) if absolute_errors else None
        ),
    }


def evaluate_melody_frames(
    reference_frequencies_hz: Iterable[float],
    estimate_frequencies_hz: Iterable[float],
    *,
    cent_tolerance: float = 50.0,
) -> dict[str, Any]:
    """Evaluate aligned monophonic f0 frames using standard melody metrics."""

    tolerance = _finite_number(
        cent_tolerance,
        label="cent_tolerance",
    )
    if tolerance <= 0:
        raise EvaluationError("cent_tolerance must be positive")
    references = [
        _finite_number(value, label="reference frequency", minimum=0)
        for value in reference_frequencies_hz
    ]
    estimates = [
        _finite_number(value, label="estimate frequency", minimum=0)
        for value in estimate_frequencies_hz
    ]
    if not references:
        raise EvaluationError("melody frame sequences must not be empty")
    if len(references) != len(estimates):
        raise EvaluationError(
            "reference and estimate melody frame sequences must have equal length"
        )

    reference_voiced_count = sum(value > 0 for value in references)
    reference_unvoiced_count = len(references) - reference_voiced_count
    estimate_voiced_count = sum(value > 0 for value in estimates)
    both_voiced_count = 0
    voicing_true_positive_count = 0
    voicing_false_positive_count = 0
    pitch_correct_count = 0
    chroma_correct_count = 0
    correct_unvoiced_count = 0
    absolute_pitch_errors_cents: list[float] = []

    for reference, estimate in zip(references, estimates, strict=True):
        reference_voiced = reference > 0
        estimate_voiced = estimate > 0
        if not reference_voiced:
            if estimate_voiced:
                voicing_false_positive_count += 1
            else:
                correct_unvoiced_count += 1
            continue
        if not estimate_voiced:
            continue
        both_voiced_count += 1
        voicing_true_positive_count += 1
        signed_error_cents = 1200.0 * math.log2(estimate / reference)
        absolute_error_cents = abs(signed_error_cents)
        absolute_pitch_errors_cents.append(absolute_error_cents)
        if _within_tolerance(absolute_error_cents, tolerance):
            pitch_correct_count += 1
        chroma_error_cents = abs((signed_error_cents + 600.0) % 1200.0 - 600.0)
        if _within_tolerance(chroma_error_cents, tolerance):
            chroma_correct_count += 1

    return {
        "schema": "amt-melody-frame-evaluation/v1",
        "cent_tolerance": tolerance,
        "threshold_comparison": "inclusive",
        "frame_count": len(references),
        "reference_voiced_count": reference_voiced_count,
        "reference_unvoiced_count": reference_unvoiced_count,
        "estimate_voiced_count": estimate_voiced_count,
        "both_voiced_count": both_voiced_count,
        "voicing_true_positive_count": voicing_true_positive_count,
        "voicing_false_positive_count": voicing_false_positive_count,
        "pitch_correct_count": pitch_correct_count,
        "chroma_correct_count": chroma_correct_count,
        "correct_unvoiced_count": correct_unvoiced_count,
        "voicing_recall": (
            voicing_true_positive_count / reference_voiced_count
            if reference_voiced_count
            else None
        ),
        "voicing_false_alarm": (
            voicing_false_positive_count / reference_unvoiced_count
            if reference_unvoiced_count
            else None
        ),
        "raw_pitch_accuracy": (
            pitch_correct_count / reference_voiced_count
            if reference_voiced_count
            else None
        ),
        "raw_chroma_accuracy": (
            chroma_correct_count / reference_voiced_count
            if reference_voiced_count
            else None
        ),
        "overall_accuracy": (
            pitch_correct_count + correct_unvoiced_count
        )
        / len(references),
        "mean_absolute_pitch_error_cents_both_voiced": (
            sum(absolute_pitch_errors_cents) / both_voiced_count
            if both_voiced_count
            else None
        ),
        "median_absolute_pitch_error_cents_both_voiced": (
            statistics.median(absolute_pitch_errors_cents)
            if both_voiced_count
            else None
        ),
        "undefined_denominator_policy": "null",
    }


@dataclass(frozen=True, slots=True)
class CorrectionOperation:
    operation_id: str
    action: str
    elapsed_edit_sec: float
    source_note_ids: tuple[str, ...] = ()
    result_note_ids: tuple[str, ...] = ()
    comment: str | None = None

    @classmethod
    def from_dict(cls, value: Any) -> CorrectionOperation:
        if not isinstance(value, dict):
            raise EvaluationError("correction operation must be an object")
        source = value.get("source_note_ids", [])
        result = value.get("result_note_ids", [])
        if not isinstance(source, list) or not isinstance(result, list):
            raise EvaluationError("correction note IDs must be arrays")
        operation = cls(
            operation_id=value.get("operation_id"),
            action=value.get("action"),
            elapsed_edit_sec=_finite_number(
                value.get("elapsed_edit_sec"),
                label="elapsed_edit_sec",
                minimum=0,
            ),
            source_note_ids=tuple(source),
            result_note_ids=tuple(result),
            comment=value.get("comment"),
        )
        operation.validate()
        return operation

    def validate(self) -> None:
        if not isinstance(self.operation_id, str) or not self.operation_id:
            raise EvaluationError("correction operation_id is required")
        if self.action not in CORRECTION_ACTIONS:
            raise EvaluationError(f"unsupported correction action: {self.action!r}")
        _finite_number(self.elapsed_edit_sec, label="elapsed_edit_sec", minimum=0)
        for values, label in (
            (self.source_note_ids, "source_note_ids"),
            (self.result_note_ids, "result_note_ids"),
        ):
            if any(not isinstance(value, str) or not value for value in values):
                raise EvaluationError(f"{label} must contain non-empty strings")
        if self.comment is not None and not isinstance(self.comment, str):
            raise EvaluationError("correction comment must be a string or null")


def summarize_correction_session(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EvaluationError("correction session must be an object")
    if value.get("schema") != CORRECTION_SESSION_SCHEMA:
        raise EvaluationError(f"unsupported correction session schema: {value.get('schema')!r}")
    for field_name in ("session_id", "excerpt_id"):
        field_value = value.get(field_name)
        if not isinstance(field_value, str) or not field_value:
            raise EvaluationError(f"{field_name} is required")
    for field_name in ("benchmark_freeze_sha256", "candidate_sha256"):
        field_value = value.get(field_name)
        if (
            not isinstance(field_value, str)
            or len(field_value) != 64
            or any(character not in "0123456789abcdef" for character in field_value)
        ):
            raise EvaluationError(f"{field_name} must be a lowercase SHA-256")
    granularity = value.get("review_granularity")
    if granularity not in {
        "note_level_edit",
        "whole_excerpt_aural_comparison",
    }:
        raise EvaluationError(
            "review_granularity must be note_level_edit or "
            "whole_excerpt_aural_comparison"
        )
    playback_count = value.get("full_playback_count")
    if playback_count is not None and (
        isinstance(playback_count, bool)
        or not isinstance(playback_count, int)
        or playback_count < 1
    ):
        raise EvaluationError("full_playback_count must be a positive integer")
    additional_review = value.get("additional_review_sec")
    if additional_review is not None:
        _finite_number(
            additional_review,
            label="additional_review_sec",
            minimum=0,
        )
    decision = value.get("decision")
    if decision is not None and decision not in {"accept_seed", "accept_empty"}:
        raise EvaluationError("correction decision is unsupported")
    audio_duration = _finite_number(
        value.get("audio_duration_sec"),
        label="audio_duration_sec",
        minimum=0,
    )
    if audio_duration <= 0:
        raise EvaluationError("audio_duration_sec must be positive")
    total_edit_time = _finite_number(
        value.get("total_edit_time_sec"),
        label="total_edit_time_sec",
        minimum=0,
    )
    if granularity == "whole_excerpt_aural_comparison":
        if (
            playback_count is None
            or additional_review is None
            or decision is None
        ):
            raise EvaluationError(
                "whole_excerpt_aural_comparison requires full_playback_count "
                "additional_review_sec, and decision"
            )
        minimum_review_time = playback_count * audio_duration + float(
            additional_review
        )
        if total_edit_time + 1e-6 < minimum_review_time:
            raise EvaluationError(
                "total_edit_time_sec does not account for declared full "
                "playbacks and additional review"
            )
    raw_operations = value.get("operations")
    if not isinstance(raw_operations, list):
        raise EvaluationError("operations must be an array")
    operations = [CorrectionOperation.from_dict(item) for item in raw_operations]
    if granularity == "note_level_edit" and (
        not operations or total_edit_time <= 0
    ):
        raise EvaluationError(
            "note_level_edit requires at least one logged operation and "
            "positive total_edit_time_sec"
        )
    identifiers = [operation.operation_id for operation in operations]
    if len(set(identifiers)) != len(identifiers):
        raise EvaluationError("correction operation_id values must be unique")
    accounted_time = sum(operation.elapsed_edit_sec for operation in operations)
    if accounted_time > total_edit_time + 1e-6:
        raise EvaluationError("operation elapsed time exceeds total_edit_time_sec")
    action_counts = Counter(operation.action for operation in operations)
    duration_minutes = audio_duration / 60
    return {
        "schema": "amt-correction-summary/v1",
        "session_id": value["session_id"],
        "benchmark_freeze_sha256": value["benchmark_freeze_sha256"],
        "excerpt_id": value["excerpt_id"],
        "candidate_sha256": value["candidate_sha256"],
        "audio_duration_sec": audio_duration,
        "review_granularity": granularity,
        "full_playback_count": playback_count,
        "additional_review_sec": additional_review,
        "decision": decision,
        "operation_count": len(operations),
        "action_counts": {
            action: action_counts.get(action, 0) for action in sorted(CORRECTION_ACTIONS)
        },
        "total_edit_time_sec": total_edit_time,
        "operation_time_sec": accounted_time,
        "unattributed_review_time_sec": total_edit_time - accounted_time,
        "corrections_per_minute_audio": len(operations) / duration_minutes,
        "edit_seconds_per_minute_audio": total_edit_time / duration_minutes,
    }
