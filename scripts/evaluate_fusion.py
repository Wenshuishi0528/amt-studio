#!/usr/bin/env python3
"""Seal and evaluate deterministic fusion on an external blind note benchmark."""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import csv
import json
import math
import platform
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_benchmark import (
    BenchmarkEvaluationError,
    InputSnapshots,
    _git_state,
    _publish_new_directory,
    _snapshot_artifact,
    _track_input,
    _verify_input_snapshots,
)
from scripts.evaluate_external_notes import (
    ExternalNoteEvaluationError,
    _correction_proxy,
    _external_reference_records,
    _portable_candidate_events_path,
    _verified_benchmark,
    _verified_candidate_set,
    _voice_events_in_window,
    read_external_note_csv,
)
from scripts.run_fusion import (
    FusionRunError,
    _select_main_melody_events,
    _stable_route_binding,
)

from amt_core.benchmark import canonical_json_sha256
from amt_core.canonical import load_rhythm_map
from amt_core.contracts import ContractValidationError, load_worker_result
from amt_core.evaluation import (
    EvaluationConfig,
    EvaluationError,
    ReferenceNote,
    evaluate_notes,
)
from amt_core.events import EventValidationError, NoteEvent, read_jsonl
from amt_core.fusion import (
    DEFAULT_FEATURE_WEIGHTS,
    FusionConfig,
    FusionError,
    IsotonicCalibrator,
    SourceProfile,
    fuse_main_melody,
    fusion_feature_model_sha256,
)
from amt_core.utils import atomic_write_json, sha256_file

SEAL_SCHEMA = "amt-fusion-blind-evaluation-seal/v1"
SEAL_PAYLOAD_SCHEMA = "amt-fusion-blind-evaluation-freeze/v1"
REPORT_SCHEMA = "amt-fusion-blind-evaluation/v1"
PROTOCOL_SCHEMA = "amt-fusion-blind-evaluation-protocol/v1"
METRIC_NAMES = (
    "onset_only",
    "onset_pitch",
    "onset_pitch_offset",
    "onset_chroma",
)
SCORING_SOURCE_PATHS = (
    "scripts/evaluate_fusion.py",
    "scripts/evaluate_benchmark.py",
    "scripts/evaluate_external_notes.py",
    "scripts/run_fusion.py",
    "src/amt_core/benchmark.py",
    "src/amt_core/canonical.py",
    "src/amt_core/contracts.py",
    "src/amt_core/evaluation.py",
    "src/amt_core/events.py",
    "src/amt_core/fusion.py",
    "src/amt_core/utils.py",
)


class FusionEvaluationError(RuntimeError):
    """Raised when blind fusion cannot be sealed or evaluated safely."""


def _evaluation_protocol(config: EvaluationConfig) -> dict[str, Any]:
    config.validate()
    return {
        "schema": PROTOCOL_SCHEMA,
        "metric_config": config.to_dict(),
        "amax_policy": {
            "scope": "per_excerpt",
            "select_by": [
                "maximum_onset_pitch_offset_f1",
                "then_maximum_onset_pitch_f1",
                "then_annotator_a1",
            ],
            "macro_policy": "unweighted_mean_across_excerpts",
            "fixed_before_blind_scoring": True,
        },
        "strongest_baseline_policy": {
            "scope": "single_worker_baselines",
            "selection": "separate_maximum_for_each_primary_metric",
            "primary_metrics": [
                "macro_amax_onset_pitch_f1",
                "macro_amax_onset_pitch_offset_f1",
            ],
            "tie_break": "lexical_system_label",
        },
        "fusion_metric_rule": {
            "schema": "amt-fusion-primary-metric-rule/v1",
            "requirement": (
                "both_primary_metrics_nonregressing_and_at_least_one_strictly_improving"
            ),
            "comparison_epsilon": 0.0,
        },
        "task_acceptance_rule": {
            "schema": "amt-task007-acceptance-rule/v1",
            "requires_blind_primary_metric_rule": True,
            "requires_same_workflow_human_correction_time_improvement": True,
            "missing_human_correction_time_result": (
                "inconclusive_manual_correction_time_unavailable"
            ),
        },
        "precision_coverage_policy": {
            "retention_denominator": ("candidate_events_with_onsets_inside_evaluation_windows"),
            "retention_numerator": (
                "retained_candidate_events_with_onsets_inside_evaluation_windows"
            ),
            "numeric_rows": "sealed_full_fusion_only",
        },
    }


def _scoring_source_hashes() -> dict[str, str]:
    return {relative: sha256_file(REPO_ROOT / relative) for relative in SCORING_SOURCE_PATHS}


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FusionEvaluationError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FusionEvaluationError(f"{label} must be a JSON object")
    return value


def _read_jsonl_objects(path: Path, *, label: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise FusionEvaluationError(
                        f"{label} {path}:{line_number} must be a JSON object"
                    )
                records.append(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FusionEvaluationError(f"cannot read {label} {path}: {exc}") from exc
    return records


def _mean(values: list[float | None]) -> float | None:
    defined = [float(value) for value in values if value is not None]
    return sum(defined) / len(defined) if defined else None


def _snapshot(
    snapshots: InputSnapshots,
    path: Path,
    *,
    label: str,
) -> dict[str, Any]:
    record = _track_input(snapshots, path, label=label)
    return _snapshot_artifact(record)


def _output_record(
    records: list[dict[str, Any]],
    *,
    name: str,
    label: str,
) -> dict[str, Any]:
    matches = [record for record in records if record.get("path") == name]
    if len(matches) != 1:
        raise FusionEvaluationError(f"{label} must record exactly one {name!r} output")
    record = matches[0]
    if not isinstance(record.get("sha256"), str) or not isinstance(record.get("size_bytes"), int):
        raise FusionEvaluationError(f"{label} output record is invalid: {name}")
    return record


def _verify_recorded_file(
    snapshots: InputSnapshots,
    path: Path,
    record: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    snapshot = _snapshot(snapshots, path, label=label)
    if snapshot["sha256"] != record.get("sha256") or snapshot["size_bytes"] != record.get(
        "size_bytes"
    ):
        raise FusionEvaluationError(f"{label} does not match its recorded hash")
    return snapshot


def _calibration_artifacts(
    profiles_path: Path,
    config_path: Path,
    calibration_path: Path,
    *,
    blind_benchmark_sha256: str,
    blind_candidate_hashes: set[str],
    snapshots: InputSnapshots,
) -> tuple[
    dict[str, SourceProfile],
    dict[str, dict[str, Any]],
    FusionConfig,
    IsotonicCalibrator,
    dict[str, dict[str, Any]],
]:
    profiles_path = profiles_path.expanduser().resolve(strict=True)
    config_path = config_path.expanduser().resolve(strict=True)
    calibration_path = calibration_path.expanduser().resolve(strict=True)
    calibration_parent = calibration_path.parent
    if profiles_path.parent != calibration_parent or config_path.parent != calibration_parent:
        raise FusionEvaluationError(
            "profiles, config, and calibration must come from one calibration run"
        )

    paths = {
        "profiles": profiles_path,
        "config": config_path,
        "calibration": calibration_path,
        "calibration_run_manifest": calibration_parent / "run_manifest.json",
    }
    bindings = {
        name: _snapshot(snapshots, path, label=name.replace("_", " "))
        for name, path in paths.items()
    }
    profiles_payload = _load_object(profiles_path, label="source profiles")
    config_payload = _load_object(config_path, label="fusion config")
    calibration_payload = _load_object(calibration_path, label="calibration")
    calibration_manifest = _load_object(
        paths["calibration_run_manifest"],
        label="calibration run manifest",
    )
    if (
        profiles_payload.get("schema") != "amt-fusion-source-profiles/v1"
        or profiles_payload.get("calibrated_on_split") != "development"
        or config_payload.get("schema") != "amt-fusion-config/v1"
        or config_payload.get("calibrated_on_split") != "development"
        or calibration_manifest.get("schema") != "amt-fusion-calibration-run/v1"
        or calibration_manifest.get("status") != "succeeded"
        or calibration_manifest.get("split") != "development"
    ):
        raise FusionEvaluationError(
            "fusion profiles, config, and calibration must be development-only"
        )
    claims = calibration_manifest.get("claims")
    if (
        not isinstance(claims, dict)
        or claims.get("blind_data_used_for_tuning") is not False
        or claims.get("manual_edits_applied") is not False
        or claims.get("confidence_calibrated") is not True
    ):
        raise FusionEvaluationError("calibration run claims are invalid")
    outputs = calibration_manifest.get("outputs")
    if not isinstance(outputs, list):
        raise FusionEvaluationError("calibration run outputs are missing")
    for name, path in (
        ("profiles.json", profiles_path),
        ("config.json", config_path),
        ("calibration.json", calibration_path),
    ):
        record = _output_record(
            outputs,
            name=name,
            label="calibration run manifest",
        )
        binding = bindings[
            {
                "profiles.json": "profiles",
                "config.json": "config",
                "calibration.json": "calibration",
            }[name]
        ]
        if binding["sha256"] != record["sha256"] or binding["size_bytes"] != record["size_bytes"]:
            raise FusionEvaluationError(f"calibration run output hash changed: {path.name}")

    raw_profiles = profiles_payload.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise FusionEvaluationError("source profiles are empty")
    profile_list = [SourceProfile.from_dict(value) for value in raw_profiles]
    profiles = {profile.label: profile for profile in profile_list}
    if len(profiles) != len(profile_list):
        raise FusionEvaluationError("source profile labels must be unique")
    raw_route_bindings = profiles_payload.get("route_bindings")
    if not isinstance(raw_route_bindings, list):
        raise FusionEvaluationError("development profiles lack route bindings")
    route_bindings: dict[str, dict[str, Any]] = {}
    for record in raw_route_bindings:
        if not isinstance(record, dict) or not isinstance(record.get("label"), str):
            raise FusionEvaluationError("development route binding is invalid")
        label = record["label"]
        route_payload = {
            key: value for key, value in record.items() if key not in {"label", "route_sha256"}
        }
        if label in route_bindings or canonical_json_sha256(route_payload) != record.get(
            "route_sha256"
        ):
            raise FusionEvaluationError("development route binding is duplicated or changed")
        route_bindings[label] = {key: value for key, value in record.items() if key != "label"}
    if set(route_bindings) != set(profiles):
        raise FusionEvaluationError("development route bindings do not match source profiles")
    config = FusionConfig.from_dict(config_payload.get("config"))
    calibrator = IsotonicCalibrator.from_dict(calibration_payload)
    provenance = calibrator.provenance
    if (
        provenance.split != "development"
        or provenance.benchmark_sha256 == blind_benchmark_sha256
        or set(provenance.candidate_sha256).intersection(blind_candidate_hashes)
        or profiles_payload.get("benchmark_freeze_sha256") != provenance.benchmark_sha256
        or provenance.feature_model_sha256 != fusion_feature_model_sha256(config, profiles)
    ):
        raise FusionEvaluationError(
            "calibration provenance is not isolated from the blind benchmark"
        )
    return profiles, route_bindings, config, calibrator, bindings


@dataclass(frozen=True, slots=True)
class VerifiedFusion:
    manifest: dict[str, Any]
    events: list[NoteEvent]
    candidates: dict[str, list[NoteEvent]]
    profiles: dict[str, SourceProfile]
    route_bindings: dict[str, dict[str, Any]]
    config: FusionConfig
    calibrator: IsotonicCalibrator
    beat_times_sec: tuple[float, ...]
    bindings: dict[str, Any]


def _verified_fusion(
    pack_dir: Path,
    manifest: dict[str, Any],
    candidate_seal: dict[str, Any],
    sealed_candidates: list[tuple[dict[str, Any], list[NoteEvent]]],
    fusion_run_dir: Path,
    profiles_path: Path,
    config_path: Path,
    calibration_path: Path,
    rhythm_path: Path | None,
    snapshots: InputSnapshots,
) -> VerifiedFusion:
    fusion_run_dir = fusion_run_dir.expanduser()
    if fusion_run_dir.is_symlink():
        raise FusionEvaluationError("fusion run directory must not be a symlink")
    fusion_run_dir = fusion_run_dir.resolve(strict=True)
    project_dir = pack_dir.parent.parent.resolve(strict=True)
    if fusion_run_dir.parent != project_dir / "fusion" or not fusion_run_dir.is_dir():
        raise FusionEvaluationError(
            "fusion run must be inside the benchmark project fusion directory"
        )
    run_manifest_path = fusion_run_dir / "run_manifest.json"
    events_path = fusion_run_dir / "events.jsonl"
    core_manifest_path = fusion_run_dir / "fusion_manifest.json"
    clusters_path = fusion_run_dir / "clusters.jsonl"
    rejected_path = fusion_run_dir / "rejected.jsonl"
    prefilter_rejected_path = fusion_run_dir / "prefilter_rejected.jsonl"
    bindings: dict[str, Any] = {
        "fusion_run_manifest": _snapshot(
            snapshots,
            run_manifest_path,
            label="fusion run manifest",
        ),
        "fusion_events": _snapshot(
            snapshots,
            events_path,
            label="fusion events",
        ),
        "fusion_manifest": _snapshot(
            snapshots,
            core_manifest_path,
            label="fusion core manifest",
        ),
        "fusion_clusters": _snapshot(
            snapshots,
            clusters_path,
            label="fusion clusters",
        ),
        "fusion_rejected": _snapshot(
            snapshots,
            rejected_path,
            label="fusion rejected clusters",
        ),
        "prefilter_rejected": _snapshot(
            snapshots,
            prefilter_rejected_path,
            label="fusion prefilter rejected candidates",
        ),
    }
    run_manifest = _load_object(run_manifest_path, label="fusion run manifest")
    if (
        run_manifest.get("schema") != "amt-fusion-run/v1"
        or run_manifest.get("status") != "succeeded"
        or run_manifest.get("mode") != "main_melody"
        or run_manifest.get("project_id") != manifest["freeze_payload"].get("project_id")
        or run_manifest.get("canonical_audio_sha256")
        != manifest["freeze_payload"].get("canonical_audio_sha256")
    ):
        raise FusionEvaluationError("fusion run identity or lineage is invalid")
    claims = run_manifest.get("claims")
    if (
        not isinstance(claims, dict)
        or claims.get("calibrated_confidence") is not True
        or claims.get("all_eligible_candidates_preserved") is not True
        or claims.get("all_input_candidates_accounted_for") is not True
        or claims.get("final_note_provenance_complete") is not True
        or claims.get("manual_edits_applied") is not False
    ):
        raise FusionEvaluationError("fusion run claims are invalid")
    outputs = run_manifest.get("outputs")
    if not isinstance(outputs, list):
        raise FusionEvaluationError("fusion run outputs are missing")
    expected_output_names = {
        "events.jsonl",
        "clusters.jsonl",
        "rejected.jsonl",
        "prefilter_rejected.jsonl",
        "fusion_manifest.json",
    }
    output_names = [record.get("path") if isinstance(record, dict) else None for record in outputs]
    if (
        len(outputs) != len(expected_output_names)
        or len(set(output_names)) != len(output_names)
        or set(output_names) != expected_output_names
    ):
        raise FusionEvaluationError("fusion run outputs must be complete, unique, and exact")
    for name, key in (
        ("events.jsonl", "fusion_events"),
        ("fusion_manifest.json", "fusion_manifest"),
        ("clusters.jsonl", "fusion_clusters"),
        ("rejected.jsonl", "fusion_rejected"),
        ("prefilter_rejected.jsonl", "prefilter_rejected"),
    ):
        record = _output_record(outputs, name=name, label="fusion run manifest")
        binding = bindings[key]
        if binding["sha256"] != record["sha256"] or binding["size_bytes"] != record["size_bytes"]:
            raise FusionEvaluationError(f"fusion output hash changed: {name}")

    candidate_freeze = candidate_seal.get("freeze_payload")
    if not isinstance(candidate_freeze, dict):
        raise FusionEvaluationError("candidate seal payload is missing")
    candidate_records = candidate_freeze.get("candidates")
    fusion_inputs = run_manifest.get("inputs")
    if not isinstance(candidate_records, list) or not isinstance(fusion_inputs, list):
        raise FusionEvaluationError("fusion candidate bindings are missing")
    candidate_by_label = {
        record.get("label"): record for record in candidate_records if isinstance(record, dict)
    }
    fusion_by_label = {
        record.get("label"): record for record in fusion_inputs if isinstance(record, dict)
    }
    if (
        len(candidate_by_label) != len(candidate_records)
        or len(fusion_by_label) != len(fusion_inputs)
        or set(candidate_by_label) != set(fusion_by_label)
    ):
        raise FusionEvaluationError(
            "fusion inputs do not exactly match the sealed blind candidates"
        )
    for label in sorted(candidate_by_label):
        candidate = candidate_by_label[label]
        fused = fusion_by_label[label]
        for key in (
            "run_id",
            "worker",
            "run_manifest_sha256",
            "events_sha256",
        ):
            if fused.get(key) != candidate.get(key):
                raise FusionEvaluationError(f"{label}: fusion input differs from candidate seal")

    blind_candidate_hashes = {str(record["events_sha256"]) for record in candidate_records}
    (
        profiles,
        route_bindings,
        config,
        calibrator,
        calibration_bindings,
    ) = _calibration_artifacts(
        profiles_path,
        config_path,
        calibration_path,
        blind_benchmark_sha256=manifest["benchmark_freeze_sha256"],
        blind_candidate_hashes=blind_candidate_hashes,
        snapshots=snapshots,
    )
    bindings.update(calibration_bindings)
    if set(profiles) != set(candidate_by_label):
        raise FusionEvaluationError(
            "development profiles do not exactly match blind candidate labels"
        )
    for key, binding_name in (
        ("source_profiles", "profiles"),
        ("configuration", "config"),
        ("calibration", "calibration"),
    ):
        recorded = run_manifest.get(key)
        binding = bindings[binding_name]
        if (
            not isinstance(recorded, dict)
            or recorded.get("sha256") != binding["sha256"]
            or recorded.get("size_bytes") != binding["size_bytes"]
        ):
            raise FusionEvaluationError(f"fusion run {key} binding changed")

    beat_times: tuple[float, ...] = ()
    recorded_rhythm = run_manifest.get("rhythm")
    if recorded_rhythm is None:
        if rhythm_path is not None:
            raise FusionEvaluationError(
                "a rhythm input was supplied but the fusion run did not use one"
            )
        bindings["rhythm"] = None
    else:
        if not isinstance(recorded_rhythm, dict) or rhythm_path is None:
            raise FusionEvaluationError(
                "the fusion run rhythm input must be supplied for verification"
            )
        rhythm_binding = _snapshot(
            snapshots,
            rhythm_path,
            label="fusion rhythm map",
        )
        if (
            recorded_rhythm.get("sha256") != rhythm_binding["sha256"]
            or recorded_rhythm.get("size_bytes") != rhythm_binding["size_bytes"]
        ):
            raise FusionEvaluationError("fusion rhythm input hash changed")
        rhythm = load_rhythm_map(Path(rhythm_binding["path"]))
        if rhythm.canonical_audio_sha256 != manifest["freeze_payload"].get(
            "canonical_audio_sha256"
        ):
            raise FusionEvaluationError("fusion rhythm lineage differs")
        beat_times = tuple(event.time_sec for event in rhythm.events)
        bindings["rhythm"] = rhythm_binding

    candidates: dict[str, list[NoteEvent]] = {}
    expected_prefilter_rejected: list[dict[str, Any]] = []
    sealed_events_by_label = {record["label"]: events for record, events in sealed_candidates}
    for fusion_input in fusion_inputs:
        label = fusion_input["label"]
        try:
            candidate_events_path = _portable_candidate_events_path(
                pack_dir,
                candidate_by_label[label],
            )
            worker_result = load_worker_result(candidate_events_path.parent.parent)
            observed_route = _stable_route_binding(
                worker_result,
                sealed_events_by_label[label],
            )
        except (
            ContractValidationError,
            ExternalNoteEvaluationError,
            OSError,
            ValueError,
        ) as exc:
            raise FusionEvaluationError(
                f"{label}: cannot independently verify worker route: {exc}"
            ) from exc
        if observed_route != route_bindings[label]:
            raise FusionEvaluationError(
                f"{label}: sealed worker route differs from development profile"
            )
        selected, selection = _select_main_melody_events(
            sealed_events_by_label[label],
            config.target_instrument,
        )
        if fusion_by_label[label].get("selection") != selection:
            raise FusionEvaluationError(f"{label}: fusion main-melody selection binding changed")
        expected_prefilter_rejected.extend(
            {"source_label": label, **record} for record in selection["excluded_events"]
        )
        candidates[label] = selected

    try:
        stored_events = read_jsonl(events_path)
        replay = fuse_main_melody(
            candidates,
            profiles,
            fusion_run_id=run_manifest["run_id"],
            config=config,
            calibrator=calibrator,
            beat_times_sec=beat_times,
        )
    except (EventValidationError, FusionError, OSError, ValueError) as exc:
        raise FusionEvaluationError(f"cannot replay sealed fusion: {exc}") from exc
    if [event.to_dict() for event in stored_events] != [
        event.to_dict() for event in replay.final_events
    ]:
        raise FusionEvaluationError("sealed fusion events do not match deterministic replay")
    core_manifest = _load_object(core_manifest_path, label="fusion core manifest")
    if core_manifest != replay.manifest:
        raise FusionEvaluationError("sealed fusion manifest does not match deterministic replay")
    if _read_jsonl_objects(
        clusters_path,
        label="fusion clusters",
    ) != list(replay.clusters):
        raise FusionEvaluationError("sealed fusion clusters do not match deterministic replay")
    if _read_jsonl_objects(
        rejected_path,
        label="fusion rejected clusters",
    ) != list(replay.rejected):
        raise FusionEvaluationError(
            "sealed fusion rejected clusters do not match deterministic replay"
        )
    if (
        _read_jsonl_objects(
            prefilter_rejected_path,
            label="fusion prefilter rejected candidates",
        )
        != expected_prefilter_rejected
    ):
        raise FusionEvaluationError(
            "sealed fusion prefilter accounting does not match worker inputs"
        )
    if any(
        not event.source_event_ids
        or event.instrument != config.target_instrument
        or not event.is_main_melody_candidate
        for event in stored_events
    ):
        raise FusionEvaluationError(
            "fusion final-note provenance or main-melody identity is incomplete"
        )
    return VerifiedFusion(
        manifest=run_manifest,
        events=stored_events,
        candidates=candidates,
        profiles=profiles,
        route_bindings=route_bindings,
        config=config,
        calibrator=calibrator,
        beat_times_sec=beat_times,
        bindings=bindings,
    )


def _seal_payload(
    benchmark_manifest: dict[str, Any],
    candidate_seal: dict[str, Any],
    candidate_seal_binding: dict[str, Any],
    fusion: VerifiedFusion,
    evaluation_config: EvaluationConfig,
) -> dict[str, Any]:
    return {
        "schema": SEAL_PAYLOAD_SCHEMA,
        "split": "blind_test",
        "benchmark": {
            "benchmark_freeze_sha256": benchmark_manifest["benchmark_freeze_sha256"],
        },
        "candidate_set": {
            "candidate_set_sha256": candidate_seal["candidate_set_sha256"],
            "candidate_set_seal_sha256": candidate_seal_binding["sha256"],
        },
        "fusion": {
            "run_id": fusion.manifest["run_id"],
            "run_manifest_sha256": fusion.bindings["fusion_run_manifest"]["sha256"],
            "events_sha256": fusion.bindings["fusion_events"]["sha256"],
            "fusion_manifest_sha256": fusion.bindings["fusion_manifest"]["sha256"],
            "clusters_sha256": fusion.bindings["fusion_clusters"]["sha256"],
            "rejected_sha256": fusion.bindings["fusion_rejected"]["sha256"],
            "prefilter_rejected_sha256": fusion.bindings["prefilter_rejected"]["sha256"],
        },
        "inputs": {
            "profiles_sha256": fusion.bindings["profiles"]["sha256"],
            "config_sha256": fusion.bindings["config"]["sha256"],
            "calibration_sha256": fusion.bindings["calibration"]["sha256"],
            "calibration_run_manifest_sha256": fusion.bindings["calibration_run_manifest"][
                "sha256"
            ],
            "rhythm_sha256": (
                fusion.bindings["rhythm"]["sha256"]
                if fusion.bindings["rhythm"] is not None
                else None
            ),
        },
        "ablation_plan": {
            "workers": sorted(fusion.candidates),
            "feature_weights": sorted(DEFAULT_FEATURE_WEIGHTS),
            "fixed_development_configuration": True,
            "fixed_threshold_no_blind_retuning": True,
        },
        "evaluation_protocol": _evaluation_protocol(evaluation_config),
        "scoring_source_sha256": _scoring_source_hashes(),
        "confirmation": {
            "created_before_blind_fusion_scoring": True,
            "blind_fusion_output_quality_uninspected_before_seal": True,
            "blind_reference_not_used_for_fusion_configuration": True,
        },
    }


def create_fusion_evaluation_seal(
    pack_dir: Path,
    fusion_run_dir: Path,
    profiles_path: Path,
    config_path: Path,
    calibration_path: Path,
    output_path: Path,
    *,
    rhythm_path: Path | None = None,
    evaluation_config: EvaluationConfig | None = None,
    confirm_blind_output_uninspected: bool = False,
    confirm_reference_not_used: bool = False,
) -> dict[str, Any]:
    """Create an immutable pre-scoring seal for one blind fusion run."""

    if not confirm_blind_output_uninspected or not confirm_reference_not_used:
        raise FusionEvaluationError(
            "seal creation requires explicit uninspected-output and "
            "reference-not-used confirmations"
        )
    frozen_evaluation_config = evaluation_config or EvaluationConfig()
    frozen_evaluation_config.validate()
    output_path = output_path.expanduser().resolve(strict=False)
    if output_path.exists() or output_path.is_symlink():
        raise FusionEvaluationError(f"seal output already exists: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pack_dir = pack_dir.expanduser().resolve(strict=True)
    snapshots: InputSnapshots = {}
    try:
        benchmark_manifest, payload = _verified_benchmark(pack_dir, snapshots)
        candidate_seal, candidates = _verified_candidate_set(
            pack_dir,
            benchmark_manifest,
            payload,
            snapshots,
        )
    except (ExternalNoteEvaluationError, BenchmarkEvaluationError) as exc:
        raise FusionEvaluationError(str(exc)) from exc
    candidate_seal_binding = _snapshot(
        snapshots,
        pack_dir / "candidate_set_seal.json",
        label="candidate set seal",
    )
    fusion = _verified_fusion(
        pack_dir,
        benchmark_manifest,
        candidate_seal,
        candidates,
        fusion_run_dir,
        profiles_path,
        config_path,
        calibration_path,
        rhythm_path,
        snapshots,
    )
    freeze_payload = _seal_payload(
        benchmark_manifest,
        candidate_seal,
        candidate_seal_binding,
        fusion,
        frozen_evaluation_config,
    )
    seal = {
        "schema": SEAL_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "freeze_payload": freeze_payload,
        "seal_payload_sha256": canonical_json_sha256(freeze_payload),
    }
    _verify_input_snapshots(snapshots)
    atomic_write_json(output_path, seal)
    return seal


def _verify_evaluation_seal(
    seal_path: Path,
    benchmark_manifest: dict[str, Any],
    candidate_seal: dict[str, Any],
    candidate_seal_binding: dict[str, Any],
    fusion: VerifiedFusion,
    evaluation_config: EvaluationConfig,
    snapshots: InputSnapshots,
) -> dict[str, Any]:
    binding = _snapshot(snapshots, seal_path, label="fusion evaluation seal")
    seal = _load_object(Path(binding["path"]), label="fusion evaluation seal")
    payload = seal.get("freeze_payload")
    expected = _seal_payload(
        benchmark_manifest,
        candidate_seal,
        candidate_seal_binding,
        fusion,
        evaluation_config,
    )
    if (
        seal.get("schema") != SEAL_SCHEMA
        or not isinstance(payload, dict)
        or canonical_json_sha256(payload) != seal.get("seal_payload_sha256")
        or payload != expected
    ):
        raise FusionEvaluationError("fusion evaluation seal is invalid or an input hash changed")
    return seal


def _load_blind_references(
    pack_dir: Path,
    payload: dict[str, Any],
    snapshots: InputSnapshots,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, list[ReferenceNote]]],
    float,
]:
    project_dir = pack_dir.parent.parent
    project_manifest_path = project_dir / "manifest.json"
    _snapshot(snapshots, project_manifest_path, label="project manifest")
    project = _load_object(project_manifest_path, label="project manifest")
    canonical = project.get("canonical_audio")
    selection_record = payload.get("selection_manifest")
    concatenation_record = payload.get("concatenation_manifest")
    if (
        project.get("schema_version") != 1
        or project.get("project_id") != payload.get("project_id")
        or not isinstance(canonical, dict)
        or canonical.get("sha256") != payload.get("canonical_audio_sha256")
        or not isinstance(selection_record, dict)
        or not isinstance(concatenation_record, dict)
    ):
        raise FusionEvaluationError("project and benchmark lineage do not match")
    external: dict[str, dict[str, Any]] = {}
    for name, record in (
        ("selection", selection_record),
        ("concatenation", concatenation_record),
    ):
        path = Path(str(record.get("path"))).expanduser().resolve(strict=True)
        binding = _snapshot(
            snapshots,
            path,
            label=f"external {name} manifest",
        )
        if binding["sha256"] != record.get("sha256"):
            raise FusionEvaluationError(f"external {name} manifest SHA-256 changed")
        external[name] = _load_object(path, label=f"external {name} manifest")
    try:
        _external_reference_records(
            payload,
            external["selection"],
            external["concatenation"],
        )
    except ExternalNoteEvaluationError as exc:
        raise FusionEvaluationError(str(exc)) from exc
    concatenated_audio = external["concatenation"].get("concatenated_audio")
    if (
        not isinstance(concatenated_audio, dict)
        or not isinstance(project.get("source"), dict)
        or project["source"].get("sha256") != concatenated_audio.get("sha256")
    ):
        raise FusionEvaluationError("project source is not bound to the frozen concatenation")

    excerpts = payload.get("excerpts")
    if not isinstance(excerpts, list) or len(excerpts) < 3:
        raise FusionEvaluationError("blind benchmark has too few excerpts")
    references: dict[str, dict[str, list[ReferenceNote]]] = {}
    total_duration = 0.0
    for excerpt in excerpts:
        if not isinstance(excerpt, dict):
            raise FusionEvaluationError("blind excerpt record must be an object")
        excerpt_id = excerpt.get("excerpt_id")
        start = excerpt.get("evaluation_start_sec")
        end = excerpt.get("evaluation_end_sec")
        duration = excerpt.get("duration_sec")
        raw_references = excerpt.get("note_references")
        if (
            not isinstance(excerpt_id, str)
            or isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or isinstance(duration, bool)
            or not isinstance(duration, (int, float))
            or not math.isclose(
                float(end) - float(start),
                float(duration),
                rel_tol=0.0,
                abs_tol=1e-6,
            )
            or not isinstance(raw_references, dict)
        ):
            raise FusionEvaluationError("blind excerpt timing is invalid")
        total_duration += float(duration)
        references[excerpt_id] = {}
        for annotator in ("a1", "a2"):
            record = raw_references.get(annotator)
            if not isinstance(record, dict):
                raise FusionEvaluationError(f"{excerpt_id}: missing {annotator} reference")
            path = Path(str(record.get("path"))).expanduser().resolve(strict=True)
            binding = _snapshot(
                snapshots,
                path,
                label=f"{excerpt_id} {annotator} note reference",
            )
            if binding["sha256"] != record.get("sha256"):
                raise FusionEvaluationError(f"{excerpt_id}: {annotator} reference SHA-256 changed")
            notes = read_external_note_csv(
                path,
                excerpt_id=excerpt_id,
                annotator=annotator,
                start_sec=float(start),
                duration_sec=float(duration),
            )
            if len(notes) != record.get("note_count"):
                raise FusionEvaluationError(f"{excerpt_id}: {annotator} reference count changed")
            references[excerpt_id][annotator] = notes
    return excerpts, references, total_duration


def _metric_row(
    *,
    system: str,
    system_kind: str,
    excerpt_id: str,
    annotator: str,
    metric_name: str,
    metric: dict[str, Any],
) -> dict[str, Any]:
    return {
        "task_mode": "main_melody",
        "status": "evaluated",
        "system": system,
        "system_kind": system_kind,
        "excerpt_id": excerpt_id,
        "annotator": annotator,
        "metric": metric_name,
        "precision": metric.get("precision"),
        "recall": metric.get("recall"),
        "f1": metric.get("f1"),
        "matches": metric.get("matches"),
        "reference_count": metric.get("reference_count"),
        "estimate_count": metric.get("estimate_count"),
    }


def _score_system(
    system: str,
    system_kind: str,
    events: list[NoteEvent],
    excerpts: list[dict[str, Any]],
    references: dict[str, dict[str, list[ReferenceNote]]],
    config: EvaluationConfig,
    *,
    emit_rows: bool,
) -> dict[str, Any]:
    metric_rows: list[dict[str, Any]] = []
    correction_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    per_excerpt: list[dict[str, Any]] = []
    macro_values = {
        metric: {field: [] for field in ("precision", "recall", "f1")} for metric in METRIC_NAMES
    }
    total_duration = 0.0
    discrepancy_count = 0
    for excerpt in excerpts:
        excerpt_id = excerpt["excerpt_id"]
        duration = float(excerpt["duration_sec"])
        total_duration += duration
        estimates = _voice_events_in_window(
            events,
            start_sec=float(excerpt["evaluation_start_sec"]),
            end_sec=float(excerpt["evaluation_end_sec"]),
        )
        annotator_reports: dict[str, dict[str, Any]] = {}
        for annotator in ("a1", "a2"):
            try:
                note_report = evaluate_notes(
                    references[excerpt_id][annotator],
                    estimates,
                    config,
                )
            except EvaluationError as exc:
                raise FusionEvaluationError(str(exc)) from exc
            annotator_reports[annotator] = note_report
            if emit_rows:
                for metric_name in METRIC_NAMES:
                    metric_rows.append(
                        _metric_row(
                            system=system,
                            system_kind=system_kind,
                            excerpt_id=excerpt_id,
                            annotator=annotator,
                            metric_name=metric_name,
                            metric=note_report["primary"][metric_name],
                        )
                    )
        selected_annotator = max(
            ("a1", "a2"),
            key=lambda annotator: (
                annotator_reports[annotator]["primary"]["onset_pitch_offset"]["f1"],
                annotator_reports[annotator]["primary"]["onset_pitch"]["f1"],
                annotator == "a1",
            ),
        )
        selected = annotator_reports[selected_annotator]
        proxy = _correction_proxy(selected, duration_sec=duration)
        discrepancy_count += int(proxy["note_object_discrepancy_count"])
        for metric_name in METRIC_NAMES:
            metric = selected["primary"][metric_name]
            for field in ("precision", "recall", "f1"):
                macro_values[metric_name][field].append(metric[field])
            if emit_rows:
                metric_rows.append(
                    _metric_row(
                        system=system,
                        system_kind=system_kind,
                        excerpt_id=excerpt_id,
                        annotator="Amax",
                        metric_name=metric_name,
                        metric=metric,
                    )
                )
        if emit_rows:
            correction_rows.append(
                {
                    "task_mode": "main_melody",
                    "system": system,
                    "system_kind": system_kind,
                    "excerpt_id": excerpt_id,
                    "reference_policy": f"Amax:{selected_annotator}",
                    "workflow": "blind_automated_evaluation",
                    "human_correction_time_status": "unavailable_not_measured",
                    "assisted_correction_time_status": "unavailable_not_measured",
                    "owner_final_review_time_status": "unavailable_not_measured",
                    "direct_owner_edit_time_status": "unavailable_not_measured",
                    "automated_proxy_status": "available_not_human_time",
                    **proxy,
                }
            )
            for category in (
                "unmatched_reference_after_onset",
                "unmatched_estimate_after_onset",
                "onset_matched_pitch_mismatch",
                "onset_pitch_matched_offset_mismatch",
            ):
                error_rows.append(
                    {
                        "task_mode": "main_melody",
                        "system": system,
                        "system_kind": system_kind,
                        "excerpt_id": excerpt_id,
                        "reference_policy": f"Amax:{selected_annotator}",
                        "category": category,
                        "count": proxy[category],
                    }
                )
            octave = selected["primary"]["octave_error"]
            error_rows.append(
                {
                    "task_mode": "main_melody",
                    "system": system,
                    "system_kind": system_kind,
                    "excerpt_id": excerpt_id,
                    "reference_policy": f"Amax:{selected_annotator}",
                    "category": "octave_error",
                    "count": octave["errors"],
                }
            )
        per_excerpt.append(
            {
                "excerpt_id": excerpt_id,
                "estimate_count": len(estimates),
                "predeclared_amax_annotator": selected_annotator,
                "annotators": annotator_reports,
            }
        )
    macro = {
        metric: {field: _mean(values) for field, values in fields.items()}
        for metric, fields in macro_values.items()
    }
    return {
        "system": system,
        "system_kind": system_kind,
        "event_count": len(events),
        "macro_amax": macro,
        "amax_note_object_discrepancy_count": discrepancy_count,
        "amax_note_object_discrepancy_per_minute": (
            discrepancy_count / total_duration * 60.0 if total_duration else None
        ),
        "manual_correction_time_measured": False,
        "per_excerpt": per_excerpt,
        "metric_rows": metric_rows,
        "correction_rows": correction_rows,
        "error_rows": error_rows,
    }


def _precision_coverage_rows(
    systems: list[tuple[str, str, list[NoteEvent]]],
    excerpts: list[dict[str, Any]],
    references: dict[str, dict[str, list[ReferenceNote]]],
    config: EvaluationConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    thresholds = (0.0, *config.confidence_thresholds)
    for system, kind, events in systems:
        scoped_events = [
            event
            for event in events
            if any(
                float(excerpt["evaluation_start_sec"])
                <= event.onset_sec
                < float(excerpt["evaluation_end_sec"])
                for excerpt in excerpts
            )
        ]
        if kind != "fusion":
            rows.append(
                {
                    "task_mode": "main_melody",
                    "system": system,
                    "system_kind": kind,
                    "status": (
                        "unavailable_ablation_changes_feature_model"
                        if kind in {"worker_removal", "feature_weight_removal"}
                        else "unavailable_not_fusion_calibrated_confidence"
                    ),
                    "threshold": None,
                    "estimate_retention": None,
                    "estimates_retained": None,
                    "estimates_total": len(scoped_events),
                    "onset_pitch_precision": None,
                    "onset_pitch_recall": None,
                    "onset_pitch_f1": None,
                    "onset_pitch_offset_f1": None,
                }
            )
            continue
        confidence_count = sum(event.confidence is not None for event in scoped_events)
        if confidence_count != len(scoped_events):
            rows.append(
                {
                    "task_mode": "main_melody",
                    "system": system,
                    "system_kind": kind,
                    "status": "unavailable_incomplete_candidate_confidence",
                    "threshold": None,
                    "estimate_retention": None,
                    "estimates_retained": None,
                    "estimates_total": len(scoped_events),
                    "onset_pitch_precision": None,
                    "onset_pitch_recall": None,
                    "onset_pitch_f1": None,
                    "onset_pitch_offset_f1": None,
                }
            )
            continue
        for threshold in thresholds:
            retained = [
                event
                for event in scoped_events
                if event.confidence is not None and event.confidence >= threshold
            ]
            score = _score_system(
                system,
                kind,
                retained,
                excerpts,
                references,
                config,
                emit_rows=False,
            )
            onset_pitch = score["macro_amax"]["onset_pitch"]
            rows.append(
                {
                    "task_mode": "main_melody",
                    "system": system,
                    "system_kind": kind,
                    "status": "available_calibrated_confidence",
                    "threshold": threshold,
                    "estimate_retention": (
                        len(retained) / len(scoped_events) if scoped_events else 0.0
                    ),
                    "estimates_retained": len(retained),
                    "estimates_total": len(scoped_events),
                    "onset_pitch_precision": onset_pitch["precision"],
                    "onset_pitch_recall": onset_pitch["recall"],
                    "onset_pitch_f1": onset_pitch["f1"],
                    "onset_pitch_offset_f1": score["macro_amax"]["onset_pitch_offset"]["f1"],
                }
            )
    return rows


def _fusion_variants(
    fusion: VerifiedFusion,
) -> list[tuple[str, str, str | None, list[NoteEvent]]]:
    run_id = fusion.manifest["run_id"]
    variants: list[tuple[str, str, str | None, list[NoteEvent]]] = []
    for index, removed in enumerate(sorted(fusion.candidates), start=1):
        candidates = {
            label: events for label, events in fusion.candidates.items() if label != removed
        }
        profiles = {
            label: profile for label, profile in fusion.profiles.items() if label != removed
        }
        result = fuse_main_melody(
            candidates,
            profiles,
            fusion_run_id=f"{run_id}-worker-ablation-{index:02d}",
            config=fusion.config,
            calibrator=None,
            beat_times_sec=fusion.beat_times_sec,
        )
        variants.append(
            (
                f"without_worker:{removed}",
                "worker_removal",
                removed,
                list(result.final_events),
            )
        )
    for index, feature in enumerate(sorted(DEFAULT_FEATURE_WEIGHTS), start=1):
        result = fuse_main_melody(
            fusion.candidates,
            fusion.profiles,
            fusion_run_id=f"{run_id}-feature-ablation-{index:02d}",
            config=fusion.config.without_feature(feature),
            calibrator=None,
            beat_times_sec=fusion.beat_times_sec,
        )
        variants.append(
            (
                f"without_feature:{feature}",
                "feature_weight_removal",
                feature,
                list(result.final_events),
            )
        )
    return variants


def _primary_metric_comparison(
    baseline_scores: list[dict[str, Any]],
    fusion_score: dict[str, Any],
) -> dict[str, Any]:
    if not baseline_scores:
        raise FusionEvaluationError("at least one single-worker baseline is required")
    strongest_by_metric: dict[str, dict[str, Any]] = {}
    for metric_name in ("onset_pitch", "onset_pitch_offset"):
        strongest = sorted(
            baseline_scores,
            key=lambda score: (
                -score["macro_amax"][metric_name]["f1"],
                score["system"],
            ),
        )[0]
        baseline_f1 = strongest["macro_amax"][metric_name]["f1"]
        fusion_f1 = fusion_score["macro_amax"][metric_name]["f1"]
        strongest_by_metric[metric_name] = {
            "system": strongest["system"],
            "baseline_f1": baseline_f1,
            "fusion_f1": fusion_f1,
            "delta": fusion_f1 - baseline_f1,
            "nonregressing": fusion_f1 >= baseline_f1,
            "strictly_improving": fusion_f1 > baseline_f1,
        }
    primary_metric_rule_passed = all(
        record["nonregressing"] for record in strongest_by_metric.values()
    ) and any(record["strictly_improving"] for record in strongest_by_metric.values())
    return {
        "strongest_baseline_by_metric": strongest_by_metric,
        "primary_metric_rule": ("pass" if primary_metric_rule_passed else "fail"),
        "primary_metric_rule_passed": primary_metric_rule_passed,
        "task_acceptance": ("inconclusive_manual_correction_time_unavailable"),
        "task_acceptance_passed": None,
    }


def _write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    fieldnames: list[str],
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def evaluate_fusion(
    pack_dir: Path,
    fusion_run_dir: Path,
    profiles_path: Path,
    config_path: Path,
    calibration_path: Path,
    seal_path: Path,
    output_dir: Path,
    *,
    rhythm_path: Path | None = None,
    config: EvaluationConfig | None = None,
    command: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate one pre-sealed fusion run and its fixed ablations."""

    started_at = datetime.now(UTC).isoformat()
    metric_config = config or EvaluationConfig()
    metric_config.validate()
    pack_dir = pack_dir.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().resolve(strict=False)
    if output_dir.exists() or output_dir.is_symlink():
        raise FusionEvaluationError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    snapshots: InputSnapshots = {}
    try:
        benchmark_manifest, payload = _verified_benchmark(pack_dir, snapshots)
        candidate_seal, sealed_candidates = _verified_candidate_set(
            pack_dir,
            benchmark_manifest,
            payload,
            snapshots,
        )
    except (ExternalNoteEvaluationError, BenchmarkEvaluationError) as exc:
        raise FusionEvaluationError(str(exc)) from exc
    candidate_seal_binding = _snapshot(
        snapshots,
        pack_dir / "candidate_set_seal.json",
        label="candidate set seal",
    )
    fusion = _verified_fusion(
        pack_dir,
        benchmark_manifest,
        candidate_seal,
        sealed_candidates,
        fusion_run_dir,
        profiles_path,
        config_path,
        calibration_path,
        rhythm_path,
        snapshots,
    )
    seal = _verify_evaluation_seal(
        seal_path,
        benchmark_manifest,
        candidate_seal,
        candidate_seal_binding,
        fusion,
        metric_config,
        snapshots,
    )
    excerpts, references, total_duration = _load_blind_references(
        pack_dir,
        payload,
        snapshots,
    )

    baseline_scores: list[dict[str, Any]] = []
    metric_rows: list[dict[str, Any]] = []
    correction_rows: list[dict[str, Any]] = []
    error_rows: list[dict[str, Any]] = []
    confidence_systems: list[tuple[str, str, list[NoteEvent]]] = []
    for label in sorted(fusion.candidates):
        score = _score_system(
            label,
            "single_worker_baseline",
            fusion.candidates[label],
            excerpts,
            references,
            metric_config,
            emit_rows=True,
        )
        baseline_scores.append(score)
        metric_rows.extend(score["metric_rows"])
        correction_rows.extend(score["correction_rows"])
        error_rows.extend(score["error_rows"])
        confidence_systems.append((label, "single_worker_baseline", fusion.candidates[label]))
    fusion_score = _score_system(
        "fusion",
        "fusion",
        fusion.events,
        excerpts,
        references,
        metric_config,
        emit_rows=True,
    )
    metric_rows.extend(fusion_score["metric_rows"])
    correction_rows.extend(fusion_score["correction_rows"])
    error_rows.extend(fusion_score["error_rows"])
    confidence_systems.append(("fusion", "fusion", fusion.events))

    ablation_scores: list[dict[str, Any]] = []
    for name, variant_type, removed, events in _fusion_variants(fusion):
        score = _score_system(
            name,
            variant_type,
            events,
            excerpts,
            references,
            metric_config,
            emit_rows=True,
        )
        score["variant_type"] = variant_type
        score["removed_component"] = removed
        score["confidence_status"] = "unavailable_ablation_changes_feature_model"
        ablation_scores.append(score)
        metric_rows.extend(score["metric_rows"])
        correction_rows.extend(score["correction_rows"])
        error_rows.extend(score["error_rows"])
        confidence_systems.append((name, variant_type, events))

    fusion_full = fusion_score["macro_amax"]["onset_pitch_offset"]["f1"]
    fusion_pitch = fusion_score["macro_amax"]["onset_pitch"]["f1"]
    primary_comparison = _primary_metric_comparison(
        baseline_scores,
        fusion_score,
    )
    strongest_correction_proxy = min(
        baseline_scores,
        key=lambda score: (
            score["amax_note_object_discrepancy_per_minute"],
            score["system"],
        ),
    )
    correction_proxy_delta = (
        fusion_score["amax_note_object_discrepancy_per_minute"]
        - strongest_correction_proxy["amax_note_object_discrepancy_per_minute"]
    )

    precision_rows = _precision_coverage_rows(
        confidence_systems,
        excerpts,
        references,
        metric_config,
    )
    ablation_rows = [
        {
            "task_mode": "main_melody",
            "variant": "full_fusion",
            "variant_type": "full",
            "removed_component": None,
            "event_count": fusion_score["event_count"],
            "onset_pitch_precision": fusion_score["macro_amax"]["onset_pitch"]["precision"],
            "onset_pitch_recall": fusion_score["macro_amax"]["onset_pitch"]["recall"],
            "onset_pitch_f1": fusion_pitch,
            "onset_pitch_offset_f1": fusion_full,
            "delta_onset_pitch_f1_vs_full": 0.0,
            "delta_onset_pitch_offset_f1_vs_full": 0.0,
        }
    ]
    for score in ablation_scores:
        ablation_rows.append(
            {
                "task_mode": "main_melody",
                "variant": score["system"],
                "variant_type": score["variant_type"],
                "removed_component": score["removed_component"],
                "event_count": score["event_count"],
                "onset_pitch_precision": score["macro_amax"]["onset_pitch"]["precision"],
                "onset_pitch_recall": score["macro_amax"]["onset_pitch"]["recall"],
                "onset_pitch_f1": score["macro_amax"]["onset_pitch"]["f1"],
                "onset_pitch_offset_f1": score["macro_amax"]["onset_pitch_offset"]["f1"],
                "delta_onset_pitch_f1_vs_full": (
                    score["macro_amax"]["onset_pitch"]["f1"] - fusion_pitch
                ),
                "delta_onset_pitch_offset_f1_vs_full": (
                    score["macro_amax"]["onset_pitch_offset"]["f1"] - fusion_full
                ),
            }
        )

    report = {
        "schema": REPORT_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(),
        "benchmark": {
            "benchmark_id": payload.get("benchmark_id"),
            "project_id": payload.get("project_id"),
            "split": "blind_test",
            "benchmark_freeze_sha256": benchmark_manifest["benchmark_freeze_sha256"],
            "candidate_set_sha256": candidate_seal["candidate_set_sha256"],
            "fusion_evaluation_seal_sha256": seal["seal_payload_sha256"],
            "excerpt_count": len(excerpts),
            "evaluated_audio_duration_sec": total_duration,
        },
        "metric_config": metric_config.to_dict(),
        "evaluation_protocol": _evaluation_protocol(metric_config),
        "reference_policy": payload["reference_policy"],
        "tasks": {
            "main_melody": {
                "status": "evaluated",
                "baseline_count": len(baseline_scores),
                "strongest_baseline_by_metric": primary_comparison["strongest_baseline_by_metric"],
                "fusion": {
                    key: value
                    for key, value in fusion_score.items()
                    if key
                    not in {
                        "metric_rows",
                        "correction_rows",
                        "error_rows",
                    }
                },
                "comparison": {
                    **primary_comparison,
                    "strongest_correction_proxy_baseline": (strongest_correction_proxy["system"]),
                    "automated_discrepancy_per_minute_delta": (correction_proxy_delta),
                },
            },
            "multi_track": {
                "status": "unavailable_no_sealed_multitrack_reference",
                "metrics": None,
                "interpretation": (
                    "This external benchmark seals voice main-melody notes only; "
                    "no multi-track score is inferred from it."
                ),
            },
        },
        "baselines": [
            {
                key: value
                for key, value in score.items()
                if key
                not in {
                    "metric_rows",
                    "correction_rows",
                    "error_rows",
                }
            }
            for score in baseline_scores
        ],
        "ablations": [
            {
                key: value
                for key, value in score.items()
                if key
                not in {
                    "metric_rows",
                    "correction_rows",
                    "error_rows",
                }
            }
            for score in ablation_scores
        ],
        "claims": {
            "blind_fusion_seal_verified": True,
            "candidate_preinspection_seal_verified": True,
            "development_only_calibration_verified": True,
            "blind_retuning_performed": False,
            "hidden_manual_edits_in_automated_results": False,
            "final_note_provenance_complete": True,
            "manual_correction_time_measured": False,
            "automated_correction_proxy_available": True,
            "multi_track_reference_available": False,
            "blind_primary_metric_rule_passed": primary_comparison["primary_metric_rule_passed"],
            "task007_acceptance": ("inconclusive_manual_correction_time_unavailable"),
            "task007_acceptance_passed": None,
        },
        "limitations": {
            "human_correction_time": "unavailable_not_measured",
            "correction_proxy": (
                "Note-object discrepancy is not edit time and cannot establish "
                "a human correction-efficiency improvement."
            ),
            "ablation_calibration": (
                "Worker and feature removals hold the development raw-score "
                "threshold fixed and are not retuned. Their confidence is "
                "unavailable because each removal changes the feature model "
                "fingerprint, so the full-fusion isotonic calibrator is not reused."
            ),
        },
    }

    metric_rows.append(
        {
            "task_mode": "multi_track",
            "status": "unavailable_no_sealed_multitrack_reference",
            "system": None,
            "system_kind": None,
            "excerpt_id": None,
            "annotator": None,
            "metric": None,
            "precision": None,
            "recall": None,
            "f1": None,
            "matches": None,
            "reference_count": None,
            "estimate_count": None,
        }
    )
    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        report_path = stage / "evaluation_report.json"
        atomic_write_json(report_path, report)
        _write_csv(
            stage / "metrics_by_track.csv",
            metric_rows,
            [
                "task_mode",
                "status",
                "system",
                "system_kind",
                "excerpt_id",
                "annotator",
                "metric",
                "precision",
                "recall",
                "f1",
                "matches",
                "reference_count",
                "estimate_count",
            ],
        )
        _write_csv(
            stage / "precision_coverage.csv",
            precision_rows,
            [
                "task_mode",
                "system",
                "system_kind",
                "status",
                "threshold",
                "estimate_retention",
                "estimates_retained",
                "estimates_total",
                "onset_pitch_precision",
                "onset_pitch_recall",
                "onset_pitch_f1",
                "onset_pitch_offset_f1",
            ],
        )
        _write_csv(
            stage / "error_taxonomy.csv",
            error_rows,
            [
                "task_mode",
                "system",
                "system_kind",
                "excerpt_id",
                "reference_policy",
                "category",
                "count",
            ],
        )
        _write_csv(
            stage / "correction_time.csv",
            correction_rows,
            [
                "task_mode",
                "system",
                "system_kind",
                "excerpt_id",
                "reference_policy",
                "workflow",
                "human_correction_time_status",
                "assisted_correction_time_status",
                "owner_final_review_time_status",
                "direct_owner_edit_time_status",
                "automated_proxy_status",
                "schema",
                "audio_duration_sec",
                "note_object_discrepancy_count",
                "note_object_discrepancy_per_minute",
                "unmatched_reference_after_onset",
                "unmatched_estimate_after_onset",
                "onset_matched_pitch_mismatch",
                "onset_pitch_matched_offset_mismatch",
                "manual_edit_time_measured",
                "interpretation",
            ],
        )
        _write_csv(
            stage / "ablation.csv",
            ablation_rows,
            [
                "task_mode",
                "variant",
                "variant_type",
                "removed_component",
                "event_count",
                "onset_pitch_precision",
                "onset_pitch_recall",
                "onset_pitch_f1",
                "onset_pitch_offset_f1",
                "delta_onset_pitch_f1_vs_full",
                "delta_onset_pitch_offset_f1_vs_full",
            ],
        )
        source_paths = [REPO_ROOT / relative for relative in SCORING_SOURCE_PATHS]
        run_manifest = {
            "schema": "amt-fusion-blind-evaluation-run/v1",
            "status": "succeeded",
            "started_at": started_at,
            "ended_at": datetime.now(UTC).isoformat(),
            "command": command,
            "inputs": [_snapshot_artifact(snapshots[path]) for path in sorted(snapshots, key=str)],
            "outputs": [
                {
                    "path": path.name,
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in sorted(stage.iterdir())
                if path.is_file() and path.name != "run_manifest.json"
            ],
            "environment": {
                "hostname": platform.node(),
                "device": "cpu",
                "python": platform.python_version(),
                "platform": platform.platform(),
            },
            "code": {
                **_git_state(REPO_ROOT),
                "source_files": [
                    {
                        "path": str(path.relative_to(REPO_ROOT)),
                        "sha256": sha256_file(path),
                    }
                    for path in source_paths
                ],
            },
            "benchmark": report["benchmark"],
            "claims": report["claims"],
        }
        atomic_write_json(stage / "run_manifest.json", run_manifest)
        _verify_input_snapshots(snapshots)
        _publish_new_directory(stage, output_dir)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    def add_common(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--pack-dir", required=True, type=Path)
        subparser.add_argument("--fusion-run", required=True, type=Path)
        subparser.add_argument("--profiles", required=True, type=Path)
        subparser.add_argument("--config", required=True, type=Path)
        subparser.add_argument("--calibration", required=True, type=Path)
        subparser.add_argument("--rhythm", type=Path)

    seal_parser = subparsers.add_parser("seal")
    add_common(seal_parser)
    seal_parser.add_argument("--output", required=True, type=Path)
    seal_parser.add_argument(
        "--confirm-blind-output-uninspected",
        required=True,
        action="store_true",
    )
    seal_parser.add_argument(
        "--confirm-reference-not-used",
        required=True,
        action="store_true",
    )

    evaluate_parser = subparsers.add_parser("evaluate")
    add_common(evaluate_parser)
    evaluate_parser.add_argument("--seal", required=True, type=Path)
    evaluate_parser.add_argument("--output-dir", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    raw_args = argv if argv is not None else sys.argv[1:]
    command = [str(Path(__file__).resolve()), *raw_args]
    try:
        if args.command_name == "seal":
            result = create_fusion_evaluation_seal(
                args.pack_dir,
                args.fusion_run,
                args.profiles,
                args.config,
                args.calibration,
                args.output,
                rhythm_path=args.rhythm,
                confirm_blind_output_uninspected=(args.confirm_blind_output_uninspected),
                confirm_reference_not_used=args.confirm_reference_not_used,
            )
        else:
            result = evaluate_fusion(
                args.pack_dir,
                args.fusion_run,
                args.profiles,
                args.config,
                args.calibration,
                args.seal,
                args.output_dir,
                rhythm_path=args.rhythm,
                command=command,
            )
    except (
        BenchmarkEvaluationError,
        EventValidationError,
        ExternalNoteEvaluationError,
        FusionError,
        FusionEvaluationError,
        FusionRunError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
