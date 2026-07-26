from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amt_core.canonical import MeterPoint, TempoPoint
from amt_core.events import NoteEvent, read_jsonl, write_jsonl
from amt_core.midi import export_performance_midi
from amt_core.project import load_project
from amt_core.utils import atomic_write_json, sha256_file
try:
    from workers.muscriptor import run_baseline
except ModuleNotFoundError:
    import run_baseline


IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", re.ASCII)


class GapProbeError(RuntimeError):
    """Raised when a directed MuScriptor gap probe is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class TargetInterval:
    target_id: str
    start_sec: float
    end_sec: float
    expectation: str

    @property
    def duration_sec(self) -> float:
        return self.end_sec - self.start_sec


@dataclass(frozen=True, slots=True)
class ProbeWindow:
    window_id: str
    clip_start_sec: float
    clip_end_sec: float
    targets: tuple[TargetInterval, ...]


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    probe_id: str
    source_bundle_id: str
    source_voice_track_id: str
    canonical_duration_sec: float
    context_sec: float
    windows: tuple[ProbeWindow, ...]


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GapProbeError(f"cannot read JSON object {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GapProbeError(f"expected JSON object: {path}")
    return value


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GapProbeError(f"{label} must be a number")
    result = float(value)
    if not math.isfinite(result):
        raise GapProbeError(f"{label} must be finite")
    return result


def _safe_identifier(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or IDENTIFIER.fullmatch(value) is None or ".." in value:
        raise GapProbeError(f"{label} is not a safe identifier")
    return value


def load_spec(path: Path) -> ProbeSpec:
    value = _load_object(path)
    if value.get("schema_version") != 1:
        raise GapProbeError("unsupported gap probe schema_version")
    probe_id = _safe_identifier(value.get("probe_id"), label="probe_id")
    source_bundle_id = _safe_identifier(
        value.get("source_bundle_id"),
        label="source_bundle_id",
    )
    source_voice_track_id = _safe_identifier(
        value.get("source_voice_track_id"),
        label="source_voice_track_id",
    )
    duration = _finite_number(
        value.get("canonical_duration_sec"),
        label="canonical_duration_sec",
    )
    context = _finite_number(value.get("context_sec"), label="context_sec")
    if duration <= 0 or context < 0:
        raise GapProbeError("duration must be positive and context must be non-negative")
    raw_windows = value.get("windows")
    if not isinstance(raw_windows, list) or not raw_windows:
        raise GapProbeError("windows must be a non-empty list")

    windows: list[ProbeWindow] = []
    target_ids: set[str] = set()
    window_ids: set[str] = set()
    all_targets: list[TargetInterval] = []
    for index, raw_window in enumerate(raw_windows):
        if not isinstance(raw_window, dict):
            raise GapProbeError(f"windows[{index}] must be an object")
        window_id = _safe_identifier(
            raw_window.get("window_id"),
            label=f"windows[{index}].window_id",
        )
        if window_id in window_ids:
            raise GapProbeError(f"duplicate window_id: {window_id}")
        window_ids.add(window_id)
        clip_start = _finite_number(
            raw_window.get("clip_start_sec"),
            label=f"{window_id}.clip_start_sec",
        )
        clip_end = _finite_number(
            raw_window.get("clip_end_sec"),
            label=f"{window_id}.clip_end_sec",
        )
        if clip_start < 0 or clip_end <= clip_start or clip_end > duration + 0.02:
            raise GapProbeError(f"invalid clip interval for {window_id}")
        raw_targets = raw_window.get("targets")
        if not isinstance(raw_targets, list) or not raw_targets:
            raise GapProbeError(f"{window_id} must contain at least one target")
        targets: list[TargetInterval] = []
        for target_index, raw_target in enumerate(raw_targets):
            if not isinstance(raw_target, dict):
                raise GapProbeError(f"{window_id}.targets[{target_index}] must be an object")
            target_id = _safe_identifier(
                raw_target.get("target_id"),
                label=f"{window_id}.targets[{target_index}].target_id",
            )
            if target_id in target_ids:
                raise GapProbeError(f"duplicate target_id: {target_id}")
            target_ids.add(target_id)
            start = _finite_number(
                raw_target.get("start_sec"),
                label=f"{target_id}.start_sec",
            )
            end = _finite_number(
                raw_target.get("end_sec"),
                label=f"{target_id}.end_sec",
            )
            expectation = raw_target.get("expectation")
            if not isinstance(expectation, str) or not expectation.strip():
                raise GapProbeError(f"{target_id}.expectation must be non-empty")
            if start < clip_start or end > clip_end or end <= start:
                raise GapProbeError(f"target {target_id} is outside its clip")
            target = TargetInterval(target_id, start, end, expectation.strip())
            targets.append(target)
            all_targets.append(target)
        windows.append(ProbeWindow(window_id, clip_start, clip_end, tuple(targets)))

    ordered_targets = sorted(all_targets, key=lambda item: (item.start_sec, item.end_sec))
    for previous, current in zip(ordered_targets, ordered_targets[1:], strict=False):
        if current.start_sec < previous.end_sec:
            raise GapProbeError(
                f"target intervals overlap: {previous.target_id} and {current.target_id}"
            )
    return ProbeSpec(
        probe_id=probe_id,
        source_bundle_id=source_bundle_id,
        source_voice_track_id=source_voice_track_id,
        canonical_duration_sec=duration,
        context_sec=context,
        windows=tuple(windows),
    )


def _resolve_inside(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise GapProbeError("artifact path must be non-empty")
    try:
        resolved = (root / relative).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise GapProbeError(f"artifact escapes the project: {relative}") from exc
    if not resolved.is_file():
        raise GapProbeError(f"artifact is not a file: {relative}")
    return resolved


def _source_context(
    project_dir: Path,
    spec: ProbeSpec,
) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    project = load_project(project_dir)
    canonical_record = project.get("canonical_audio")
    if not isinstance(canonical_record, dict):
        raise GapProbeError("project has no canonical audio record")
    canonical_audio = _resolve_inside(project_dir, canonical_record.get("path"))
    if sha256_file(canonical_audio) != canonical_record.get("sha256"):
        raise GapProbeError("canonical audio hash does not match project manifest")
    bundle_dir = project_dir / "exports" / spec.source_bundle_id
    canonical_project_path = _resolve_inside(bundle_dir, "canonical_project.json")
    canonical_project = _load_object(canonical_project_path)
    if (
        canonical_project.get("project_id") != project.get("project_id")
        or canonical_project.get("canonical_audio", {}).get("sha256")
        != canonical_record.get("sha256")
    ):
        raise GapProbeError("source bundle does not match the project or canonical audio")
    tracks = canonical_project.get("tracks")
    if not isinstance(tracks, list):
        raise GapProbeError("source bundle has no tracks")
    matches = [
        track
        for track in tracks
        if isinstance(track, dict) and track.get("track_id") == spec.source_voice_track_id
    ]
    if len(matches) != 1:
        raise GapProbeError("source voice track is missing or ambiguous")
    source_track = matches[0]
    source_voice = _resolve_inside(project_dir, source_track.get("source_events_path"))
    expected_hash = source_track.get("provenance", {}).get("normalized_artifact_sha256")
    if sha256_file(source_voice) != expected_hash:
        raise GapProbeError("source voice events hash does not match source bundle")
    return project, canonical_audio, source_voice, canonical_project


def _overlaps(event: NoteEvent, target: TargetInterval) -> bool:
    return event.offset_sec > target.start_sec and event.onset_sec < target.end_sec


def validate_empty_source_gaps(
    source_events: list[NoteEvent],
    spec: ProbeSpec,
) -> None:
    for window in spec.windows:
        for target in window.targets:
            count = sum(_overlaps(event, target) for event in source_events)
            if count:
                raise GapProbeError(
                    f"source voice is not empty in {target.target_id}: {count} overlapping notes"
                )


def shift_voice_candidates(
    events: list[NoteEvent],
    *,
    probe_id: str,
    window: ProbeWindow,
) -> list[NoteEvent]:
    shifted: list[NoteEvent] = []
    for event in events:
        if (event.instrument or "").lower() != "voice":
            continue
        original_onset = event.onset_sec + window.clip_start_sec
        original_offset = event.offset_sec + window.clip_start_sec
        matching = [
            target
            for target in window.targets
            if original_offset > target.start_sec and original_onset < target.end_sec
        ]
        if not matching:
            continue
        if len(matching) != 1:
            raise GapProbeError(f"candidate overlaps multiple targets: {event.event_id}")
        target = matching[0]
        extra = dict(event.extra)
        extra["gap_probe"] = {
            "probe_id": probe_id,
            "window_id": window.window_id,
            "target_id": target.target_id,
            "clip_start_sec": window.clip_start_sec,
            "clip_onset_sec": event.onset_sec,
            "clip_offset_sec": event.offset_sec,
            "source_event_id": event.event_id,
            "automatic_merge_performed": False,
        }
        shifted.append(
            NoteEvent(
                event_id=f"{probe_id}:{window.window_id}:{event.event_id}",
                track_id="muscriptor-gap:voice",
                instrument="voice",
                onset_sec=original_onset,
                offset_sec=original_offset,
                pitch_midi=event.pitch_midi,
                quantized_pitch_midi=event.quantized_pitch_midi,
                velocity=event.velocity,
                confidence=event.confidence,
                is_main_melody_candidate=True,
                source_run_id=event.source_run_id,
                source_model=event.source_model,
                source_event_ids=[*event.source_event_ids, event.event_id],
                tags=sorted(
                    {
                        *event.tags,
                        "candidate",
                        "directed-gap-probe",
                        target.target_id,
                    }
                ),
                extra=extra,
            )
        )
    return shifted


def _union_duration(events: list[NoteEvent], target: TargetInterval) -> float:
    intervals = sorted(
        (
            max(target.start_sec, event.onset_sec),
            min(target.end_sec, event.offset_sec),
        )
        for event in events
        if _overlaps(event, target)
    )
    merged: list[tuple[float, float]] = []
    for start, end in intervals:
        if end <= start:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return sum(end - start for start, end in merged)


def build_coverage_report(
    spec: ProbeSpec,
    candidates: list[NoteEvent],
) -> dict[str, Any]:
    targets: list[dict[str, Any]] = []
    for window in spec.windows:
        for target in window.targets:
            notes = [event for event in candidates if _overlaps(event, target)]
            coverage = _union_duration(notes, target)
            pitches = [event.pitch_midi for event in notes]
            targets.append(
                {
                    "target_id": target.target_id,
                    "expectation": target.expectation,
                    "start_sec": target.start_sec,
                    "end_sec": target.end_sec,
                    "duration_sec": round(target.duration_sec, 6),
                    "candidate_note_count": len(notes),
                    "candidate_union_duration_sec": round(coverage, 6),
                    "candidate_time_coverage": round(
                        coverage / target.duration_sec,
                        6,
                    ),
                    "candidate_pitch_min": min(pitches) if pitches else None,
                    "candidate_pitch_max": max(pitches) if pitches else None,
                    "correct_recovered_note_count": None,
                    "false_positive_note_count": None,
                    "owner_review_required": True,
                }
            )
    return {
        "schema_version": 1,
        "artifact_type": "amt-muscriptor-gap-probe-report",
        "probe_id": spec.probe_id,
        "candidate_track_id": "voice_gap_candidate",
        "source_track_id": spec.source_voice_track_id,
        "automatic_merge_performed": False,
        "accuracy_claimed": False,
        "candidate_note_count": len(candidates),
        "targets": targets,
        "decision": "awaiting_owner_gap_review",
    }


def _artifact_records(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "run_manifest.json":
            continue
        records.append(
            {
                "path": str(path.relative_to(root)),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
        )
    return records


def _run_checked(argv: list[str], *, stdout: Path | None = None, stderr: Path | None = None) -> None:
    stdout_handle = stdout.open("wb") if stdout else subprocess.DEVNULL
    stderr_handle = stderr.open("wb") if stderr else subprocess.PIPE
    try:
        result = subprocess.run(
            argv,
            check=False,
            stdout=stdout_handle,
            stderr=stderr_handle,
        )
    finally:
        if stdout:
            stdout_handle.close()
        if stderr:
            stderr_handle.close()
    if result.returncode != 0:
        detail = ""
        if stderr is None and isinstance(result.stderr, bytes):
            detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GapProbeError(f"command failed ({result.returncode}): {argv[0]} {detail}")


def _clip_audio(
    canonical_audio: Path,
    destination: Path,
    *,
    start_sec: float,
    end_sec: float,
    ffmpeg: str,
) -> list[str]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        ffmpeg,
        "-nostdin",
        "-v",
        "error",
        "-i",
        str(canonical_audio),
        "-af",
        f"atrim=start={start_sec:.6f}:end={end_sec:.6f},asetpts=PTS-STARTPTS",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-c:a",
        "flac",
        str(destination),
    ]
    _run_checked(argv)
    if not destination.is_file() or destination.stat().st_size == 0:
        raise GapProbeError(f"ffmpeg did not create clip: {destination}")
    return argv


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve(strict=True).relative_to(root.resolve(strict=True)))
    except (OSError, ValueError) as exc:
        raise GapProbeError(f"output is outside project: {path}") from exc


def _rhythm_points(
    source_canonical: dict[str, Any],
) -> tuple[list[TempoPoint], list[MeterPoint]]:
    rhythm = source_canonical.get("rhythm")
    if not isinstance(rhythm, dict):
        raise GapProbeError("source canonical project has no rhythm map")
    tempo = [
        TempoPoint.from_dict(row)
        for row in rhythm.get("tempo_map", [])
        if isinstance(row, dict)
    ]
    meter = [
        MeterPoint.from_dict(row)
        for row in rhythm.get("meter_map", [])
        if isinstance(row, dict)
    ]
    if not tempo:
        tempo = [
            TempoPoint(
                time_sec=0.0,
                bpm=120.0,
                confidence=None,
                uncertainty_bpm=None,
                source_event_ids=("gap-probe-default-tempo",),
                method="gap_probe_default",
            )
        ]
    if not meter:
        meter = [
            MeterPoint(
                time_sec=0.0,
                numerator=4,
                denominator=4,
                confidence=None,
                source_event_ids=("gap-probe-default-meter",),
                status="defaulted",
            )
        ]
    return tempo, meter


def build_review_bundle(
    project_dir: Path,
    *,
    spec: ProbeSpec,
    source_voice_path: Path,
    source_canonical: dict[str, Any],
    source_events: list[NoteEvent],
    candidate_path: Path,
    candidates: list[NoteEvent],
    parent_manifest_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    if output_dir.exists() or output_dir.is_symlink():
        raise GapProbeError(f"review bundle already exists: {output_dir}")
    source_track = next(
        track
        for track in source_canonical["tracks"]
        if track["track_id"] == spec.source_voice_track_id
    )
    project = load_project(project_dir)
    canonical = project["canonical_audio"]
    tempo, meter = _rhythm_points(source_canonical)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{output_dir.name}.",
        dir=output_dir.parent,
    ) as temporary_name:
        temporary = Path(temporary_name)
        midi_report = export_performance_midi(
            temporary / "performance.mid",
            {
                "voice_raw": source_events,
                "voice_gap_candidate": candidates,
            },
            tempo,
            meter,
        )
        parent_hash = sha256_file(parent_manifest_path)
        candidate_hash = sha256_file(candidate_path)
        canonical_project = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-project",
            "project_id": project["project_id"],
            "timeline_basis": "original_canonical_mix_seconds",
            "canonical_audio": canonical,
            "tracks": [
                {
                    "track_id": "voice_raw",
                    "label": "voice raw（原始，不修改）",
                    "role": "candidate",
                    "instrument": "voice",
                    "event_count": len(source_events),
                    "source_events_path": _relative(source_voice_path, project_dir),
                    "provenance": source_track["provenance"],
                },
                {
                    "track_id": "voice_gap_candidate",
                    "label": "voice gap candidate（仅补漏候选）",
                    "role": "candidate",
                    "instrument": "voice",
                    "event_count": len(candidates),
                    "source_events_path": _relative(candidate_path, project_dir),
                    "provenance": {
                        "source_run_id": spec.probe_id,
                        "source_model": candidates[0].source_model
                        if candidates
                        else source_track["provenance"]["source_model"],
                        "run_manifest_sha256": parent_hash,
                        "normalized_artifact_sha256": candidate_hash,
                    },
                },
            ],
            "rhythm": source_canonical["rhythm"],
            "exports": {
                "performance_midi": {
                    "path": "performance.mid",
                    "representation": "performance",
                    "report": midi_report,
                }
            },
            "claims": {
                "candidate_fusion_performed": False,
                "automatic_merge_performed": False,
                "preferred_candidate_selected": False,
                "accuracy_claimed": False,
            },
        }
        atomic_write_json(temporary / "canonical_project.json", canonical_project)
        outputs = [
            {
                "path": path.name,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(temporary.iterdir())
            if path.is_file()
        ]
        bundle_manifest = {
            "schema_version": 1,
            "artifact_type": "amt-canonical-bundle",
            "status": "succeeded",
            "project_id": project["project_id"],
            "canonical_audio_sha256": canonical["sha256"],
            "bundle_id": output_dir.name,
            "tracks": ["voice_raw", "voice_gap_candidate"],
            "outputs": outputs,
            "claims": canonical_project["claims"],
        }
        atomic_write_json(temporary / "bundle_manifest.json", bundle_manifest)
        temporary.replace(output_dir)
    return bundle_manifest


def run_probe(
    project_dir: Path,
    config_path: Path,
    *,
    worker_env: Path,
    weight_provenance: Path,
    ffmpeg: str,
) -> dict[str, Any]:
    if not os.environ.get("SLURM_JOB_ID"):
        raise GapProbeError("gap probe requires an active Slurm allocation")
    hostname = platform.node()
    if "login" in hostname:
        raise GapProbeError("refusing to run gap probe on a login node")
    project_dir = project_dir.expanduser().resolve()
    config_path = config_path.expanduser().resolve()
    worker_env = worker_env.expanduser().resolve()
    weight_provenance = weight_provenance.expanduser().resolve()
    spec = load_spec(config_path)
    project, canonical_audio, source_voice_path, source_canonical = _source_context(
        project_dir,
        spec,
    )
    source_events = read_jsonl(source_voice_path)
    validate_empty_source_gaps(source_events, spec)
    run_dir = project_dir / "runs" / spec.probe_id
    review_bundle = project_dir / "exports" / f"{spec.probe_id}-review"
    if run_dir.exists() or run_dir.is_symlink():
        raise GapProbeError(f"probe run already exists: {run_dir}")
    if review_bundle.exists() or review_bundle.is_symlink():
        raise GapProbeError(f"review bundle already exists: {review_bundle}")
    clips_dir = run_dir / "clips"
    normalized_dir = run_dir / "normalized"
    logs_dir = run_dir / "logs"
    for directory in (clips_dir, normalized_dir, logs_dir):
        directory.mkdir(parents=True)
    request = {
        "schema_version": 1,
        "probe_id": spec.probe_id,
        "project_id": project["project_id"],
        "config_path": _relative(config_path, project_dir),
        "config_sha256": sha256_file(config_path),
        "canonical_audio": {
            "path": _relative(canonical_audio, project_dir),
            "sha256": sha256_file(canonical_audio),
        },
        "source_voice_events": {
            "path": _relative(source_voice_path, project_dir),
            "sha256": sha256_file(source_voice_path),
            "event_count": len(source_events),
        },
        "decoding": {
            "model": "MuScriptor/muscriptor-large",
            "beam_size": 4,
            "prelude_forcing": True,
            "skip_midi": True,
            "instrument_allowlist": None,
            "sampling": False,
        },
        "automatic_merge_performed": False,
    }
    atomic_write_json(run_dir / "request.json", request)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "artifact_type": "amt-muscriptor-gap-probe-run",
        "probe_id": spec.probe_id,
        "project_id": project["project_id"],
        "status": "running",
        "started_at": _utc_now(),
        "ended_at": None,
        "hostname": hostname,
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "request_sha256": sha256_file(run_dir / "request.json"),
        "child_runs": [],
        "outputs": [],
        "code": {
            **run_baseline.git_state(run_baseline.REPO_ROOT),
            "source_files": [
                {
                    "path": "workers/muscriptor/gap_probe.py",
                    "sha256": sha256_file(Path(__file__).resolve()),
                },
                {
                    "path": "workers/muscriptor/run_baseline.py",
                    "sha256": sha256_file(Path(run_baseline.__file__).resolve()),
                },
                {
                    "path": "slurm/41_muscriptor_gap_probe.slurm",
                    "sha256": sha256_file(
                        run_baseline.REPO_ROOT
                        / "slurm"
                        / "41_muscriptor_gap_probe.slurm"
                    ),
                },
            ],
        },
        "error": None,
    }
    atomic_write_json(run_dir / "run_manifest.json", manifest)
    candidates: list[NoteEvent] = []
    try:
        for window in spec.windows:
            clip_path = clips_dir / f"{window.window_id}.flac"
            command = _clip_audio(
                canonical_audio,
                clip_path,
                start_sec=window.clip_start_sec,
                end_sec=window.clip_end_sec,
                ffmpeg=ffmpeg,
            )
            atomic_write_json(
                logs_dir / f"{window.window_id}-clip.json",
                {
                    "argv": command,
                    "sha256": sha256_file(clip_path),
                    "clip_start_sec": window.clip_start_sec,
                    "clip_end_sec": window.clip_end_sec,
                },
            )
            child_run_id = f"{spec.probe_id}-{window.window_id}"
            exit_code = run_baseline.main(
                [
                    "--project",
                    str(project_dir),
                    "--audio",
                    str(clip_path),
                    "--worker-env",
                    str(worker_env),
                    "--weight-provenance",
                    str(weight_provenance),
                    "--run-id",
                    child_run_id,
                    "--beam-size",
                    "4",
                    "--device",
                    "cuda",
                    "--prelude-forcing",
                    "--skip-midi",
                ]
            )
            child_dir = project_dir / "runs" / child_run_id
            child_manifest = child_dir / "run_manifest.json"
            if exit_code != 0 or not child_manifest.is_file():
                raise GapProbeError(f"MuScriptor child run failed: {child_run_id}")
            child_value = _load_object(child_manifest)
            if child_value.get("status") != "succeeded":
                raise GapProbeError(f"MuScriptor child run did not succeed: {child_run_id}")
            child_events = read_jsonl(child_dir / "normalized" / "events.jsonl")
            window_candidates = shift_voice_candidates(
                child_events,
                probe_id=spec.probe_id,
                window=window,
            )
            candidates.extend(window_candidates)
            manifest["child_runs"].append(
                {
                    "window_id": window.window_id,
                    "run_id": child_run_id,
                    "run_manifest_path": _relative(child_manifest, project_dir),
                    "run_manifest_sha256": sha256_file(child_manifest),
                    "clip_sha256": sha256_file(clip_path),
                    "all_event_count": len(child_events),
                    "voice_gap_candidate_count": len(window_candidates),
                }
            )
        candidates.sort(key=lambda event: (event.onset_sec, event.pitch_midi, event.event_id))
        candidate_path = normalized_dir / "voice_gap_candidate.jsonl"
        write_jsonl(candidate_path, candidates)
        report = build_coverage_report(spec, candidates)
        atomic_write_json(normalized_dir / "gap_report.json", report)
        manifest["status"] = "succeeded"
    except (GapProbeError, OSError, RuntimeError, ValueError) as exc:
        manifest["status"] = "failed"
        manifest["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        manifest["ended_at"] = _utc_now()
        manifest["outputs"] = _artifact_records(run_dir)
        atomic_write_json(run_dir / "run_manifest.json", manifest)
    if manifest["status"] != "succeeded":
        return manifest
    try:
        build_review_bundle(
            project_dir,
            spec=spec,
            source_voice_path=source_voice_path,
            source_canonical=source_canonical,
            source_events=source_events,
            candidate_path=normalized_dir / "voice_gap_candidate.jsonl",
            candidates=candidates,
            parent_manifest_path=run_dir / "run_manifest.json",
            output_dir=review_bundle,
        )
    except (GapProbeError, OSError, RuntimeError, ValueError) as exc:
        manifest["status"] = "failed"
        manifest["ended_at"] = _utc_now()
        manifest["error"] = {
            "type": type(exc).__name__,
            "message": f"review bundle failed: {exc}",
        }
        atomic_write_json(run_dir / "run_manifest.json", manifest)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run same-model MuScriptor probes only over frozen voice gaps."
    )
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--worker-env", type=Path, required=True)
    parser.add_argument("--weight-provenance", type=Path, required=True)
    parser.add_argument("--ffmpeg", default=shutil.which("ffmpeg") or "ffmpeg")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = run_probe(
            args.project,
            args.config,
            worker_env=args.worker_env,
            weight_provenance=args.weight_provenance,
            ffmpeg=args.ffmpeg,
        )
    except GapProbeError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["status"] == "succeeded" else 1


if __name__ == "__main__":
    raise SystemExit(main())
