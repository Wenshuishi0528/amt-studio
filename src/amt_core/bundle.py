from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

from .canonical import (
    CanonicalTrack,
    CanonicalValidationError,
    ProvenanceRef,
    RhythmMap,
    build_score_grid,
)
from .contracts import ContractValidationError, WorkerResultV1, load_worker_result
from .events import NoteEvent
from .midi import export_performance_midi
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
    "parse_candidate",
]
