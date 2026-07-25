from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import atomic_write_json


class NativeEventError(ValueError):
    """Raised when a MuScriptor native event stream violates its contract."""


def _read_object(path: Path, line_number: int, line: str) -> dict[str, Any]:
    try:
        value = json.loads(line)
    except json.JSONDecodeError as exc:
        raise NativeEventError(f"{path}:{line_number}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise NativeEventError(f"{path}:{line_number}: event must be a JSON object")
    return value


def _number(value: Any, *, field: str, path: Path, line_number: int) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NativeEventError(f"{path}:{line_number}: {field} must be a number")
    return float(value)


def normalize_native_events(
    native_path: Path,
    output_path: Path,
    summary_path: Path,
    *,
    run_id: str,
    source_model: str,
    rejected_path: Path | None = None,
) -> dict[str, Any]:
    starts: dict[int, tuple[dict[str, Any], int]] = {}
    ended: set[int] = set()
    canonical: list[NoteEvent] = []
    rejected: list[dict[str, Any]] = []

    with native_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = _read_object(native_path, line_number, line)
            event_type = value.get("type")
            index = value.get("index" if event_type == "start" else "start_event_index")
            if isinstance(index, bool) or not isinstance(index, int) or index < 0:
                raise NativeEventError(
                    f"{native_path}:{line_number}: invalid native event index {index!r}"
                )

            if event_type == "start":
                if index in starts:
                    raise NativeEventError(
                        f"{native_path}:{line_number}: duplicate start index {index}"
                    )
                pitch_value = value.get("pitch")
                if isinstance(pitch_value, bool) or not isinstance(pitch_value, int):
                    raise NativeEventError(
                        f"{native_path}:{line_number}: pitch must be an integer"
                    )
                pitch = float(pitch_value)
                onset = _number(
                    value.get("start_time"),
                    field="start_time",
                    path=native_path,
                    line_number=line_number,
                )
                instrument = value.get("instrument")
                if not isinstance(instrument, str) or not instrument.strip():
                    raise NativeEventError(
                        f"{native_path}:{line_number}: instrument must be non-empty"
                    )
                if not 0 <= pitch <= 127 or onset < 0:
                    raise NativeEventError(
                        f"{native_path}:{line_number}: invalid pitch/onset"
                    )
                starts[index] = (value, line_number)
                continue

            if event_type != "end":
                raise NativeEventError(
                    f"{native_path}:{line_number}: unknown event type {event_type!r}"
                )
            if index in ended:
                raise NativeEventError(
                    f"{native_path}:{line_number}: duplicate end index {index}"
                )
            if index not in starts:
                raise NativeEventError(
                    f"{native_path}:{line_number}: end references missing start {index}"
                )

            start, start_line = starts[index]
            offset = _number(
                value.get("end_time"),
                field="end_time",
                path=native_path,
                line_number=line_number,
            )
            onset = float(start["start_time"])
            instrument = str(start["instrument"])
            if offset < onset:
                raise NativeEventError(
                    f"{native_path}:{line_number}: end_time {offset} precedes "
                    f"start_time {onset} for native event {index}"
                )
            if offset == onset:
                if rejected_path is None:
                    raise NativeEventError(
                        f"{native_path}:{line_number}: zero-duration native event {index}; "
                        "provide rejected_path to quarantine it explicitly"
                    )
                rejected.append(
                    {
                        "reason": "zero_duration",
                        "native_start_index": index,
                        "native_start_line": start_line,
                        "native_end_line": line_number,
                        "onset_sec": onset,
                        "offset_sec": offset,
                        "pitch_midi": start["pitch"],
                        "instrument": instrument,
                        "native_start_event": start,
                        "native_end_event": value,
                    }
                )
                ended.add(index)
                continue
            event = NoteEvent(
                event_id=f"{run_id}:muscriptor:{index}",
                track_id=f"muscriptor-native:{instrument}",
                instrument=instrument,
                onset_sec=onset,
                offset_sec=offset,
                pitch_midi=float(start["pitch"]),
                quantized_pitch_midi=start["pitch"],
                velocity=None,
                confidence=None,
                source_run_id=run_id,
                source_model=source_model,
                source_event_ids=[
                    f"native-start:{index}",
                    f"native-end:{index}",
                ],
                tags=["candidate", "native-instrument-unmapped"],
                extra={
                    "native_instrument": instrument,
                    "native_start_index": index,
                    "native_start_line": start_line,
                    "native_end_line": line_number,
                    "native_start_event": start,
                    "native_end_event": value,
                    "velocity_unavailable": True,
                },
            )
            event.validate()
            canonical.append(event)
            ended.add(index)

    missing_ends = sorted(set(starts) - ended)
    if missing_ends:
        sample = ", ".join(str(value) for value in missing_ends[:10])
        raise NativeEventError(
            f"{native_path}: {len(missing_ends)} start event(s) have no end: {sample}"
        )

    canonical.sort(key=lambda event: (event.onset_sec, event.offset_sec, event.event_id))
    write_jsonl(output_path, canonical)
    if rejected_path is not None:
        atomic_write_json(
            rejected_path,
            {
                "schema_version": 1,
                "run_id": run_id,
                "policy": "quarantine_exact_zero_duration_only",
                "rejected_event_count": len(rejected),
                "events": rejected,
            },
        )

    instruments = Counter(event.instrument for event in canonical)
    summary: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "source_model": source_model,
        "event_count": len(canonical),
        "instrument_counts": dict(sorted(instruments.items())),
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
            "reason": "MuScriptor 0.2.2 native events do not expose confidence.",
        },
        "velocity": {
            "available": False,
            "reason": "MuScriptor 0.2.2 tokenizer does not preserve velocity.",
        },
        "instrument_mapping": {
            "status": "unmapped",
            "reason": "Native names are preserved until a later measured taxonomy mapping.",
        },
        "rejected_events": {
            "count": len(rejected),
            "policy": "quarantine_exact_zero_duration_only",
            "path": str(rejected_path) if rejected_path is not None else None,
        },
    }
    atomic_write_json(summary_path, summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert MuScriptor 0.2.2 native JSONL into canonical note events."
    )
    parser.add_argument("native_jsonl", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-model", required=True)
    parser.add_argument(
        "--rejected",
        type=Path,
        help="Write an explicit quarantine report for exact zero-duration native notes.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = normalize_native_events(
        args.native_jsonl.resolve(),
        args.output.resolve(),
        args.summary.resolve(),
        run_id=args.run_id,
        source_model=args.source_model,
        rejected_path=args.rejected.resolve() if args.rejected is not None else None,
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
