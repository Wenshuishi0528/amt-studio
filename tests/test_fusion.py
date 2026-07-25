from __future__ import annotations

import unittest

from amt_core.events import NoteEvent
from amt_core.fusion import (
    CalibrationProvenance,
    FusionConfig,
    FusionError,
    SourceProfile,
    fit_isotonic_calibrator,
    fuse_main_melody,
    fusion_feature_model_sha256,
)


def _event(
    source: str,
    identifier: str,
    onset: float,
    offset: float,
    pitch: float,
    *,
    instrument: str = "voice",
) -> NoteEvent:
    return NoteEvent(
        event_id=identifier,
        track_id=f"{source}:voice",
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        source_run_id=f"{source}-run",
        source_model=f"{source}-model",
        instrument=instrument,
        is_main_melody_candidate=True,
    )


def _profiles() -> dict[str, SourceProfile]:
    return {
        "a": SourceProfile("a", 0.9, 1.0, 1.0),
        "b": SourceProfile("b", 0.8, 1.0, 1.0),
        "c": SourceProfile("c", 0.5, 0.6, 1.0),
    }


def _provenance(
    *,
    split: str = "development",
    feature_model_sha256: str = "d" * 64,
) -> CalibrationProvenance:
    return CalibrationProvenance(
        calibration_id="fixture-calibration",
        split=split,
        benchmark_sha256="a" * 64,
        candidate_sha256=("b" * 64, "c" * 64),
        feature_model_sha256=feature_model_sha256,
    )


class FusionTests(unittest.TestCase):
    def test_clusters_agreeing_sources_and_preserves_every_candidate(self) -> None:
        candidates = {
            "a": [
                _event("a", "a1", 1.00, 1.50, 60.0),
                _event("a", "a2", 2.00, 2.40, 62.0),
            ],
            "b": [
                _event("b", "b1", 1.03, 1.48, 60.2),
                _event("b", "b2", 2.02, 2.42, 62.1),
            ],
            "c": [_event("c", "c1", 1.01, 1.47, 60.1)],
        }
        result = fuse_main_melody(
            candidates,
            _profiles(),
            fusion_run_id="fusion-fixture",
            config=FusionConfig(minimum_raw_score=0.0),
        )

        self.assertEqual(len(result.clusters), 2)
        self.assertEqual(len(result.final_events), 2)
        self.assertEqual(result.manifest["input_event_count"], 5)
        self.assertTrue(result.manifest["all_eligible_candidates_preserved"])
        self.assertTrue(result.manifest["final_note_provenance_complete"])
        self.assertEqual(len(result.final_events[0].source_event_ids), 3)
        represented = {
            event_id for cluster in result.clusters for event_id in cluster["source_event_ids"]
        }
        self.assertEqual(len(represented), 5)

    def test_same_source_events_never_self_agree(self) -> None:
        candidates = {
            "a": [
                _event("a", "a1", 1.00, 1.50, 60.0),
                _event("a", "a2", 1.02, 1.48, 60.1),
            ],
            "b": [],
            "c": [],
        }
        result = fuse_main_melody(
            candidates,
            _profiles(),
            fusion_run_id="fusion-no-self-agreement",
            config=FusionConfig(minimum_raw_score=0.0),
        )
        self.assertEqual(len(result.clusters), 2)

    def test_rejected_competing_pitch_retains_reason_and_source_ids(self) -> None:
        candidates = {
            "a": [_event("a", "a-high", 1.00, 1.50, 72.0)],
            "b": [_event("b", "b-low", 1.01, 1.50, 60.0)],
            "c": [_event("c", "c-low", 1.02, 1.48, 60.1)],
        }
        result = fuse_main_melody(
            candidates,
            _profiles(),
            fusion_run_id="fusion-competition",
            config=FusionConfig(minimum_raw_score=0.0),
        )
        self.assertEqual(len(result.final_events), 1)
        self.assertAlmostEqual(result.final_events[0].pitch_midi, 60.0)
        self.assertEqual(len(result.rejected), 1)
        self.assertTrue(result.rejected[0]["reason"].startswith("competing_onset"))
        self.assertEqual(
            result.rejected[0]["source_event_ids"],
            ["a:a-high"],
        )

    def test_offset_overlap_is_clipped_without_hiding_original_cluster(self) -> None:
        candidates = {
            "a": [
                _event("a", "a1", 1.0, 2.0, 60),
                _event("a", "a2", 1.5, 2.2, 62),
            ],
            "b": [
                _event("b", "b1", 1.0, 2.0, 60),
                _event("b", "b2", 1.5, 2.2, 62),
            ],
            "c": [],
        }
        result = fuse_main_melody(
            candidates,
            _profiles(),
            fusion_run_id="fusion-overlap",
            config=FusionConfig(minimum_raw_score=0.0),
        )
        self.assertEqual(len(result.final_events), 2)
        self.assertEqual(result.final_events[0].offset_sec, 1.5)
        self.assertIn(
            "offset-clipped-at-next-onset",
            result.final_events[0].tags,
        )
        first_cluster = result.final_events[0].extra["cluster_id"]
        cluster_record = next(
            record for record in result.clusters if record["cluster_id"] == first_cluster
        )
        self.assertEqual(cluster_record["offset_sec"], 2.0)

    def test_overlap_clipping_uses_next_surviving_note(self) -> None:
        candidates = {
            "a": [
                _event("a", "a1", 0.0, 2.0, 60),
                _event("a", "a2", 1.0, 1.02, 62),
                _event("a", "a3", 1.2, 1.6, 64),
            ],
            "b": [
                _event("b", "b1", 0.0, 2.0, 60),
                _event("b", "b2", 1.0, 1.02, 62),
                _event("b", "b3", 1.2, 1.6, 64),
            ],
            "c": [],
        }
        result = fuse_main_melody(
            candidates,
            _profiles(),
            fusion_run_id="fusion-survivor-clipping",
            config=FusionConfig(
                minimum_raw_score=0.0,
                minimum_final_duration_sec=0.04,
            ),
        )
        self.assertEqual(len(result.final_events), 2)
        self.assertEqual(result.final_events[0].offset_sec, 1.2)
        self.assertEqual(result.final_events[1].onset_sec, 1.2)
        self.assertTrue(
            any(
                record["reason"] == "overlap_would_create_too_short_final_note"
                for record in result.rejected
            )
        )

    def test_isotonic_calibration_is_monotonic_and_development_only(self) -> None:
        calibrator = fit_isotonic_calibrator(
            [0.1, 0.2, 0.3, 0.4, 0.8, 0.9],
            [False, True, False, True, True, True],
            _provenance(),
        )
        predictions = [calibrator.predict(value / 10) for value in range(11)]
        self.assertEqual(predictions, sorted(predictions))
        self.assertEqual(calibrator.sample_count, 6)
        self.assertEqual(calibrator.positive_count, 4)

        with self.assertRaisesRegex(FusionError, "development only"):
            fit_isotonic_calibrator(
                [0.5],
                [True],
                _provenance(split="blind_test"),
            )

    def test_calibrated_confidence_and_missing_beat_feature_are_explicit(self) -> None:
        profiles = _profiles()
        config = FusionConfig(minimum_raw_score=0.0)
        calibrator = fit_isotonic_calibrator(
            [0.0, 0.5, 1.0],
            [False, True, True],
            _provenance(
                feature_model_sha256=fusion_feature_model_sha256(
                    config,
                    profiles,
                )
            ),
        )
        result = fuse_main_melody(
            {
                "a": [_event("a", "a1", 1.0, 1.5, 60)],
                "b": [_event("b", "b1", 1.0, 1.5, 60)],
                "c": [],
            },
            profiles,
            fusion_run_id="fusion-calibrated",
            config=config,
            calibrator=calibrator,
        )
        self.assertIsNotNone(result.final_events[0].confidence)
        self.assertIsNone(result.final_events[0].extra["features"]["beat_phase"])
        self.assertEqual(
            result.manifest["missing_feature_policy"],
            "renormalize_available_feature_weights",
        )

    def test_feature_ablation_is_explicit_and_validated(self) -> None:
        config = FusionConfig().without_feature("register")
        self.assertEqual(config.feature_weights["register"], 0.0)
        with self.assertRaisesRegex(FusionError, "unknown feature"):
            config.without_feature("unknown")


if __name__ == "__main__":
    unittest.main()
