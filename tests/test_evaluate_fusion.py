from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_fusion import (
    FusionEvaluationError,
    _primary_metric_comparison,
    create_fusion_evaluation_seal,
    evaluate_fusion,
)
from scripts.run_fusion import _stable_route_binding, create_fusion_run

from amt_core.benchmark import canonical_json_sha256
from amt_core.contracts import load_worker_result
from amt_core.evaluation import EvaluationConfig
from amt_core.events import NoteEvent, write_jsonl
from amt_core.fusion import (
    CalibrationProvenance,
    FusionConfig,
    IsotonicCalibrator,
    SourceProfile,
    fusion_feature_model_sha256,
)
from amt_core.utils import sha256_file


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _artifact(path: Path, relative_to: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(relative_to)),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _frequency(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


class FusionBlindEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.project = self.root / "fixture-project"
        canonical = self.project / "audio" / "canonical" / "mix.flac"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"canonical-fixture")
        self.canonical_sha = sha256_file(canonical)
        source = self.project / "audio" / "original" / "blind.wav"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"concatenated-source-fixture")
        self.source_sha = sha256_file(source)
        _write_json(
            self.project / "manifest.json",
            {
                "schema_version": 1,
                "project_id": "fixture-project",
                "source": {"sha256": self.source_sha},
                "canonical_audio": {"sha256": self.canonical_sha},
            },
        )
        self.pack = self.project / "annotations" / "external-blind"
        self.pack.mkdir(parents=True)
        self._build_external_benchmark()
        self.runs = {
            "game": self._worker_run("game-run", "game", pitch_delta=0.0),
            "basic": self._worker_run(
                "basic-run",
                "basic_pitch",
                pitch_delta=0.08,
            ),
            "seed": self._worker_run(
                "seed-run",
                "muscriptor",
                pitch_delta=-0.08,
            ),
        }
        self._build_candidate_seal()
        (
            self.profiles,
            self.config,
            self.calibration,
        ) = self._build_calibration()
        self.fusion = self.project / "fusion" / "blind-fusion-v1"
        self.fusion.parent.mkdir()
        create_fusion_run(
            [(label, path) for label, path in self.runs.items()],
            self.profiles,
            self.config,
            self.fusion,
            run_id="blind-fusion-v1",
            calibration_path=self.calibration,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _build_external_benchmark(self) -> None:
        excerpts = []
        selected_tracks = []
        concatenated_tracks = []
        pitches = (60.0, 62.0, 64.0)
        for index, pitch in enumerate(pitches, start=1):
            excerpt_id = f"blind-{index:02d}"
            start = float(index - 1)
            duration = 0.8
            references = {}
            for annotator in ("a1", "a2"):
                path = self.pack / f"{excerpt_id}-{annotator}.csv"
                path.write_text(
                    f"0.1,{_frequency(pitch):.9f},0.3\n",
                    encoding="utf-8",
                )
                references[annotator] = {
                    "path": str(path),
                    "sha256": sha256_file(path),
                    "note_count": 1,
                }
            track_id = index
            common = {
                "track_id": track_id,
                "singer_id": f"singer-{index}",
                "language": "fixture",
                "average_midi_pitch": pitch,
                "audio_sha256": f"{index}" * 64,
            }
            selected_tracks.append(
                {
                    **common,
                    "notes_a1_sha256": references["a1"]["sha256"],
                    "notes_a1_count": 1,
                    "notes_a2_sha256": references["a2"]["sha256"],
                    "notes_a2_count": 1,
                }
            )
            concatenated_tracks.append(
                {
                    **common,
                    "excerpt_id": excerpt_id,
                    "start_sec": start,
                    "end_sec": start + duration,
                    "duration_sec": duration,
                    "note_references": references,
                }
            )
            excerpts.append(
                {
                    "excerpt_id": excerpt_id,
                    "track_id": track_id,
                    "singer_group_id": f"singer-{index}",
                    "language": "fixture",
                    "average_midi_pitch": pitch,
                    "source_audio_sha256": f"{index}" * 64,
                    "evaluation_start_sec": start,
                    "evaluation_end_sec": start + duration,
                    "duration_sec": duration,
                    "note_references": references,
                }
            )
        selection_path = self.pack / "selection.json"
        concatenation_path = self.pack / "concatenation.json"
        _write_json(
            selection_path,
            {
                "schema": "amt-external-note-selection/v1",
                "selection_before_candidate_inference": True,
                "candidate_output_inspected": False,
                "split": "blind_test",
                "tracks": selected_tracks,
            },
        )
        _write_json(
            concatenation_path,
            {
                "schema": "amt-external-note-concatenation/v1",
                "created_before_candidate_inference": True,
                "concatenated_audio": {"sha256": self.source_sha},
                "tracks": concatenated_tracks,
            },
        )
        payload = {
            "schema": "amt-external-note-benchmark-manifest/v1",
            "benchmark_id": "fixture-external-blind",
            "project_id": "fixture-project",
            "canonical_audio_sha256": self.canonical_sha,
            "split": "blind_test",
            "prior_system_exposure": False,
            "reference_policy": {
                "annotators": ["a1", "a2"],
                "report_each_annotator": True,
                "aggregate_policy": "per_track_max_onset_pitch_offset_f1",
                "aggregate_policy_fixed_before_candidate_inference": True,
            },
            "selection_manifest": {
                "path": str(selection_path),
                "sha256": sha256_file(selection_path),
            },
            "concatenation_manifest": {
                "path": str(concatenation_path),
                "sha256": sha256_file(concatenation_path),
            },
            "excerpts": excerpts,
        }
        self.benchmark_freeze_sha = canonical_json_sha256(payload)
        _write_json(
            self.pack / "benchmark_manifest.json",
            {
                "schema": "amt-benchmark-pack/v1",
                "freeze_payload": payload,
                "benchmark_freeze_sha256": self.benchmark_freeze_sha,
            },
        )

    def _worker_run(
        self,
        run_id: str,
        worker: str,
        *,
        pitch_delta: float,
    ) -> Path:
        events = [
            NoteEvent(
                event_id=f"{run_id}:{index}",
                track_id=f"{run_id}:voice",
                onset_sec=float(index - 1) + 0.1,
                offset_sec=float(index - 1) + 0.4,
                pitch_midi=pitch + pitch_delta,
                source_run_id=run_id,
                source_model=f"fixture/{worker}",
                instrument="voice",
                is_main_melody_candidate=True,
            )
            for index, pitch in enumerate((60.0, 62.0, 64.0), start=1)
        ]
        events.append(
            NoteEvent(
                event_id=f"{run_id}:outside-window",
                track_id=f"{run_id}:voice",
                onset_sec=10.1,
                offset_sec=10.4,
                pitch_midi=67.0 + pitch_delta,
                source_run_id=run_id,
                source_model=f"fixture/{worker}",
                instrument="voice",
                is_main_melody_candidate=True,
            )
        )
        run_dir = self.project / "runs" / run_id
        events_path = run_dir / "normalized" / "events.jsonl"
        write_jsonl(events_path, events)
        summary = run_dir / "normalized" / "summary.json"
        _write_json(summary, {"event_count": len(events)})
        _write_json(
            run_dir / "run_manifest.json",
            {
                "schema_version": 1,
                "contract_version": "amt-worker-result/v1",
                "status": "succeeded",
                "run_id": run_id,
                "project_id": "fixture-project",
                "worker": worker,
                "input_lineage": {
                    "canonical_mix_sha256": self.canonical_sha,
                },
                "outputs": [
                    _artifact(events_path, run_dir),
                    _artifact(summary, run_dir),
                ],
            },
        )
        return run_dir

    def _build_candidate_seal(self) -> None:
        candidates = []
        workers = {
            "game": "game",
            "basic": "basic_pitch",
            "seed": "muscriptor",
        }
        for label, run_dir in self.runs.items():
            events = run_dir / "normalized" / "events.jsonl"
            candidates.append(
                {
                    "label": label,
                    "run_id": run_dir.name,
                    "worker": workers[label],
                    "events_path": str(events),
                    "events_sha256": sha256_file(events),
                    "run_manifest_sha256": sha256_file(run_dir / "run_manifest.json"),
                }
            )
        payload = {
            "schema": "amt-evaluation-candidate-set/v1",
            "benchmark_freeze_sha256": self.benchmark_freeze_sha,
            "split": "blind_test",
            "confirmation": {
                "candidate_output_quality_uninspected_before_freeze": True,
                "candidate_selection_or_tuning_after_freeze_prohibited": True,
            },
            "candidates": candidates,
        }
        _write_json(
            self.pack / "candidate_set_seal.json",
            {
                "schema": "amt-evaluation-candidate-set-seal/v1",
                "freeze_payload": payload,
                "candidate_set_sha256": canonical_json_sha256(payload),
            },
        )

    def _build_calibration(self) -> tuple[Path, Path, Path]:
        directory = self.root / "development-calibration"
        directory.mkdir()
        profiles = directory / "profiles.json"
        config = directory / "config.json"
        calibration = directory / "calibration.json"
        development_freeze = "d" * 64
        profile_records = [
            {
                "label": label,
                "reliability": reliability,
                "stem_quality": 0.9,
                "instrument_presence": 1.0,
            }
            for label, reliability in (
                ("basic", 0.8),
                ("game", 0.9),
                ("seed", 0.85),
            )
        ]
        _write_json(
            profiles,
            {
                "schema": "amt-fusion-source-profiles/v1",
                "calibrated_on_split": "development",
                "benchmark_freeze_sha256": development_freeze,
                "profiles": profile_records,
                "route_bindings": [
                    {
                        "label": label,
                        **_stable_route_binding(
                            load_worker_result(run_dir),
                            load_worker_result(run_dir).read_note_events(),
                        ),
                    }
                    for label, run_dir in sorted(self.runs.items())
                ],
            },
        )
        fusion_config = FusionConfig(minimum_raw_score=0.0)
        _write_json(
            config,
            {
                "schema": "amt-fusion-config/v1",
                "calibrated_on_split": "development",
                "selection_objective": "fixture",
                "config": fusion_config.to_dict(),
            },
        )
        parsed_profiles = {
            record["label"]: SourceProfile.from_dict(record) for record in profile_records
        }
        calibrator = IsotonicCalibrator(
            provenance=CalibrationProvenance(
                calibration_id="fixture-development-calibration",
                split="development",
                benchmark_sha256=development_freeze,
                candidate_sha256=("a" * 64, "b" * 64, "c" * 64),
                feature_model_sha256=fusion_feature_model_sha256(
                    fusion_config,
                    parsed_profiles,
                ),
            ),
            upper_bounds=(1.0,),
            probabilities=(0.9,),
            sample_count=3,
            positive_count=3,
        )
        _write_json(calibration, calibrator.to_dict())
        outputs = [
            {
                "path": path.name,
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in (profiles, config, calibration)
        ]
        _write_json(
            directory / "run_manifest.json",
            {
                "schema": "amt-fusion-calibration-run/v1",
                "status": "succeeded",
                "split": "development",
                "outputs": outputs,
                "claims": {
                    "blind_data_used_for_tuning": False,
                    "manual_edits_applied": False,
                    "confidence_calibrated": True,
                },
            },
        )
        return profiles, config, calibration

    def _seal(self) -> Path:
        path = self.pack / "fusion_evaluation_seal.json"
        create_fusion_evaluation_seal(
            self.pack,
            self.fusion,
            self.profiles,
            self.config,
            self.calibration,
            path,
            confirm_blind_output_uninspected=True,
            confirm_reference_not_used=True,
        )
        return path

    def test_seal_is_non_overwriting_and_rejects_tampered_fusion(self) -> None:
        seal = self._seal()
        with self.assertRaisesRegex(FusionEvaluationError, "already exists"):
            create_fusion_evaluation_seal(
                self.pack,
                self.fusion,
                self.profiles,
                self.config,
                self.calibration,
                seal,
                confirm_blind_output_uninspected=True,
                confirm_reference_not_used=True,
            )
        events_path = self.fusion / "events.jsonl"
        events_path.write_text(
            events_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            FusionEvaluationError,
            "hash changed|input hash changed",
        ):
            evaluate_fusion(
                self.pack,
                self.fusion,
                self.profiles,
                self.config,
                self.calibration,
                seal,
                self.root / "tampered-evaluation",
            )

    def test_seal_rejects_incomplete_or_duplicate_fusion_outputs(self) -> None:
        manifest_path = self.fusion / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["outputs"].append(dict(manifest["outputs"][0]))
        _write_json(manifest_path, manifest)
        with self.assertRaisesRegex(
            FusionEvaluationError,
            "complete, unique, and exact",
        ):
            self._seal()

    def test_evaluation_rejects_tampered_cluster_artifact(self) -> None:
        seal = self._seal()
        clusters_path = self.fusion / "clusters.jsonl"
        clusters_path.write_text(
            clusters_path.read_text(encoding="utf-8") + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(
            FusionEvaluationError,
            "hash changed|input hash changed",
        ):
            evaluate_fusion(
                self.pack,
                self.fusion,
                self.profiles,
                self.config,
                self.calibration,
                seal,
                self.root / "tampered-cluster-evaluation",
            )

    def test_seal_recomputes_worker_route_instead_of_trusting_labels(self) -> None:
        profiles_payload = json.loads(self.profiles.read_text(encoding="utf-8"))
        first = profiles_payload["route_bindings"][0]
        second = profiles_payload["route_bindings"][1]
        first["label"], second["label"] = second["label"], first["label"]
        _write_json(self.profiles, profiles_payload)

        calibration_manifest_path = self.calibration.parent / "run_manifest.json"
        calibration_manifest = json.loads(calibration_manifest_path.read_text(encoding="utf-8"))
        profile_output = next(
            record
            for record in calibration_manifest["outputs"]
            if record["path"] == "profiles.json"
        )
        profile_output["sha256"] = sha256_file(self.profiles)
        profile_output["size_bytes"] = self.profiles.stat().st_size
        _write_json(calibration_manifest_path, calibration_manifest)

        fusion_manifest_path = self.fusion / "run_manifest.json"
        fusion_manifest = json.loads(fusion_manifest_path.read_text(encoding="utf-8"))
        fusion_manifest["source_profiles"]["sha256"] = sha256_file(self.profiles)
        fusion_manifest["source_profiles"]["size_bytes"] = self.profiles.stat().st_size
        _write_json(fusion_manifest_path, fusion_manifest)
        with self.assertRaisesRegex(
            FusionEvaluationError,
            "worker route differs",
        ):
            self._seal()

    def test_evaluation_writes_required_outputs_and_fixed_ablations(self) -> None:
        seal = self._seal()
        seal_payload = json.loads(seal.read_text(encoding="utf-8"))["freeze_payload"]
        self.assertEqual(
            seal_payload["evaluation_protocol"]["schema"],
            "amt-fusion-blind-evaluation-protocol/v1",
        )
        self.assertIn(
            "scripts/evaluate_fusion.py",
            seal_payload["scoring_source_sha256"],
        )
        with self.assertRaisesRegex(
            FusionEvaluationError,
            "seal is invalid|input hash changed",
        ):
            evaluate_fusion(
                self.pack,
                self.fusion,
                self.profiles,
                self.config,
                self.calibration,
                seal,
                self.root / "unsealed-config-evaluation",
                config=EvaluationConfig(onset_tolerance_sec=0.06),
            )
        output = self.root / "blind-evaluation"
        report = evaluate_fusion(
            self.pack,
            self.fusion,
            self.profiles,
            self.config,
            self.calibration,
            seal,
            output,
        )
        self.assertEqual(
            report["tasks"]["multi_track"]["status"],
            "unavailable_no_sealed_multitrack_reference",
        )
        self.assertFalse(report["claims"]["manual_correction_time_measured"])
        self.assertEqual(
            report["claims"]["task007_acceptance"],
            "inconclusive_manual_correction_time_unavailable",
        )
        self.assertIsNone(report["claims"]["task007_acceptance_passed"])
        for name in (
            "evaluation_report.json",
            "metrics_by_track.csv",
            "precision_coverage.csv",
            "error_taxonomy.csv",
            "correction_time.csv",
            "ablation.csv",
            "run_manifest.json",
        ):
            self.assertTrue((output / name).is_file(), name)
        with (output / "ablation.csv").open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            ablations = list(csv.DictReader(handle))
        self.assertEqual(len(ablations), 1 + 3 + 8)
        with (output / "precision_coverage.csv").open(
            "r",
            encoding="utf-8",
            newline="",
        ) as handle:
            coverage = list(csv.DictReader(handle))
        numeric = [row for row in coverage if row["status"] == "available_calibrated_confidence"]
        self.assertTrue(numeric)
        self.assertEqual({row["system"] for row in numeric}, {"fusion"})
        self.assertEqual(
            {row["estimates_total"] for row in numeric},
            {"3"},
        )
        ablation_statuses = {
            row["status"]
            for row in coverage
            if row["system_kind"] in {"worker_removal", "feature_weight_removal"}
        }
        self.assertEqual(
            ablation_statuses,
            {"unavailable_ablation_changes_feature_model"},
        )
        correction_text = (output / "correction_time.csv").read_text(encoding="utf-8")
        self.assertIn("unavailable_not_measured", correction_text)
        with self.assertRaisesRegex(FusionEvaluationError, "already exists"):
            evaluate_fusion(
                self.pack,
                self.fusion,
                self.profiles,
                self.config,
                self.calibration,
                seal,
                output,
            )


class FusionPrimaryMetricRuleTests(unittest.TestCase):
    @staticmethod
    def _score(
        system: str,
        onset_pitch_f1: float,
        onset_pitch_offset_f1: float,
    ) -> dict[str, object]:
        return {
            "system": system,
            "macro_amax": {
                "onset_pitch": {"f1": onset_pitch_f1},
                "onset_pitch_offset": {"f1": onset_pitch_offset_f1},
            },
        }

    def test_each_primary_metric_uses_its_own_strongest_baseline(self) -> None:
        baselines = [
            self._score("pitch-best", 0.90, 0.60),
            self._score("offset-best", 0.80, 0.95),
        ]
        equal_envelope = _primary_metric_comparison(
            baselines,
            self._score("fusion", 0.90, 0.95),
        )
        self.assertEqual(
            equal_envelope["strongest_baseline_by_metric"]["onset_pitch"]["system"],
            "pitch-best",
        )
        self.assertEqual(
            equal_envelope["strongest_baseline_by_metric"]["onset_pitch_offset"]["system"],
            "offset-best",
        )
        self.assertFalse(equal_envelope["primary_metric_rule_passed"])
        self.assertEqual(
            equal_envelope["task_acceptance"],
            "inconclusive_manual_correction_time_unavailable",
        )

        improved = _primary_metric_comparison(
            baselines,
            self._score("fusion", 0.91, 0.95),
        )
        self.assertTrue(improved["primary_metric_rule_passed"])
        self.assertIsNone(improved["task_acceptance_passed"])


if __name__ == "__main__":
    unittest.main()
