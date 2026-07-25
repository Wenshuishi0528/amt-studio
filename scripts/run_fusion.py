#!/usr/bin/env python3
"""Create an immutable deterministic-fusion run from verified worker outputs."""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from amt_core.benchmark import canonical_json_sha256
from amt_core.canonical import load_rhythm_map
from amt_core.contracts import ContractValidationError, load_worker_result
from amt_core.events import NoteEvent, write_jsonl
from amt_core.fusion import (
    FUSION_SCHEMA,
    FusionConfig,
    FusionError,
    IsotonicCalibrator,
    SourceProfile,
    fuse_main_melody,
    fusion_feature_model_sha256,
)
from amt_core.utils import atomic_write_json, sha256_file


class FusionRunError(RuntimeError):
    """Raised when a fusion artifact cannot be created safely."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FusionRunError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FusionRunError(f"{label} must be a JSON object")
    return value


def _parse_candidate(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if (
        separator != "="
        or not label
        or label in {".", ".."}
        or "/" in label
        or "\\" in label
        or not raw_path
    ):
        raise argparse.ArgumentTypeError("candidate must be LABEL=RUN_DIR")
    return label, Path(raw_path).expanduser()


def _write_jsonl_records(path: Path, records: list[dict[str, Any]]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    os.replace(temporary, path)


def _artifact(path: Path, *, relative_to: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(relative_to)),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _select_main_melody_events(
    events: list[NoteEvent], target: str
) -> tuple[
    list[NoteEvent],
    dict[str, Any],
]:
    matching = [event for event in events if event.instrument == target]
    explicitly_flagged = [event for event in matching if event.is_main_melody_candidate]
    selected = explicitly_flagged or matching
    if not selected:
        raise FusionRunError(f"candidate contains no {target!r} events")
    selected_tracks = sorted({event.track_id for event in selected})
    if len(selected_tracks) != 1:
        raise FusionRunError(
            "main-melody input must resolve to exactly one target-instrument track"
        )
    selected_identities = {id(event) for event in selected}
    excluded_events = []
    for event in events:
        if id(event) in selected_identities:
            continue
        excluded_events.append(
            {
                "event_id": event.event_id,
                "track_id": event.track_id,
                "instrument": event.instrument,
                "reason": (
                    "non_target_instrument"
                    if event.instrument != target
                    else "not_explicit_main_melody_candidate"
                ),
            }
        )
    return selected, {
        "input_event_count": len(events),
        "eligible_event_count": len(selected),
        "excluded_event_count": len(events) - len(selected),
        "excluded_events": excluded_events,
        "all_input_events_accounted_for": (len(selected) + len(excluded_events) == len(events)),
        "target_instrument": target,
        "selection": (
            "explicit_is_main_melody_candidate"
            if explicitly_flagged
            else "single_target_instrument_track_fallback"
        ),
        "selected_track_id": selected_tracks[0],
    }


def _stable_route_binding(result: Any, events: list[NoteEvent]) -> dict[str, Any]:
    lineage = result.manifest.get("input_lineage")
    payload = {
        "schema": "amt-fusion-route-binding/v1",
        "worker": result.worker,
        "event_source_models": sorted({event.source_model for event in events}),
        "model": result.manifest.get("model"),
        "input_kind": (lineage.get("kind") if isinstance(lineage, dict) else None),
        "decoding": result.manifest.get("decoding"),
    }
    return {
        **payload,
        "route_sha256": canonical_json_sha256(payload),
    }


def _git_state() -> dict[str, Any]:
    import subprocess

    try:
        commit = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None, "status": []}
    return {"commit": commit, "dirty": bool(status), "status": status}


def create_fusion_run(
    candidates: list[tuple[str, Path]],
    profiles_path: Path,
    config_path: Path,
    output_dir: Path,
    *,
    run_id: str,
    calibration_path: Path | None = None,
    rhythm_path: Path | None = None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    if not candidates:
        raise FusionRunError("at least one candidate is required")
    labels = [label for label, _path in candidates]
    if len(set(labels)) != len(labels):
        raise FusionRunError("candidate labels must be unique")
    profiles_path = profiles_path.expanduser().resolve(strict=True)
    config_path = config_path.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().resolve(strict=False)
    if output_dir.exists() or output_dir.is_symlink():
        raise FusionRunError(f"output path already exists: {output_dir}")
    if not output_dir.parent.is_dir():
        raise FusionRunError(f"output parent does not exist: {output_dir.parent}")

    profiles_payload = _load_object(profiles_path, label="source profiles")
    raw_profiles = profiles_payload.get("profiles")
    if profiles_payload.get("schema") != "amt-fusion-source-profiles/v1" or not isinstance(
        raw_profiles, list
    ):
        raise FusionRunError("source profiles use an unsupported schema")
    profiles_list = [SourceProfile.from_dict(value) for value in raw_profiles]
    profiles = {profile.label: profile for profile in profiles_list}
    if len(profiles) != len(profiles_list) or set(profiles) != set(labels):
        raise FusionRunError("source profiles must match candidate labels exactly")
    raw_route_bindings = profiles_payload.get("route_bindings")
    if not isinstance(raw_route_bindings, list):
        raise FusionRunError("source profiles are missing route bindings")
    route_bindings: dict[str, dict[str, Any]] = {}
    for record in raw_route_bindings:
        if not isinstance(record, dict) or not isinstance(record.get("label"), str):
            raise FusionRunError("source route binding is invalid")
        label = record["label"]
        binding = {key: value for key, value in record.items() if key != "label"}
        payload_without_hash = {
            key: value for key, value in binding.items() if key != "route_sha256"
        }
        if label in route_bindings or canonical_json_sha256(payload_without_hash) != binding.get(
            "route_sha256"
        ):
            raise FusionRunError("source route binding is duplicated or changed")
        route_bindings[label] = binding
    if set(route_bindings) != set(labels):
        raise FusionRunError("source route bindings must match candidate labels exactly")

    config_payload = _load_object(config_path, label="fusion config")
    if config_payload.get("schema") != "amt-fusion-config/v1":
        raise FusionRunError("fusion config uses an unsupported schema")
    config = FusionConfig.from_dict(config_payload.get("config"))

    calibration = None
    calibration_snapshot = None
    if calibration_path is not None:
        calibration_path = calibration_path.expanduser().resolve(strict=True)
        calibration = IsotonicCalibrator.from_dict(
            _load_object(calibration_path, label="calibration")
        )
        calibration_snapshot = {
            "path": str(calibration_path),
            "sha256": sha256_file(calibration_path),
            "size_bytes": calibration_path.stat().st_size,
        }
        expected_feature_model = fusion_feature_model_sha256(config, profiles)
        if calibration.provenance.feature_model_sha256 != expected_feature_model:
            raise FusionRunError("calibration does not match the fusion config and source profiles")

    project_dir: Path | None = None
    project_id: str | None = None
    canonical_audio_sha256: str | None = None
    event_inputs: dict[str, list[NoteEvent]] = {}
    input_records: list[dict[str, Any]] = []
    prefilter_rejected: list[dict[str, Any]] = []
    for label, raw_run_dir in candidates:
        run_dir = raw_run_dir.resolve(strict=True)
        result = load_worker_result(run_dir)
        candidate_project = run_dir.parent.parent
        if run_dir.parent.name != "runs" or not (candidate_project / "manifest.json").is_file():
            raise FusionRunError(f"{label}: run is not inside a standard project")
        lineage = result.manifest.get("input_lineage")
        candidate_canonical_sha = (
            lineage.get("canonical_mix_sha256") if isinstance(lineage, dict) else None
        )
        if not isinstance(candidate_canonical_sha, str):
            raise FusionRunError(f"{label}: canonical-mix lineage is unavailable")
        if project_dir is None:
            project_dir = candidate_project
            project_id = result.project_id
            canonical_audio_sha256 = candidate_canonical_sha
        elif (
            candidate_project != project_dir
            or result.project_id != project_id
            or candidate_canonical_sha != canonical_audio_sha256
        ):
            raise FusionRunError("candidate project or canonical-audio lineage differs")
        events = result.read_note_events()
        if _stable_route_binding(result, events) != route_bindings[label]:
            raise FusionRunError(f"{label}: worker route does not match calibration")
        selected, selection = _select_main_melody_events(
            events,
            config.target_instrument,
        )
        prefilter_rejected.extend(
            {"source_label": label, **record} for record in selection["excluded_events"]
        )
        event_inputs[label] = selected
        events_path = result.output_path("normalized/events.jsonl")
        input_records.append(
            {
                "label": label,
                "worker": result.worker,
                "run_id": result.run_id,
                "run_dir": str(run_dir),
                "run_manifest_sha256": sha256_file(result.manifest_path),
                "events_sha256": sha256_file(events_path),
                "events_size_bytes": events_path.stat().st_size,
                "selection": selection,
            }
        )
    if project_dir is None or project_id is None or canonical_audio_sha256 is None:
        raise AssertionError("candidate validation did not establish project identity")
    project_manifest = _load_object(project_dir / "manifest.json", label="project")
    canonical = project_manifest.get("canonical_audio")
    if (
        project_manifest.get("project_id") != project_id
        or not isinstance(canonical, dict)
        or canonical.get("sha256") != canonical_audio_sha256
    ):
        raise FusionRunError("project manifest does not match candidate lineage")

    beat_times: list[float] = []
    rhythm_snapshot = None
    if rhythm_path is not None:
        rhythm_path = rhythm_path.expanduser().resolve(strict=True)
        rhythm = load_rhythm_map(rhythm_path)
        if rhythm.canonical_audio_sha256 != canonical_audio_sha256:
            raise FusionRunError("rhythm map uses a different canonical audio")
        beat_times = [event.time_sec for event in rhythm.events]
        rhythm_snapshot = {
            "path": str(rhythm_path),
            "sha256": sha256_file(rhythm_path),
            "size_bytes": rhythm_path.stat().st_size,
            "beat_count": len(beat_times),
        }

    result = fuse_main_melody(
        event_inputs,
        profiles,
        fusion_run_id=run_id,
        config=config,
        calibrator=calibration,
        beat_times_sec=beat_times,
    )
    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        events_path = stage / "events.jsonl"
        clusters_path = stage / "clusters.jsonl"
        rejected_path = stage / "rejected.jsonl"
        prefilter_rejected_path = stage / "prefilter_rejected.jsonl"
        write_jsonl(events_path, result.final_events)
        _write_jsonl_records(clusters_path, list(result.clusters))
        _write_jsonl_records(rejected_path, list(result.rejected))
        _write_jsonl_records(prefilter_rejected_path, prefilter_rejected)
        core_manifest_path = stage / "fusion_manifest.json"
        atomic_write_json(core_manifest_path, result.manifest)
        outputs = [
            _artifact(path, relative_to=stage)
            for path in (
                events_path,
                clusters_path,
                rejected_path,
                prefilter_rejected_path,
                core_manifest_path,
            )
        ]
        run_manifest = {
            "schema": "amt-fusion-run/v1",
            "status": "succeeded",
            "created_at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "project_id": project_id,
            "canonical_audio_sha256": canonical_audio_sha256,
            "fusion_schema": FUSION_SCHEMA,
            "mode": "main_melody",
            "inputs": input_records,
            "source_profiles": {
                "path": str(profiles_path),
                "sha256": sha256_file(profiles_path),
                "size_bytes": profiles_path.stat().st_size,
            },
            "configuration": {
                "path": str(config_path),
                "sha256": sha256_file(config_path),
                "size_bytes": config_path.stat().st_size,
            },
            "calibration": calibration_snapshot,
            "rhythm": rhythm_snapshot,
            "outputs": outputs,
            "code": {
                "git": _git_state(),
                "sources": {
                    str(path.relative_to(REPO_ROOT)): sha256_file(path)
                    for path in (
                        REPO_ROOT / "src/amt_core/fusion.py",
                        REPO_ROOT / "src/amt_core/events.py",
                        REPO_ROOT / "src/amt_core/contracts.py",
                        Path(__file__).resolve(),
                    )
                },
            },
            "environment": {
                "hostname": platform.node(),
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "command": command,
            "claims": {
                "calibrated_confidence": calibration is not None,
                "all_eligible_candidates_preserved": result.manifest[
                    "all_eligible_candidates_preserved"
                ],
                "all_input_candidates_accounted_for": all(
                    record["selection"]["all_input_events_accounted_for"]
                    for record in input_records
                ),
                "final_note_provenance_complete": result.manifest["final_note_provenance_complete"],
                "manual_edits_applied": False,
                "accuracy_claimed": False,
            },
        }
        atomic_write_json(stage / "run_manifest.json", run_manifest)
        os.replace(stage, output_dir)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return run_manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", action="append", required=True, type=_parse_candidate)
    parser.add_argument("--profiles", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument("--rhythm", type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = [str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])]
    try:
        manifest = create_fusion_run(
            args.candidate,
            args.profiles,
            args.config,
            args.output,
            run_id=args.run_id,
            calibration_path=args.calibration,
            rhythm_path=args.rhythm,
            command=command,
        )
    except (
        ContractValidationError,
        FusionError,
        FusionRunError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
