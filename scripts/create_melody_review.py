#!/usr/bin/env python3
"""Create a synchronized Task 004 piano-listening package from canonical events."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import struct
import subprocess
import tempfile
import unicodedata
import wave
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from amt_core.events import EventValidationError, NoteEvent, read_jsonl
from amt_core.utils import atomic_write_json

EVENTS_RELATIVE_PATH = "normalized/events.jsonl"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,198}\Z", re.ASCII)
SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")

MIDI_FORMAT = 0
MIDI_TICKS_PER_BEAT = 480
MIDI_TEMPO_BPM = 120
MIDI_TEMPO_US_PER_BEAT = 500_000
MIDI_TICKS_PER_SECOND = MIDI_TICKS_PER_BEAT * MIDI_TEMPO_BPM // 60
MIDI_PROGRAM = 0
DEFAULT_VELOCITY = 96


class MelodyReviewError(RuntimeError):
    """Raised when a trustworthy Task 004 review package cannot be created."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_filename_component(value: str, *, kind: str, reserved: set[str]) -> str:
    if not value or value != value.strip():
        raise MelodyReviewError(f"{kind} must be a non-empty filename component")
    if value in {".", ".."} or Path(value).is_absolute() or "/" in value or "\\" in value:
        raise MelodyReviewError(f"{kind} must be one safe filename component: {value!r}")
    if value.startswith(".") or any(
        unicodedata.category(character).startswith("C") for character in value
    ):
        raise MelodyReviewError(f"{kind} contains an unsafe character: {value!r}")
    if any(not (character.isalnum() or character in {"-", "_", "."}) for character in value):
        raise MelodyReviewError(f"{kind} contains an unsafe character: {value!r}")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    if normalized in reserved:
        raise MelodyReviewError(f"{kind} is reserved: {value!r}")
    return value


def _validate_unique_components(
    values: list[str],
    *,
    kind: str,
    reserved: set[str] | None = None,
) -> None:
    seen: dict[str, str] = {}
    for value in values:
        _validate_filename_component(value, kind=kind, reserved=reserved or set())
        normalized = unicodedata.normalize("NFKC", value).casefold()
        if normalized in seen:
            raise MelodyReviewError(
                f"{kind} values collide as filename components: {seen[normalized]!r}, {value!r}"
            )
        seen[normalized] = value


def parse_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise MelodyReviewError(f"Invalid candidate (expected LABEL=RUN_DIR): {value!r}")
    label, raw_path = value.split("=", 1)
    _validate_filename_component(label, kind="Candidate label", reserved={"mix"})
    if not raw_path.strip():
        raise MelodyReviewError(f"Candidate run directory is empty: {label!r}")
    return label, Path(raw_path.strip()).expanduser()


def parse_passage(value: str) -> tuple[str, tuple[float, float]]:
    if "=" not in value:
        raise MelodyReviewError(f"Invalid passage (expected ID=START:DURATION): {value!r}")
    passage_id, raw_window = value.split("=", 1)
    _validate_filename_component(passage_id, kind="Passage ID", reserved=set())
    parts = raw_window.split(":")
    if len(parts) != 2:
        raise MelodyReviewError(f"Invalid passage window (expected START:DURATION): {raw_window!r}")
    try:
        start_sec, duration_sec = (float(part) for part in parts)
    except ValueError as exc:
        raise MelodyReviewError(f"Passage times must be numbers: {raw_window!r}") from exc
    _validate_passage_window(passage_id, start_sec, duration_sec)
    return passage_id, (start_sec, duration_sec)


def _validate_passage_window(
    passage_id: str,
    start_sec: float,
    duration_sec: float,
) -> None:
    if not math.isfinite(start_sec) or start_sec < 0:
        raise MelodyReviewError(f"Passage {passage_id!r} start must be finite and non-negative")
    if not math.isfinite(duration_sec) or duration_sec <= 0:
        raise MelodyReviewError(f"Passage {passage_id!r} duration must be finite and positive")
    if not math.isfinite(start_sec + duration_sec):
        raise MelodyReviewError(f"Passage {passage_id!r} end time is not finite")


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MelodyReviewError(f"Cannot read {label} JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MelodyReviewError(f"{label} root must be a JSON object: {path}")
    return value


def _snapshot_file(path: Path, *, label: str) -> dict[str, Any]:
    try:
        resolved = path.expanduser().resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise MelodyReviewError(f"{label} is missing or unreadable: {path}") from exc
    if not resolved.is_file():
        raise MelodyReviewError(f"{label} is not a regular file: {resolved}")
    return {
        "path": str(resolved),
        "sha256": sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _verify_snapshot(record: dict[str, Any], *, label: str) -> None:
    path = Path(record["path"])
    if not path.is_file():
        raise MelodyReviewError(f"{label} changed or disappeared during rendering: {path}")
    actual_size = path.stat().st_size
    if actual_size != record["size_bytes"]:
        raise MelodyReviewError(f"{label} size changed during rendering: {path}")
    if sha256_file(path) != record["sha256"]:
        raise MelodyReviewError(f"{label} SHA-256 changed during rendering: {path}")


def _safe_manifest_relative_path(value: Any, *, label: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/") or "\\" in value:
        raise MelodyReviewError(f"{label} is not a safe POSIX relative path")
    parts = value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise MelodyReviewError(f"{label} is not a safe POSIX relative path")
    return Path(*parts)


def _resolve_owned_path(
    owner: Path,
    relative_path: Path,
    *,
    label: str,
    expect_file: bool,
) -> Path:
    try:
        resolved_owner = owner.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise MelodyReviewError(f"{label} owner is missing or unreadable") from exc
    cursor = resolved_owner
    for part in relative_path.parts:
        cursor /= part
        if cursor.is_symlink():
            raise MelodyReviewError(f"{label} contains a symbolic-link component: {cursor}")
    try:
        resolved = cursor.resolve(strict=True)
        resolved.relative_to(resolved_owner)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise MelodyReviewError(f"{label} is missing or escapes its owner") from exc
    if expect_file and not resolved.is_file():
        raise MelodyReviewError(f"{label} is not a regular file")
    if not expect_file and not resolved.is_dir():
        raise MelodyReviewError(f"{label} is not a directory")
    return resolved


def _load_project_identity(
    run_dir: Path,
    manifest: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    if run_dir.parent.name != "runs":
        raise MelodyReviewError(f"{label} run must be stored under one project runs/ directory")
    project_dir = run_dir.parent.parent
    project_manifest_path = project_dir / "manifest.json"
    if project_manifest_path.is_symlink() or not project_manifest_path.is_file():
        raise MelodyReviewError(
            f"{label} project manifest is missing or unsafe: {project_manifest_path}"
        )
    project_manifest = _load_json_object(
        project_manifest_path,
        label=f"{label} project manifest",
    )
    if project_manifest.get("schema_version") != 1:
        raise MelodyReviewError(f"{label} project manifest schema_version must be 1")
    project_id = project_manifest.get("project_id")
    if not isinstance(project_id, str) or not project_id or project_id != project_dir.name:
        raise MelodyReviewError(f"{label} project identity does not match its directory")
    run_project_id = manifest.get("project_id")
    if run_project_id is not None and run_project_id != project_id:
        raise MelodyReviewError(f"{label} run project_id does not match its project manifest")

    canonical_record = project_manifest.get("canonical_audio")
    if not isinstance(canonical_record, dict):
        raise MelodyReviewError(f"{label} project has no canonical_audio record")
    canonical_relative = _safe_manifest_relative_path(
        canonical_record.get("path"),
        label=f"{label} canonical_audio.path",
    )
    canonical_path = _resolve_owned_path(
        project_dir,
        canonical_relative,
        label=f"{label} project canonical mix",
        expect_file=True,
    )
    canonical_snapshot = _snapshot_file(canonical_path, label=f"{label} canonical mix")
    expected_hash = canonical_record.get("sha256")
    if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
        raise MelodyReviewError(f"{label} project canonical mix SHA-256 is invalid")
    if canonical_snapshot["sha256"] != expected_hash.lower():
        raise MelodyReviewError(
            f"{label} project canonical mix SHA-256 does not match the current file"
        )
    return {
        "project_id": project_id,
        "project_id_source": (
            "run_and_project_manifests"
            if run_project_id is not None
            else "legacy_run_directory_and_project_manifest"
        ),
        "project_dir": str(project_dir),
        "project_manifest": _snapshot_file(
            project_manifest_path,
            label=f"{label} project manifest",
        ),
        "canonical_mix": canonical_snapshot,
    }


def _single_input(manifest: dict[str, Any], *, label: str) -> dict[str, str]:
    inputs = manifest.get("inputs")
    if not isinstance(inputs, list) or len(inputs) != 1 or not isinstance(inputs[0], dict):
        raise MelodyReviewError(f"{label} manifest must record exactly one input")
    input_record = inputs[0]
    input_path = input_record.get("path")
    input_hash = input_record.get("sha256")
    if not isinstance(input_path, str) or not input_path:
        raise MelodyReviewError(f"{label} manifest input path is missing")
    if not isinstance(input_hash, str) or SHA256_PATTERN.fullmatch(input_hash) is None:
        raise MelodyReviewError(f"{label} manifest input SHA-256 is invalid")
    return {"path": input_path, "sha256": input_hash.lower()}


def _input_path_stem_parts(input_path: str) -> tuple[str, str] | None:
    parts = PurePosixPath(input_path).parts
    matches: list[tuple[str, str]] = []
    for index in range(len(parts) - 3):
        if parts[index] != "runs" or parts[index + 2 : index + 4] != ("raw", "stems"):
            continue
        if index + 4 != len(parts) - 1:
            continue
        matches.append((parts[index + 1], "/".join(parts[index + 2 :])))
    if len(matches) != 1:
        return None
    return matches[0]


def _verified_parent_separator(
    project: dict[str, Any],
    *,
    parent_run_id: str,
    parent_output_path: str,
    input_sha256: str,
    label: str,
    expected_parent_manifest_sha256: str | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if RUN_ID_PATTERN.fullmatch(parent_run_id) is None or ".." in parent_run_id:
        raise MelodyReviewError(f"{label} parent separator run_id is unsafe")
    relative_output = _safe_manifest_relative_path(
        parent_output_path,
        label=f"{label} parent output path",
    )
    if (
        len(relative_output.parts) != 3
        or relative_output.parts[:2] != ("raw", "stems")
        or relative_output.stem != "vocals"
    ):
        raise MelodyReviewError(f"{label} lineage must resolve to a separator vocals stem")

    project_dir = Path(project["project_dir"])
    parent_run_dir = _resolve_owned_path(
        project_dir,
        Path("runs", parent_run_id),
        label=f"{label} parent separator run",
        expect_file=False,
    )
    parent_manifest_path = parent_run_dir / "run_manifest.json"
    if parent_manifest_path.is_symlink() or not parent_manifest_path.is_file():
        raise MelodyReviewError(f"{label} parent separator manifest is missing or unsafe")
    parent_manifest = _load_json_object(
        parent_manifest_path,
        label=f"{label} parent separator manifest",
    )
    if (
        parent_manifest.get("schema_version") != 1
        or parent_manifest.get("status") != "succeeded"
        or parent_manifest.get("worker") != "separator"
        or parent_manifest.get("run_id") != parent_run_id
    ):
        raise MelodyReviewError(f"{label} parent lineage is not a matching succeeded separator run")
    parent_manifest_snapshot = _snapshot_file(
        parent_manifest_path,
        label=f"{label} parent separator manifest",
    )
    if (
        expected_parent_manifest_sha256 is not None
        and parent_manifest_snapshot["sha256"] != expected_parent_manifest_sha256
    ):
        raise MelodyReviewError(f"{label} parent separator manifest SHA-256 does not match lineage")

    parent_inputs = parent_manifest.get("inputs")
    if (
        not isinstance(parent_inputs, list)
        or len(parent_inputs) != 1
        or not isinstance(parent_inputs[0], dict)
        or parent_inputs[0].get("sha256") != project["canonical_mix"]["sha256"]
    ):
        raise MelodyReviewError(
            f"{label} parent separator is not bound to the project canonical mix SHA-256"
        )

    parent_outputs = parent_manifest.get("outputs")
    if not isinstance(parent_outputs, list):
        raise MelodyReviewError(f"{label} parent separator outputs must be a list")
    matching_outputs = [
        record
        for record in parent_outputs
        if isinstance(record, dict) and record.get("path") == parent_output_path
    ]
    if len(matching_outputs) != 1:
        raise MelodyReviewError(
            f"{label} parent separator must record exactly one matching vocals stem"
        )
    output_record = matching_outputs[0]
    if output_record.get("sha256") != input_sha256:
        raise MelodyReviewError(
            f"{label} candidate input SHA-256 does not match its parent vocals stem"
        )

    stem_path = _resolve_owned_path(
        parent_run_dir,
        relative_output,
        label=f"{label} parent vocals stem",
        expect_file=True,
    )
    stem_snapshot = _snapshot_file(stem_path, label=f"{label} parent vocals stem")
    expected_size = output_record.get("size_bytes")
    if (
        isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
        or stem_snapshot["size_bytes"] != expected_size
    ):
        raise MelodyReviewError(f"{label} parent vocals stem size does not match manifest")
    if stem_snapshot["sha256"] != input_sha256:
        raise MelodyReviewError(f"{label} parent vocals stem SHA-256 does not match manifest")

    return (
        {
            "parent_separator_run_id": parent_run_id,
            "parent_manifest": parent_manifest_snapshot,
            "parent_output_path": parent_output_path,
            "parent_stem": stem_snapshot,
            "canonical_mix_sha256": project["canonical_mix"]["sha256"],
        },
        [parent_manifest_snapshot, stem_snapshot],
    )


def _verify_input_lineage(
    manifest: dict[str, Any],
    project: dict[str, Any],
    *,
    label: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    input_record = _single_input(manifest, label=label)
    canonical_hash = project["canonical_mix"]["sha256"]
    lineage = manifest.get("input_lineage")
    if lineage is None:
        if input_record["sha256"] == canonical_hash:
            return (
                {
                    "kind": "direct_canonical_mix",
                    "source": "legacy_manifest_input_derived_and_verified",
                    "canonical_mix_sha256": canonical_hash,
                },
                [],
            )
        stem_parts = _input_path_stem_parts(input_record["path"])
        if stem_parts is None:
            raise MelodyReviewError(
                f"{label} legacy input cannot be resolved to the project canonical mix "
                "or a separator vocals stem"
            )
        parent_run_id, parent_output_path = stem_parts
        parent, snapshots = _verified_parent_separator(
            project,
            parent_run_id=parent_run_id,
            parent_output_path=parent_output_path,
            input_sha256=input_record["sha256"],
            label=label,
            expected_parent_manifest_sha256=None,
        )
        return (
            {
                "kind": "separator_vocal_stem",
                "source": "legacy_manifest_path_derived_and_verified",
                **parent,
            },
            snapshots,
        )

    if not isinstance(lineage, dict):
        raise MelodyReviewError(f"{label} input_lineage must be a JSON object")
    kind = lineage.get("kind")
    if kind == "direct_canonical_mix":
        if (
            input_record["sha256"] != canonical_hash
            or lineage.get("canonical_mix_sha256") != canonical_hash
        ):
            raise MelodyReviewError(
                f"{label} direct input lineage canonical mix SHA-256 does not match project"
            )
        return (
            {
                "kind": kind,
                "source": "manifest_input_lineage_verified",
                "canonical_mix_sha256": canonical_hash,
            },
            [],
        )
    if kind not in {"separator_stem", "separator_vocal_stem"}:
        raise MelodyReviewError(
            f"{label} input lineage kind is unresolved or unsupported: {kind!r}"
        )
    if lineage.get("canonical_mix_sha256") != canonical_hash:
        raise MelodyReviewError(
            f"{label} separator lineage canonical mix SHA-256 does not match project"
        )
    timeline_basis = lineage.get("timeline_basis")
    if timeline_basis is not None and timeline_basis != "original_canonical_mix_seconds":
        raise MelodyReviewError(f"{label} lineage timeline basis is not canonical seconds")

    parent_run_id = lineage.get("parent_separator_run_id")
    parent_output_path = lineage.get("parent_output_path")
    parent_manifest_hash = lineage.get("parent_manifest_sha256")
    parent_stem_hash = lineage.get("parent_stem_sha256")
    if (
        not isinstance(parent_run_id, str)
        or not isinstance(parent_output_path, str)
        or not isinstance(parent_manifest_hash, str)
        or SHA256_PATTERN.fullmatch(parent_manifest_hash) is None
        or not isinstance(parent_stem_hash, str)
        or SHA256_PATTERN.fullmatch(parent_stem_hash) is None
    ):
        raise MelodyReviewError(f"{label} separator lineage fields are incomplete")
    if parent_stem_hash.lower() != input_record["sha256"]:
        raise MelodyReviewError(
            f"{label} lineage parent stem SHA-256 does not match candidate input"
        )
    path_stem_parts = _input_path_stem_parts(input_record["path"])
    if path_stem_parts != (parent_run_id, parent_output_path):
        raise MelodyReviewError(
            f"{label} candidate input path does not match its separator lineage"
        )
    parent, snapshots = _verified_parent_separator(
        project,
        parent_run_id=parent_run_id,
        parent_output_path=parent_output_path,
        input_sha256=input_record["sha256"],
        label=label,
        expected_parent_manifest_sha256=parent_manifest_hash.lower(),
    )
    return (
        {
            "kind": "separator_vocal_stem",
            "source": "manifest_input_lineage_verified",
            **parent,
        },
        snapshots,
    )


def _load_candidate(label: str, run_path: Path) -> dict[str, Any]:
    if run_path.is_symlink() or not run_path.is_dir():
        raise MelodyReviewError(f"{label} run directory is missing or unsafe: {run_path}")
    run_dir = run_path.resolve(strict=True)
    manifest_path = run_dir / "run_manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise MelodyReviewError(f"{label} run manifest is missing or unsafe: {manifest_path}")
    manifest = _load_json_object(manifest_path, label=f"{label} manifest")

    if manifest.get("schema_version") != 1:
        raise MelodyReviewError(f"{label} manifest schema_version must be 1")
    if manifest.get("status") != "succeeded":
        raise MelodyReviewError(f"{label} manifest status is not succeeded")
    run_id = manifest.get("run_id")
    if not isinstance(run_id, str) or RUN_ID_PATTERN.fullmatch(run_id) is None or ".." in run_id:
        raise MelodyReviewError(f"{label} manifest run_id is missing or unsafe")
    if run_id != run_dir.name:
        raise MelodyReviewError(f"{label} manifest run_id does not match its directory")
    worker = manifest.get("worker")
    if not isinstance(worker, str) or not worker.strip():
        raise MelodyReviewError(f"{label} manifest worker is missing")
    project = _load_project_identity(run_dir, manifest, label=label)
    lineage, lineage_snapshots = _verify_input_lineage(
        manifest,
        project,
        label=label,
    )

    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise MelodyReviewError(f"{label} manifest outputs must be a list")
    event_records = [
        record
        for record in outputs
        if isinstance(record, dict) and record.get("path") == EVENTS_RELATIVE_PATH
    ]
    if len(event_records) != 1:
        raise MelodyReviewError(
            f"{label} manifest must record exactly one {EVENTS_RELATIVE_PATH} output"
        )

    normalized_dir = run_dir / "normalized"
    events_path = normalized_dir / "events.jsonl"
    if normalized_dir.is_symlink() or events_path.is_symlink():
        raise MelodyReviewError(f"{label} canonical events path must not use symlinks")
    try:
        resolved_events = events_path.resolve(strict=True)
        resolved_events.relative_to(run_dir)
    except (FileNotFoundError, OSError, ValueError) as exc:
        raise MelodyReviewError(
            f"{label} canonical events are missing or escape the run directory"
        ) from exc
    if not resolved_events.is_file():
        raise MelodyReviewError(f"{label} canonical events are not a regular file")

    event_record = event_records[0]
    expected_size = event_record.get("size_bytes")
    if isinstance(expected_size, bool) or not isinstance(expected_size, int) or expected_size < 0:
        raise MelodyReviewError(f"{label} canonical events size_bytes is invalid")
    actual_size = resolved_events.stat().st_size
    if actual_size != expected_size:
        raise MelodyReviewError(
            f"{label} canonical events size mismatch: {actual_size} != {expected_size}"
        )
    expected_hash = event_record.get("sha256")
    if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
        raise MelodyReviewError(f"{label} canonical events SHA-256 is invalid")
    actual_hash = sha256_file(resolved_events)
    if actual_hash != expected_hash.lower():
        raise MelodyReviewError(
            f"{label} canonical events SHA-256 mismatch: {actual_hash} != {expected_hash.lower()}"
        )

    try:
        events = read_jsonl(resolved_events)
    except (OSError, UnicodeDecodeError, EventValidationError) as exc:
        raise MelodyReviewError(f"{label} canonical events are invalid: {exc}") from exc
    for event in events:
        if event.source_run_id != run_id:
            raise MelodyReviewError(
                f"{label} canonical event source_run_id does not match {run_id!r}"
            )
        if not all(
            math.isfinite(value) for value in (event.onset_sec, event.offset_sec, event.pitch_midi)
        ):
            raise MelodyReviewError(f"{label} canonical events contain a non-finite number")
    if events and any(event.instrument != "voice" for event in events):
        raise MelodyReviewError(f"{label} nonempty melody candidate is not entirely voice-scoped")

    manifest_snapshot = _snapshot_file(manifest_path, label=f"{label} manifest")
    events_snapshot = {
        "path": str(resolved_events),
        "sha256": actual_hash,
        "size_bytes": actual_size,
    }
    return {
        "label": label,
        "run_dir": str(run_dir),
        "run_id": run_id,
        "worker": worker,
        "model": manifest.get("model"),
        "project": project,
        "input": _single_input(manifest, label=label),
        "input_lineage": lineage,
        "manifest": manifest_snapshot,
        "canonical_events": {
            **events_snapshot,
            "manifest_output_path": EVENTS_RELATIVE_PATH,
            "event_count": len(events),
            "run_id_verified": True,
            "source_run_id_verified": True,
            "voice_scope_verified": True,
        },
        "events": events,
        "_source_snapshots": [
            project["project_manifest"],
            project["canonical_mix"],
            *lineage_snapshots,
        ],
    }


def _encode_variable_length(value: int) -> bytes:
    if not 0 <= value <= 0x0FFFFFFF:
        raise MelodyReviewError(f"MIDI delta time is outside the standard VLQ range: {value}")
    encoded = [value & 0x7F]
    value >>= 7
    while value:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    return bytes(reversed(encoded))


def _seconds_to_tick(seconds: float) -> int:
    return math.floor(seconds * MIDI_TICKS_PER_SECOND + 0.5)


def _midi_pitch(event: NoteEvent) -> int:
    if event.quantized_pitch_midi is not None:
        return event.quantized_pitch_midi
    return math.floor(event.pitch_midi + 0.5)


def _midi_velocity(event: NoteEvent) -> int:
    if event.velocity is None:
        return DEFAULT_VELOCITY
    return min(127, max(1, event.velocity))


def build_standard_midi(
    events: list[NoteEvent],
    *,
    minimum_duration_sec: float = 0.0,
) -> bytes:
    """Build a format-0 review MIDI while retaining absolute canonical time."""

    if not math.isfinite(minimum_duration_sec) or minimum_duration_sec < 0:
        raise MelodyReviewError("MIDI minimum duration must be finite and non-negative")

    # priority guarantees note_off before note_on at a shared tick.
    timed_events: list[tuple[int, int, int, int, bytes]] = [
        (0, -2, 0, 0, b"\xff\x51\x03" + MIDI_TEMPO_US_PER_BEAT.to_bytes(3, "big")),
        (0, -1, 0, 0, bytes((0xC0, MIDI_PROGRAM))),
    ]
    final_tick = _seconds_to_tick(minimum_duration_sec)
    for index, event in enumerate(events):
        if not all(
            math.isfinite(value) for value in (event.onset_sec, event.offset_sec, event.pitch_midi)
        ):
            raise MelodyReviewError("Cannot render a canonical event with non-finite timing/pitch")
        onset_tick = _seconds_to_tick(event.onset_sec)
        offset_tick = max(onset_tick + 1, _seconds_to_tick(event.offset_sec))
        pitch = _midi_pitch(event)
        if not 0 <= pitch <= 127:
            raise MelodyReviewError(f"Cannot render pitch outside MIDI range: {pitch}")
        timed_events.append((offset_tick, 0, pitch, index, bytes((0x80, pitch, 0))))
        timed_events.append(
            (onset_tick, 1, pitch, index, bytes((0x90, pitch, _midi_velocity(event))))
        )
        final_tick = max(final_tick, offset_tick)
    timed_events.append((final_tick, 2, 0, 0, b"\xff\x2f\x00"))
    timed_events.sort(key=lambda item: item[:4])

    track = bytearray()
    previous_tick = 0
    for tick, _priority, _pitch, _index, message in timed_events:
        delta = tick - previous_tick
        track.extend(_encode_variable_length(delta))
        track.extend(message)
        previous_tick = tick

    header = b"MThd" + struct.pack(
        ">IHHH",
        6,
        MIDI_FORMAT,
        1,
        MIDI_TICKS_PER_BEAT,
    )
    return header + b"MTrk" + struct.pack(">I", len(track)) + bytes(track)


def _write_midi(path: Path, events: list[NoteEvent], *, minimum_duration_sec: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_standard_midi(events, minimum_duration_sec=minimum_duration_sec)
    with path.open("wb") as handle:
        handle.write(payload)


def _resolve_executable(value: str | Path, *, label: str) -> dict[str, Any]:
    requested = str(value)
    if not requested:
        raise MelodyReviewError(f"{label} executable must not be empty")
    if "/" in requested or "\\" in requested:
        candidate = Path(requested).expanduser()
        try:
            executable = candidate.resolve(strict=True)
        except (FileNotFoundError, OSError) as exc:
            raise MelodyReviewError(f"{label} executable is missing: {candidate}") from exc
    else:
        located = shutil.which(requested)
        if located is None:
            raise MelodyReviewError(f"{label} executable is not on PATH: {requested}")
        executable = Path(located).resolve(strict=True)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise MelodyReviewError(f"{label} executable is not an executable file: {executable}")
    return {
        "requested": requested,
        **_snapshot_file(executable, label=f"{label} executable"),
    }


def _write_command_log(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(payload)


def _run_command(
    argv: list[str],
    *,
    stage: Path,
    command_index: int,
    tool: str,
    purpose: str,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[bytes]]:
    result = subprocess.run(argv, check=False, capture_output=True)
    log_stem = f"command-{command_index:03d}-{tool}"
    stdout_path = stage / "logs" / f"{log_stem}.stdout.log"
    stderr_path = stage / "logs" / f"{log_stem}.stderr.log"
    _write_command_log(stdout_path, result.stdout)
    _write_command_log(stderr_path, result.stderr)
    record = {
        "index": command_index,
        "tool": tool,
        "purpose": purpose,
        "argv": argv,
        "returncode": result.returncode,
        "stdout_log": stdout_path.relative_to(stage).as_posix(),
        "stderr_log": stderr_path.relative_to(stage).as_posix(),
    }
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise MelodyReviewError(
            f"{tool} failed for {purpose} with exit code {result.returncode}: {detail}"
        )
    return record, result


def _require_generated_file(path: Path, *, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise MelodyReviewError(f"{label} was not created as a regular file: {path}")
    if path.stat().st_size == 0:
        raise MelodyReviewError(f"{label} is empty: {path}")


def _verify_pcm_excerpt(path: Path, *, duration_sec: float, label: str) -> dict[str, Any]:
    expected_frames = round(duration_sec * 44_100)
    try:
        with wave.open(str(path), "rb") as handle:
            channels = handle.getnchannels()
            sample_width_bytes = handle.getsampwidth()
            sample_rate_hz = handle.getframerate()
            frame_count = handle.getnframes()
            compression_type = handle.getcomptype()
    except (EOFError, OSError, wave.Error) as exc:
        raise MelodyReviewError(f"{label} is not a readable PCM WAV: {exc}") from exc
    if (
        channels != 2
        or sample_width_bytes != 2
        or sample_rate_hz != 44_100
        or compression_type != "NONE"
    ):
        raise MelodyReviewError(f"{label} is not 44.1 kHz stereo 16-bit PCM WAV")
    frame_error = frame_count - expected_frames
    if abs(frame_error) > 1:
        raise MelodyReviewError(
            f"{label} duration is truncated or mismatched: "
            f"{frame_count} frames != {expected_frames} expected"
        )
    return {
        "container": "wav",
        "encoding": "pcm_s16le",
        "sample_rate_hz": sample_rate_hz,
        "channels": channels,
        "sample_width_bytes": sample_width_bytes,
        "frame_count": frame_count,
        "expected_frame_count": expected_frames,
        "frame_error": frame_error,
        "duration_sec": frame_count / sample_rate_hz,
        "requested_duration_sec": duration_sec,
        "duration_tolerance_frames": 1,
        "synchronized_window_verified": True,
    }


def _artifact_records(stage: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(stage.rglob("*")):
        if path.is_symlink():
            raise MelodyReviewError(f"Generated review output must not be a symlink: {path}")
        if not path.is_file():
            continue
        relative_path = path.relative_to(stage).as_posix()
        if relative_path == "review_manifest.json":
            continue
        records.append(
            {
                "path": relative_path,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def _artifact_by_path(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {record["path"]: record for record in records}


def _output_is_present(path: Path) -> bool:
    return os.path.lexists(path)


def _cleanup_staging(path: Path) -> None:
    if path.is_symlink():
        path.unlink(missing_ok=True)
    elif path.exists():
        shutil.rmtree(path)


def create_review(
    *,
    mix: Path,
    candidates: dict[str, Path],
    passages: dict[str, tuple[float, float]],
    soundfont: Path,
    output: Path,
    fluidsynth: str | Path = "fluidsynth",
    ffmpeg: str | Path = "ffmpeg",
) -> dict[str, Any]:
    """Create an immutable synchronized review package in a new directory."""

    if len(candidates) < 3:
        raise MelodyReviewError("At least three independent candidate runs are required")
    if len(passages) < 3:
        raise MelodyReviewError("At least three review passages are required")
    _validate_unique_components(
        list(candidates),
        kind="Candidate label",
        reserved={"mix"},
    )
    _validate_unique_components(list(passages), kind="Passage ID")
    for passage_id, (start_sec, duration_sec) in passages.items():
        _validate_passage_window(passage_id, start_sec, duration_sec)

    output = output.expanduser().absolute()
    if _output_is_present(output):
        raise MelodyReviewError(f"Refusing to overwrite or follow output path: {output}")

    mix_record = _snapshot_file(mix, label="Mix")
    soundfont_record = _snapshot_file(soundfont, label="SoundFont")
    tool_records = {
        "fluidsynth": _resolve_executable(fluidsynth, label="FluidSynth"),
        "ffmpeg": _resolve_executable(ffmpeg, label="ffmpeg"),
    }

    loaded_candidates = {
        label: _load_candidate(label, run_path) for label, run_path in candidates.items()
    }
    run_paths = [record["run_dir"] for record in loaded_candidates.values()]
    if len(set(run_paths)) != len(run_paths):
        raise MelodyReviewError("Candidate run directories must be distinct")
    run_ids = [record["run_id"] for record in loaded_candidates.values()]
    if len(set(run_ids)) != len(run_ids):
        raise MelodyReviewError("Candidate run_id values must be distinct")
    project_ids = {record["project"]["project_id"] for record in loaded_candidates.values()}
    project_dirs = {record["project"]["project_dir"] for record in loaded_candidates.values()}
    canonical_hashes = {
        record["project"]["canonical_mix"]["sha256"] for record in loaded_candidates.values()
    }
    if len(project_ids) != 1 or len(project_dirs) != 1 or len(canonical_hashes) != 1:
        raise MelodyReviewError(
            "All candidate runs must share one project identity and canonical mix SHA-256"
        )
    candidate_canonical = next(iter(loaded_candidates.values()))["project"]["canonical_mix"]
    shared_project = next(iter(loaded_candidates.values()))["project"]
    if (
        mix_record["path"] != candidate_canonical["path"]
        or mix_record["sha256"] != candidate_canonical["sha256"]
    ):
        raise MelodyReviewError(
            "Supplied mix must be the shared project canonical mix with the same SHA-256"
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    commands: list[dict[str, Any]] = []
    try:
        for tool, version_args in (
            ("fluidsynth", ["--version"]),
            ("ffmpeg", ["-version"]),
        ):
            executable = tool_records[tool]["path"]
            command, result = _run_command(
                [executable, *version_args],
                stage=stage,
                command_index=len(commands) + 1,
                tool=tool,
                purpose="version_probe",
            )
            commands.append(command)
            tool_records[tool]["version_argv"] = command["argv"]
            version_payload = result.stdout + result.stderr
            tool_records[tool]["version_output_sha256"] = hashlib.sha256(
                version_payload
            ).hexdigest()
            tool_records[tool]["version_text"] = version_payload.decode(
                "utf-8", errors="replace"
            ).strip()[:2000]

        preview_end_sec = max(start + duration for start, duration in passages.values())
        candidate_manifest_records: dict[str, Any] = {}
        full_wav_paths: dict[str, Path] = {}
        for label, candidate in loaded_candidates.items():
            candidate_dir = stage / "candidates" / label
            midi_path = candidate_dir / "candidate.mid"
            full_wav = candidate_dir / "piano-full.wav"
            _write_midi(
                midi_path,
                candidate["events"],
                minimum_duration_sec=preview_end_sec,
            )
            command, _result = _run_command(
                [
                    tool_records["fluidsynth"]["path"],
                    "-ni",
                    "-F",
                    str(full_wav),
                    "-r",
                    "44100",
                    soundfont_record["path"],
                    str(midi_path),
                ],
                stage=stage,
                command_index=len(commands) + 1,
                tool="fluidsynth",
                purpose=f"render_full_piano:{label}",
            )
            commands.append(command)
            _require_generated_file(full_wav, label=f"{label} full piano WAV")
            full_wav_paths[label] = full_wav
            candidate_manifest_records[label] = {
                key: value
                for key, value in candidate.items()
                if key not in {"events", "_source_snapshots"}
            }
            candidate_manifest_records[label]["preview"] = {
                "midi_path": midi_path.relative_to(stage).as_posix(),
                "full_piano_wav_path": full_wav.relative_to(stage).as_posix(),
                "fluidsynth_command_index": command["index"],
            }

        passage_records: list[dict[str, Any]] = []
        for passage_id, (start_sec, duration_sec) in passages.items():
            passage_dir = stage / "passages" / passage_id
            sources = {"mix": Path(mix_record["path"]), **full_wav_paths}
            rendered: dict[str, Any] = {}
            for source_label, source_path in sources.items():
                suffix = "mix.wav" if source_label == "mix" else f"{source_label}-piano.wav"
                destination = passage_dir / suffix
                destination.parent.mkdir(parents=True, exist_ok=True)
                command, _result = _run_command(
                    [
                        tool_records["ffmpeg"]["path"],
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-nostdin",
                        "-y",
                        "-ss",
                        repr(start_sec),
                        "-i",
                        str(source_path),
                        "-t",
                        repr(duration_sec),
                        "-map",
                        "0:a:0",
                        "-ar",
                        "44100",
                        "-ac",
                        "2",
                        "-c:a",
                        "pcm_s16le",
                        str(destination),
                    ],
                    stage=stage,
                    command_index=len(commands) + 1,
                    tool="ffmpeg",
                    purpose=f"crop_passage:{passage_id}:{source_label}",
                )
                commands.append(command)
                _require_generated_file(
                    destination,
                    label=f"{passage_id} {source_label} excerpt",
                )
                rendered[source_label] = {
                    "path": destination.relative_to(stage).as_posix(),
                    "command_index": command["index"],
                    "pcm_validation": _verify_pcm_excerpt(
                        destination,
                        duration_sec=duration_sec,
                        label=f"{passage_id} {source_label} excerpt",
                    ),
                }
            passage_records.append(
                {
                    "passage_id": passage_id,
                    "start_sec": start_sec,
                    "duration_sec": duration_sec,
                    "end_sec": start_sec + duration_sec,
                    "outputs": rendered,
                }
            )

        artifacts = _artifact_records(stage)
        artifact_index = _artifact_by_path(artifacts)
        for candidate in candidate_manifest_records.values():
            preview = candidate["preview"]
            preview["midi"] = artifact_index[preview.pop("midi_path")]
            preview["full_piano_wav"] = artifact_index[preview.pop("full_piano_wav_path")]
        for passage in passage_records:
            for rendered in passage["outputs"].values():
                rendered["artifact"] = artifact_index[rendered.pop("path")]

        review_manifest = {
            "schema_version": 1,
            "generated_at": datetime.now(UTC).isoformat(),
            "status": "awaiting_human_review",
            "artifact_type": "task004_synchronized_piano_review",
            "task": "004",
            "task005_export": False,
            "accuracy_claimed": False,
            "human_review_pending": True,
            "scope": {
                "purpose": "Task 004 baseline listening review only",
                "is_task005_export": False,
                "canonical_events_are_source_of_truth": True,
            },
            "timeline_binding": {
                "project_id": shared_project["project_id"],
                "project_dir": shared_project["project_dir"],
                "canonical_mix_sha256": candidate_canonical["sha256"],
                "canonical_mix_path": candidate_canonical["path"],
                "all_candidates_share_project_and_canonical_mix": True,
                "basis": "original_canonical_mix_seconds",
            },
            "mix": mix_record,
            "soundfont": soundfont_record,
            "tools": tool_records,
            "midi_encoding": {
                "format": MIDI_FORMAT,
                "tempo_bpm": MIDI_TEMPO_BPM,
                "ticks_per_beat": MIDI_TICKS_PER_BEAT,
                "ticks_per_second": MIDI_TICKS_PER_SECOND,
                "program": MIDI_PROGRAM,
                "program_name": "Acoustic Grand Piano",
                "timeline": "original absolute canonical seconds; no excerpt-relative shift",
                "same_tick_order": "note_off before note_on",
                "pitch_mapping": (
                    "quantized_pitch_midi when present; otherwise nearest integer MIDI pitch"
                ),
            },
            "candidates": candidate_manifest_records,
            "passages": passage_records,
            "commands": commands,
            "outputs": artifacts,
            "integrity": {
                "algorithm": "sha256",
                "all_generated_files_hashed_except_manifest_itself": True,
                "review_manifest_self_hashed": False,
            },
            "limitations": [
                "This package is an audition aid, not a Task 005 MIDI export.",
                "No note, melody, or model accuracy is claimed without Task 006 references.",
                "Human listening review is pending.",
            ],
        }

        source_snapshots = [mix_record, soundfont_record, *tool_records.values()]
        for candidate in loaded_candidates.values():
            source_snapshots.extend(
                (
                    candidate["manifest"],
                    candidate["canonical_events"],
                    *candidate["_source_snapshots"],
                )
            )
        for index, record in enumerate(source_snapshots, start=1):
            _verify_snapshot(record, label=f"Source artifact {index}")

        atomic_write_json(stage / "review_manifest.json", review_manifest)
        if _output_is_present(output):
            raise MelodyReviewError(
                f"Output appeared during rendering; refusing overwrite: {output}"
            )
        stage.rename(output)
        return review_manifest
    except BaseException:
        _cleanup_staging(stage)
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a synchronized piano audition package for Task 004 only."
    )
    parser.add_argument("--mix", type=Path, required=True)
    parser.add_argument("--soundfont", type=Path, required=True)
    parser.add_argument(
        "--candidate",
        action="append",
        default=[],
        metavar="LABEL=RUN_DIR",
        help="Canonical candidate run; repeat at least three times.",
    )
    parser.add_argument(
        "--passage",
        action="append",
        default=[],
        metavar="ID=START:DURATION",
        help="Canonical-timeline excerpt; repeat at least three times.",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fluidsynth", default="fluidsynth")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    candidate_pairs = [parse_candidate(value) for value in args.candidate]
    passage_pairs = [parse_passage(value) for value in args.passage]
    _validate_unique_components(
        [label for label, _path in candidate_pairs],
        kind="Candidate label",
        reserved={"mix"},
    )
    _validate_unique_components(
        [passage_id for passage_id, _window in passage_pairs],
        kind="Passage ID",
    )
    result = create_review(
        mix=args.mix,
        candidates=dict(candidate_pairs),
        passages=dict(passage_pairs),
        soundfont=args.soundfont,
        output=args.output,
        fluidsynth=args.fluidsynth,
        ffmpeg=args.ffmpeg,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
