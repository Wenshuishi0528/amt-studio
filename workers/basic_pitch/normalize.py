from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import atomic_write_json

EXPECTED_HEADER = [
    "start_time_s",
    "end_time_s",
    "pitch_midi",
    "velocity",
    "pitch_bend",
]


class NativeEventError(ValueError):
    """Raised when a Basic Pitch native note-event CSV violates its contract."""


def _float_field(value: str, *, field: str, path: Path, row_number: int) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise NativeEventError(f"{path}:{row_number}: {field} must be a number") from exc
    if not math.isfinite(parsed):
        raise NativeEventError(f"{path}:{row_number}: {field} must be finite")
    return parsed


def _int_field(value: str, *, field: str, path: Path, row_number: int) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise NativeEventError(f"{path}:{row_number}: {field} must be an integer") from exc
    return parsed


def normalize_note_events(
    native_csv: Path,
    output_path: Path,
    summary_path: Path,
    *,
    run_id: str,
    source_model: str,
) -> dict[str, Any]:
    canonical: list[NoteEvent] = []

    try:
        handle = native_csv.open("r", encoding="utf-8", newline="")
    except (OSError, UnicodeError) as exc:
        raise NativeEventError(f"Cannot read Basic Pitch CSV {native_csv}: {exc}") from exc

    with handle:
        reader = csv.reader(handle, strict=True)
        try:
            header = next(reader)
        except StopIteration as exc:
            raise NativeEventError(f"{native_csv}: missing CSV header") from exc
        except csv.Error as exc:
            raise NativeEventError(f"{native_csv}: invalid CSV header: {exc}") from exc
        if header != EXPECTED_HEADER:
            raise NativeEventError(
                f"{native_csv}: unsupported CSV header {header!r}; expected {EXPECTED_HEADER!r}"
            )

        try:
            for row_number, row in enumerate(reader, start=2):
                if not row or all(not value.strip() for value in row):
                    continue
                if len(row) < 4:
                    raise NativeEventError(f"{native_csv}:{row_number}: expected at least 4 fields")
                onset = _float_field(
                    row[0],
                    field="start_time_s",
                    path=native_csv,
                    row_number=row_number,
                )
                offset = _float_field(
                    row[1],
                    field="end_time_s",
                    path=native_csv,
                    row_number=row_number,
                )
                pitch = _int_field(
                    row[2],
                    field="pitch_midi",
                    path=native_csv,
                    row_number=row_number,
                )
                velocity = _int_field(
                    row[3],
                    field="velocity",
                    path=native_csv,
                    row_number=row_number,
                )
                bends = [
                    _int_field(
                        value,
                        field=f"pitch_bend[{index}]",
                        path=native_csv,
                        row_number=row_number,
                    )
                    for index, value in enumerate(row[4:])
                    if value != ""
                ]
                if onset < 0 or offset <= onset:
                    raise NativeEventError(
                        f"{native_csv}:{row_number}: invalid onset/offset {onset}/{offset}"
                    )
                if not 0 <= pitch <= 127:
                    raise NativeEventError(
                        f"{native_csv}:{row_number}: pitch_midi must be in [0, 127]"
                    )
                if not 0 <= velocity <= 127:
                    raise NativeEventError(
                        f"{native_csv}:{row_number}: velocity must be in [0, 127]"
                    )

                native_index = row_number - 2
                event = NoteEvent(
                    event_id=f"{run_id}:basic-pitch:{native_index}",
                    track_id="basic-pitch-native:voice",
                    instrument="voice",
                    onset_sec=onset,
                    offset_sec=offset,
                    pitch_midi=float(pitch),
                    quantized_pitch_midi=pitch,
                    velocity=velocity,
                    confidence=None,
                    is_main_melody_candidate=True,
                    source_run_id=run_id,
                    source_model=source_model,
                    source_event_ids=[f"native-csv-row:{row_number}"],
                    tags=[
                        "candidate",
                        "lead-vocal-baseline",
                        "confidence-unavailable",
                    ],
                    extra={
                        "native_csv_row_number": row_number,
                        "native_csv_row": row,
                        "pitch_bend_values": bends,
                        "velocity_interpretation": (
                            "Basic Pitch amplitude rounded to MIDI velocity"
                        ),
                        "confidence_unavailable_reason": (
                            "The decoded CSV exposes velocity, not calibrated "
                            "per-note confidence; raw model tensors are preserved "
                            "in the native NPZ."
                        ),
                    },
                )
                event.validate()
                canonical.append(event)
        except csv.Error as exc:
            raise NativeEventError(
                f"{native_csv}: invalid CSV row near line {reader.line_num}: {exc}"
            ) from exc

    canonical.sort(key=lambda event: (event.onset_sec, event.offset_sec, event.event_id))
    write_jsonl(output_path, canonical)

    pitch_class_counts = Counter(int(event.pitch_midi) % 12 for event in canonical)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "source_model": source_model,
        "event_count": len(canonical),
        "instrument_counts": {"voice": len(canonical)},
        "pitch_midi": {
            "minimum": min((event.pitch_midi for event in canonical), default=None),
            "maximum": max((event.pitch_midi for event in canonical), default=None),
        },
        "pitch_class_counts": {
            str(key): value for key, value in sorted(pitch_class_counts.items())
        },
        "timeline_sec": {
            "first_onset": min((event.onset_sec for event in canonical), default=None),
            "last_offset": max((event.offset_sec for event in canonical), default=None),
        },
        "confidence": {
            "available_in_canonical_events": False,
            "raw_model_outputs_preserved": True,
            "reason": (
                "Basic Pitch 0.4.0 CSV velocity is not a calibrated per-note "
                "confidence; raw note/onset/contour tensors are preserved in NPZ."
            ),
        },
        "decoding_cleanup": {
            "song_specific_tuning": False,
            "additional_note_deletion": False,
        },
    }
    atomic_write_json(summary_path, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert Basic Pitch 0.4.0 native CSV into canonical note events."
    )
    parser.add_argument("native_csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-model", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = normalize_note_events(
        args.native_csv.resolve(),
        args.output.resolve(),
        args.summary.resolve(),
        run_id=args.run_id,
        source_model=args.source_model,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
