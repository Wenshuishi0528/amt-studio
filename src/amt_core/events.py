from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class EventValidationError(ValueError):
    """Raised for invalid canonical note events."""


@dataclass(slots=True)
class NoteEvent:
    event_id: str
    track_id: str
    onset_sec: float
    offset_sec: float
    pitch_midi: float
    source_run_id: str
    source_model: str
    instrument: str | None = None
    quantized_pitch_midi: int | None = None
    velocity: int | None = None
    confidence: float | None = None
    is_main_melody_candidate: bool = False
    source_event_ids: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1

    def validate(self) -> None:
        if self.schema_version != 1:
            raise EventValidationError(f"Unsupported schema_version: {self.schema_version}")
        if not self.event_id or not self.track_id:
            raise EventValidationError("event_id and track_id are required")
        if not math.isfinite(self.onset_sec) or self.onset_sec < 0:
            raise EventValidationError("onset_sec must be finite and non-negative")
        if not math.isfinite(self.offset_sec) or self.offset_sec <= self.onset_sec:
            raise EventValidationError(
                "offset_sec must be finite and greater than onset_sec"
            )
        if not math.isfinite(self.pitch_midi) or not 0 <= self.pitch_midi <= 127:
            raise EventValidationError("pitch_midi must be finite and in [0, 127]")
        if self.quantized_pitch_midi is not None and not 0 <= self.quantized_pitch_midi <= 127:
            raise EventValidationError("quantized_pitch_midi must be in [0, 127]")
        if self.velocity is not None and not 0 <= self.velocity <= 127:
            raise EventValidationError("velocity must be in [0, 127]")
        if self.confidence is not None and (
            not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1
        ):
            raise EventValidationError("confidence must be finite and in [0, 1]")
        if not self.source_run_id or not self.source_model:
            raise EventValidationError("source_run_id and source_model are required")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> NoteEvent:
        event = cls(**value)
        event.validate()
        return event

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "track_id": self.track_id,
            "instrument": self.instrument,
            "onset_sec": self.onset_sec,
            "offset_sec": self.offset_sec,
            "pitch_midi": self.pitch_midi,
            "quantized_pitch_midi": self.quantized_pitch_midi,
            "velocity": self.velocity,
            "confidence": self.confidence,
            "is_main_melody_candidate": self.is_main_melody_candidate,
            "source_run_id": self.source_run_id,
            "source_model": self.source_model,
            "source_event_ids": self.source_event_ids,
            "tags": self.tags,
            "extra": self.extra,
        }


def read_jsonl(path: Path) -> list[NoteEvent]:
    events: list[NoteEvent] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
                events.append(NoteEvent.from_dict(value))
            except (json.JSONDecodeError, TypeError, EventValidationError) as exc:
                raise EventValidationError(f"{path}:{line_number}: {exc}") from exc
    return events


def write_jsonl(path: Path, events: Iterable[NoteEvent]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8") as handle:
        for event in events:
            handle.write(json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    temp.replace(path)
