#!/usr/bin/env python3
"""Fit deterministic fusion profiles, threshold, and confidence on development."""

from __future__ import annotations

# ruff: noqa: E402
import argparse
import csv
import json
import os
import shutil
import sys
import tempfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.evaluate_external_notes import read_external_note_csv
from scripts.run_fusion import (
    _parse_candidate,
    _select_main_melody_events,
    _stable_route_binding,
)

from amt_core.benchmark import canonical_json_sha256
from amt_core.contracts import load_worker_result
from amt_core.evaluation import (
    EvaluationConfig,
    ReferenceNote,
    evaluate_notes,
    match_note_pairs,
)
from amt_core.events import NoteEvent
from amt_core.fusion import (
    CalibrationProvenance,
    CandidateCluster,
    FusionConfig,
    FusionError,
    SourceProfile,
    cluster_candidates,
    fit_isotonic_calibrator,
    fuse_main_melody,
    fusion_feature_model_sha256,
    score_clusters,
)
from amt_core.utils import atomic_write_json, sha256_file


class CalibrationRunError(RuntimeError):
    """Raised when development-only fusion calibration is not auditable."""


def _load_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CalibrationRunError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CalibrationRunError(f"{label} must be a JSON object")
    return value


def _sha_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _verified_development_benchmark(
    benchmark_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _load_object(benchmark_path, label="development benchmark")
    payload = manifest.get("freeze_payload")
    if (
        manifest.get("schema") != "amt-benchmark-pack/v1"
        or not isinstance(payload, dict)
        or payload.get("schema") != "amt-external-note-benchmark-manifest/v1"
        or payload.get("split") != "development"
        or canonical_json_sha256(payload) != manifest.get("benchmark_freeze_sha256")
    ):
        raise CalibrationRunError("development benchmark freeze is invalid")
    excerpts = payload.get("excerpts")
    if not isinstance(excerpts, list) or not excerpts:
        raise CalibrationRunError("development benchmark has no excerpts")
    return manifest, payload


def _references(
    excerpts: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, list[ReferenceNote]]], list[dict[str, Any]]]:
    references: dict[str, dict[str, list[ReferenceNote]]] = {}
    snapshots: list[dict[str, Any]] = []
    for excerpt in excerpts:
        excerpt_id = excerpt.get("excerpt_id")
        start = excerpt.get("evaluation_start_sec")
        end = excerpt.get("evaluation_end_sec")
        raw_references = excerpt.get("note_references")
        if (
            not isinstance(excerpt_id, str)
            or isinstance(start, bool)
            or not isinstance(start, (int, float))
            or isinstance(end, bool)
            or not isinstance(end, (int, float))
            or end <= start
            or not isinstance(raw_references, dict)
        ):
            raise CalibrationRunError("development excerpt record is invalid")
        per_annotator: dict[str, list[ReferenceNote]] = {}
        for annotator in ("a1", "a2"):
            record = raw_references.get(annotator)
            if not isinstance(record, dict):
                raise CalibrationRunError(f"{excerpt_id}: missing {annotator} reference")
            path = Path(record.get("path", "")).expanduser().resolve(strict=True)
            if sha256_file(path) != record.get("sha256"):
                raise CalibrationRunError(f"{excerpt_id}: {annotator} reference SHA-256 changed")
            notes = read_external_note_csv(
                path,
                excerpt_id=excerpt_id,
                annotator=annotator,
                start_sec=float(start),
                duration_sec=float(end) - float(start),
            )
            if len(notes) != record.get("note_count"):
                raise CalibrationRunError(f"{excerpt_id}: {annotator} reference count changed")
            per_annotator[annotator] = notes
            snapshots.append(_sha_record(path))
        references[excerpt_id] = per_annotator
    return references, snapshots


def _events_in_excerpt(
    events: list[NoteEvent],
    excerpt: dict[str, Any],
) -> list[NoteEvent]:
    start = float(excerpt["evaluation_start_sec"])
    end = float(excerpt["evaluation_end_sec"])
    return [event for event in events if start <= event.onset_sec < end]


def _macro_amax(
    events: list[NoteEvent],
    excerpts: list[dict[str, Any]],
    references: dict[str, dict[str, list[ReferenceNote]]],
) -> dict[str, Any]:
    per_excerpt = []
    metric_names = ("onset_only", "onset_pitch", "onset_pitch_offset", "onset_chroma")
    aggregates = {metric: {"precision": [], "recall": [], "f1": []} for metric in metric_names}
    chosen_references: list[ReferenceNote] = []
    for excerpt in excerpts:
        excerpt_id = excerpt["excerpt_id"]
        estimates = _events_in_excerpt(events, excerpt)
        reports = {
            annotator: evaluate_notes(notes, estimates)
            for annotator, notes in references[excerpt_id].items()
        }
        chosen_annotator = max(
            ("a1", "a2"),
            key=lambda annotator: (
                reports[annotator]["primary"]["onset_pitch_offset"]["f1"],
                reports[annotator]["primary"]["onset_pitch"]["f1"],
                annotator == "a1",
            ),
        )
        chosen = reports[chosen_annotator]["primary"]
        chosen_references.extend(references[excerpt_id][chosen_annotator])
        for metric in metric_names:
            for quantity in ("precision", "recall", "f1"):
                aggregates[metric][quantity].append(chosen[metric][quantity])
        per_excerpt.append(
            {
                "excerpt_id": excerpt_id,
                "estimate_count": len(estimates),
                "chosen_annotator": chosen_annotator,
                "annotators": reports,
            }
        )
    macro = {
        metric: {quantity: sum(values) / len(values) for quantity, values in quantities.items()}
        for metric, quantities in aggregates.items()
    }
    return {
        "macro_amax": macro,
        "per_excerpt": per_excerpt,
        "chosen_references": chosen_references,
    }


def _cluster_events(
    clusters: list[CandidateCluster],
    *,
    run_id: str,
) -> list[NoteEvent]:
    return [
        NoteEvent(
            event_id=f"{run_id}:{cluster.cluster_id}",
            track_id=f"{run_id}:clusters",
            onset_sec=cluster.onset_sec,
            offset_sec=cluster.offset_sec,
            pitch_midi=cluster.pitch_midi,
            source_run_id=run_id,
            source_model="amt-studio/deterministic-fusion-v1-calibration",
            instrument="voice",
            is_main_melody_candidate=True,
        )
        for cluster in clusters
    ]


def _calibration_diagnostics(
    raw_scores: list[float],
    outcomes: list[bool],
    probabilities: list[float],
) -> dict[str, Any]:
    brier = sum(
        (probability - int(outcome)) ** 2
        for probability, outcome in zip(probabilities, outcomes, strict=True)
    ) / len(outcomes)
    bins = []
    weighted_error = 0.0
    for lower_index in range(10):
        lower = lower_index / 10
        upper = (lower_index + 1) / 10
        indices = [
            index
            for index, probability in enumerate(probabilities)
            if lower <= probability < upper or (upper == 1.0 and probability == 1.0)
        ]
        if not indices:
            continue
        mean_confidence = sum(probabilities[index] for index in indices) / len(indices)
        empirical_accuracy = sum(outcomes[index] for index in indices) / len(indices)
        weighted_error += (len(indices) / len(outcomes)) * abs(mean_confidence - empirical_accuracy)
        bins.append(
            {
                "lower": lower,
                "upper": upper,
                "count": len(indices),
                "mean_confidence": mean_confidence,
                "empirical_accuracy": empirical_accuracy,
                "raw_score_min": min(raw_scores[index] for index in indices),
                "raw_score_max": max(raw_scores[index] for index in indices),
            }
        )
    return {
        "brier_score": brier,
        "expected_calibration_error_10_bin": weighted_error,
        "bins": bins,
    }


def calibrate(
    benchmark_path: Path,
    candidates: list[tuple[str, Path]],
    source_metadata_path: Path,
    base_config_path: Path,
    output_dir: Path,
    *,
    calibration_id: str,
    command: list[str] | None = None,
) -> dict[str, Any]:
    benchmark_path = benchmark_path.expanduser().resolve(strict=True)
    source_metadata_path = source_metadata_path.expanduser().resolve(strict=True)
    base_config_path = base_config_path.expanduser().resolve(strict=True)
    output_dir = output_dir.expanduser().resolve(strict=False)
    if output_dir.exists() or output_dir.is_symlink():
        raise CalibrationRunError(f"output path already exists: {output_dir}")
    if not output_dir.parent.is_dir():
        raise CalibrationRunError(f"output parent does not exist: {output_dir.parent}")
    benchmark, payload = _verified_development_benchmark(benchmark_path)
    excerpts = payload["excerpts"]
    references, reference_snapshots = _references(excerpts)

    metadata = _load_object(source_metadata_path, label="source metadata")
    raw_sources = metadata.get("sources")
    if metadata.get("schema") != "amt-fusion-source-metadata/v1" or not isinstance(
        raw_sources, list
    ):
        raise CalibrationRunError("source metadata uses an unsupported schema")
    source_metadata = {}
    for record in raw_sources:
        if not isinstance(record, dict) or not isinstance(record.get("label"), str):
            raise CalibrationRunError("source metadata record is invalid")
        label = record["label"]
        if label in source_metadata:
            raise CalibrationRunError("source metadata labels must be unique")
        source_metadata[label] = record

    config_payload = _load_object(base_config_path, label="base fusion config")
    if config_payload.get("schema") != "amt-fusion-config/v1":
        raise CalibrationRunError("base fusion config uses an unsupported schema")
    base_config = FusionConfig.from_dict(config_payload.get("config"))

    labels = [label for label, _path in candidates]
    if not candidates or len(labels) != len(set(labels)) or set(labels) != set(source_metadata):
        raise CalibrationRunError("candidate and source-metadata labels must match exactly")
    project_dir = None
    canonical_sha = None
    event_inputs: dict[str, list[NoteEvent]] = {}
    candidate_snapshots = []
    baseline_reports = {}
    route_bindings: dict[str, dict[str, Any]] = {}
    for label, raw_run_dir in candidates:
        run_dir = raw_run_dir.expanduser().resolve(strict=True)
        result = load_worker_result(run_dir)
        candidate_project = run_dir.parent.parent
        lineage = result.manifest.get("input_lineage")
        candidate_sha = lineage.get("canonical_mix_sha256") if isinstance(lineage, dict) else None
        if (
            run_dir.parent.name != "runs"
            or result.project_id != payload.get("project_id")
            or candidate_sha != payload.get("canonical_audio_sha256")
        ):
            raise CalibrationRunError(f"{label}: benchmark lineage differs")
        if project_dir is None:
            project_dir = candidate_project
            canonical_sha = candidate_sha
        elif candidate_project != project_dir or candidate_sha != canonical_sha:
            raise CalibrationRunError("candidate project lineage differs")
        all_events = result.read_note_events()
        route_bindings[label] = _stable_route_binding(result, all_events)
        events, selection = _select_main_melody_events(
            all_events,
            base_config.target_instrument,
        )
        event_inputs[label] = events
        events_path = result.output_path("normalized/events.jsonl")
        candidate_snapshots.append(
            {
                "label": label,
                "run_id": result.run_id,
                "worker": result.worker,
                "run_manifest": _sha_record(result.manifest_path),
                "events": _sha_record(events_path),
                "selection": selection,
            }
        )
        baseline_reports[label] = _macro_amax(
            events,
            excerpts,
            references,
        )

    profiles = {
        label: SourceProfile(
            label=label,
            reliability=baseline_reports[label]["macro_amax"]["onset_pitch"]["f1"],
            stem_quality=source_metadata[label].get("stem_quality"),
            instrument_presence=source_metadata[label].get("instrument_presence"),
        )
        for label in labels
    }
    for profile in profiles.values():
        profile.validate()

    clusters = cluster_candidates(event_inputs, profiles, base_config)
    score_clusters(clusters, profiles, base_config)
    cluster_events = _cluster_events(clusters, run_id=f"{calibration_id}-clusters")
    cluster_reference_report = _macro_amax(
        cluster_events,
        excerpts,
        references,
    )
    cluster_reference_report.pop("chosen_references")
    chosen_annotators = {
        record["excerpt_id"]: record["chosen_annotator"]
        for record in cluster_reference_report["per_excerpt"]
    }
    eligible_cluster_indices: list[int] = []
    matched_cluster_indices: set[int] = set()
    for excerpt in excerpts:
        excerpt_id = excerpt["excerpt_id"]
        start = float(excerpt["evaluation_start_sec"])
        end = float(excerpt["evaluation_end_sec"])
        excerpt_indices = [
            index for index, event in enumerate(cluster_events) if start <= event.onset_sec < end
        ]
        if set(eligible_cluster_indices).intersection(excerpt_indices):
            raise CalibrationRunError("development excerpts overlap cluster onsets")
        eligible_cluster_indices.extend(excerpt_indices)
        excerpt_events = [cluster_events[index] for index in excerpt_indices]
        annotator = chosen_annotators[excerpt_id]
        for _reference_index, local_estimate_index in match_note_pairs(
            references[excerpt_id][annotator],
            excerpt_events,
            EvaluationConfig(),
        ):
            matched_cluster_indices.add(excerpt_indices[local_estimate_index])
    if not eligible_cluster_indices:
        raise CalibrationRunError(
            "no candidate clusters fall inside development evaluation excerpts"
        )
    raw_scores = [clusters[index].raw_score for index in eligible_cluster_indices]
    outcomes = [index in matched_cluster_indices for index in eligible_cluster_indices]
    provenance = CalibrationProvenance(
        calibration_id=calibration_id,
        split="development",
        benchmark_sha256=benchmark["benchmark_freeze_sha256"],
        candidate_sha256=tuple(
            record["events"]["sha256"]
            for record in sorted(candidate_snapshots, key=lambda item: item["label"])
        ),
        feature_model_sha256=fusion_feature_model_sha256(
            base_config,
            profiles,
        ),
    )
    calibrator = fit_isotonic_calibrator(raw_scores, outcomes, provenance)

    threshold_trials = []
    for index in range(41):
        threshold = index / 40
        trial_config = replace(base_config, minimum_raw_score=threshold)
        trial = fuse_main_melody(
            event_inputs,
            profiles,
            fusion_run_id=f"{calibration_id}-threshold-{index:02d}",
            config=trial_config,
            calibrator=calibrator,
        )
        report = _macro_amax(
            list(trial.final_events),
            excerpts,
            references,
        )
        report.pop("chosen_references")
        onset_pitch = report["macro_amax"]["onset_pitch"]
        threshold_trials.append(
            {
                "threshold": threshold,
                "selected_event_count": len(trial.final_events),
                "macro_amax": report["macro_amax"],
                "selection_key": [
                    onset_pitch["f1"],
                    onset_pitch["precision"],
                    onset_pitch["recall"],
                    threshold,
                ],
            }
        )
    selected_trial = max(
        threshold_trials,
        key=lambda trial: tuple(trial["selection_key"]),
    )
    frozen_config = replace(
        base_config,
        minimum_raw_score=selected_trial["threshold"],
    )
    final = fuse_main_melody(
        event_inputs,
        profiles,
        fusion_run_id=f"{calibration_id}-development-final",
        config=frozen_config,
        calibrator=calibrator,
    )
    final_report = _macro_amax(
        list(final.final_events),
        excerpts,
        references,
    )
    final_report.pop("chosen_references")
    probabilities = [calibrator.predict(score) for score in raw_scores]
    strongest_label = max(
        labels,
        key=lambda label: (
            baseline_reports[label]["macro_amax"]["onset_pitch"]["f1"],
            label,
        ),
    )

    stage = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent))
    try:
        profiles_output = stage / "profiles.json"
        config_output = stage / "config.json"
        calibration_output = stage / "calibration.json"
        report_output = stage / "development_report.json"
        atomic_write_json(
            profiles_output,
            {
                "schema": "amt-fusion-source-profiles/v1",
                "calibrated_on_split": "development",
                "benchmark_freeze_sha256": benchmark["benchmark_freeze_sha256"],
                "profiles": [profiles[label].to_dict() for label in sorted(profiles)],
                "route_bindings": [
                    {"label": label, **route_bindings[label]} for label in sorted(route_bindings)
                ],
            },
        )
        atomic_write_json(
            config_output,
            {
                "schema": "amt-fusion-config/v1",
                "calibrated_on_split": "development",
                "selection_objective": "maximum_macro_amax_onset_pitch_f1",
                "config": frozen_config.to_dict(),
            },
        )
        atomic_write_json(calibration_output, calibrator.to_dict())
        report = {
            "schema": "amt-fusion-development-calibration-report/v1",
            "created_at": datetime.now(UTC).isoformat(),
            "calibration_id": calibration_id,
            "benchmark": _sha_record(benchmark_path),
            "source_metadata_input": {
                **_sha_record(source_metadata_path),
                "role": ("predeclared stem-quality and instrument-presence metadata"),
            },
            "base_config_input": {
                **_sha_record(base_config_path),
                "role": "predeclared deterministic fusion configuration",
            },
            "benchmark_freeze_sha256": benchmark["benchmark_freeze_sha256"],
            "split": "development",
            "inputs": {
                "benchmark": _sha_record(benchmark_path),
                "source_metadata": _sha_record(source_metadata_path),
                "base_config": _sha_record(base_config_path),
                "candidate_count": len(candidate_snapshots),
                "reference_count": len(reference_snapshots),
            },
            "candidate_inputs": candidate_snapshots,
            "reference_inputs": reference_snapshots,
            "baseline_reports": {
                label: {
                    key: value
                    for key, value in baseline_reports[label].items()
                    if key != "chosen_references"
                }
                for label in sorted(baseline_reports)
            },
            "strongest_baseline": {
                "label": strongest_label,
                "macro_amax": baseline_reports[strongest_label]["macro_amax"],
            },
            "cluster_count": len(clusters),
            "calibration_cluster_count": len(eligible_cluster_indices),
            "clusters_outside_evaluation_windows_excluded": (
                len(clusters) - len(eligible_cluster_indices)
            ),
            "positive_cluster_count": sum(outcomes),
            "calibration_diagnostics": _calibration_diagnostics(
                raw_scores,
                outcomes,
                probabilities,
            ),
            "threshold_trials": threshold_trials,
            "selected_threshold": selected_trial["threshold"],
            "final_fusion": {
                "event_count": len(final.final_events),
                "macro_amax": final_report["macro_amax"],
            },
            "rules": {
                "source_reliability": ("per-source development macro Amax onset+pitch F1"),
                "annotator_choice": (
                    "per-excerpt greater onset+pitch+offset F1, fixed Amax policy"
                ),
                "threshold_selection": (
                    "maximum development macro Amax onset+pitch F1; "
                    "ties use precision, recall, then higher threshold"
                ),
                "blind_results_used": False,
            },
            "command": command,
        }
        atomic_write_json(report_output, report)
        with (stage / "threshold_trials.csv").open(
            "w",
            encoding="utf-8",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "threshold",
                    "selected_event_count",
                    "onset_pitch_precision",
                    "onset_pitch_recall",
                    "onset_pitch_f1",
                ],
            )
            writer.writeheader()
            for trial in threshold_trials:
                metric = trial["macro_amax"]["onset_pitch"]
                writer.writerow(
                    {
                        "threshold": trial["threshold"],
                        "selected_event_count": trial["selected_event_count"],
                        "onset_pitch_precision": metric["precision"],
                        "onset_pitch_recall": metric["recall"],
                        "onset_pitch_f1": metric["f1"],
                    }
                )
        manifest = {
            "schema": "amt-fusion-calibration-run/v1",
            "status": "succeeded",
            "calibration_id": calibration_id,
            "split": "development",
            "inputs": {
                "benchmark": _sha_record(benchmark_path),
                "source_metadata": _sha_record(source_metadata_path),
                "base_config": _sha_record(base_config_path),
                "candidate_inputs": candidate_snapshots,
                "reference_inputs": reference_snapshots,
            },
            "outputs": [
                {
                    "path": path.name,
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in (
                    profiles_output,
                    config_output,
                    calibration_output,
                    report_output,
                    stage / "threshold_trials.csv",
                )
            ],
            "claims": {
                "blind_data_used_for_tuning": False,
                "manual_edits_applied": False,
                "confidence_calibrated": True,
            },
        }
        atomic_write_json(stage / "run_manifest.json", manifest)
        os.replace(stage, output_dir)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", required=True, type=Path)
    parser.add_argument("--candidate", action="append", required=True, type=_parse_candidate)
    parser.add_argument("--source-metadata", required=True, type=Path)
    parser.add_argument("--base-config", required=True, type=Path)
    parser.add_argument("--calibration-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    command = [str(Path(__file__).resolve()), *(argv if argv is not None else sys.argv[1:])]
    try:
        manifest = calibrate(
            args.benchmark,
            args.candidate,
            args.source_metadata,
            args.base_config,
            args.output,
            calibration_id=args.calibration_id,
            command=command,
        )
    except (CalibrationRunError, FusionError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
