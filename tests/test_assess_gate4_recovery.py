from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.assess_gate4_recovery import (
    Gate4RecoveryAssessmentError,
    assess,
)


def _report(onset_pitch_delta: float, offset_delta: float) -> dict[str, object]:
    return {
        "schema": "amt-fusion-blind-evaluation/v1",
        "claims": {
            "blind_fusion_seal_verified": True,
            "candidate_preinspection_seal_verified": True,
            "development_only_calibration_verified": True,
            "blind_retuning_performed": False,
            "manual_correction_time_measured": False,
        },
        "tasks": {
            "main_melody": {
                "comparison": {
                    "strongest_baseline_by_metric": {
                        "onset_pitch": {"delta": onset_pitch_delta},
                        "onset_pitch_offset": {"delta": offset_delta},
                    }
                }
            }
        },
        "ablations": [
            {
                "variant_type": "worker_removal",
                "removed_component": "game-vocal-a",
            },
            {
                "variant_type": "worker_removal",
                "removed_component": "basic-pitch-vocal-a",
            },
        ],
    }


class AssessGate4RecoveryTests(unittest.TestCase):
    def test_pass_requires_improvement_and_offset_guard(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.json"
            output = root / "decision.json"
            report.write_text(json.dumps(_report(0.01, -0.01)), encoding="utf-8")

            decision = assess(report, output)

            self.assertTrue(decision["automatic_precondition_passed"])
            self.assertFalse(decision["gate4_passed"])
            self.assertEqual(
                decision["decision"],
                "eligible_for_matched_human_correction",
            )

    def test_failed_metric_is_a_valid_rejection_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            report = root / "report.json"
            output = root / "decision.json"
            report.write_text(json.dumps(_report(0.009, 0.2)), encoding="utf-8")

            decision = assess(report, output)

            self.assertFalse(decision["automatic_precondition_passed"])
            self.assertEqual(decision["decision"], "reject_v2_without_blind_retuning")

    def test_rejects_missing_worker_ablation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = _report(0.02, 0.0)
            payload["ablations"] = payload["ablations"][:1]  # type: ignore[index]
            report = root / "report.json"
            report.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(
                Gate4RecoveryAssessmentError,
                "worker ablations",
            ):
                assess(report, root / "decision.json")
