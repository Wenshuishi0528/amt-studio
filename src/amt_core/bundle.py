from __future__ import annotations

import json
import re
import shutil
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from .canonical import (
    CanonicalTrack,
    CanonicalValidationError,
    MeterPoint,
    ProvenanceRef,
    RhythmMap,
    TempoPoint,
    build_score_grid,
)
from .contracts import ContractValidationError, WorkerResultV1, load_worker_result
from .events import NoteEvent, write_jsonl
from .midi import export_performance_midi
from .product_postprocess import clean_trailing_fragments
from .project import load_project
from .utils import atomic_write_json, sha256_file

LABEL_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z", re.ASCII)


class BundleBuildError(RuntimeError):
    """Raised when a canonical project bundle cannot be built safely."""


def _project_relative(path: Path, project_dir: Path) -> str:
    try:
        return str(path.resolve(strict=True).relative_to(project_dir))
    except (OSError, ValueError) as exc:
        raise BundleBuildError(f"artifact is outside the project directory: {path}") from exc


def _canonical_project_identity(project_dir: Path) -> tuple[str, Path, str]:
    project = load_project(project_dir)
    project_id = project.get("project_id")
    canonical = project.get("canonical_audio")
    if not isinstance(project_id, str) or not project_id:
        raise BundleBuildError("project manifest has no project_id")
    if not isinstance(canonical, dict):
        raise BundleBuildError("project manifest has no canonical audio")
    relative = canonical.get("path")
    expected_sha = canonical.get("sha256")
    if not isinstance(relative, str) or not isinstance(expected_sha, str):
        raise BundleBuildError("project canonical audio record is malformed")
    try:
        canonical_path = (project_dir / relative).resolve(strict=True)
        canonical_path.relative_to(project_dir)
    except (OSError, ValueError) as exc:
        raise BundleBuildError("project canonical audio escapes the project directory") from exc
    if not canonical_path.is_file() or sha256_file(canonical_path) != expected_sha:
        raise BundleBuildError("project canonical audio does not match its manifest")
    return project_id, canonical_path, expected_sha


def _manifest_canonical_hash(result: WorkerResultV1) -> str | None:
    lineage = result.manifest.get("input_lineage")
    if isinstance(lineage, dict):
        value = lineage.get("canonical_mix_sha256")
        if isinstance(value, str):
            return value
    inputs = result.manifest.get("inputs")
    if isinstance(inputs, list) and len(inputs) == 1 and isinstance(inputs[0], dict):
        value = inputs[0].get("sha256")
        return value if isinstance(value, str) else None
    return None


def _load_note_candidate(
    label: str,
    run_dir: Path,
    *,
    project_dir: Path,
    project_id: str,
    canonical_sha256: str,
) -> tuple[WorkerResultV1, list[NoteEvent], CanonicalTrack]:
    if LABEL_PATTERN.fullmatch(label) is None:
        raise BundleBuildError(f"candidate label is unsafe: {label!r}")
    result = load_worker_result(run_dir)
    if result.project_id != project_id:
        raise BundleBuildError(f"candidate {label!r} belongs to another project")
    if _manifest_canonical_hash(result) != canonical_sha256:
        raise BundleBuildError(f"candidate {label!r} is not bound to the canonical mix")
    events = result.read_note_events()
    if not events:
        raise BundleBuildError(f"candidate {label!r} has no note events")
    if any(event.source_run_id != result.run_id for event in events):
        raise BundleBuildError(f"candidate {label!r} event provenance does not match its run")
    source_models = {event.source_model for event in events}
    if len(source_models) != 1:
        raise BundleBuildError(f"candidate {label!r} has ambiguous source models")
    instruments = {event.instrument for event in events}
    instrument = next(iter(instruments)) if len(instruments) == 1 else None
    normalized = result.outputs["normalized/events.jsonl"]
    track = CanonicalTrack(
        track_id=label,
        label=label,
        role="candidate",
        instrument=instrument,
        event_count=len(events),
        source_events_path=_project_relative(
            result.output_path("normalized/events.jsonl"),
            project_dir,
        ),
        provenance=ProvenanceRef(
            source_run_id=result.run_id,
            source_model=next(iter(source_models)),
            run_manifest_sha256=sha256_file(result.manifest_path),
            normalized_artifact_sha256=normalized.sha256,
        ),
    )
    track.to_dict()
    return result, events, track


def _write_score_grid(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def build_canonical_bundle(
    project_dir: Path,
    beat_run_dir: Path,
    candidates: dict[str, Path],
    output_dir: Path,
    *,
    score_subdivision: int = 4,
) -> dict[str, Any]:
    project_dir = project_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if len(candidates) < 1:
        raise BundleBuildError("at least one note candidate is required")
    if len(set(path.expanduser().resolve() for path in candidates.values())) != len(candidates):
        raise BundleBuildError("candidate run paths must be distinct")
    if output_dir.exists() or output_dir.is_symlink():
        raise BundleBuildError(f"output path already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)

    project_id, canonical_path, canonical_sha256 = _canonical_project_identity(project_dir)
    beat_result = load_worker_result(beat_run_dir)
    if beat_result.worker != "beat_this" or beat_result.project_id != project_id:
        raise BundleBuildError("rhythm result worker or project identity is invalid")
    if _manifest_canonical_hash(beat_result) != canonical_sha256:
        raise BundleBuildError("rhythm result is not bound to the canonical mix")
    rhythm = RhythmMap.from_dict(beat_result.read_rhythm_map())
    if rhythm.canonical_audio_sha256 != canonical_sha256:
        raise BundleBuildError("normalized rhythm map is not bound to the canonical mix")

    loaded: dict[str, list[NoteEvent]] = {}
    tracks: list[CanonicalTrack] = []
    result_contracts: list[dict[str, Any]] = []
    for label, run_dir in candidates.items():
        result, events, track = _load_note_candidate(
            label,
            run_dir,
            project_dir=project_dir,
            project_id=project_id,
            canonical_sha256=canonical_sha256,
        )
        loaded[label] = events
        tracks.append(track)
        result_contracts.append(
            {
                "contract_version": result.manifest.get(
                    "contract_version",
                    "amt-worker-result/v1",
                ),
                "worker": result.worker,
                "run_id": result.run_id,
                "manifest_path": _project_relative(result.manifest_path, project_dir),
                "manifest_sha256": sha256_file(result.manifest_path),
            }
        )
    result_contracts.append(
        {
            "contract_version": beat_result.manifest.get(
                "contract_version",
                "amt-worker-result/v1",
            ),
            "worker": beat_result.worker,
            "run_id": beat_result.run_id,
            "manifest_path": _project_relative(beat_result.manifest_path, project_dir),
            "manifest_sha256": sha256_file(beat_result.manifest_path),
        }
    )

    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.",
        dir=output_dir.parent,
    ) as temporary_name:
        temporary_dir = Path(temporary_name)
        performance_midi = temporary_dir / "performance.mid"
        midi_report = export_performance_midi(
            performance_midi,
            loaded,
            rhythm.tempo_map,
            rhythm.meter_map,
        )
        score_notes = build_score_grid(
            loaded,
            rhythm,
            subdivision=score_subdivision,
        )
        score_path = temporary_dir / "score-grid-experiment.jsonl"
        _write_score_grid(score_path, [note.to_dict() for note in score_notes])

        canonical_project = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-project",
            "project_id": project_id,
            "timeline_basis": "original_canonical_mix_seconds",
            "canonical_audio": {
                "path": _project_relative(canonical_path, project_dir),
                "sha256": canonical_sha256,
            },
            "worker_results": sorted(
                result_contracts,
                key=lambda item: (item["worker"], item["run_id"]),
            ),
            "tracks": [track.to_dict() for track in tracks],
            "rhythm": {
                "source_run_id": rhythm.source_run_id,
                "source_model": rhythm.source_model,
                "normalized_path": _project_relative(
                    beat_result.output_path("normalized/rhythm.json"),
                    project_dir,
                ),
                "normalized_sha256": beat_result.outputs["normalized/rhythm.json"].sha256,
                "events": [event.to_dict() for event in rhythm.events],
                "tempo_map": [point.to_dict() for point in rhythm.tempo_map],
                "meter_map": [point.to_dict() for point in rhythm.meter_map],
                "uncertainty": rhythm.uncertainty,
            },
            "exports": {
                "performance_midi": {
                    "path": "performance.mid",
                    "representation": "performance",
                    "report": midi_report,
                },
                "score_grid_experiment": {
                    "path": "score-grid-experiment.jsonl",
                    "representation": "score",
                    "event_count": len(score_notes),
                    "subdivision_per_beat": score_subdivision,
                    "status": "experimental_not_notation",
                },
            },
            "claims": {
                "candidate_fusion_performed": False,
                "preferred_candidate_selected": False,
                "accuracy_claimed": False,
                "score_notation_claimed": False,
            },
        }
        atomic_write_json(temporary_dir / "canonical_project.json", canonical_project)

        output_records = []
        for path in sorted(temporary_dir.iterdir()):
            if path.name == "bundle_manifest.json" or not path.is_file():
                continue
            output_records.append(
                {
                    "path": path.name,
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
            )
        bundle_manifest = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-bundle",
            "project_id": project_id,
            "canonical_audio_sha256": canonical_sha256,
            "status": "succeeded",
            "outputs": output_records,
            "limitations": [
                "Candidate tracks are not fused or ranked.",
                "Score-grid events are an experiment, not a notation result.",
                "MIDI rounds floating canonical pitch to the nearest semitone.",
                "No transcription accuracy is claimed without human references.",
            ],
        }
        atomic_write_json(temporary_dir / "bundle_manifest.json", bundle_manifest)
        temporary_dir.replace(output_dir)
    return bundle_manifest


def _safe_track_id(instrument: str, used: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_-]+", "-", instrument.strip().lower()).strip("-")
    if not base:
        base = "unknown"
    candidate = base[:64]
    suffix = 2
    while candidate in used:
        tail = f"-{suffix}"
        candidate = f"{base[: 64 - len(tail)]}{tail}"
        suffix += 1
    used.add(candidate)
    return candidate


def _bundle_output_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "bundle_manifest.json":
            continue
        records.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def build_muscriptor_multitrack_bundle(
    project_dir: Path,
    run_dir: Path,
    output_dir: Path,
    *,
    default_bpm: float = 120.0,
    beat_run_dir: Path | None = None,
    expected_worker: str = "muscriptor",
) -> dict[str, Any]:
    """Build an editable product bundle from one immutable note-worker run."""

    project_dir = project_dir.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    try:
        output_relative = output_dir.relative_to(project_dir)
    except ValueError as exc:
        raise BundleBuildError("output path must be inside the project directory") from exc
    if output_dir.exists() or output_dir.is_symlink():
        raise BundleBuildError(f"output path already exists: {output_dir}")
    if not 1 <= default_bpm <= 1000:
        raise BundleBuildError("default BPM must be in [1, 1000]")

    project_id, canonical_path, canonical_sha256 = _canonical_project_identity(project_dir)
    project_manifest = load_project(project_dir)
    canonical_metadata = project_manifest.get("canonical_audio", {}).get("metadata", {})
    timeline_end = (
        float(canonical_metadata["duration_sec"])
        if isinstance(canonical_metadata, dict)
        and isinstance(canonical_metadata.get("duration_sec"), (int, float))
        and not isinstance(canonical_metadata.get("duration_sec"), bool)
        and float(canonical_metadata["duration_sec"]) > 0
        else None
    )
    result = load_worker_result(run_dir)
    if result.worker != expected_worker or result.project_id != project_id:
        raise BundleBuildError(
            f"result is not a {expected_worker} run for this project"
        )
    if _manifest_canonical_hash(result) != canonical_sha256:
        raise BundleBuildError(
            f"{expected_worker} result is not bound to the canonical mix"
        )

    events = result.read_note_events()
    if not events:
        if result.worker != "game":
            raise BundleBuildError("MuScriptor result has no note events")
        source_model = str(result.manifest.get("model") or "GAME-1.0-medium")
    else:
        source_model = events[0].source_model
    if any(event.source_run_id != result.run_id for event in events):
        raise BundleBuildError(
            f"{expected_worker} event provenance does not match its run"
        )
    if any(event.source_model != source_model for event in events):
        raise BundleBuildError(
            f"{expected_worker} result has ambiguous source models"
        )

    rhythm: RhythmMap | None = None
    beat_result: WorkerResultV1 | None = None
    if beat_run_dir is not None:
        beat_result = load_worker_result(beat_run_dir)
        if beat_result.worker != "beat_this" or beat_result.project_id != project_id:
            raise BundleBuildError("rhythm result worker or project identity is invalid")
        if _manifest_canonical_hash(beat_result) != canonical_sha256:
            raise BundleBuildError("rhythm result is not bound to the canonical mix")
        rhythm = RhythmMap.from_dict(beat_result.read_rhythm_map())
        if rhythm.canonical_audio_sha256 != canonical_sha256:
            raise BundleBuildError("normalized rhythm map is not bound to the canonical mix")

    grouped: dict[str, list[NoteEvent]] = defaultdict(list)
    for event in events:
        instrument = event.instrument.strip() if isinstance(event.instrument, str) else ""
        grouped[instrument or "unknown"].append(event)
    if result.worker == "game" and not grouped:
        grouped["voice"] = []

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.",
        dir=output_dir.parent,
    ) as temporary_name:
        temporary_dir = Path(temporary_name)
        tracks_dir = temporary_dir / "tracks"
        tracks_dir.mkdir()
        raw_tracks_dir = temporary_dir / "raw_tracks"
        cleanup_records: list[dict[str, Any]] = []
        used_track_ids: set[str] = set()
        loaded: dict[str, list[NoteEvent]] = {}
        tracks: list[CanonicalTrack] = []

        ordered_instruments = sorted(grouped, key=lambda name: (name != "voice", name))
        for instrument in ordered_instruments:
            track_id = _safe_track_id(instrument, used_track_ids)
            track_events = sorted(
                grouped[instrument],
                key=lambda event: (event.onset_sec, event.offset_sec, event.event_id),
            )
            source_track_events = track_events
            cleanup = {
                "decision": "not_applicable",
                "group_count": 0,
                "fragment_count": 0,
                "merged_note_count": 0,
                "source_overwritten": False,
            }
            if timeline_end is not None and instrument.lower() != "voice":
                track_events, cleanup = clean_trailing_fragments(
                    source_track_events,
                    timeline_end=timeline_end,
                    run_id=result.run_id,
                )
            if cleanup["group_count"]:
                raw_tracks_dir.mkdir(exist_ok=True)
                raw_path = raw_tracks_dir / f"{track_id}.jsonl"
                write_jsonl(raw_path, source_track_events)
                cleanup["raw_source_path"] = str(
                    output_relative / "raw_tracks" / raw_path.name
                )
                cleanup["raw_source_sha256"] = sha256_file(raw_path)
            cleanup_records.append(
                {
                    "track_id": track_id,
                    "instrument": instrument,
                    **cleanup,
                }
            )
            track_path = tracks_dir / f"{track_id}.jsonl"
            write_jsonl(track_path, track_events)
            loaded[track_id] = track_events
            tracks.append(
                CanonicalTrack(
                    track_id=track_id,
                    label=instrument.replace("_", " "),
                    role="candidate",
                    instrument=instrument,
                    event_count=len(track_events),
                    source_events_path=str(output_relative / "tracks" / track_path.name),
                    provenance=ProvenanceRef(
                        source_run_id=result.run_id,
                        source_model=(
                            "deterministic:instrument-aware-tail-cleanup"
                            if cleanup["group_count"]
                            else source_model
                        ),
                        run_manifest_sha256=sha256_file(result.manifest_path),
                        normalized_artifact_sha256=sha256_file(track_path),
                    ),
                )
            )

        tempo_points = (
            rhythm.tempo_map
            if rhythm is not None
            else (
                TempoPoint(
                    time_sec=0.0,
                    bpm=float(default_bpm),
                    confidence=None,
                    uncertainty_bpm=None,
                    source_event_ids=("private-beta-default-tempo",),
                    method="private_beta_default",
                ),
            )
        )
        meter_points = (
            rhythm.meter_map
            if rhythm is not None
            else (
                MeterPoint(
                    time_sec=0.0,
                    numerator=4,
                    denominator=4,
                    confidence=None,
                    source_event_ids=("private-beta-default-meter",),
                    status="defaulted",
                ),
            )
        )
        performance_midi = temporary_dir / "performance.mid"
        melodic_track_count = sum(track_id != "drums" for track_id in loaded)
        if melodic_track_count <= 15:
            midi_report: dict[str, Any] = export_performance_midi(
                performance_midi,
                loaded,
                tempo_points,
                meter_points,
            )
        else:
            midi_report = {
                "status": "unavailable",
                "reason": (
                    "The canonical result has more than the 15 melodic channels "
                    "available in one General MIDI port."
                ),
                "track_count": len(loaded),
                "note_count": sum(len(track_events) for track_events in loaded.values()),
            }
        native_midi = (
            result.outputs.get("raw/full.native.mid")
            if result.worker == "muscriptor"
            else None
        )
        if native_midi is not None:
            shutil.copy2(
                result.output_path(native_midi.path),
                temporary_dir / "muscriptor.native.mid",
            )

        canonical_project = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-project",
            "project_id": project_id,
            "timeline_basis": "original_canonical_mix_seconds",
            "canonical_audio": {
                "path": _project_relative(canonical_path, project_dir),
                "sha256": canonical_sha256,
                **(
                    {"metadata": canonical_metadata}
                    if isinstance(canonical_metadata, dict) and canonical_metadata
                    else {}
                ),
            },
            "worker_results": [
                {
                    "contract_version": result.manifest.get(
                        "contract_version",
                        "amt-worker-result/v1",
                    ),
                    "worker": result.worker,
                    "run_id": result.run_id,
                    "manifest_path": _project_relative(result.manifest_path, project_dir),
                    "manifest_sha256": sha256_file(result.manifest_path),
                },
                *(
                    [
                        {
                            "contract_version": beat_result.manifest.get(
                                "contract_version",
                                "amt-worker-result/v1",
                            ),
                            "worker": beat_result.worker,
                            "run_id": beat_result.run_id,
                            "manifest_path": _project_relative(
                                beat_result.manifest_path,
                                project_dir,
                            ),
                            "manifest_sha256": sha256_file(beat_result.manifest_path),
                        }
                    ]
                    if beat_result is not None
                    else []
                ),
            ],
            "tracks": [track.to_dict() for track in tracks],
            "main_melody_track_id": next(
                (track.track_id for track in tracks if track.instrument == "voice"),
                None,
            ),
            "rhythm": {
                "source_run_id": rhythm.source_run_id if rhythm is not None else None,
                "source_model": rhythm.source_model if rhythm is not None else None,
                "normalized_path": (
                    _project_relative(
                        beat_result.output_path("normalized/rhythm.json"),
                        project_dir,
                    )
                    if beat_result is not None
                    else None
                ),
                "normalized_sha256": (
                    beat_result.outputs["normalized/rhythm.json"].sha256
                    if beat_result is not None
                    else None
                ),
                "events": (
                    [event.to_dict() for event in rhythm.events]
                    if rhythm is not None
                    else []
                ),
                "tempo_map": [point.to_dict() for point in tempo_points],
                "meter_map": [point.to_dict() for point in meter_points],
                "uncertainty": (
                    rhythm.uncertainty
                    if rhythm is not None
                    else {
                        "status": "defaulted_for_midi_serialization",
                        "tempo_bpm": float(default_bpm),
                        "meter": "4/4",
                        "warning": "No beat or tempo model was run.",
                    }
                ),
            },
            "exports": {
                "performance_midi": {
                    "path": (
                        "performance.mid"
                        if midi_report.get("status") != "unavailable"
                        else None
                    ),
                    "representation": "performance",
                    "report": midi_report,
                },
                "muscriptor_native_midi": (
                    {
                        "path": "muscriptor.native.mid",
                        "representation": "native_model_output",
                    }
                    if native_midi is not None
                    else None
                ),
            },
            "claims": {
                "all_muscriptor_instruments_preserved": (
                    result.worker == "muscriptor"
                ),
                "game_singing_voice_only": result.worker == "game",
                "voice_used_as_default_main_melody": "voice" in grouped,
                "instrument_labels_verified": False,
                "accuracy_claimed": False,
                "tempo_inferred": rhythm is not None,
                "score_notation_claimed": False,
                "automatic_trailing_sustain_cleanup_performed": any(
                    record["group_count"] for record in cleanup_records
                ),
                "automatic_trailing_sustain_cleanup_source_overwritten": False,
            },
        }
        reports_dir = temporary_dir / "reports"
        reports_dir.mkdir()
        atomic_write_json(
            reports_dir / "trailing_sustain_cleanup.json",
            {
                "schema_version": 1,
                "artifact_type": "amt-trailing-sustain-cleanup-report",
                "timeline_end_sec": timeline_end,
                "tracks": cleanup_records,
                "accuracy_claimed": False,
                "source_overwritten": False,
            },
        )
        atomic_write_json(temporary_dir / "canonical_project.json", canonical_project)
        bundle_manifest = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-bundle",
            "project_id": project_id,
            "canonical_audio_sha256": canonical_sha256,
            "status": "succeeded",
            "outputs": _bundle_output_records(temporary_dir),
            "claims": {
                "game_singing_voice_only": result.worker == "game",
            },
            "limitations": [
                *(
                    [
                        (
                            "GAME receives a separated vocal stem and recognizes "
                            "singing voice; it is not a universal instrumental-melody model."
                        ),
                        (
                            "The GAME model does not provide calibrated per-note "
                            "confidence or velocity."
                        ),
                    ]
                    if result.worker == "game"
                    else [
                        (
                            "Instrument names are MuScriptor predictions and may "
                            "be incomplete or wrong."
                        ),
                        (
                            "The voice track is the default main-melody view, "
                            "not a formal accuracy claim."
                        ),
                    ]
                ),
                *(
                    [
                        "Beat and meter are model estimates and may require correction."
                    ]
                    if rhythm is not None
                    else [
                        (
                            f"A fixed {default_bpm:g} BPM and 4/4 meter are used only "
                            "to serialize performance MIDI."
                        )
                    ]
                ),
                "Original normalized events and native MIDI remain preserved in the worker run.",
                (
                    "Pitched accompaniment tail-fragment cleanup is a conservative "
                    "derived product view; raw source events remain preserved."
                ),
            ],
        }
        atomic_write_json(temporary_dir / "bundle_manifest.json", bundle_manifest)
        temporary_dir.replace(output_dir)
    return bundle_manifest


def build_game_vocal_bundle(
    project_dir: Path,
    run_dir: Path,
    output_dir: Path,
    *,
    default_bpm: float = 120.0,
    beat_run_dir: Path | None = None,
) -> dict[str, Any]:
    """Build a one-track product bundle from a verified GAME singing-voice run."""

    return build_muscriptor_multitrack_bundle(
        project_dir,
        run_dir,
        output_dir,
        default_bpm=default_bpm,
        beat_run_dir=beat_run_dir,
        expected_worker="game",
    )


def parse_candidate(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise BundleBuildError("--candidate must use LABEL=RUN_DIR")
    label, raw_path = value.split("=", 1)
    if LABEL_PATTERN.fullmatch(label) is None or not raw_path:
        raise BundleBuildError("--candidate label or path is invalid")
    return label, Path(raw_path)


__all__ = [
    "BundleBuildError",
    "CanonicalValidationError",
    "ContractValidationError",
    "build_canonical_bundle",
    "build_game_vocal_bundle",
    "build_muscriptor_multitrack_bundle",
    "parse_candidate",
]
