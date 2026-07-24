from __future__ import annotations

import argparse
import ast
import math
import statistics
import struct
from pathlib import Path
from typing import Any

from amt_core.canonical import MeterPoint, RhythmEvent, RhythmMap, TempoPoint
from amt_core.utils import atomic_write_json


class NativeRhythmError(ValueError):
    """Raised when Beat This native rhythm output is malformed."""


def probe_npy(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) < 10 or payload[:6] != b"\x93NUMPY":
        raise NativeRhythmError("activation output is not a NumPy .npy file")
    version = (payload[6], payload[7])
    if version == (1, 0):
        header_size = struct.unpack("<H", payload[8:10])[0]
        header_start = 10
    elif version in {(2, 0), (3, 0)}:
        if len(payload) < 12:
            raise NativeRhythmError("activation .npy header is truncated")
        header_size = struct.unpack("<I", payload[8:12])[0]
        header_start = 12
    else:
        raise NativeRhythmError(f"unsupported activation .npy version: {version}")
    header_end = header_start + header_size
    if header_end > len(payload):
        raise NativeRhythmError("activation .npy header is truncated")
    try:
        header = ast.literal_eval(
            payload[header_start:header_end]
            .decode("latin1" if version != (3, 0) else "utf-8")
            .strip()
        )
    except (SyntaxError, ValueError, UnicodeDecodeError) as exc:
        raise NativeRhythmError("activation .npy header is invalid") from exc
    if not isinstance(header, dict):
        raise NativeRhythmError("activation .npy header is not a dictionary")
    shape = header.get("shape")
    descr = header.get("descr")
    fortran_order = header.get("fortran_order")
    if (
        not isinstance(shape, tuple)
        or len(shape) != 2
        or shape[0] != 2
        or isinstance(shape[1], bool)
        or not isinstance(shape[1], int)
        or shape[1] < 1
    ):
        raise NativeRhythmError("activation .npy must have shape (2, frame_count)")
    if descr not in {"<f4", ">f4", "=f4", "|f4"} or fortran_order is not False:
        raise NativeRhythmError("activation .npy must be a C-order float32 beat/downbeat matrix")
    expected_size = header_end + 2 * shape[1] * 4
    if len(payload) != expected_size:
        raise NativeRhythmError(
            f"activation .npy size does not match its header: {len(payload)} != {expected_size}"
        )
    return {
        "version": list(version),
        "descr": descr,
        "fortran_order": fortran_order,
        "shape": list(shape),
        "frame_count": shape[1],
        "data_offset_bytes": header_end,
    }


def parse_beats(path: Path, *, duration_sec: float) -> list[tuple[float, int]]:
    if not math.isfinite(duration_sec) or duration_sec <= 0:
        raise NativeRhythmError("audio duration must be finite and positive")
    rows: list[tuple[float, int]] = []
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not raw_line.strip():
            continue
        fields = raw_line.split("\t")
        if len(fields) != 2:
            raise NativeRhythmError(f"{path}:{line_number}: expected TIME<TAB>BEAT_NUMBER")
        try:
            time_sec = float(fields[0])
            beat_number = int(fields[1])
        except ValueError as exc:
            raise NativeRhythmError(f"{path}:{line_number}: invalid beat row") from exc
        if not math.isfinite(time_sec) or not 0 <= time_sec <= duration_sec + 0.02:
            raise NativeRhythmError(f"{path}:{line_number}: beat time is outside the audio")
        if not 1 <= beat_number <= 32:
            raise NativeRhythmError(f"{path}:{line_number}: beat number is outside [1, 32]")
        if rows and time_sec <= rows[-1][0]:
            raise NativeRhythmError(f"{path}:{line_number}: beat times must increase")
        if rows:
            previous_number = rows[-1][1]
            if beat_number != 1 and beat_number != previous_number + 1:
                raise NativeRhythmError(
                    f"{path}:{line_number}: beat numbering must increment or reset to 1"
                )
        rows.append((time_sec, beat_number))
    if len(rows) < 2:
        raise NativeRhythmError("Beat This output must contain at least two beats")
    return rows


def _tempo_points(events: list[RhythmEvent]) -> tuple[TempoPoint, ...]:
    points: list[TempoPoint] = []
    bpms: list[float] = []
    for first, second in zip(events, events[1:], strict=False):
        interval = second.time_sec - first.time_sec
        bpm = 60.0 / interval
        if not 1 <= bpm <= 1000:
            raise NativeRhythmError(f"derived adjacent-beat tempo is implausible: {bpm}")
        bpms.append(bpm)
    for index, (first, second) in enumerate(zip(events, events[1:], strict=False)):
        neighboring = [bpms[index]]
        if index:
            neighboring.append(bpms[index - 1])
        if index + 1 < len(bpms):
            neighboring.append(bpms[index + 1])
        uncertainty = max(neighboring) - min(neighboring) if len(neighboring) > 1 else None
        points.append(
            TempoPoint(
                time_sec=first.time_sec,
                bpm=round(bpms[index], 9),
                confidence=None,
                uncertainty_bpm=None if uncertainty is None else round(uncertainty, 9),
                source_event_ids=(first.event_id, second.event_id),
                method="adjacent_beat_interval_v1",
            )
        )
    return tuple(points)


def _meter_points(events: list[RhythmEvent]) -> tuple[MeterPoint, ...]:
    downbeat_indices = [index for index, event in enumerate(events) if event.is_downbeat]
    if len(downbeat_indices) < 2:
        source = events[downbeat_indices[0] if downbeat_indices else 0]
        return (
            MeterPoint(
                time_sec=source.time_sec,
                numerator=4,
                denominator=4,
                confidence=None,
                source_event_ids=(source.event_id,),
                status="defaulted",
            ),
        )

    points: list[MeterPoint] = []
    previous_numerator: int | None = None
    for first_index, second_index in zip(
        downbeat_indices,
        downbeat_indices[1:],
        strict=False,
    ):
        numerator = second_index - first_index
        if not 1 <= numerator <= 32:
            raise NativeRhythmError("inferred meter numerator is outside [1, 32]")
        if numerator != previous_numerator:
            first = events[first_index]
            second = events[second_index]
            points.append(
                MeterPoint(
                    time_sec=first.time_sec,
                    numerator=numerator,
                    denominator=4,
                    confidence=None,
                    source_event_ids=(first.event_id, second.event_id),
                    status="inferred",
                )
            )
            previous_numerator = numerator
    return tuple(points)


def normalize_native_rhythm(
    beats_path: Path,
    activations_path: Path,
    *,
    run_id: str,
    source_model: str,
    canonical_audio_sha256: str,
    duration_sec: float,
    frame_rate_hz: int = 50,
) -> tuple[RhythmMap, dict[str, Any]]:
    rows = parse_beats(beats_path, duration_sec=duration_sec)
    npy = probe_npy(activations_path)
    expected_frames = math.ceil(duration_sec * frame_rate_hz)
    frame_delta = abs(npy["frame_count"] - expected_frames)
    if frame_delta > frame_rate_hz:
        raise NativeRhythmError(
            "activation frame count differs from the audio duration by more than one second"
        )
    events = [
        RhythmEvent(
            event_id=f"{run_id}-beat-{index + 1:06d}",
            time_sec=round(time_sec, 9),
            beat_number=beat_number,
            is_downbeat=beat_number == 1,
            confidence=None,
            source_frame_index=round(time_sec * frame_rate_hz),
        )
        for index, (time_sec, beat_number) in enumerate(rows)
    ]
    tempo = _tempo_points(events)
    meter = _meter_points(events)
    rhythm = RhythmMap(
        source_run_id=run_id,
        source_model=source_model,
        canonical_audio_sha256=canonical_audio_sha256,
        events=tuple(events),
        tempo_map=tempo,
        meter_map=meter,
        uncertainty={
            "event_confidence_available": False,
            "probabilities_calibrated": False,
            "raw_framewise_logits_preserved": True,
            "raw_framewise_logits_path": "raw/native/mix.npy",
            "reason": (
                "Beat This CLI emits framewise logits but no calibrated per-event "
                "confidence. Event confidence remains null."
            ),
            "tempo_uncertainty_definition": (
                "local range across the current and adjacent beat-interval BPM values"
            ),
            "meter_status_meaning": (
                "inferred counts beats between consecutive downbeats; defaulted uses "
                "4/4 when fewer than two downbeats are available"
            ),
        },
    )
    rhythm.validate()
    bpms = [point.bpm for point in tempo]
    summary = {
        "schema_version": 1,
        "run_id": run_id,
        "beat_count": len(events),
        "downbeat_count": sum(event.is_downbeat for event in events),
        "first_beat_sec": events[0].time_sec,
        "last_beat_sec": events[-1].time_sec,
        "tempo_bpm": {
            "minimum": min(bpms),
            "median": statistics.median(bpms),
            "maximum": max(bpms),
        },
        "meter_change_count": len(meter),
        "meters": [
            {
                "time_sec": point.time_sec,
                "numerator": point.numerator,
                "denominator": point.denominator,
                "status": point.status,
            }
            for point in meter
        ],
        "activation_npy": npy,
        "expected_frame_count_ceil": expected_frames,
        "activation_frame_delta": frame_delta,
        "accuracy_claimed": False,
    }
    return rhythm, summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Normalize Beat This timestamps without importing its model stack."
    )
    parser.add_argument("--beats", type=Path, required=True)
    parser.add_argument("--activations", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-model", required=True)
    parser.add_argument("--canonical-audio-sha256", required=True)
    parser.add_argument("--duration-sec", type=float, required=True)
    parser.add_argument("--frame-rate-hz", type=int, default=50)
    parser.add_argument("--rhythm-output", type=Path, required=True)
    parser.add_argument("--summary-output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rhythm, summary = normalize_native_rhythm(
        args.beats,
        args.activations,
        run_id=args.run_id,
        source_model=args.source_model,
        canonical_audio_sha256=args.canonical_audio_sha256,
        duration_sec=args.duration_sec,
        frame_rate_hz=args.frame_rate_hz,
    )
    atomic_write_json(args.rhythm_output, rhythm.to_dict())
    atomic_write_json(args.summary_output, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
