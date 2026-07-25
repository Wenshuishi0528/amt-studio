from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_melody_contour import (
    MelodyContourEvaluationError,
    _portable_candidate_events_path,
    _verify_project_reference_binding,
    evaluate_contour_candidate,
    read_melody_contour_csv,
)

from amt_core.events import NoteEvent


def _event(identifier: str, onset: float, offset: float, pitch: float) -> NoteEvent:
    return NoteEvent(
        event_id=identifier,
        track_id="voice",
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        source_run_id="fixture",
        source_model="fixture",
        instrument="voice",
    )


class MelodyContourEvaluationTests(unittest.TestCase):
    def test_reads_headerless_contour_and_rejects_nonmonotonic_time(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            valid = Path(directory) / "valid.csv"
            valid.write_text("0.0,0.0\n0.01,440.0\n", encoding="utf-8")
            self.assertEqual(
                read_melody_contour_csv(valid),
                ([0.0, 0.01], [0.0, 440.0]),
            )

            invalid = Path(directory) / "invalid.csv"
            invalid.write_text("0.01,440\n0.01,220\n", encoding="utf-8")
            with self.assertRaisesRegex(
                MelodyContourEvaluationError,
                "strictly increasing",
            ):
                read_melody_contour_csv(invalid)

    def test_candidate_report_uses_only_frozen_excerpt_frames(self) -> None:
        a4 = 440.0
        c5 = 440.0 * 2 ** (3 / 12)
        groups = [
            (
                {
                    "excerpt_id": "blind-01",
                    "evaluation_start_sec": 0.0,
                    "evaluation_end_sec": 1.0,
                },
                [0.0, 0.5],
                [a4, a4],
            ),
            (
                {
                    "excerpt_id": "blind-02",
                    "evaluation_start_sec": 2.0,
                    "evaluation_end_sec": 3.0,
                },
                [2.0, 2.5],
                [0.0, c5],
            ),
        ]
        report = evaluate_contour_candidate(
            [
                _event("a4", 0.0, 1.0, 69),
                _event("c5", 2.5, 3.0, 72),
            ],
            groups,
            instrument="voice",
            cent_tolerance=50,
        )
        metrics = report["aggregate_frame_metrics"]
        self.assertTrue(math.isclose(metrics["overall_accuracy"], 1.0))
        self.assertTrue(math.isclose(metrics["raw_pitch_accuracy"], 1.0))
        self.assertEqual(len(report["per_excerpt"]), 2)

    def test_external_reference_binds_to_project_source_and_canonical_mix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "project"
            pack = project / "annotations" / "pack"
            pack.mkdir(parents=True)
            (project / "manifest.json").write_text(
                """
                {
                  "schema_version": 1,
                  "project_id": "fixture-project",
                  "source": {"sha256": "source-hash"},
                  "canonical_audio": {"sha256": "canonical-hash"}
                }
                """,
                encoding="utf-8",
            )
            payload = {
                "project_id": "fixture-project",
                "canonical_audio_sha256": "canonical-hash",
            }
            tracks = [
                {
                    "role": "blind_test_vocal_melody",
                    "melody1_sha256": "reference-hash",
                    "mix_sha256": "source-hash",
                }
            ]
            _verify_project_reference_binding(
                pack,
                payload,
                tracks,
                {},
                reference_sha256="reference-hash",
            )
            tracks[0]["mix_sha256"] = "another-source"
            with self.assertRaisesRegex(
                MelodyContourEvaluationError,
                "not bound",
            ):
                _verify_project_reference_binding(
                    pack,
                    payload,
                    tracks,
                    {},
                    reference_sha256="reference-hash",
                )

            tracks[:] = [
                {
                    "role": "blind_test_vocal_melody",
                    "melody1_sha256": "reference-hash",
                    "mix_sha256": "another-source",
                },
                {
                    "role": "blind_test_vocal_melody",
                    "melody1_sha256": "another-reference",
                    "mix_sha256": "source-hash",
                },
            ]
            with self.assertRaisesRegex(
                MelodyContourEvaluationError,
                "not bound",
            ):
                _verify_project_reference_binding(
                    pack,
                    payload,
                    tracks,
                    {},
                    reference_sha256="reference-hash",
                )

    def test_sealed_candidate_path_relocates_by_verified_run_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "local-project"
            pack = project / "annotations" / "pack"
            pack.mkdir(parents=True)
            path = _portable_candidate_events_path(
                pack,
                {
                    "run_id": "candidate-run",
                    "events_path": (
                        "/remote/project/runs/candidate-run/normalized/events.jsonl"
                    ),
                },
            )
            self.assertEqual(
                path,
                project / "runs" / "candidate-run" / "normalized" / "events.jsonl",
            )
            with self.assertRaisesRegex(
                MelodyContourEvaluationError,
                "standard worker output",
            ):
                _portable_candidate_events_path(
                    pack,
                    {
                        "run_id": "candidate-run",
                        "events_path": "/remote/project/other/events.jsonl",
                    },
                )


if __name__ == "__main__":
    unittest.main()
