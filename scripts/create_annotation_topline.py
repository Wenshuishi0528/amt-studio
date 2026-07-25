#!/usr/bin/env python3
"""Create an annotation-only monophonic top-line proposal from canonical events."""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import math
import platform
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from amt_core.events import NoteEvent, read_jsonl, write_jsonl
from amt_core.utils import atomic_write_json, sha256_file

EXCERPT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)


class ToplineError(ValueError):
    """Raised when an annotation top-line proposal would be ambiguous or unsafe."""


def parse_excerpt(value: str) -> tuple[str, float, float]:
    try:
        excerpt_id, window = value.split("=", 1)
        start_text, end_text = window.split(":", 1)
        start = float(start_text)
        end = float(end_text)
    except ValueError as exc:
        raise ToplineError("excerpt must use ID=START:END") from exc
    if (
        EXCERPT_ID.fullmatch(excerpt_id) is None
        or ".." in excerpt_id
        or not math.isfinite(start)
        or not math.isfinite(end)
        or start < 0
        or end <= start
    ):
        raise ToplineError(f"invalid excerpt: {value!r}")
    return excerpt_id, start, end


def _proposal(
    selected: list[NoteEvent],
    *,
    excerpt_id: str,
    start_sec: float,
    end_sec: float,
    onset_group_tolerance_sec: float,
    merge_gap_sec: float,
) -> list[NoteEvent]:
    groups: list[list[NoteEvent]] = []
    for event in sorted(selected, key=lambda item: (item.onset_sec, item.event_id)):
        if (
            not groups
            or event.onset_sec - groups[-1][0].onset_sec > onset_group_tolerance_sec
        ):
            groups.append([event])
        else:
            groups[-1].append(event)

    chosen = [
        max(
            group,
            key=lambda event: (
                event.pitch_midi,
                event.offset_sec - event.onset_sec,
                event.event_id,
            ),
        )
        for group in groups
    ]
    proposal: list[NoteEvent] = []
    for source in chosen:
        onset = max(start_sec, source.onset_sec)
        offset = min(end_sec, source.offset_sec)
        if offset <= onset:
            continue
        if (
            proposal
            and proposal[-1].pitch_midi == source.pitch_midi
            and onset - proposal[-1].offset_sec <= merge_gap_sec
        ):
            previous = proposal[-1]
            proposal[-1] = NoteEvent(
                event_id=previous.event_id,
                track_id=previous.track_id,
                instrument=previous.instrument,
                onset_sec=previous.onset_sec,
                offset_sec=max(previous.offset_sec, offset),
                pitch_midi=previous.pitch_midi,
                quantized_pitch_midi=previous.quantized_pitch_midi,
                velocity=previous.velocity,
                confidence=None,
                is_main_melody_candidate=True,
                source_run_id=previous.source_run_id,
                source_model=previous.source_model,
                source_event_ids=[*previous.source_event_ids, source.event_id],
                tags=previous.tags,
                extra={
                    **previous.extra,
                    "merged_source_event_count": len(previous.source_event_ids) + 1,
                },
            )
            continue
        if proposal and proposal[-1].offset_sec > onset:
            previous = proposal[-1]
            proposal[-1] = NoteEvent(
                event_id=previous.event_id,
                track_id=previous.track_id,
                instrument=previous.instrument,
                onset_sec=previous.onset_sec,
                offset_sec=onset,
                pitch_midi=previous.pitch_midi,
                quantized_pitch_midi=previous.quantized_pitch_midi,
                velocity=previous.velocity,
                confidence=None,
                is_main_melody_candidate=True,
                source_run_id=previous.source_run_id,
                source_model=previous.source_model,
                source_event_ids=previous.source_event_ids,
                tags=previous.tags,
                extra=previous.extra,
            )
        proposal.append(
            NoteEvent(
                event_id=f"annotation-topline:{excerpt_id}:{len(proposal) + 1:04d}",
                track_id=f"annotation-topline:{excerpt_id}",
                instrument="main_melody",
                onset_sec=onset,
                offset_sec=offset,
                pitch_midi=source.pitch_midi,
                quantized_pitch_midi=source.quantized_pitch_midi,
                velocity=source.velocity,
                confidence=None,
                is_main_melody_candidate=True,
                source_run_id=source.source_run_id,
                source_model=source.source_model,
                source_event_ids=[source.event_id],
                tags=[
                    "annotation-only",
                    "top-line-reduction",
                    "not-evaluation-candidate",
                ],
                extra={
                    "source_instrument": source.instrument,
                    "selection_policy": "highest_pitch_per_simultaneous_onset_group",
                    "human_confirmed": False,
                },
            )
        )
    return proposal


def create_topline(
    *,
    events_path: Path,
    instrument: str,
    excerpts: list[tuple[str, float, float]],
    output_dir: Path,
    onset_group_tolerance_sec: float = 0.005,
    merge_gap_sec: float = 0.02,
) -> dict[str, Any]:
    started_at = datetime.now(UTC).isoformat()
    if not instrument.strip():
        raise ToplineError("instrument must be non-empty")
    if not 0 <= onset_group_tolerance_sec <= 0.05:
        raise ToplineError("onset-group tolerance must be in [0, 0.05]")
    if not 0 <= merge_gap_sec <= 0.1:
        raise ToplineError("merge gap must be in [0, 0.1]")
    if len({excerpt_id for excerpt_id, _start, _end in excerpts}) != len(excerpts):
        raise ToplineError("excerpt IDs must be unique")
    requested_events = events_path.expanduser()
    if requested_events.is_symlink():
        raise ToplineError("events input must be a regular non-symlink file")
    events_path = requested_events.resolve(strict=True)
    if not events_path.is_file():
        raise ToplineError("events input must be a regular non-symlink file")
    output_dir = output_dir.expanduser().absolute()
    if output_dir.exists() or output_dir.is_symlink():
        raise ToplineError(f"refusing to overwrite output directory: {output_dir}")
    events = read_jsonl(events_path)
    matching = [event for event in events if event.instrument == instrument]
    if not matching:
        raise ToplineError(f"no events match instrument {instrument!r}")

    output_dir.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    try:
        for excerpt_id, start, end in excerpts:
            selected = [
                event for event in matching if start <= event.onset_sec < end
            ]
            if not selected:
                raise ToplineError(f"{excerpt_id} has no matching source events")
            proposed = _proposal(
                selected,
                excerpt_id=excerpt_id,
                start_sec=start,
                end_sec=end,
                onset_group_tolerance_sec=onset_group_tolerance_sec,
                merge_gap_sec=merge_gap_sec,
            )
            path = output_dir / excerpt_id / "events.jsonl"
            write_jsonl(path, proposed)
            records.append(
                {
                    "excerpt_id": excerpt_id,
                    "start_sec": start,
                    "end_sec": end,
                    "source_event_count": len(selected),
                    "proposed_event_count": len(proposed),
                    "events_path": str(path.relative_to(output_dir)),
                    "events_sha256": sha256_file(path),
                }
            )
        summary = {
            "schema": "amt-annotation-topline/v1",
            "status": "awaiting_human_review",
            "source_events_path": str(events_path),
            "source_events_sha256": sha256_file(events_path),
            "source_instrument": instrument,
            "policy": {
                "simultaneous_group_selection": "highest_pitch",
                "onset_group_tolerance_sec": onset_group_tolerance_sec,
                "same_pitch_merge_gap_sec": merge_gap_sec,
                "overlap_policy": "clip_previous_at_next_onset",
                "annotation_only": True,
                "eligible_for_primary_metrics": False,
            },
            "excerpts": records,
            "claims": {
                "human_confirmed": False,
                "accuracy_claimed": False,
            },
        }
        atomic_write_json(output_dir / "summary.json", summary)
        commit = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        status = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--events",
            str(events_path),
            "--instrument",
            instrument,
        ]
        for excerpt_id, start, end in excerpts:
            command.extend(["--excerpt", f"{excerpt_id}={start}:{end}"])
        command.extend(["--output-dir", str(output_dir)])
        output_paths = sorted(
            path
            for path in output_dir.rglob("*")
            if path.is_file() and path.name != "run_manifest.json"
        )
        run_manifest = {
            "schema_version": 1,
            "artifact_type": "amt-annotation-topline-run",
            "run_id": output_dir.name,
            "status": "succeeded",
            "started_at": started_at,
            "ended_at": datetime.now(UTC).isoformat(),
            "command": command,
            "configuration": summary["policy"],
            "inputs": [
                {
                    "path": str(events_path),
                    "sha256": summary["source_events_sha256"],
                    "size_bytes": events_path.stat().st_size,
                }
            ],
            "outputs": [
                {
                    "path": str(path.relative_to(output_dir)),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in output_paths
            ],
            "source_lineage": {
                "source_run_ids": sorted({event.source_run_id for event in matching}),
                "source_models": sorted({event.source_model for event in matching}),
                "source_event_count": len(matching),
            },
            "model": {
                "name": "deterministic-highest-pitch-topline",
                "version": "1",
                "weight_sha256": None,
                "reason_no_weight": "deterministic heuristic; no learned model",
            },
            "code": {
                "commit": (
                    commit.stdout.strip() if commit.returncode == 0 else None
                ),
                "dirty": (
                    bool(status.stdout.strip()) if status.returncode == 0 else None
                ),
                "source_files": [
                    {
                        "path": str(Path(__file__).resolve().relative_to(REPO_ROOT)),
                        "sha256": sha256_file(Path(__file__).resolve()),
                    }
                ],
            },
            "environment": {
                "hostname": platform.node(),
                "device": "cpu",
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "claims": summary["claims"],
        }
        atomic_write_json(output_dir / "run_manifest.json", run_manifest)
        return summary
    except BaseException:
        for path in sorted(output_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        output_dir.rmdir()
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--instrument", required=True)
    parser.add_argument("--excerpt", action="append", default=[], required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = create_topline(
        events_path=args.events,
        instrument=args.instrument,
        excerpts=[parse_excerpt(value) for value in args.excerpt],
        output_dir=args.output_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
