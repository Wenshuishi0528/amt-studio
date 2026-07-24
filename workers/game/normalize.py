from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any

from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import atomic_write_json


class GameNativeError(ValueError):
    """Raised when a GAME native output violates its published contract."""


def _number(value: str | None, *, field: str, path: Path, row_number: int) -> float:
    try:
        number = float(value) if value is not None else math.nan
    except ValueError as exc:
        raise GameNativeError(
            f"{path}:{row_number}: {field} must be numeric, got {value!r}"
        ) from exc
    if not math.isfinite(number):
        raise GameNativeError(f"{path}:{row_number}: {field} must be finite")
    return number


def normalize_native_csv(
    native_path: Path,
    output_path: Path,
    summary_path: Path,
    *,
    run_id: str,
    source_model: str,
) -> dict[str, Any]:
    canonical: list[NoteEvent] = []
    previous_onset = -math.inf
    previous_offset = -math.inf

    with native_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["onset", "offset", "pitch"]:
            raise GameNativeError(
                f"{native_path}: expected CSV header onset,offset,pitch; got {reader.fieldnames!r}"
            )
        for row_number, row in enumerate(reader, start=2):
            if None in row:
                raise GameNativeError(f"{native_path}:{row_number}: unexpected extra columns")
            onset = _number(
                row.get("onset"),
                field="onset",
                path=native_path,
                row_number=row_number,
            )
            offset = _number(
                row.get("offset"),
                field="offset",
                path=native_path,
                row_number=row_number,
            )
            pitch = _number(
                row.get("pitch"),
                field="pitch",
                path=native_path,
                row_number=row_number,
            )
            if onset < previous_onset:
                raise GameNativeError(
                    f"{native_path}:{row_number}: events are not ordered by onset"
                )
            if canonical and onset < previous_offset - 1e-9:
                raise GameNativeError(
                    f"{native_path}:{row_number}: native events unexpectedly overlap"
                )

            event_index = len(canonical)
            event = NoteEvent(
                event_id=f"{run_id}:game:{event_index}",
                track_id="game-native:voice",
                instrument="voice",
                onset_sec=onset,
                offset_sec=offset,
                pitch_midi=pitch,
                quantized_pitch_midi=round(pitch),
                velocity=None,
                confidence=None,
                is_main_melody_candidate=True,
                source_run_id=run_id,
                source_model=source_model,
                source_event_ids=[f"native-csv-row:{row_number}"],
                tags=["candidate", "lead-vocal", "game-native"],
                extra={
                    "native_csv_row": row,
                    "native_csv_row_number": row_number,
                    "confidence_unavailable": True,
                    "velocity_unavailable": True,
                    "serialization_note": (
                        "GAME v1.0.3 clamps serialized notes to a monophonic sequence."
                    ),
                },
            )
            event.validate()
            canonical.append(event)
            previous_onset = onset
            previous_offset = offset

    write_jsonl(output_path, canonical)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "source_model": source_model,
        "event_count": len(canonical),
        "pitch_midi": {
            "minimum": min((event.pitch_midi for event in canonical), default=None),
            "maximum": max((event.pitch_midi for event in canonical), default=None),
        },
        "timeline_sec": {
            "first_onset": min((event.onset_sec for event in canonical), default=None),
            "last_offset": max((event.offset_sec for event in canonical), default=None),
        },
        "confidence": {
            "available": False,
            "reason": "GAME v1.0.3 extract CLI does not serialize confidence or logits.",
        },
        "velocity": {
            "available": False,
            "reason": "GAME v1.0.3 text callbacks do not serialize velocity.",
        },
        "native_serialization": {
            "source": "numeric CSV",
            "time_precision_decimal_places": 3,
            "pitch_precision_decimal_places": 3,
            "monophonic_non_overlapping": True,
        },
        "accuracy_claimed": False,
    }
    atomic_write_json(summary_path, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert GAME v1.0.3 native numeric CSV to canonical note events."
    )
    parser.add_argument("native_csv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-model", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = normalize_native_csv(
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
