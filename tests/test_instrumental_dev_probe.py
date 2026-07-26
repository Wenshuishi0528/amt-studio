from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.assess_instrumental_dev_probe import (
    InstrumentalProbeAssessmentError,
    assess_report,
)

from amt_core.benchmark import canonical_json_sha256
from amt_core.utils import sha256_file


def _artifact(path: Path) -> dict[str, object]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _write_evidence(
    root: Path,
    *,
    raw_pitch: float,
    overall: float,
    false_alarm: float,
    cent_tolerance: float = 50.0,
) -> tuple[Path, Path, Path]:
    project = root / "project"
    pack = (
        project
        / "annotations"
        / "reference-task007c-phoenix-development-v1"
    )
    pack.mkdir(parents=True)
    run_id = "basic-pitch-task007c-phoenix-direct-v1"
    run_dir = project / "runs" / run_id
    events = run_dir / "normalized" / "events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text('{"fixture":true}\n', encoding="utf-8")
    candidate_manifest = run_dir / "run_manifest.json"
    candidate_manifest.write_text('{"fixture":"candidate"}\n', encoding="utf-8")

    benchmark_payload = {
        "schema": "amt-benchmark-manifest/v1",
        "benchmark_id": "medleydb-phoenix-task007c-development-v1",
        "project_id": "medleydb-phoenix-scotch-morris",
        "split": "development",
        "canonical_audio_sha256": "a" * 64,
        "excerpts": [{"excerpt_id": "dev-01"}],
    }
    benchmark = {
        "schema": "amt-benchmark-pack/v1",
        "freeze_payload": benchmark_payload,
        "benchmark_freeze_sha256": canonical_json_sha256(benchmark_payload),
    }
    benchmark_path = pack / "benchmark_manifest.json"
    benchmark_path.write_text(json.dumps(benchmark), encoding="utf-8")

    seal_payload = {
        "schema": "amt-evaluation-candidate-set/v1",
        "split": "development",
        "benchmark_freeze_sha256": benchmark["benchmark_freeze_sha256"],
        "confirmation": {
            "candidate_output_quality_uninspected_before_freeze": True,
            "candidate_selection_or_tuning_after_freeze_prohibited": False,
        },
        "candidates": [
            {
                "label": "basic-pitch-direct-mix",
                "worker": "basic_pitch",
                "run_id": run_id,
                "events_sha256": sha256_file(events),
                "run_manifest_sha256": sha256_file(candidate_manifest),
            }
        ],
    }
    seal = {
        "schema": "amt-evaluation-candidate-set-seal/v1",
        "freeze_payload": seal_payload,
        "candidate_set_sha256": canonical_json_sha256(seal_payload),
    }
    seal_path = pack / "candidate_set_seal.json"
    seal_path.write_text(json.dumps(seal), encoding="utf-8")

    report_dir = project / "reports" / "instrumental-development-task007c-v1"
    report_dir.mkdir(parents=True)
    report = {
        "schema": "amt-external-melody-contour-evaluation/v1",
        "benchmark": {
            "benchmark_id": "medleydb-phoenix-task007c-development-v1",
            "project_id": "medleydb-phoenix-scotch-morris",
            "split": "development",
            "benchmark_freeze_sha256": benchmark["benchmark_freeze_sha256"],
            "candidate_set_sha256": seal["candidate_set_sha256"],
            "candidate_output_quality_uninspected_before_freeze": True,
        },
        "reference": {
            "sha256": (
                "c1cb36655177b353e81d11778b755d92263e4f6b53070659c4d1e3dd8b34f508"
            ),
        },
        "policy": {
            "reference_role": "development_instrumental_melody",
            "instrument_filter": "other",
            "projection_rule": (
                "highest_pitch_then_latest_onset_then_lexical_event_id"
            ),
            "cent_tolerance": cent_tolerance,
            "candidate_selection_after_scoring_prohibited": False,
            "owner_listening_percentages_used_as_formal_accuracy": False,
        },
        "candidates": [
            {
                "label": "basic-pitch-direct-mix",
                "worker": "basic_pitch",
                "run_id": run_id,
                "events_sha256": sha256_file(events),
                "aggregate_frame_metrics": {
                    "cent_tolerance": cent_tolerance,
                    "raw_pitch_accuracy": raw_pitch,
                    "overall_accuracy": overall,
                    "voicing_false_alarm": false_alarm,
                },
                "aggregate_projection": {
                    "instrument_filter": "other",
                    "overlap_rule": (
                        "highest_pitch_then_latest_onset_then_lexical_event_id"
                    ),
                },
            }
        ],
    }
    report_path = report_dir / "report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    run_manifest = {
        "schema": "amt-external-melody-contour-evaluation-run/v1",
        "status": "succeeded",
        "project_id": "medleydb-phoenix-scotch-morris",
        "configuration": {
            "cent_tolerance": cent_tolerance,
            "instrument_filter": "other",
            "projection_rule": (
                "highest_pitch_then_latest_onset_then_lexical_event_id"
            ),
            "reference_role": "development_instrumental_melody",
        },
        "benchmark": report["benchmark"],
        "reference": report["reference"],
        "inputs": [
            _artifact(benchmark_path),
            _artifact(seal_path),
            _artifact(events),
            _artifact(candidate_manifest),
        ],
        "outputs": [
            {
                "path": "report.json",
                "sha256": sha256_file(report_path),
                "size_bytes": report_path.stat().st_size,
            }
        ],
    }
    run_manifest_path = report_dir / "run_manifest.json"
    run_manifest_path.write_text(json.dumps(run_manifest), encoding="utf-8")
    return pack, report_path, run_manifest_path


class InstrumentalDevelopmentProbeTests(unittest.TestCase):
    def test_all_frozen_thresholds_must_pass(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack, report, run_manifest = _write_evidence(
                root,
                raw_pitch=0.70,
                overall=0.71,
                false_alarm=0.25,
            )
            decision = assess_report(
                report,
                root / "decision.json",
                pack_dir=pack,
                run_manifest_path=run_manifest,
            )

        self.assertTrue(decision["all_conditions_passed"])
        self.assertEqual(
            decision["decision"],
            "advance_to_new_artist_disjoint_instrumental_blind",
        )
        self.assertFalse(decision["scope"]["gate4_passed"])
        self.assertFalse(decision["scope"]["phoenix_is_blind"])
        self.assertIn("candidate_set_seal", decision["verified_evidence"])

    def test_one_failure_rejects_without_authorizing_retuning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack, report, run_manifest = _write_evidence(
                root,
                raw_pitch=0.69,
                overall=0.90,
                false_alarm=0.10,
            )
            decision = assess_report(
                report,
                root / "decision.json",
                pack_dir=pack,
                run_manifest_path=run_manifest,
            )

        self.assertFalse(decision["all_conditions_passed"])
        self.assertEqual(
            decision["decision"],
            "reject_direct_mix_instrumental_route_for_v1",
        )
        self.assertFalse(decision["scope"]["phoenix_retuning_authorized"])
        self.assertFalse(decision["scope"]["task009b2b_authorized"])

    def test_nonfrozen_tolerance_is_rejected_even_with_matching_run_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack, report, run_manifest = _write_evidence(
                root,
                raw_pitch=1.0,
                overall=1.0,
                false_alarm=0.0,
                cent_tolerance=1200.0,
            )
            with self.assertRaisesRegex(
                InstrumentalProbeAssessmentError,
                "frozen policy",
            ):
                assess_report(
                    report,
                    root / "decision.json",
                    pack_dir=pack,
                    run_manifest_path=run_manifest,
                )

    def test_report_cannot_substitute_benchmark_or_candidate_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack, report_path, run_manifest_path = _write_evidence(
                root,
                raw_pitch=0.9,
                overall=0.9,
                false_alarm=0.1,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["benchmark"]["candidate_set_sha256"] = "f" * 64
            report_path.write_text(json.dumps(report), encoding="utf-8")
            run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
            run_manifest["benchmark"] = report["benchmark"]
            run_manifest["outputs"][0]["sha256"] = sha256_file(report_path)
            run_manifest["outputs"][0]["size_bytes"] = report_path.stat().st_size
            run_manifest_path.write_text(json.dumps(run_manifest), encoding="utf-8")
            with self.assertRaisesRegex(
                InstrumentalProbeAssessmentError,
                "frozen benchmark",
            ):
                assess_report(
                    report_path,
                    root / "decision.json",
                    pack_dir=pack,
                    run_manifest_path=run_manifest_path,
                )


if __name__ == "__main__":
    unittest.main()
