from __future__ import annotations

import json
import math
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .events import NoteEvent


class CanonicalValidationError(ValueError):
    """Raised when canonical project or rhythm data is malformed."""


def _finite_non_negative(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalValidationError(f"{label} must be a number")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise CanonicalValidationError(f"{label} must be finite and non-negative")
    return number


def _optional_unit_interval(value: Any, *, label: str) -> float | None:
    if value is None:
        return None
    number = _finite_non_negative(value, label=label)
    if number > 1:
        raise CanonicalValidationError(f"{label} must be in [0, 1]")
    return number


def _validate_sha256(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CanonicalValidationError(f"{label} SHA-256 is invalid")
    return value


@dataclass(frozen=True, slots=True)
class ProvenanceRef:
    source_run_id: str
    source_model: str
    run_manifest_sha256: str
    normalized_artifact_sha256: str
    source_event_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        if not self.source_run_id or not self.source_model:
            raise CanonicalValidationError("provenance source run and model are required")
        for label, value in (
            ("run manifest", self.run_manifest_sha256),
            ("normalized artifact", self.normalized_artifact_sha256),
        ):
            _validate_sha256(value, label=label)
        return {
            "source_run_id": self.source_run_id,
            "source_model": self.source_model,
            "run_manifest_sha256": self.run_manifest_sha256,
            "normalized_artifact_sha256": self.normalized_artifact_sha256,
            "source_event_ids": list(self.source_event_ids),
        }


@dataclass(frozen=True, slots=True)
class CanonicalTrack:
    track_id: str
    label: str
    role: str
    instrument: str | None
    event_count: int
    source_events_path: str
    provenance: ProvenanceRef

    def to_dict(self) -> dict[str, Any]:
        if not self.track_id or not self.label:
            raise CanonicalValidationError("track_id and label are required")
        if self.role not in {"candidate", "final"}:
            raise CanonicalValidationError("track role must be candidate or final")
        if isinstance(self.event_count, bool) or not isinstance(self.event_count, int):
            raise CanonicalValidationError("track event_count must be an integer")
        if self.event_count < 0:
            raise CanonicalValidationError("track event_count must be non-negative")
        if self.instrument is not None and not isinstance(self.instrument, str):
            raise CanonicalValidationError("track instrument must be a string or null")
        if not isinstance(self.source_events_path, str) or not self.source_events_path:
            raise CanonicalValidationError("track source_events_path is required")
        return {
            "track_id": self.track_id,
            "label": self.label,
            "role": self.role,
            "instrument": self.instrument,
            "event_count": self.event_count,
            "source_events_path": self.source_events_path,
            "provenance": self.provenance.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RhythmEvent:
    event_id: str
    time_sec: float
    beat_number: int
    is_downbeat: bool
    confidence: float | None
    source_frame_index: int | None

    @classmethod
    def from_dict(cls, value: Any) -> RhythmEvent:
        if not isinstance(value, dict):
            raise CanonicalValidationError("rhythm event must be an object")
        event = cls(
            event_id=value.get("event_id"),
            time_sec=_finite_non_negative(value.get("time_sec"), label="rhythm time_sec"),
            beat_number=value.get("beat_number"),
            is_downbeat=value.get("is_downbeat"),
            confidence=_optional_unit_interval(
                value.get("confidence"),
                label="rhythm confidence",
            ),
            source_frame_index=value.get("source_frame_index"),
        )
        event.validate()
        return event

    def validate(self) -> None:
        if not self.event_id:
            raise CanonicalValidationError("rhythm event_id is required")
        _finite_non_negative(self.time_sec, label="rhythm time_sec")
        if (
            isinstance(self.beat_number, bool)
            or not isinstance(self.beat_number, int)
            or self.beat_number < 1
        ):
            raise CanonicalValidationError("beat_number must be a positive integer")
        if not isinstance(self.is_downbeat, bool):
            raise CanonicalValidationError("is_downbeat must be boolean")
        if self.is_downbeat != (self.beat_number == 1):
            raise CanonicalValidationError("downbeat flag must match beat_number 1")
        _optional_unit_interval(self.confidence, label="rhythm confidence")
        if self.source_frame_index is not None and (
            isinstance(self.source_frame_index, bool)
            or not isinstance(self.source_frame_index, int)
            or self.source_frame_index < 0
        ):
            raise CanonicalValidationError(
                "source_frame_index must be a non-negative integer or null"
            )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "event_id": self.event_id,
            "time_sec": self.time_sec,
            "beat_number": self.beat_number,
            "is_downbeat": self.is_downbeat,
            "confidence": self.confidence,
            "source_frame_index": self.source_frame_index,
        }


@dataclass(frozen=True, slots=True)
class TempoPoint:
    time_sec: float
    bpm: float
    confidence: float | None
    uncertainty_bpm: float | None
    source_event_ids: tuple[str, ...]
    method: str

    @classmethod
    def from_dict(cls, value: Any) -> TempoPoint:
        if not isinstance(value, dict):
            raise CanonicalValidationError("tempo point must be an object")
        point = cls(
            time_sec=_finite_non_negative(value.get("time_sec"), label="tempo time_sec"),
            bpm=_finite_non_negative(value.get("bpm"), label="tempo bpm"),
            confidence=_optional_unit_interval(
                value.get("confidence"),
                label="tempo confidence",
            ),
            uncertainty_bpm=None
            if value.get("uncertainty_bpm") is None
            else _finite_non_negative(
                value.get("uncertainty_bpm"),
                label="tempo uncertainty_bpm",
            ),
            source_event_ids=tuple(value.get("source_event_ids", [])),
            method=value.get("method"),
        )
        point.validate()
        return point

    def validate(self) -> None:
        _finite_non_negative(self.time_sec, label="tempo time_sec")
        bpm = _finite_non_negative(self.bpm, label="tempo bpm")
        if not 1 <= bpm <= 1000:
            raise CanonicalValidationError("tempo bpm must be in [1, 1000]")
        _optional_unit_interval(self.confidence, label="tempo confidence")
        if self.uncertainty_bpm is not None:
            _finite_non_negative(self.uncertainty_bpm, label="tempo uncertainty_bpm")
        if not self.method:
            raise CanonicalValidationError("tempo method is required")
        if not self.source_event_ids or any(
            not isinstance(event_id, str) or not event_id for event_id in self.source_event_ids
        ):
            raise CanonicalValidationError("tempo point requires provenance events")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "time_sec": self.time_sec,
            "bpm": self.bpm,
            "confidence": self.confidence,
            "uncertainty_bpm": self.uncertainty_bpm,
            "source_event_ids": list(self.source_event_ids),
            "method": self.method,
        }


@dataclass(frozen=True, slots=True)
class MeterPoint:
    time_sec: float
    numerator: int
    denominator: int
    confidence: float | None
    source_event_ids: tuple[str, ...]
    status: str

    @classmethod
    def from_dict(cls, value: Any) -> MeterPoint:
        if not isinstance(value, dict):
            raise CanonicalValidationError("meter point must be an object")
        point = cls(
            time_sec=_finite_non_negative(value.get("time_sec"), label="meter time_sec"),
            numerator=value.get("numerator"),
            denominator=value.get("denominator"),
            confidence=_optional_unit_interval(
                value.get("confidence"),
                label="meter confidence",
            ),
            source_event_ids=tuple(value.get("source_event_ids", [])),
            status=value.get("status"),
        )
        point.validate()
        return point

    def validate(self) -> None:
        _finite_non_negative(self.time_sec, label="meter time_sec")
        if (
            isinstance(self.numerator, bool)
            or not isinstance(self.numerator, int)
            or not 1 <= self.numerator <= 32
        ):
            raise CanonicalValidationError("meter numerator must be in [1, 32]")
        if (
            isinstance(self.denominator, bool)
            or not isinstance(self.denominator, int)
            or self.denominator not in {1, 2, 4, 8, 16, 32}
        ):
            raise CanonicalValidationError("meter denominator is unsupported")
        _optional_unit_interval(self.confidence, label="meter confidence")
        if self.status not in {"observed", "inferred", "defaulted"}:
            raise CanonicalValidationError("meter status is unsupported")
        if not self.source_event_ids or any(
            not isinstance(event_id, str) or not event_id for event_id in self.source_event_ids
        ):
            raise CanonicalValidationError("meter point requires provenance events")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "time_sec": self.time_sec,
            "numerator": self.numerator,
            "denominator": self.denominator,
            "confidence": self.confidence,
            "source_event_ids": list(self.source_event_ids),
            "status": self.status,
        }


@dataclass(frozen=True, slots=True)
class RhythmMap:
    source_run_id: str
    source_model: str
    canonical_audio_sha256: str
    events: tuple[RhythmEvent, ...]
    tempo_map: tuple[TempoPoint, ...]
    meter_map: tuple[MeterPoint, ...]
    uncertainty: dict[str, Any]
    timeline_basis: str = "original_canonical_mix_seconds"
    schema_version: int = 1

    @classmethod
    def from_dict(cls, value: Any) -> RhythmMap:
        if not isinstance(value, dict):
            raise CanonicalValidationError("rhythm map must be an object")
        rhythm = cls(
            schema_version=value.get("schema_version"),
            timeline_basis=value.get("timeline_basis"),
            source_run_id=value.get("source_run_id"),
            source_model=value.get("source_model"),
            canonical_audio_sha256=value.get("canonical_audio_sha256"),
            events=tuple(RhythmEvent.from_dict(item) for item in value.get("events", [])),
            tempo_map=tuple(TempoPoint.from_dict(item) for item in value.get("tempo_map", [])),
            meter_map=tuple(MeterPoint.from_dict(item) for item in value.get("meter_map", [])),
            uncertainty=value.get("uncertainty"),
        )
        rhythm.validate()
        return rhythm

    def validate(self) -> None:
        if self.schema_version != 1:
            raise CanonicalValidationError("unsupported rhythm map schema_version")
        if self.timeline_basis != "original_canonical_mix_seconds":
            raise CanonicalValidationError("unsupported rhythm timeline basis")
        if not self.source_run_id or not self.source_model:
            raise CanonicalValidationError("rhythm source run and model are required")
        _validate_sha256(self.canonical_audio_sha256, label="canonical audio")
        if not self.events or not self.tempo_map or not self.meter_map:
            raise CanonicalValidationError("rhythm events, tempo map, and meter map are required")
        event_times = [event.time_sec for event in self.events]
        if event_times != sorted(event_times) or len(set(event_times)) != len(event_times):
            raise CanonicalValidationError("rhythm events must be strictly increasing in time")
        tempo_times = [point.time_sec for point in self.tempo_map]
        meter_times = [point.time_sec for point in self.meter_map]
        if tempo_times != sorted(tempo_times) or meter_times != sorted(meter_times):
            raise CanonicalValidationError("tempo and meter maps must be time-sorted")
        if not isinstance(self.uncertainty, dict):
            raise CanonicalValidationError("rhythm uncertainty must be an object")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "timeline_basis": self.timeline_basis,
            "source_run_id": self.source_run_id,
            "source_model": self.source_model,
            "canonical_audio_sha256": self.canonical_audio_sha256,
            "events": [event.to_dict() for event in self.events],
            "tempo_map": [point.to_dict() for point in self.tempo_map],
            "meter_map": [point.to_dict() for point in self.meter_map],
            "uncertainty": self.uncertainty,
        }


@dataclass(frozen=True, slots=True)
class ScoreGridNote:
    score_note_id: str
    source_event_id: str
    track_id: str
    pitch_midi: int
    onset_beats: float
    duration_beats: float
    performance_onset_sec: float
    performance_offset_sec: float
    grid_subdivision: int
    derivation: str = "nearest_beat_subdivision_v1"
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        if (
            self.schema_version != 1
            or not self.score_note_id
            or not self.source_event_id
            or not self.track_id
        ):
            raise CanonicalValidationError("score-grid note identity is invalid")
        if (
            isinstance(self.pitch_midi, bool)
            or not isinstance(self.pitch_midi, int)
            or not 0 <= self.pitch_midi <= 127
        ):
            raise CanonicalValidationError("score-grid pitch must be in [0, 127]")
        _finite_non_negative(self.onset_beats, label="score-grid onset_beats")
        duration = _finite_non_negative(
            self.duration_beats,
            label="score-grid duration_beats",
        )
        if duration <= 0:
            raise CanonicalValidationError("score-grid duration must be positive")
        onset_sec = _finite_non_negative(
            self.performance_onset_sec,
            label="score-grid performance_onset_sec",
        )
        offset_sec = _finite_non_negative(
            self.performance_offset_sec,
            label="score-grid performance_offset_sec",
        )
        if offset_sec <= onset_sec:
            raise CanonicalValidationError("score-grid performance offset must follow onset")
        if (
            isinstance(self.grid_subdivision, bool)
            or not isinstance(self.grid_subdivision, int)
            or self.grid_subdivision < 1
        ):
            raise CanonicalValidationError("grid subdivision must be positive")
        if self.derivation != "nearest_beat_subdivision_v1":
            raise CanonicalValidationError("score-grid derivation is unsupported")
        return {
            "schema_version": self.schema_version,
            "score_note_id": self.score_note_id,
            "source_event_id": self.source_event_id,
            "track_id": self.track_id,
            "pitch_midi": self.pitch_midi,
            "onset_beats": self.onset_beats,
            "duration_beats": self.duration_beats,
            "performance_onset_sec": self.performance_onset_sec,
            "performance_offset_sec": self.performance_offset_sec,
            "grid_subdivision": self.grid_subdivision,
            "derivation": self.derivation,
        }


def load_rhythm_map(path: Path) -> RhythmMap:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CanonicalValidationError(f"cannot read rhythm map: {exc}") from exc
    return RhythmMap.from_dict(value)


def _continuous_beat_position(time_sec: float, beat_times: list[float]) -> float:
    if len(beat_times) < 2:
        raise CanonicalValidationError("score-grid mapping requires at least two beats")
    index = bisect_right(beat_times, time_sec) - 1
    if index < 0:
        interval = beat_times[1] - beat_times[0]
        return (time_sec - beat_times[0]) / interval
    if index >= len(beat_times) - 1:
        interval = beat_times[-1] - beat_times[-2]
        return len(beat_times) - 1 + (time_sec - beat_times[-1]) / interval
    interval = beat_times[index + 1] - beat_times[index]
    return index + (time_sec - beat_times[index]) / interval


def build_score_grid(
    tracks: dict[str, Iterable[NoteEvent]],
    rhythm: RhythmMap,
    *,
    subdivision: int = 4,
) -> list[ScoreGridNote]:
    if (
        isinstance(subdivision, bool)
        or not isinstance(subdivision, int)
        or subdivision < 1
        or subdivision > 32
    ):
        raise CanonicalValidationError("subdivision must be in [1, 32]")
    beat_times = [event.time_sec for event in rhythm.events]
    grid = 1.0 / subdivision
    score_notes: list[ScoreGridNote] = []
    for track_id, events in tracks.items():
        for event in events:
            event.validate()
            onset = round(_continuous_beat_position(event.onset_sec, beat_times) / grid) * grid
            offset = round(_continuous_beat_position(event.offset_sec, beat_times) / grid) * grid
            offset = max(offset, onset + grid)
            pitch = min(127, max(0, int(math.floor(event.pitch_midi + 0.5))))
            score_notes.append(
                ScoreGridNote(
                    score_note_id=f"score-{track_id}-{event.event_id}",
                    source_event_id=event.event_id,
                    track_id=track_id,
                    pitch_midi=pitch,
                    onset_beats=round(onset, 9),
                    duration_beats=round(offset - onset, 9),
                    performance_onset_sec=event.onset_sec,
                    performance_offset_sec=event.offset_sec,
                    grid_subdivision=subdivision,
                )
            )
    return sorted(
        score_notes,
        key=lambda note: (note.onset_beats, note.track_id, note.pitch_midi, note.score_note_id),
    )
