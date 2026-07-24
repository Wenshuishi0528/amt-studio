#!/usr/bin/env python3
"""Compare canonical melody candidates without importing model environments."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from amt_core.events import EventValidationError, NoteEvent, read_jsonl
from amt_core.utils import atomic_write_json

EVENTS_RELATIVE_PATH = "normalized/events.jsonl"
LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z", re.ASCII)
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,198}\Z", re.ASCII)
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")

PHRASE_GAP_THRESHOLD_SEC = 1.0
SHORT_NOTE_THRESHOLD_SEC = 0.12
FRAGMENTATION_MIN_EVENT_COUNT = 5
FRAGMENTATION_SHORT_NOTE_RATE = 0.35
POLYPHONY_REVIEW_RATE = 0.10
WIDE_REGISTER_SPAN_SEMITONES = 36.0

PAIR_EVENT_COUNT_RATIO = 2.0
PAIR_DURATION_RATIO = 2.0
PAIR_MEDIAN_PITCH_DIFFERENCE = 12.0
PAIR_POLYPHONY_RATE_DIFFERENCE = 0.10

REGISTER_BANDS = (
    ("low", 0.0, 48.0),
    ("lower_middle", 48.0, 60.0),
    ("middle", 60.0, 72.0),
    ("upper_middle", 72.0, 84.0),
    ("high", 84.0, 128.0),
)


class MelodyComparisonError(ValueError):
    """Raised when candidate runs cannot form a trustworthy comparison."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_named_runs(values: list[str]) -> dict[str, Path]:
    """Parse and validate repeated LABEL=RUN_DIR arguments."""

    runs: dict[str, Path] = {}
    normalized_labels: set[str] = set()
    for value in values:
        if "=" not in value:
            raise MelodyComparisonError(f"Invalid --run value (expected LABEL=RUN_DIR): {value!r}")
        raw_label, raw_path = value.split("=", 1)
        label = raw_label.strip()
        if LABEL_PATTERN.fullmatch(label) is None or ".." in label:
            raise MelodyComparisonError(
                "Candidate labels must be 1-64 ASCII letters, digits, dots, "
                "underscores, or hyphens; they must start with a letter or digit "
                "and cannot contain '..'"
            )
        normalized_label = label.casefold()
        if normalized_label in normalized_labels:
            raise MelodyComparisonError(f"Duplicate candidate label: {label}")
        if not raw_path.strip():
            raise MelodyComparisonError(f"Empty run directory for candidate: {label}")
        normalized_labels.add(normalized_label)
        runs[label] = Path(raw_path.strip()).expanduser().resolve()

    if len(runs) < 2:
        raise MelodyComparisonError("At least two distinct melody candidate runs are required")
    if len(set(runs.values())) != len(runs):
        raise MelodyComparisonError("Candidate run directories must be distinct")
    return runs


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MelodyComparisonError(f"Cannot read {label} JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MelodyComparisonError(f"{label} root must be a JSON object: {path}")
    return value


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise MelodyComparisonError(f"{label} must be a valid SHA-256")
    return value.lower()


def _single_input(manifest: dict[str, Any], *, label: str) -> dict[str, str]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1:
        raise MelodyComparisonError(
            f"{label} manifest must record exactly one unambiguous audio input"
        )
    record = inputs[0]
    if not isinstance(record, dict):
        raise MelodyComparisonError(f"{label} manifest audio input must be an object")
    path = record.get("path")
    if not isinstance(path, str) or not path.strip():
        raise MelodyComparisonError(f"{label} manifest audio input path is missing")
    return {
        "path": path,
        "sha256": _require_sha256(
            record.get("sha256"),
            label=f"{label} manifest audio input sha256",
        ),
    }


def _path_has_suffix(path: str, suffix: tuple[str, ...]) -> bool:
    parts = PurePosixPath(path).parts
    return len(parts) >= len(suffix) and tuple(parts[-len(suffix) :]) == suffix


def _load_project_identity(
    label: str,
    run_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    if run_dir.parent.name != "runs":
        raise MelodyComparisonError(f"{label} run must be stored under a project's runs directory")
    project_dir = run_dir.parent.parent
    project_manifest_path = project_dir / "manifest.json"
    if not project_manifest_path.is_file() or project_manifest_path.is_symlink():
        raise MelodyComparisonError(
            f"{label} project manifest is missing or unsafe: {project_manifest_path}"
        )
    project_manifest = _load_json_object(
        project_manifest_path,
        label=f"{label} project manifest",
    )
    if project_manifest.get("schema_version") != 1:
        raise MelodyComparisonError(f"{label} project manifest schema_version must be 1")

    candidate_project_id = manifest.get("project_id")
    project_id = project_manifest.get("project_id")
    if (
        not isinstance(candidate_project_id, str)
        or not candidate_project_id.strip()
        or not isinstance(project_id, str)
        or not project_id.strip()
    ):
        raise MelodyComparisonError(f"{label} project identity is missing")
    if candidate_project_id != project_id:
        raise MelodyComparisonError(f"{label} run project_id does not match its project manifest")

    canonical_audio = project_manifest.get("canonical_audio")
    if not isinstance(canonical_audio, dict):
        raise MelodyComparisonError(f"{label} project manifest has no canonical_audio object")
    canonical_relative = canonical_audio.get("path")
    if not isinstance(canonical_relative, str) or not canonical_relative.strip():
        raise MelodyComparisonError(f"{label} project manifest canonical audio path is missing")
    relative_path = PurePosixPath(canonical_relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise MelodyComparisonError(f"{label} project manifest canonical audio path is unsafe")
    canonical_sha256 = _require_sha256(
        canonical_audio.get("sha256"),
        label=f"{label} project canonical audio sha256",
    )

    canonical_path = project_dir.joinpath(*relative_path.parts)
    if canonical_path.is_symlink():
        raise MelodyComparisonError(
            f"{label} project canonical audio must not be a symlink: {canonical_path}"
        )
    try:
        resolved_canonical = canonical_path.resolve(strict=True)
        resolved_canonical.relative_to(project_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise MelodyComparisonError(
            f"{label} project canonical audio is missing or escapes the project"
        ) from exc
    if not resolved_canonical.is_file():
        raise MelodyComparisonError(f"{label} project canonical audio is not a regular file")
    actual_canonical_sha256 = sha256_file(resolved_canonical)
    if actual_canonical_sha256 != canonical_sha256:
        raise MelodyComparisonError(
            f"{label} project canonical audio SHA-256 mismatch: "
            f"{actual_canonical_sha256} != {canonical_sha256}"
        )

    return {
        "project_dir": project_dir,
        "project_id": project_id,
        "project_manifest_path": project_manifest_path,
        "project_manifest_sha256": sha256_file(project_manifest_path),
        "canonical_mix_path": resolved_canonical,
        "canonical_mix_relative_path": tuple(relative_path.parts),
        "canonical_mix_sha256": canonical_sha256,
    }


def _safe_parent_output_path(label: str, value: object) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, str) or not value.strip():
        raise MelodyComparisonError(f"{label} separator lineage has no parent output path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise MelodyComparisonError(f"{label} separator lineage parent output path is unsafe")
    return value, tuple(path.parts)


def _validate_separator_lineage(
    label: str,
    run_dir: Path,
    manifest: dict[str, Any],
    lineage: dict[str, Any],
    input_record: dict[str, str],
    project: dict[str, Any],
) -> dict[str, Any]:
    if lineage.get("parent_stem_name") != "vocals":
        raise MelodyComparisonError(f"{label} separator descendant must use the vocals stem")
    stem_sha256 = _require_sha256(
        lineage.get("parent_stem_sha256"),
        label=f"{label} separator lineage parent_stem_sha256",
    )
    if stem_sha256 != input_record["sha256"]:
        raise MelodyComparisonError(
            f"{label} audio input SHA-256 differs from its parent vocals stem"
        )

    parent_run_id = lineage.get("parent_separator_run_id")
    if (
        not isinstance(parent_run_id, str)
        or RUN_ID_PATTERN.fullmatch(parent_run_id) is None
        or ".." in parent_run_id
    ):
        raise MelodyComparisonError(f"{label} separator lineage parent run_id is missing or unsafe")
    parent_output_path, parent_output_parts = _safe_parent_output_path(
        label,
        lineage.get("parent_output_path"),
    )
    expected_input_suffix = ("runs", parent_run_id, *parent_output_parts)
    if not _path_has_suffix(input_record["path"], expected_input_suffix):
        raise MelodyComparisonError(
            f"{label} audio input path does not identify its recorded parent output"
        )

    recorded_parent_path = lineage.get("parent_manifest_path")
    if not isinstance(recorded_parent_path, str) or not _path_has_suffix(
        recorded_parent_path,
        ("runs", parent_run_id, "run_manifest.json"),
    ):
        raise MelodyComparisonError(
            f"{label} separator lineage parent manifest path is missing or ambiguous"
        )

    parent_run_dir = run_dir.parent / parent_run_id
    parent_manifest_path = parent_run_dir / "run_manifest.json"
    if (
        not parent_run_dir.is_dir()
        or parent_run_dir.is_symlink()
        or not parent_manifest_path.is_file()
        or parent_manifest_path.is_symlink()
    ):
        raise MelodyComparisonError(f"{label} parent separator manifest is missing or unsafe")
    parent_manifest_sha256 = sha256_file(parent_manifest_path)
    recorded_parent_sha256 = _require_sha256(
        lineage.get("parent_manifest_sha256"),
        label=f"{label} separator lineage parent_manifest_sha256",
    )
    if parent_manifest_sha256 != recorded_parent_sha256:
        raise MelodyComparisonError(f"{label} parent separator manifest SHA-256 has changed")
    parent = _load_json_object(
        parent_manifest_path,
        label=f"{label} parent separator manifest",
    )
    if parent.get("schema_version") != 1:
        raise MelodyComparisonError(f"{label} parent separator manifest schema_version must be 1")
    if (
        parent.get("worker") != "separator"
        or parent.get("status") != "succeeded"
        or parent.get("run_id") != parent_run_id
    ):
        raise MelodyComparisonError(f"{label} parent is not the recorded succeeded separator run")
    if parent.get("project_id") != project["project_id"]:
        raise MelodyComparisonError(f"{label} parent separator belongs to another project")

    parent_input = _single_input(parent, label=f"{label} parent separator")
    if parent_input["sha256"] != project["canonical_mix_sha256"]:
        raise MelodyComparisonError(
            f"{label} parent separator does not originate from the canonical mix"
        )
    canonical_path_record = lineage.get("canonical_mix_path")
    if not isinstance(canonical_path_record, str) or canonical_path_record != parent_input["path"]:
        raise MelodyComparisonError(
            f"{label} canonical mix path is missing or ambiguous in separator lineage"
        )
    if not _path_has_suffix(
        parent_input["path"],
        project["canonical_mix_relative_path"],
    ):
        raise MelodyComparisonError(
            f"{label} parent separator input path does not identify the canonical mix"
        )

    outputs = parent.get("outputs")
    if not isinstance(outputs, list):
        raise MelodyComparisonError(f"{label} parent separator outputs must be a list")
    output_records = [
        record
        for record in outputs
        if isinstance(record, dict) and record.get("path") == parent_output_path
    ]
    if len(output_records) != 1:
        raise MelodyComparisonError(
            f"{label} parent separator must contain exactly one recorded vocals output"
        )
    parent_output = output_records[0]
    output_sha256 = _require_sha256(
        parent_output.get("sha256"),
        label=f"{label} parent separator vocals output sha256",
    )
    if output_sha256 != stem_sha256:
        raise MelodyComparisonError(
            f"{label} parent separator vocals hash differs from the candidate input"
        )
    expected_size = parent_output.get("size_bytes")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        raise MelodyComparisonError(
            f"{label} parent separator vocals size_bytes must be a non-negative integer"
        )

    stem_path = parent_run_dir.joinpath(*parent_output_parts)
    if stem_path.is_symlink():
        raise MelodyComparisonError(f"{label} parent separator vocals output must not be a symlink")
    try:
        resolved_stem = stem_path.resolve(strict=True)
        resolved_stem.relative_to(parent_run_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise MelodyComparisonError(
            f"{label} parent separator vocals output is missing or unsafe"
        ) from exc
    if not resolved_stem.is_file() or resolved_stem.stat().st_size != expected_size:
        raise MelodyComparisonError(
            f"{label} parent separator vocals output size differs from its manifest"
        )
    if sha256_file(resolved_stem) != stem_sha256:
        raise MelodyComparisonError(f"{label} parent separator vocals output SHA-256 has changed")

    return {
        "kind": lineage["kind"],
        "project_id": project["project_id"],
        "canonical_mix_sha256": project["canonical_mix_sha256"],
        "input_sha256": input_record["sha256"],
        "parent_separator_run_id": parent_run_id,
        "parent_manifest_sha256": parent_manifest_sha256,
        "parent_output_path": parent_output_path,
        "parent_stem_name": "vocals",
        "parent_stem_sha256": stem_sha256,
        "verified": True,
    }


def _validated_lineage(
    label: str,
    run_dir: Path,
    manifest: dict[str, Any],
    project: dict[str, Any],
) -> dict[str, Any]:
    input_record = _single_input(manifest, label=label)
    lineage = manifest.get("input_lineage")
    if not isinstance(lineage, dict):
        raise MelodyComparisonError(f"{label} manifest has no unambiguous input_lineage object")
    canonical_sha256 = _require_sha256(
        lineage.get("canonical_mix_sha256"),
        label=f"{label} input lineage canonical_mix_sha256",
    )
    if canonical_sha256 != project["canonical_mix_sha256"]:
        raise MelodyComparisonError(
            f"{label} input lineage does not match its project canonical mix"
        )

    kind = lineage.get("kind")
    if kind == "direct_canonical_mix":
        if any(
            field in lineage
            for field in (
                "parent_separator_run_id",
                "parent_manifest_path",
                "parent_manifest_sha256",
                "parent_output_path",
                "parent_stem_name",
                "parent_stem_sha256",
            )
        ):
            raise MelodyComparisonError(
                f"{label} direct lineage ambiguously includes separator parent fields"
            )
        if input_record["sha256"] != canonical_sha256:
            raise MelodyComparisonError(
                f"{label} direct input SHA-256 differs from the canonical mix"
            )
        canonical_path_record = lineage.get("canonical_mix_path")
        if (
            not isinstance(canonical_path_record, str)
            or canonical_path_record != input_record["path"]
            or not _path_has_suffix(
                canonical_path_record,
                project["canonical_mix_relative_path"],
            )
        ):
            raise MelodyComparisonError(
                f"{label} direct canonical mix path is missing or ambiguous"
            )
        return {
            "kind": kind,
            "project_id": project["project_id"],
            "canonical_mix_sha256": canonical_sha256,
            "input_sha256": input_record["sha256"],
            "verified": True,
        }
    if kind in {"separator_stem", "separator_vocal_stem"}:
        return _validate_separator_lineage(
            label,
            run_dir,
            manifest,
            lineage,
            input_record,
            project,
        )
    raise MelodyComparisonError(f"{label} input lineage kind is unsupported or ambiguous: {kind!r}")


def _verified_events_path(
    run_dir: Path,
    manifest: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise MelodyComparisonError("Manifest outputs must be a list")
    records = [
        record
        for record in outputs
        if isinstance(record, dict) and record.get("path") == EVENTS_RELATIVE_PATH
    ]
    if len(records) != 1:
        raise MelodyComparisonError(
            f"Manifest must contain exactly one output record for {EVENTS_RELATIVE_PATH}"
        )

    normalized_dir = run_dir / "normalized"
    events_path = normalized_dir / "events.jsonl"
    if normalized_dir.is_symlink() or events_path.is_symlink():
        raise MelodyComparisonError(f"Canonical events path must not use symlinks: {events_path}")
    try:
        resolved_events = events_path.resolve(strict=True)
        resolved_events.relative_to(run_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise MelodyComparisonError(
            f"Canonical events file is missing or escapes the run directory: {events_path}"
        ) from exc
    if not resolved_events.is_file():
        raise MelodyComparisonError(f"Canonical events output is not a regular file: {events_path}")

    record = records[0]
    expected_size = record.get("size_bytes")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int):
        raise MelodyComparisonError("Canonical events size_bytes must be an integer")
    if expected_size < 0:
        raise MelodyComparisonError("Canonical events size_bytes cannot be negative")
    actual_size = resolved_events.stat().st_size
    if actual_size != expected_size:
        raise MelodyComparisonError(
            f"Canonical events size mismatch: {actual_size} != {expected_size}"
        )

    expected_hash = record.get("sha256")
    if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
        raise MelodyComparisonError("Canonical events output has an invalid SHA-256")
    actual_hash = sha256_file(resolved_events)
    if actual_hash != expected_hash.lower():
        raise MelodyComparisonError(
            f"Canonical events SHA-256 mismatch: {actual_hash} != {expected_hash.lower()}"
        )
    return resolved_events, {"sha256": actual_hash, "size_bytes": actual_size}


def _load_candidate(label: str, candidate_path: Path) -> dict[str, Any]:
    if not candidate_path.is_dir() or candidate_path.is_symlink():
        raise MelodyComparisonError(f"{label} run directory is missing or unsafe: {candidate_path}")
    run_dir = candidate_path.resolve(strict=True)
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise MelodyComparisonError(f"{label} run manifest is missing or unsafe: {manifest_path}")
    manifest = _load_json_object(manifest_path, label=f"{label} manifest")

    if manifest.get("schema_version") != 1:
        raise MelodyComparisonError(f"{label} manifest schema_version must be 1")
    if manifest.get("status") != "succeeded":
        raise MelodyComparisonError(f"{label} manifest status is not succeeded")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None or ".." in run_id:
        raise MelodyComparisonError(f"{label} manifest run_id is missing or unsafe")
    if run_id != run_dir.name:
        raise MelodyComparisonError(
            f"{label} manifest run_id does not match its directory: {run_id!r}"
        )
    worker = manifest.get("worker")
    if not isinstance(worker, str) or not worker.strip():
        raise MelodyComparisonError(f"{label} manifest worker source is missing")

    project = _load_project_identity(label, run_dir, manifest)
    lineage = _validated_lineage(label, run_dir, manifest, project)
    events_path, artifact = _verified_events_path(run_dir, manifest)
    try:
        events = read_jsonl(events_path)
    except (OSError, UnicodeDecodeError, EventValidationError) as exc:
        raise MelodyComparisonError(f"{label} canonical events are invalid: {exc}") from exc

    for event in events:
        finite_fields = {
            "onset_sec": event.onset_sec,
            "offset_sec": event.offset_sec,
            "pitch_midi": event.pitch_midi,
            "confidence": event.confidence,
        }
        for field, value in finite_fields.items():
            if value is not None and not math.isfinite(value):
                raise MelodyComparisonError(
                    f"{label} canonical event {event.event_id!r} has non-finite {field}"
                )
    if events and any(event.instrument != "voice" for event in events):
        raise MelodyComparisonError(
            f"{label} nonempty melody candidate is not entirely voice-scoped"
        )

    event_ids = [event.event_id for event in events]
    if len(set(event_ids)) != len(event_ids):
        raise MelodyComparisonError(f"{label} canonical events contain duplicate event_id values")
    if any(event.source_run_id != run_id for event in events):
        raise MelodyComparisonError(
            f"{label} canonical events contain source_run_id values from another run"
        )
    source_models = sorted({event.source_model for event in events})
    if len(source_models) > 1:
        raise MelodyComparisonError(
            f"{label} baseline candidate mixes multiple source_model values"
        )

    return {
        "label": label,
        "run_dir": run_dir,
        "run_id": run_id,
        "worker": worker,
        "model": manifest.get("model"),
        "project": project,
        "lineage": lineage,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_file(manifest_path),
        "events_path": events_path,
        "events_artifact": artifact,
        "source_models": source_models,
        "events": events,
    }


def _number(value: float) -> float:
    return round(value, 9)


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "count": 0,
            "minimum": None,
            "median": None,
            "mean": None,
            "maximum": None,
        }
    return {
        "count": len(values),
        "minimum": _number(min(values)),
        "median": _number(float(statistics.median(values))),
        "mean": _number(statistics.fmean(values)),
        "maximum": _number(max(values)),
    }


def _polyphony_summary(events: list[NoteEvent]) -> dict[str, float | int]:
    changes: dict[float, int] = defaultdict(int)
    for event in events:
        changes[event.onset_sec] += 1
        changes[event.offset_sec] -= 1

    active = 0
    active_time = 0.0
    polyphonic_time = 0.0
    maximum_simultaneous = 0
    previous_time: float | None = None
    for time_point in sorted(changes):
        if previous_time is not None:
            duration = time_point - previous_time
            if active >= 1:
                active_time += duration
            if active >= 2:
                polyphonic_time += duration
        active += changes[time_point]
        maximum_simultaneous = max(maximum_simultaneous, active)
        previous_time = time_point

    return {
        "active_time_sec": _number(active_time),
        "polyphonic_time_sec": _number(polyphonic_time),
        "active_time_rate": (_number(polyphonic_time / active_time) if active_time > 0.0 else 0.0),
        "maximum_simultaneous_notes": maximum_simultaneous,
    }


def _register_summary(pitches: list[float]) -> dict[str, Any]:
    octave_counts = Counter(math.floor(pitch / 12.0) - 1 for pitch in pitches)
    band_counts = {
        name: sum(lower <= pitch < upper for pitch in pitches)
        for name, lower, upper in REGISTER_BANDS
    }
    event_count = len(pitches)
    return {
        "octave_definition": "scientific octave = floor(pitch_midi / 12) - 1",
        "octave_counts": {str(octave): count for octave, count in sorted(octave_counts.items())},
        "register_bands": {
            name: {
                "count": count,
                "rate": _number(count / event_count) if event_count else 0.0,
            }
            for name, count in band_counts.items()
        },
    }


def _candidate_statistics(events: list[NoteEvent]) -> dict[str, Any]:
    ordered = sorted(
        events,
        key=lambda event: (event.onset_sec, event.offset_sec, event.event_id),
    )
    pitches = [event.pitch_midi for event in ordered]
    durations = [event.offset_sec - event.onset_sec for event in ordered]
    onset_gaps = [
        current.onset_sec - previous.onset_sec for previous, current in itertools.pairwise(ordered)
    ]

    silence_gaps: list[float] = []
    phrase_gaps: list[float] = []
    overlapping_onset_count = 0
    if ordered:
        latest_offset = ordered[0].offset_sec
        for event in ordered[1:]:
            if event.onset_sec < latest_offset:
                overlapping_onset_count += 1
                silence_gap = 0.0
            else:
                silence_gap = event.onset_sec - latest_offset
            silence_gaps.append(silence_gap)
            if silence_gap >= PHRASE_GAP_THRESHOLD_SEC:
                phrase_gaps.append(silence_gap)
            latest_offset = max(latest_offset, event.offset_sec)

    short_note_count = sum(duration < SHORT_NOTE_THRESHOLD_SEC for duration in durations)
    transition_count = max(len(ordered) - 1, 0)
    pitch_distribution = _distribution(pitches)
    pitch_distribution["span_semitones"] = _number(max(pitches) - min(pitches)) if pitches else None
    return {
        "event_count": len(ordered),
        "pitch_midi": pitch_distribution,
        "note_duration_sec": {
            **_distribution(durations),
            "shorter_than_threshold_count": short_note_count,
            "shorter_than_threshold_rate": (
                _number(short_note_count / len(durations)) if durations else 0.0
            ),
        },
        "adjacent_onset_gap_sec": _distribution(onset_gaps),
        "inter_event_silence_gap_sec": _distribution(silence_gaps),
        "phrase_gap": {
            "threshold_sec": PHRASE_GAP_THRESHOLD_SEC,
            "count": len(phrase_gaps),
            "transition_rate": (
                _number(len(phrase_gaps) / transition_count) if transition_count else 0.0
            ),
            "duration_sec": _distribution(phrase_gaps),
        },
        "overlap": {
            "events_starting_during_prior_note_count": overlapping_onset_count,
            "event_rate": (_number(overlapping_onset_count / len(ordered)) if ordered else 0.0),
        },
        "polyphony": _polyphony_summary(ordered),
        "register": _register_summary(pitches),
        "timeline_sec": {
            "first_onset": _number(ordered[0].onset_sec) if ordered else None,
            "last_offset": (
                _number(max(event.offset_sec for event in ordered)) if ordered else None
            ),
        },
    }


def _failure_flags(statistics_by_candidate: dict[str, dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for label, stats in statistics_by_candidate.items():
        event_count = stats["event_count"]
        flags: list[dict[str, Any]] = []
        if event_count == 0:
            flags.append(
                {
                    "category": "empty_output",
                    "evidence": {"event_count": 0},
                    "interpretation": "The succeeded run emitted no canonical note events.",
                }
            )
        elif event_count < 2:
            flags.append(
                {
                    "category": "insufficient_sequence_for_structure_review",
                    "evidence": {"event_count": event_count},
                    "interpretation": "Gap and phrase structure cannot be assessed reliably.",
                }
            )

        short_rate = stats["note_duration_sec"]["shorter_than_threshold_rate"]
        if (
            event_count >= FRAGMENTATION_MIN_EVENT_COUNT
            and short_rate >= FRAGMENTATION_SHORT_NOTE_RATE
        ):
            flags.append(
                {
                    "category": "possible_short_note_fragmentation",
                    "evidence": {
                        "short_note_threshold_sec": SHORT_NOTE_THRESHOLD_SEC,
                        "short_note_rate": short_rate,
                    },
                    "interpretation": (
                        "Frequent short notes may be fragmentation, ornamentation, "
                        "or valid singing."
                    ),
                }
            )

        polyphony_rate = stats["polyphony"]["active_time_rate"]
        if polyphony_rate >= POLYPHONY_REVIEW_RATE:
            flags.append(
                {
                    "category": "possible_polyphonic_or_leakage_output",
                    "evidence": {
                        "polyphonic_active_time_rate": polyphony_rate,
                        "review_threshold": POLYPHONY_REVIEW_RATE,
                    },
                    "interpretation": (
                        "Concurrent notes may reflect backing vocals, accompaniment leakage, "
                        "or a non-monophonic decoder."
                    ),
                }
            )

        pitch_span = stats["pitch_midi"]["span_semitones"]
        if pitch_span is not None and pitch_span > WIDE_REGISTER_SPAN_SEMITONES:
            flags.append(
                {
                    "category": "possible_octave_or_register_instability",
                    "evidence": {
                        "pitch_span_semitones": pitch_span,
                        "review_threshold": WIDE_REGISTER_SPAN_SEMITONES,
                    },
                    "interpretation": (
                        "A wide span may be valid, an octave error, or non-vocal note leakage."
                    ),
                }
            )

        results[label] = {
            "classification": ("review_flags_present" if flags else "no_structural_review_flag"),
            "flags": flags,
        }
    return results


def _positive_ratio(value_a: float | int, value_b: float | int) -> float | None:
    lower = min(float(value_a), float(value_b))
    upper = max(float(value_a), float(value_b))
    if lower <= 0.0:
        return None
    return _number(upper / lower)


def _complementarity_draft(
    statistics_by_candidate: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for label_a, label_b in itertools.combinations(sorted(statistics_by_candidate), 2):
        stats_a = statistics_by_candidate[label_a]
        stats_b = statistics_by_candidate[label_b]
        signals: list[dict[str, Any]] = []

        count_a = stats_a["event_count"]
        count_b = stats_b["event_count"]
        if (count_a == 0) != (count_b == 0):
            signals.append(
                {
                    "signal": "event_presence_difference",
                    "values": {label_a: count_a, label_b: count_b},
                }
            )
        else:
            count_ratio = _positive_ratio(count_a, count_b)
            if count_ratio is not None and count_ratio >= PAIR_EVENT_COUNT_RATIO:
                signals.append(
                    {
                        "signal": "event_count_scale_difference",
                        "ratio": count_ratio,
                        "threshold": PAIR_EVENT_COUNT_RATIO,
                    }
                )

        duration_a = stats_a["note_duration_sec"]["median"]
        duration_b = stats_b["note_duration_sec"]["median"]
        if duration_a is not None and duration_b is not None:
            duration_ratio = _positive_ratio(duration_a, duration_b)
            if duration_ratio is not None and duration_ratio >= PAIR_DURATION_RATIO:
                signals.append(
                    {
                        "signal": "median_note_duration_difference",
                        "ratio": duration_ratio,
                        "threshold": PAIR_DURATION_RATIO,
                    }
                )

        pitch_a = stats_a["pitch_midi"]["median"]
        pitch_b = stats_b["pitch_midi"]["median"]
        if pitch_a is not None and pitch_b is not None:
            pitch_difference = _number(abs(pitch_a - pitch_b))
            if pitch_difference >= PAIR_MEDIAN_PITCH_DIFFERENCE:
                signals.append(
                    {
                        "signal": "median_register_difference",
                        "difference_semitones": pitch_difference,
                        "threshold": PAIR_MEDIAN_PITCH_DIFFERENCE,
                    }
                )

        polyphony_difference = _number(
            abs(stats_a["polyphony"]["active_time_rate"] - stats_b["polyphony"]["active_time_rate"])
        )
        if polyphony_difference >= PAIR_POLYPHONY_RATE_DIFFERENCE:
            signals.append(
                {
                    "signal": "polyphony_structure_difference",
                    "rate_difference": polyphony_difference,
                    "threshold": PAIR_POLYPHONY_RATE_DIFFERENCE,
                }
            )

        octaves_a = {
            octave for octave, count in stats_a["register"]["octave_counts"].items() if count
        }
        octaves_b = {
            octave for octave, count in stats_b["register"]["octave_counts"].items() if count
        }
        if octaves_a != octaves_b:
            signals.append(
                {
                    "signal": "octave_coverage_difference",
                    "exclusive_octaves": {
                        label_a: sorted(octaves_a - octaves_b, key=int),
                        label_b: sorted(octaves_b - octaves_a, key=int),
                    },
                }
            )

        pairs.append(
            {
                "candidates": [label_a, label_b],
                "classification": (
                    "structural_difference_for_reference_review"
                    if signals
                    else "no_strong_structural_difference_detected"
                ),
                "signals": signals,
            }
        )
    return pairs


def compare_candidates(named_runs: dict[str, Path]) -> dict[str, Any]:
    if len(named_runs) < 2:
        raise MelodyComparisonError("At least two distinct melody candidate runs are required")
    if len({label.casefold() for label in named_runs}) != len(named_runs):
        raise MelodyComparisonError("Duplicate candidate label")

    resolved_paths = {label: path.expanduser().resolve() for label, path in named_runs.items()}
    if len(set(resolved_paths.values())) != len(resolved_paths):
        raise MelodyComparisonError("Candidate run directories must be distinct")

    loaded = {
        label: _load_candidate(label, run_dir) for label, run_dir in sorted(resolved_paths.items())
    }
    run_ids = [candidate["run_id"] for candidate in loaded.values()]
    if len(set(run_ids)) != len(run_ids):
        raise MelodyComparisonError("Candidate manifests must have distinct run_id values")
    project_ids = {candidate["project"]["project_id"] for candidate in loaded.values()}
    if len(project_ids) != 1:
        raise MelodyComparisonError("Candidate runs do not share one project identity")
    canonical_mix_hashes = {
        candidate["lineage"]["canonical_mix_sha256"] for candidate in loaded.values()
    }
    if len(canonical_mix_hashes) != 1:
        raise MelodyComparisonError("Candidate runs do not share one canonical mix SHA-256")
    project_id = project_ids.pop()
    canonical_mix_sha256 = canonical_mix_hashes.pop()

    statistics_by_candidate = {
        label: _candidate_statistics(candidate["events"]) for label, candidate in loaded.items()
    }
    candidate_records = {
        label: {
            "run_dir": str(candidate["run_dir"]),
            "run_id": candidate["run_id"],
            "worker": candidate["worker"],
            "model": candidate["model"],
            "source_models": candidate["source_models"],
            "project": {
                "project_id": candidate["project"]["project_id"],
                "manifest_path": str(candidate["project"]["project_manifest_path"]),
                "manifest_sha256": candidate["project"]["project_manifest_sha256"],
                "canonical_mix_sha256": candidate["project"]["canonical_mix_sha256"],
            },
            "input_lineage": candidate["lineage"],
            "manifest": {
                "path": str(candidate["manifest_path"]),
                "sha256": candidate["manifest_sha256"],
                "status": "succeeded",
            },
            "canonical_events": {
                "path": EVENTS_RELATIVE_PATH,
                **candidate["events_artifact"],
                "run_id_verified": True,
                "source_model_count": len(candidate["source_models"]),
            },
            "statistics": statistics_by_candidate[label],
        }
        for label, candidate in loaded.items()
    }

    return {
        "schema_version": 1,
        "report_type": "descriptive_canonical_melody_candidate_comparison",
        "status": "completed",
        "generated_at": utc_now(),
        "claims": {
            "accuracy_claimed": False,
            "human_reference_annotations_used": False,
            "preferred_candidate_selected": False,
        },
        "lineage_validation": {
            "project_id": project_id,
            "shared_canonical_mix_sha256": canonical_mix_sha256,
            "all_candidates_share_project_identity": True,
            "all_candidates_share_canonical_mix": True,
            "direct_and_separator_vocal_descendants_supported": True,
        },
        "definitions": {
            "adjacent_onset_gap_sec": (
                "Current onset minus the immediately preceding onset after stable onset sorting."
            ),
            "inter_event_silence_gap_sec": (
                "Current onset minus the latest prior offset, floored at zero."
            ),
            "phrase_gap": (
                f"Inter-event silence greater than or equal to "
                f"{PHRASE_GAP_THRESHOLD_SEC:.1f} seconds."
            ),
            "overlap_event_rate": (
                "Events starting before the latest prior offset divided by all events."
            ),
            "polyphonic_active_time_rate": (
                "Time with at least two active notes divided by time with at least one active note."
            ),
            "register_bands_midi": {name: [lower, upper] for name, lower, upper in REGISTER_BANDS},
        },
        "review_thresholds": {
            "phrase_gap_sec": PHRASE_GAP_THRESHOLD_SEC,
            "short_note_sec": SHORT_NOTE_THRESHOLD_SEC,
            "fragmentation_min_event_count": FRAGMENTATION_MIN_EVENT_COUNT,
            "fragmentation_short_note_rate": FRAGMENTATION_SHORT_NOTE_RATE,
            "polyphony_active_time_rate": POLYPHONY_REVIEW_RATE,
            "wide_register_span_semitones": WIDE_REGISTER_SPAN_SEMITONES,
        },
        "candidates": candidate_records,
        "failure_taxonomy_draft": {
            "status": "heuristic_review_only",
            "candidates": _failure_flags(statistics_by_candidate),
            "interpretation": (
                "Flags identify excerpts or paths for human review. They are not error labels "
                "and do not establish transcription quality."
            ),
        },
        "complementarity_draft": {
            "status": "structural_signals_only",
            "pairs": _complementarity_draft(statistics_by_candidate),
            "interpretation": (
                "Structural differences can guide later reference annotation. They do not "
                "establish that either candidate is correct or that the paths are complementary."
            ),
        },
        "limitations": [
            "No human reference annotations are consumed.",
            "No precision, recall, F1, coverage, or accuracy metric is computed.",
            "Heuristic flags must not be used to rank or select a candidate.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare hash-verified canonical melody event sets without loading model packages."
        )
    )
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=RUN_DIR",
        help="Candidate label and immutable run directory; repeat at least twice.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    named_runs = parse_named_runs(args.run)
    result = compare_candidates(named_runs)
    output = args.output.expanduser().resolve()
    atomic_write_json(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
