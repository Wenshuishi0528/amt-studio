from __future__ import annotations

import math
import os
import struct
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .canonical import MeterPoint, TempoPoint
from .events import NoteEvent


class MidiExportError(ValueError):
    """Raised when a performance MIDI export cannot be represented safely."""


def _vlq(value: int) -> bytes:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise MidiExportError("MIDI variable-length value must be a non-negative integer")
    buffer = value & 0x7F
    while value := value >> 7:
        buffer <<= 8
        buffer |= (value & 0x7F) | 0x80
    output = bytearray()
    while True:
        output.append(buffer & 0xFF)
        if buffer & 0x80:
            buffer >>= 8
        else:
            return bytes(output)


def _meta(meta_type: int, payload: bytes) -> bytes:
    return bytes((0xFF, meta_type)) + _vlq(len(payload)) + payload


def _track_chunk(events: list[tuple[int, int, bytes]]) -> bytes:
    events.sort(key=lambda item: (item[0], item[1], item[2]))
    body = bytearray()
    previous_tick = 0
    for tick, _priority, message in events:
        if tick < previous_tick:
            raise MidiExportError("MIDI events are not time-sorted")
        body.extend(_vlq(tick - previous_tick))
        body.extend(message)
        previous_tick = tick
    body.extend(_vlq(0))
    body.extend(_meta(0x2F, b""))
    return b"MTrk" + struct.pack(">I", len(body)) + body


@dataclass(frozen=True, slots=True)
class _TempoSegment:
    time_sec: float
    tick_float: float
    tick: int
    tempo_us_per_beat: int


class TempoTimeline:
    def __init__(self, points: Iterable[TempoPoint], *, ticks_per_beat: int) -> None:
        if not 24 <= ticks_per_beat <= 32767:
            raise MidiExportError("ticks_per_beat must be in [24, 32767]")
        ordered = sorted(points, key=lambda point: point.time_sec)
        if not ordered:
            raise MidiExportError("at least one tempo point is required")
        for point in ordered:
            point.validate()
        if len({point.time_sec for point in ordered}) != len(ordered):
            raise MidiExportError("tempo point times must be unique")
        if ordered[0].time_sec > 0:
            first = ordered[0]
            ordered.insert(
                0,
                TempoPoint(
                    time_sec=0.0,
                    bpm=first.bpm,
                    confidence=first.confidence,
                    uncertainty_bpm=first.uncertainty_bpm,
                    source_event_ids=first.source_event_ids,
                    method=f"backfilled_from_{first.method}",
                ),
            )
        self.ticks_per_beat = ticks_per_beat
        segments: list[_TempoSegment] = []
        tick_float = 0.0
        previous_time = ordered[0].time_sec
        previous_tempo = self._tempo_us(ordered[0].bpm)
        for index, point in enumerate(ordered):
            if index:
                delta = point.time_sec - previous_time
                tick_float += delta * ticks_per_beat * 1_000_000.0 / previous_tempo
            tempo = self._tempo_us(point.bpm)
            segments.append(
                _TempoSegment(
                    time_sec=point.time_sec,
                    tick_float=tick_float,
                    tick=round(tick_float),
                    tempo_us_per_beat=tempo,
                )
            )
            previous_time = point.time_sec
            previous_tempo = tempo
        self.segments = tuple(segments)

    @staticmethod
    def _tempo_us(bpm: float) -> int:
        if not math.isfinite(bpm) or not 1 <= bpm <= 1000:
            raise MidiExportError("tempo BPM must be finite and in [1, 1000]")
        return min(0xFFFFFF, max(1, round(60_000_000 / bpm)))

    def seconds_to_ticks(self, time_sec: float) -> int:
        if not math.isfinite(time_sec) or time_sec < 0:
            raise MidiExportError("event time must be finite and non-negative")
        segment = self.segments[0]
        for candidate in self.segments[1:]:
            if candidate.time_sec > time_sec:
                break
            segment = candidate
        delta = time_sec - segment.time_sec
        tick_float = (
            segment.tick_float
            + delta * self.ticks_per_beat * 1_000_000.0 / segment.tempo_us_per_beat
        )
        return max(0, round(tick_float))

    def ticks_to_seconds(self, tick: int) -> float:
        if isinstance(tick, bool) or not isinstance(tick, int) or tick < 0:
            raise MidiExportError("tick must be a non-negative integer")
        segments = sorted(self.segments, key=lambda segment: segment.tick)
        elapsed = 0.0
        previous_tick = 0
        tempo = segments[0].tempo_us_per_beat
        for segment in segments[1:]:
            if segment.tick > tick:
                break
            elapsed += (segment.tick - previous_tick) * tempo / (1_000_000.0 * self.ticks_per_beat)
            previous_tick = segment.tick
            tempo = segment.tempo_us_per_beat
        elapsed += (tick - previous_tick) * tempo / (1_000_000.0 * self.ticks_per_beat)
        return elapsed


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        with suppress(FileNotFoundError):
            os.unlink(temporary_name)
        raise


def export_performance_midi(
    path: Path,
    tracks: dict[str, Iterable[NoteEvent]],
    tempo_points: Iterable[TempoPoint],
    meter_points: Iterable[MeterPoint],
    *,
    ticks_per_beat: int = 960,
) -> dict[str, int | float | str]:
    if not tracks:
        raise MidiExportError("at least one performance track is required")
    if len(tracks) > 15:
        raise MidiExportError("performance MIDI v1 supports at most 15 candidate tracks")
    timeline = TempoTimeline(tempo_points, ticks_per_beat=ticks_per_beat)

    conductor_events: list[tuple[int, int, bytes]] = [
        (0, 0, _meta(0x03, b"AMT Studio tempo and meter"))
    ]
    for segment in timeline.segments:
        conductor_events.append(
            (
                segment.tick,
                1,
                _meta(0x51, segment.tempo_us_per_beat.to_bytes(3, "big")),
            )
        )
    for point in sorted(meter_points, key=lambda item: item.time_sec):
        point.validate()
        denominator_power = int(math.log2(point.denominator))
        conductor_events.append(
            (
                timeline.seconds_to_ticks(point.time_sec),
                2,
                _meta(0x58, bytes((point.numerator, denominator_power, 24, 8))),
            )
        )

    midi_tracks = [_track_chunk(conductor_events)]
    note_count = 0
    maximum_timing_error = 0.0
    channels = [channel for channel in range(16) if channel != 9]
    for channel, (track_name, raw_events) in zip(
        channels,
        tracks.items(),
        strict=False,
    ):
        encoded_events: list[tuple[int, int, bytes]] = [
            (0, 0, _meta(0x03, track_name.encode("utf-8")))
        ]
        for event in raw_events:
            event.validate()
            onset_tick = timeline.seconds_to_ticks(event.onset_sec)
            offset_tick = max(
                onset_tick + 1,
                timeline.seconds_to_ticks(event.offset_sec),
            )
            pitch = min(127, max(0, int(math.floor(event.pitch_midi + 0.5))))
            velocity = event.velocity if event.velocity not in (None, 0) else 64
            velocity = min(127, max(1, velocity))
            encoded_events.append((onset_tick, 2, bytes((0x90 | channel, pitch, velocity))))
            encoded_events.append((offset_tick, 1, bytes((0x80 | channel, pitch, 0))))
            maximum_timing_error = max(
                maximum_timing_error,
                abs(timeline.ticks_to_seconds(onset_tick) - event.onset_sec),
                abs(timeline.ticks_to_seconds(offset_tick) - event.offset_sec),
            )
            note_count += 1
        midi_tracks.append(_track_chunk(encoded_events))

    header = b"MThd" + struct.pack(">IHHH", 6, 1, len(midi_tracks), ticks_per_beat)
    _atomic_write_bytes(path, header + b"".join(midi_tracks))
    return {
        "representation": "performance",
        "track_count": len(tracks),
        "note_count": note_count,
        "ticks_per_beat": ticks_per_beat,
        "maximum_internal_roundtrip_error_sec": round(maximum_timing_error, 9),
        "pitch_policy": "nearest_integer_midi_json_retains_float_pitch",
    }
