#!/usr/bin/env python3
"""Prepare fixed Task 007 Vocadito development and blind benchmark projects."""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import csv
import json
import math
import os
import re
import shutil
import socket
import sys
import tempfile
import wave
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from amt_core.benchmark import canonical_json_sha256
from amt_core.project import initialize_project
from amt_core.utils import atomic_write_json, sha256_file

CONFIG_SCHEMA = "amt-task007-vocadito-split/v1"
RECOVERY_CONFIG_SCHEMA = "amt-task007-vocadito-split/v2"
SELECTION_SCHEMA = "amt-external-note-selection/v1"
CONCATENATION_SCHEMA = "amt-external-note-concatenation/v1"
BENCHMARK_SCHEMA = "amt-external-note-benchmark-manifest/v1"
PACK_SCHEMA = "amt-benchmark-pack/v1"
EXPECTED_ROUTES = (
    "game-vocal-a",
    "basic-pitch-vocal-a",
    "muscriptor-vocal-a",
    "muscriptor-direct",
)
RECOVERY_EXPECTED_ROUTES = (
    "game-vocal-a",
    "basic-pitch-vocal-a",
)
TASK006_BLIND_SINGERS = frozenset({"S1", "S5", "S11", "S19", "S28", "S29"})
EXPECTED_TRACKS = {
    "development": (
        (2, "S2"),
        (4, "S3"),
        (10, "S7"),
        (13, "S10"),
        (15, "S12"),
        (25, "S20"),
    ),
    "blind_test": (
        (5, "S4"),
        (7, "S6"),
        (11, "S8"),
        (18, "S13"),
        (27, "S22"),
        (34, "S27"),
    ),
}
TASK007_V1_SINGERS = frozenset(
    singer_id
    for pairs in EXPECTED_TRACKS.values()
    for _track_id, singer_id in pairs
)
RECOVERY_EXCLUDED_SINGERS = TASK006_BLIND_SINGERS | TASK007_V1_SINGERS
RECOVERY_EXPECTED_TRACKS = {
    "development": (
        (12, "S9"),
        (20, "S15"),
        (23, "S18"),
        (29, "S23"),
        (33, "S26"),
    ),
    "blind_test": (
        (19, "S14"),
        (21, "S16"),
        (22, "S17"),
        (26, "S21"),
        (30, "S24"),
        (32, "S25"),
    ),
}
SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z", re.ASCII)
SAMPLE_RATE = 44_100
SAMPLE_WIDTH = 2
CHANNELS = 1
NOTE_BOUNDARY_TOLERANCE_SEC = 0.005
LEAD_SILENCE_FRAMES = SAMPLE_RATE
BETWEEN_SILENCE_FRAMES = 2 * SAMPLE_RATE
TAIL_SILENCE_FRAMES = SAMPLE_RATE


class VocaditoPreparationError(RuntimeError):
    """Raised when the fixed Task 007 split cannot be prepared safely."""


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VocaditoPreparationError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise VocaditoPreparationError(f"{label} must be a JSON object")
    return value


def _require_safe_id(value: object, *, label: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None or ".." in value:
        raise VocaditoPreparationError(f"{label} is missing or unsafe")
    return value


def validate_split_config(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and return the exact fixed Task 007 split configuration."""

    schema = value.get("schema")
    if schema not in {CONFIG_SCHEMA, RECOVERY_CONFIG_SCHEMA}:
        raise VocaditoPreparationError(
            f"config schema must be {CONFIG_SCHEMA} or {RECOVERY_CONFIG_SCHEMA}"
        )
    dataset = value.get("dataset")
    if (
        not isinstance(dataset, dict)
        or dataset.get("name") != "vocadito"
        or dataset.get("version") != "v3"
        or dataset.get("doi") != "10.5281/zenodo.5578807"
        or dataset.get("license") != "CC-BY-4.0"
    ):
        raise VocaditoPreparationError("config must identify the pinned Vocadito v3 dataset")
    routes = value.get("candidate_routes")
    if schema == CONFIG_SCHEMA:
        expected_routes = EXPECTED_ROUTES
        expected_tracks = EXPECTED_TRACKS
        excluded_singers = TASK006_BLIND_SINGERS
        excluded = value.get("excluded_task006_blind_singers")
        if not isinstance(excluded, list) or set(excluded) != excluded_singers:
            raise VocaditoPreparationError("Task 006 blind singer exclusion is incomplete")
    else:
        expected_routes = RECOVERY_EXPECTED_ROUTES
        expected_tracks = RECOVERY_EXPECTED_TRACKS
        excluded_singers = RECOVERY_EXCLUDED_SINGERS
        excluded = value.get("excluded_prior_experiment_singers")
        policy = value.get("selection_policy")
        if (
            value.get("experiment_id") != "task007b-gate4-recovery-v2"
            or not isinstance(excluded, list)
            or set(excluded) != excluded_singers
            or not isinstance(policy, dict)
            or policy.get("chosen_before_candidate_inference") is not True
            or policy.get("one_track_per_singer") is not True
            or policy.get("withheld_same_singer_tracks") != [28, 31, 40]
        ):
            raise VocaditoPreparationError(
                "Task 007B recovery identity, prior-singer exclusion, or selection policy "
                "is incomplete"
            )
    if routes != list(expected_routes):
        raise VocaditoPreparationError("candidate routes differ from the fixed Task 007 plan")

    splits = value.get("splits")
    if not isinstance(splits, dict) or set(splits) != set(expected_tracks):
        raise VocaditoPreparationError("config must contain development and blind_test only")
    all_tracks: set[int] = set()
    all_singers: set[str] = set()
    for split_name, expected_pairs in expected_tracks.items():
        split = splits.get(split_name)
        if not isinstance(split, dict) or split.get("split") != split_name:
            raise VocaditoPreparationError(f"{split_name} split identity is invalid")
        for field in ("project_id", "benchmark_id", "pack_id"):
            _require_safe_id(split.get(field), label=f"{split_name} {field}")
        if split.get("prior_system_exposure") is not False:
            raise VocaditoPreparationError(f"{split_name} must precede system exposure")
        if split.get("candidate_output_quality_uninspected_before_freeze") is not True:
            raise VocaditoPreparationError(
                f"{split_name} must declare candidate output quality uninspected"
            )
        tracks = split.get("tracks")
        if not isinstance(tracks, list):
            raise VocaditoPreparationError(f"{split_name} tracks must be a list")
        pairs: list[tuple[int, str]] = []
        for record in tracks:
            if not isinstance(record, dict):
                raise VocaditoPreparationError(f"{split_name} track must be an object")
            track_id = record.get("track_id")
            singer_id = record.get("singer_id")
            average_pitch = record.get("average_midi_pitch")
            language = record.get("language")
            if (
                isinstance(track_id, bool)
                or not isinstance(track_id, int)
                or not isinstance(singer_id, str)
                or isinstance(average_pitch, bool)
                or not isinstance(average_pitch, int)
                or not isinstance(language, str)
                or not language
            ):
                raise VocaditoPreparationError(f"{split_name} track metadata is incomplete")
            pairs.append((track_id, singer_id))
            if track_id in all_tracks or singer_id in all_singers:
                raise VocaditoPreparationError("tracks and singers must be split-disjoint")
            if singer_id in excluded_singers:
                exclusion_label = (
                    "Task 006 blind data"
                    if schema == CONFIG_SCHEMA
                    else "Task 006/007 prior experiments"
                )
                raise VocaditoPreparationError(
                    f"{split_name} singer {singer_id} overlaps {exclusion_label}"
                )
            all_tracks.add(track_id)
            all_singers.add(singer_id)
        if tuple(pairs) != expected_pairs:
            raise VocaditoPreparationError(
                f"{split_name} track/singer pairs differ from the fixed Task 007 split"
            )
    return dict(value)


def load_split_config(path: Path) -> dict[str, Any]:
    """Load the committed split configuration."""

    return validate_split_config(_load_json_object(path, label="split config"))


def require_slurm_compute_node(
    environment: Mapping[str, str] | None = None,
    *,
    hostname: str | None = None,
) -> None:
    """Refuse preprocessing outside a Slurm compute allocation."""

    environment = environment if environment is not None else os.environ
    hostname = hostname if hostname is not None else socket.gethostname()
    if not environment.get("SLURM_JOB_ID") or hostname.startswith("klone-login"):
        raise VocaditoPreparationError(
            "Submit with sbatch; do not prepare Vocadito data on a login node."
        )


def _read_metadata(extracted_root: Path) -> tuple[dict[int, dict[str, Any]], Path]:
    metadata_path = extracted_root / "vocadito_metadata.csv"
    if not metadata_path.is_file() or metadata_path.is_symlink():
        raise VocaditoPreparationError(f"Vocadito metadata is unavailable: {metadata_path}")
    records: dict[int, dict[str, Any]] = {}
    try:
        with metadata_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                track_id = int(row["track_id"])
                if track_id in records:
                    raise VocaditoPreparationError(
                        f"duplicate track in Vocadito metadata: {track_id}"
                    )
                records[track_id] = {
                    "singer_id": row["singer_id"],
                    "average_midi_pitch": int(row["average_pitch"]),
                    "language": row["language"],
                }
    except (KeyError, OSError, TypeError, ValueError) as exc:
        raise VocaditoPreparationError(f"Vocadito metadata is malformed: {metadata_path}") from exc
    return records, metadata_path


def _validated_note_csv(path: Path, *, duration_sec: float) -> int:
    if not path.is_file() or path.is_symlink():
        raise VocaditoPreparationError(f"note annotation is unavailable: {path}")
    count = 0
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for line_number, row in enumerate(csv.reader(handle), start=1):
                if not row or all(not item.strip() for item in row):
                    continue
                if len(row) != 3:
                    raise VocaditoPreparationError(
                        f"{path}:{line_number}: expected onset, pitch Hz, duration"
                    )
                onset, pitch_hz, duration = (float(item) for item in row)
                if (
                    not all(math.isfinite(item) for item in (onset, pitch_hz, duration))
                    or onset < 0
                    or pitch_hz <= 0
                    or duration <= 0
                    # Vocadito timestamps are decimal annotations independent
                    # of the PCM frame grid. Preserve the official CSV while
                    # accepting at most 5 ms of end-boundary quantization drift.
                    or onset + duration
                    > duration_sec + NOTE_BOUNDARY_TOLERANCE_SEC
                ):
                    raise VocaditoPreparationError(
                        f"{path}:{line_number}: note is outside the source audio"
                    )
                count += 1
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise VocaditoPreparationError(f"cannot validate note annotation {path}") from exc
    if count == 0:
        raise VocaditoPreparationError(f"note annotation is empty: {path}")
    return count


def collect_source_records(
    extracted_root: Path,
    track_specs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Verify selected source audio, metadata, and both note annotations."""

    extracted_root = extracted_root.resolve(strict=True)
    audio_root = extracted_root / "Audio"
    note_root = extracted_root / "Annotations" / "Notes"
    if not audio_root.is_dir() or not note_root.is_dir():
        raise VocaditoPreparationError(
            "extracted Vocadito must contain Audio and Annotations/Notes"
        )
    metadata, metadata_path = _read_metadata(extracted_root)
    records: list[dict[str, Any]] = []
    for spec in track_specs:
        track_id = int(spec["track_id"])
        observed_metadata = metadata.get(track_id)
        expected_metadata = {
            "singer_id": spec["singer_id"],
            "average_midi_pitch": spec["average_midi_pitch"],
            "language": spec["language"],
        }
        if observed_metadata != expected_metadata:
            raise VocaditoPreparationError(
                f"Vocadito metadata mismatch for track {track_id}: "
                f"{observed_metadata!r} != {expected_metadata!r}"
            )
        audio_path = audio_root / f"vocadito_{track_id}.wav"
        if not audio_path.is_file() or audio_path.is_symlink():
            raise VocaditoPreparationError(f"source audio is unavailable: {audio_path}")
        try:
            with wave.open(str(audio_path), "rb") as source:
                format_tuple = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                )
                frame_count = source.getnframes()
        except (OSError, EOFError, wave.Error) as exc:
            raise VocaditoPreparationError(f"cannot read source audio {audio_path}") from exc
        if format_tuple != (CHANNELS, SAMPLE_WIDTH, SAMPLE_RATE) or frame_count <= 0:
            raise VocaditoPreparationError(
                f"unsupported Vocadito WAV format for track {track_id}: {format_tuple}"
            )
        duration_sec = frame_count / SAMPLE_RATE
        references: dict[str, dict[str, Any]] = {}
        for annotator in ("a1", "a2"):
            note_path = note_root / f"vocadito_{track_id}_notes{annotator.upper()}.csv"
            note_count = _validated_note_csv(note_path, duration_sec=duration_sec)
            references[annotator] = {
                "path": str(note_path.resolve(strict=True)),
                "sha256": sha256_file(note_path),
                "note_count": note_count,
            }
        records.append(
            {
                "track_id": track_id,
                **expected_metadata,
                "audio_path": str(audio_path.resolve(strict=True)),
                "audio_sha256": sha256_file(audio_path),
                "audio_frame_count": frame_count,
                "note_references": references,
            }
        )
    return records, {
        "path": str(metadata_path.resolve(strict=True)),
        "sha256": sha256_file(metadata_path),
    }


def _write_concatenation(
    output_audio: Path,
    records: list[dict[str, Any]],
    *,
    split_name: str,
    config_sha256: str,
) -> dict[str, Any]:
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_audio.parent / f".{output_audio.name}.{os.getpid()}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise VocaditoPreparationError(f"temporary output already exists: {temporary}")
    cursor = 0
    mapped: list[dict[str, Any]] = []
    try:
        with wave.open(str(temporary), "wb") as output:
            output.setnchannels(CHANNELS)
            output.setsampwidth(SAMPLE_WIDTH)
            output.setframerate(SAMPLE_RATE)
            output.writeframes(b"\0" * LEAD_SILENCE_FRAMES * SAMPLE_WIDTH)
            cursor += LEAD_SILENCE_FRAMES
            for index, record in enumerate(records):
                source_path = Path(record["audio_path"])
                start_frame = cursor
                with wave.open(str(source_path), "rb") as source:
                    while frames := source.readframes(65_536):
                        output.writeframes(frames)
                cursor += int(record["audio_frame_count"])
                end_frame = cursor
                mapped.append(
                    {
                        **{key: value for key, value in record.items() if key != "audio_path"},
                        "excerpt_id": f"{'dev' if split_name == 'development' else 'blind'}"
                        f"-{index + 1:02d}",
                        "start_frame": start_frame,
                        "end_frame": end_frame,
                        "start_sec": start_frame / SAMPLE_RATE,
                        "end_sec": end_frame / SAMPLE_RATE,
                        "duration_sec": (end_frame - start_frame) / SAMPLE_RATE,
                    }
                )
                if index + 1 < len(records):
                    output.writeframes(b"\0" * BETWEEN_SILENCE_FRAMES * SAMPLE_WIDTH)
                    cursor += BETWEEN_SILENCE_FRAMES
            output.writeframes(b"\0" * TAIL_SILENCE_FRAMES * SAMPLE_WIDTH)
            cursor += TAIL_SILENCE_FRAMES
        audio_sha256 = sha256_file(temporary)
        os.replace(temporary, output_audio)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "schema": CONCATENATION_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "created_before_candidate_inference": True,
        "candidate_output_quality_inspected": False,
        "split": split_name,
        "split_config_sha256": config_sha256,
        "sample_rate_hz": SAMPLE_RATE,
        "channels": CHANNELS,
        "sample_width_bytes": SAMPLE_WIDTH,
        "frame_count": cursor,
        "duration_sec": cursor / SAMPLE_RATE,
        "lead_silence_sec": LEAD_SILENCE_FRAMES / SAMPLE_RATE,
        "between_tracks_silence_sec": BETWEEN_SILENCE_FRAMES / SAMPLE_RATE,
        "tail_silence_sec": TAIL_SILENCE_FRAMES / SAMPLE_RATE,
        "concatenated_audio": {
            "path": str(output_audio.resolve(strict=True)),
            "sha256": audio_sha256,
        },
        "tracks": mapped,
    }


def _selection_manifest(
    split_name: str,
    records: list[dict[str, Any]],
    *,
    config: dict[str, Any],
    config_sha256: str,
    metadata_record: dict[str, Any],
) -> dict[str, Any]:
    selected = []
    for record in records:
        selected.append(
            {
                **{
                    key: value
                    for key, value in record.items()
                    if key not in {"audio_path", "note_references"}
                },
                "notes_a1_sha256": record["note_references"]["a1"]["sha256"],
                "notes_a1_count": record["note_references"]["a1"]["note_count"],
                "notes_a2_sha256": record["note_references"]["a2"]["sha256"],
                "notes_a2_count": record["note_references"]["a2"]["note_count"],
            }
        )
    selection = {
        "schema": SELECTION_SCHEMA,
        "selection_frozen_at": datetime.now(UTC).isoformat(),
        "selection_before_candidate_inference": True,
        "candidate_output_inspected": False,
        "post_score_tuning_allowed": split_name == "development",
        "dataset": "vocadito v3",
        "split": split_name,
        "split_config_sha256": config_sha256,
        "metadata": metadata_record,
        "tracks": selected,
        "candidate_plan": config["candidate_routes"],
    }
    if config["schema"] == CONFIG_SCHEMA:
        selection["excluded_task006_blind_singers"] = sorted(TASK006_BLIND_SINGERS)
    else:
        selection["excluded_prior_experiment_singers"] = sorted(
            RECOVERY_EXCLUDED_SINGERS
        )
        selection["selection_policy"] = config["selection_policy"]
    return selection


def prepare_concatenation(
    extracted_root: Path,
    artifact_root: Path,
    split_name: str,
    split: dict[str, Any],
    *,
    config: dict[str, Any],
    config_sha256: str,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    """Create or verify one immutable selected-track concatenation."""

    records, metadata_record = collect_source_records(extracted_root, split["tracks"])
    split_root = artifact_root / split_name
    output_name = (
        f"vocadito-task007-{split_name}-six.wav"
        if config["schema"] == CONFIG_SCHEMA
        else f"{split['benchmark_id']}.wav"
    )
    output_audio = split_root / output_name
    mapping_path = split_root / "concatenation_manifest.json"
    selection_path = split_root / "selection_manifest.json"
    frozen_paths = (output_audio, mapping_path, selection_path)
    existing = [path.exists() or path.is_symlink() for path in frozen_paths]
    if any(existing) and not all(existing):
        raise VocaditoPreparationError(
            f"partial frozen artifacts exist for {split_name}; preserve and investigate them"
        )
    if all(existing):
        if any(path.is_symlink() for path in (output_audio, mapping_path, selection_path)):
            raise VocaditoPreparationError(f"{split_name} frozen artifacts cannot be symlinks")
        mapping = _load_json_object(mapping_path, label=f"{split_name} concatenation")
        selection = _load_json_object(selection_path, label=f"{split_name} selection")
        expected_pairs = [(record["track_id"], record["singer_id"]) for record in records]
        expected_mapping_identity = [
            {
                "track_id": record["track_id"],
                "singer_id": record["singer_id"],
                "language": record["language"],
                "average_midi_pitch": record["average_midi_pitch"],
                "audio_sha256": record["audio_sha256"],
                "audio_frame_count": record["audio_frame_count"],
                "note_references": {
                    annotator: {
                        "sha256": record["note_references"][annotator]["sha256"],
                        "note_count": record["note_references"][annotator]["note_count"],
                    }
                    for annotator in ("a1", "a2")
                },
            }
            for record in records
        ]
        observed_mapping_identity = [
            {
                "track_id": record.get("track_id"),
                "singer_id": record.get("singer_id"),
                "language": record.get("language"),
                "average_midi_pitch": record.get("average_midi_pitch"),
                "audio_sha256": record.get("audio_sha256"),
                "audio_frame_count": record.get("audio_frame_count"),
                "note_references": {
                    annotator: {
                        "sha256": record.get("note_references", {})
                        .get(annotator, {})
                        .get("sha256"),
                        "note_count": record.get("note_references", {})
                        .get(annotator, {})
                        .get("note_count"),
                    }
                    for annotator in ("a1", "a2")
                },
            }
            for record in mapping.get("tracks", [])
            if isinstance(record, dict)
        ]
        observed_pairs = [
            (record.get("track_id"), record.get("singer_id"))
            for record in mapping.get("tracks", [])
            if isinstance(record, dict)
        ]
        selected_pairs = [
            (record.get("track_id"), record.get("singer_id"))
            for record in selection.get("tracks", [])
            if isinstance(record, dict)
        ]
        audio_record = mapping.get("concatenated_audio")
        if (
            mapping.get("schema") != CONCATENATION_SCHEMA
            or mapping.get("split") != split_name
            or mapping.get("split_config_sha256") != config_sha256
            or not isinstance(audio_record, dict)
            or audio_record.get("sha256") != sha256_file(output_audio)
            or observed_pairs != expected_pairs
            or observed_mapping_identity != expected_mapping_identity
            or selection.get("schema") != SELECTION_SCHEMA
            or selection.get("split") != split_name
            or selection.get("split_config_sha256") != config_sha256
            or selection.get("candidate_output_inspected") is not False
            or selected_pairs != expected_pairs
        ):
            raise VocaditoPreparationError(
                f"existing {split_name} frozen artifacts do not match the fixed split"
            )
        return output_audio, mapping_path, mapping, selection

    split_root.mkdir(parents=True, exist_ok=True)
    mapping = _write_concatenation(
        output_audio,
        records,
        split_name=split_name,
        config_sha256=config_sha256,
    )
    selection = _selection_manifest(
        split_name,
        records,
        config=config,
        config_sha256=config_sha256,
        metadata_record=metadata_record,
    )
    atomic_write_json(mapping_path, mapping)
    atomic_write_json(selection_path, selection)
    return output_audio, mapping_path, mapping, selection


def ensure_project(audio_path: Path, project_dir: Path, *, split_name: str) -> dict[str, Any]:
    """Initialize or verify one private benchmark project."""

    expected_source_sha256 = sha256_file(audio_path)
    manifest_path = project_dir / "manifest.json"
    if project_dir.exists() or project_dir.is_symlink():
        if project_dir.is_symlink() or not manifest_path.is_file():
            raise VocaditoPreparationError(
                f"existing project is incomplete or unsafe: {project_dir}"
            )
        manifest = _load_json_object(manifest_path, label=f"{split_name} project")
    else:
        manifest = initialize_project(
            audio_path,
            project_dir,
            title=f"Vocadito v3 {project_dir.name} {split_name} fixed benchmark",
            copy_original=False,
        )
    source = manifest.get("source")
    canonical = manifest.get("canonical_audio")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("project_id") != project_dir.name
        or not isinstance(source, dict)
        or source.get("sha256") != expected_source_sha256
        or not isinstance(canonical, dict)
        or not isinstance(canonical.get("sha256"), str)
    ):
        raise VocaditoPreparationError(
            f"{split_name} project is not bound to the frozen concatenation"
        )
    canonical_path = project_dir / str(canonical.get("path"))
    if not canonical_path.is_file() or sha256_file(canonical_path) != canonical["sha256"]:
        raise VocaditoPreparationError(f"{split_name} canonical audio is missing or changed")
    return manifest


def _copy_reference(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
) -> dict[str, Any]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if sha256_file(destination) != expected_sha256:
        raise VocaditoPreparationError(f"copied reference hash mismatch: {destination}")
    return {
        "path": str(destination),
        "sha256": expected_sha256,
    }


def freeze_benchmark_pack(
    project_dir: Path,
    split_name: str,
    split: dict[str, Any],
    manifest: dict[str, Any],
    mapping_path: Path,
    mapping: dict[str, Any],
    selection_path: Path,
    selection: dict[str, Any],
    config_path: Path,
    *,
    config_sha256: str,
) -> tuple[Path, dict[str, Any]]:
    """Freeze a self-contained dual-annotator benchmark pack."""

    pack_dir = project_dir / "annotations" / split["pack_id"]
    benchmark_path = pack_dir / "benchmark_manifest.json"
    if pack_dir.exists() or pack_dir.is_symlink():
        if pack_dir.is_symlink() or not benchmark_path.is_file():
            raise VocaditoPreparationError(f"existing benchmark pack is unsafe: {pack_dir}")
        benchmark = _load_json_object(benchmark_path, label=f"{split_name} benchmark")
        payload = benchmark.get("freeze_payload")
        if (
            benchmark.get("schema") != PACK_SCHEMA
            or not isinstance(payload, dict)
            or canonical_json_sha256(payload) != benchmark.get("benchmark_freeze_sha256")
            or payload.get("split") != split_name
            or payload.get("split_config", {}).get("sha256") != config_sha256
        ):
            raise VocaditoPreparationError(
                f"existing {split_name} benchmark pack does not match the fixed split"
            )
        return pack_dir, benchmark

    pack_dir.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{pack_dir.name}.", dir=pack_dir.parent))
    try:
        stage_selection = stage / "selection_manifest.json"
        stage_mapping = stage / "concatenation_manifest.json"
        stage_config = stage / "split_config.json"
        shutil.copy2(selection_path, stage_selection)
        shutil.copy2(mapping_path, stage_mapping)
        shutil.copy2(config_path, stage_config)
        excerpts: list[dict[str, Any]] = []
        for track in mapping["tracks"]:
            references: dict[str, dict[str, Any]] = {}
            for annotator in ("a1", "a2"):
                source_record = track["note_references"][annotator]
                relative = (
                    Path("references")
                    / f"track-{int(track['track_id']):02d}-{track['singer_id']}"
                    / f"notes-{annotator}.csv"
                )
                destination = stage / relative
                copied = _copy_reference(
                    Path(source_record["path"]),
                    destination,
                    expected_sha256=source_record["sha256"],
                )
                copied["path"] = str(pack_dir / relative)
                copied["note_count"] = source_record["note_count"]
                references[annotator] = copied
            excerpts.append(
                {
                    "excerpt_id": track["excerpt_id"],
                    "track_id": track["track_id"],
                    "singer_group_id": track["singer_id"],
                    "language": track["language"],
                    "average_midi_pitch": track["average_midi_pitch"],
                    "evaluation_start_sec": track["start_sec"],
                    "evaluation_end_sec": track["end_sec"],
                    "duration_sec": track["duration_sec"],
                    "source_audio_sha256": track["audio_sha256"],
                    "note_references": references,
                }
            )
        canonical = manifest["canonical_audio"]
        freeze_payload = {
            "schema": BENCHMARK_SCHEMA,
            "benchmark_id": split["benchmark_id"],
            "project_id": manifest["project_id"],
            "split": split_name,
            "prior_system_exposure": False,
            "canonical_audio_sha256": canonical["sha256"],
            "canonical_audio_duration_sec": canonical["metadata"]["duration_sec"],
            "split_config": {
                "path": str(pack_dir / "split_config.json"),
                "sha256": config_sha256,
            },
            "concatenation_manifest": {
                "path": str(pack_dir / "concatenation_manifest.json"),
                "sha256": sha256_file(stage_mapping),
            },
            "selection_manifest": {
                "path": str(pack_dir / "selection_manifest.json"),
                "sha256": sha256_file(stage_selection),
            },
            "reference_policy": {
                "annotators": ["a1", "a2"],
                "report_each_annotator": True,
                "aggregate_policy": "per_track_max_onset_pitch_offset_f1",
                "aggregate_policy_fixed_before_candidate_inference": True,
            },
            "excerpts": excerpts,
        }
        benchmark = {
            "schema": PACK_SCHEMA,
            "created_at": datetime.now(UTC).isoformat(),
            "status": "external_human_note_reference_frozen",
            "freeze_payload": freeze_payload,
            "benchmark_freeze_sha256": canonical_json_sha256(freeze_payload),
            "claims": {
                "human_note_reference_available": True,
                "two_independent_annotators": True,
                "blind_test": split_name == "blind_test",
                "candidate_output_quality_inspected": False,
                "candidate_metrics_available": False,
                "manual_correction_time_available": False,
            },
        }
        atomic_write_json(stage / "benchmark_manifest.json", benchmark)
        (stage / "README.md").write_text(
            "# Task 007 external dual-annotator note benchmark\n\n"
            f"Split: `{split_name}`. The {len(excerpts)} singer-disjoint "
            "Vocadito v3 tracks "
            "and both trained-musician note annotations were frozen before "
            "Task 007 candidate inference. Candidate output quality was not "
            "inspected while preparing this pack.\n",
            encoding="utf-8",
        )
        for path in stage.rglob("*"):
            if path.is_file():
                path.chmod(0o600)
        os.replace(stage, pack_dir)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return pack_dir, benchmark


def prepare_all(
    extracted_root: Path,
    artifact_root: Path,
    projects_root: Path,
    config_path: Path,
) -> dict[str, Any]:
    """Prepare both fixed splits and return frozen artifact identities."""

    config_path = config_path.resolve(strict=True)
    config = load_split_config(config_path)
    config_sha256 = sha256_file(config_path)
    extracted_root = extracted_root.resolve(strict=True)
    artifact_root = artifact_root.resolve()
    projects_root = projects_root.resolve()
    results: dict[str, Any] = {}
    for split_name in ("development", "blind_test"):
        split = config["splits"][split_name]
        audio_path, mapping_path, mapping, selection = prepare_concatenation(
            extracted_root,
            artifact_root,
            split_name,
            split,
            config=config,
            config_sha256=config_sha256,
        )
        selection_path = artifact_root / split_name / "selection_manifest.json"
        project_dir = projects_root / split["project_id"]
        manifest = ensure_project(audio_path, project_dir, split_name=split_name)
        pack_dir, benchmark = freeze_benchmark_pack(
            project_dir,
            split_name,
            split,
            manifest,
            mapping_path,
            mapping,
            selection_path,
            selection,
            config_path,
            config_sha256=config_sha256,
        )
        results[split_name] = {
            "project_dir": str(project_dir),
            "project_manifest_sha256": sha256_file(project_dir / "manifest.json"),
            "pack_dir": str(pack_dir),
            "benchmark_freeze_sha256": benchmark["benchmark_freeze_sha256"],
            "concatenated_audio_sha256": mapping["concatenated_audio"]["sha256"],
            "candidate_output_quality_inspected": False,
        }
    return {
        "schema": "amt-task007-vocadito-preparation-result/v1",
        "prepared_at": datetime.now(UTC).isoformat(),
        "split_config": {
            "path": str(config_path),
            "sha256": config_sha256,
        },
        "splits": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--extracted-root", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--projects-root", type=Path, required=True)
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "configs" / "task007" / "vocadito_v3_split.json",
    )
    args = parser.parse_args()
    try:
        require_slurm_compute_node()
        result = prepare_all(
            args.extracted_root,
            args.artifact_root,
            args.projects_root,
            args.config,
        )
    except (OSError, ValueError, VocaditoPreparationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
