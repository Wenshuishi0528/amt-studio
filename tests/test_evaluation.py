from __future__ import annotations

import math
import unittest

from amt_core.evaluation import (
    CORRECTION_SESSION_SCHEMA,
    EvaluationConfig,
    EvaluationError,
    ReferenceNote,
    evaluate_melody_frames,
    evaluate_notes,
    evaluate_timed_events,
    project_note_events_to_melody_frames,
    summarize_correction_session,
)
from amt_core.events import NoteEvent


def _reference(
    identifier: str,
    *,
    onset: float,
    offset: float,
    pitch: float,
    confidence: float = 1.0,
    ambiguity: tuple[str, ...] = (),
    offset_censored: bool = False,
) -> ReferenceNote:
    return ReferenceNote(
        reference_note_id=identifier,
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        instrument="voice",
        annotator_confidence=confidence,
        ambiguity_tags=ambiguity,
        offset_censored=offset_censored,
    )


def _estimate(
    identifier: str,
    *,
    onset: float,
    offset: float,
    pitch: float,
    confidence: float | None = None,
    instrument: str = "voice",
) -> NoteEvent:
    return NoteEvent(
        event_id=identifier,
        track_id="candidate",
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        source_run_id="fixture-run",
        source_model="fixture-model",
        instrument=instrument,
        confidence=confidence,
    )


class EvaluationTests(unittest.TestCase):
    def test_note_metrics_separate_offset_octave_and_instrument_errors(self) -> None:
        references = [
            _reference("r1", onset=1.0, offset=2.0, pitch=60),
            _reference("r2", onset=3.0, offset=4.0, pitch=64),
        ]
        estimates = [
            _estimate(
                "e1",
                onset=1.01,
                offset=2.3,
                pitch=72,
                confidence=0.9,
            ),
            _estimate(
                "e2",
                onset=3.02,
                offset=4.02,
                pitch=64,
                confidence=0.4,
                instrument="guitar",
            ),
        ]
        report = evaluate_notes(references, estimates)

        self.assertEqual(report["primary"]["onset_only"]["matches"], 2)
        self.assertEqual(report["primary"]["onset_pitch"]["matches"], 1)
        self.assertEqual(report["primary"]["onset_pitch_offset"]["matches"], 1)
        self.assertEqual(report["primary"]["onset_chroma"]["matches"], 2)
        self.assertEqual(report["primary"]["octave_error"]["errors"], 1)
        self.assertEqual(
            report["primary"]["instrument_assignment"],
            {"correct": 0, "eligible_matches": 1, "accuracy": 0.0},
        )
        threshold = next(
            row for row in report["confidence_coverage"] if row["threshold"] == 0.75
        )
        self.assertEqual(threshold["estimates_retained"], 1)
        self.assertEqual(threshold["estimate_retention"], 0.5)
        self.assertEqual(threshold["onset_pitch"]["recall"], 0.0)

    def test_boundary_tolerances_are_inclusive(self) -> None:
        reference = _reference("r1", onset=1.0, offset=2.0, pitch=60)
        estimate = _estimate(
            "e1",
            onset=1.05,
            offset=2.2,
            pitch=60.5,
        )
        report = evaluate_notes([reference], [estimate], EvaluationConfig())
        self.assertEqual(report["primary"]["onset_pitch_offset"]["matches"], 1)

        censored = _reference(
            "boundary",
            onset=3.0,
            offset=3.5,
            pitch=62,
            ambiguity=("phrase_boundary",),
            offset_censored=True,
        )
        sustained = _estimate(
            "boundary-estimate",
            onset=3.0,
            offset=8.0,
            pitch=62,
        )
        censored_report = evaluate_notes([censored], [sustained])
        self.assertEqual(
            censored_report["primary"]["onset_pitch_offset"]["matches"],
            1,
        )
        self.assertEqual(
            censored_report["primary"]["offset_censored_reference_count"],
            1,
        )

    def test_ambiguity_and_annotator_confidence_define_secondary_subset(self) -> None:
        references = [
            _reference("clear", onset=1, offset=2, pitch=60),
            _reference(
                "ambiguous",
                onset=3,
                offset=4,
                pitch=62,
                ambiguity=("weak_audibility",),
            ),
            _reference("low", onset=5, offset=6, pitch=64, confidence=0.5),
        ]
        report = evaluate_notes(references, [])
        self.assertEqual(report["reference_summary"]["included"], 3)
        self.assertEqual(report["reference_summary"]["high_agreement"], 1)
        self.assertEqual(
            report["reference_summary"]["ambiguity_tag_counts"],
            {"weak_audibility": 1},
        )

        estimates = [
            _estimate("clear-estimate", onset=1, offset=2, pitch=60),
            _estimate("ambiguous-estimate", onset=3, offset=4, pitch=62),
            _estimate("low-estimate", onset=5, offset=6, pitch=64),
        ]
        secondary = evaluate_notes(references, estimates)["high_agreement_secondary"][
            "onset_pitch"
        ]
        self.assertEqual(secondary["matches"], 1)
        self.assertEqual(secondary["estimate_count"], 1)
        self.assertEqual(secondary["precision"], 1)

    def test_pair_dependent_metrics_use_global_minimum_cost_matching(self) -> None:
        references = [
            _reference("c4", onset=1, offset=2, pitch=60),
            _reference("c5", onset=1, offset=2, pitch=72),
        ]
        estimates = [
            _estimate("c4", onset=1, offset=2, pitch=60),
            _estimate("c6", onset=1, offset=2, pitch=84),
        ]
        report = evaluate_notes(references, estimates)
        self.assertEqual(report["primary"]["onset_chroma"]["matches"], 2)
        self.assertEqual(report["primary"]["octave_error"]["errors"], 1)

    def test_reference_validation_rejects_unexplained_exclusion(self) -> None:
        with self.assertRaisesRegex(EvaluationError, "exclusion_reason"):
            ReferenceNote(
                reference_note_id="bad",
                onset_sec=1,
                offset_sec=2,
                pitch_midi=60,
                instrument="voice",
                annotator_confidence=1,
                evaluation_status="exclude",
            ).validate()

    def test_timed_event_metric_uses_seventy_millisecond_default(self) -> None:
        report = evaluate_timed_events(
            [1.0, 2.0, 3.0],
            [1.07, 2.08, 3.0, 4.0],
        )
        self.assertEqual(report["matches"], 2)
        self.assertEqual(report["tolerance_sec"], 0.07)
        self.assertAlmostEqual(report["precision"], 0.5)
        self.assertAlmostEqual(report["recall"], 2 / 3)

    def test_melody_frame_metrics_separate_voicing_pitch_and_octave(self) -> None:
        report = evaluate_melody_frames(
            [0.0, 440.0, 440.0, 440.0],
            [220.0, 440.0, 880.0, 0.0],
        )
        self.assertEqual(report["reference_voiced_count"], 3)
        self.assertEqual(report["voicing_false_positive_count"], 1)
        self.assertEqual(report["pitch_correct_count"], 1)
        self.assertEqual(report["chroma_correct_count"], 2)
        self.assertEqual(report["voicing_recall"], 2 / 3)
        self.assertEqual(report["voicing_false_alarm"], 1.0)
        self.assertEqual(report["raw_pitch_accuracy"], 1 / 3)
        self.assertEqual(report["raw_chroma_accuracy"], 2 / 3)
        self.assertEqual(report["overall_accuracy"], 0.25)
        self.assertEqual(
            report["median_absolute_pitch_error_cents_both_voiced"],
            600.0,
        )

    def test_melody_frame_metrics_use_inclusive_tolerance_and_null_denominators(
        self,
    ) -> None:
        exact_boundary = 440.0 * 2 ** (50.0 / 1200.0)
        boundary = evaluate_melody_frames([440.0], [exact_boundary])
        self.assertEqual(boundary["raw_pitch_accuracy"], 1.0)
        self.assertIsNone(boundary["voicing_false_alarm"])

        unvoiced = evaluate_melody_frames([0.0, 0.0], [0.0, 440.0])
        self.assertIsNone(unvoiced["voicing_recall"])
        self.assertIsNone(unvoiced["raw_pitch_accuracy"])
        self.assertEqual(unvoiced["voicing_false_alarm"], 0.5)
        self.assertEqual(unvoiced["overall_accuracy"], 0.5)

    def test_melody_frame_metrics_reject_invalid_sequences(self) -> None:
        with self.assertRaisesRegex(EvaluationError, "must not be empty"):
            evaluate_melody_frames([], [])
        with self.assertRaisesRegex(EvaluationError, "equal length"):
            evaluate_melody_frames([440.0], [])
        with self.assertRaisesRegex(EvaluationError, "at least 0"):
            evaluate_melody_frames([440.0], [-1.0])

    def test_note_events_project_to_fixed_voice_topline(self) -> None:
        events = [
            _estimate("low", onset=0.0, offset=1.0, pitch=60),
            _estimate("high-old", onset=0.0, offset=0.75, pitch=67),
            _estimate("high-new", onset=0.25, offset=0.5, pitch=67),
            _estimate(
                "guitar",
                onset=0.0,
                offset=1.0,
                pitch=80,
                instrument="guitar",
            ),
        ]
        frequencies, diagnostics = project_note_events_to_melody_frames(
            events,
            [0.0, 0.25, 0.5, 0.75, 1.0],
        )
        midi = [
            None if frequency == 0 else round(69 + 12 * math.log2(frequency / 440))
            for frequency in frequencies
        ]
        self.assertEqual(midi, [67, 67, 67, 60, None])
        self.assertEqual(diagnostics["eligible_event_count"], 3)
        self.assertEqual(diagnostics["excluded_event_count"], 1)
        self.assertEqual(diagnostics["overlap_frame_count"], 3)
        self.assertEqual(diagnostics["maximum_active_event_count"], 3)

    def test_note_event_projection_rejects_unsorted_frames_and_duplicate_ids(self) -> None:
        with self.assertRaisesRegex(EvaluationError, "strictly increasing"):
            project_note_events_to_melody_frames([], [0.5, 0.5])
        duplicate = [
            _estimate("same", onset=0, offset=1, pitch=60),
            _estimate("same", onset=0, offset=1, pitch=61),
        ]
        with self.assertRaisesRegex(EvaluationError, "duplicate event_id"):
            project_note_events_to_melody_frames(duplicate, [0.0])

    def test_correction_effort_is_auditable_and_normalized(self) -> None:
        summary = summarize_correction_session(
            {
                "schema": CORRECTION_SESSION_SCHEMA,
                "session_id": "session-1",
                "benchmark_freeze_sha256": "a" * 64,
                "excerpt_id": "excerpt-1",
                "candidate_sha256": "b" * 64,
                "audio_duration_sec": 30,
                "total_edit_time_sec": 90,
                "review_granularity": "note_level_edit",
                "operations": [
                    {
                        "operation_id": "op-1",
                        "action": "pitch",
                        "elapsed_edit_sec": 10,
                        "source_note_ids": ["candidate-1"],
                        "result_note_ids": ["reference-1"],
                    },
                    {
                        "operation_id": "op-2",
                        "action": "add",
                        "elapsed_edit_sec": 5,
                        "source_note_ids": [],
                        "result_note_ids": ["reference-2"],
                    },
                ],
            }
        )
        self.assertEqual(summary["operation_count"], 2)
        self.assertEqual(summary["corrections_per_minute_audio"], 4)
        self.assertEqual(summary["edit_seconds_per_minute_audio"], 180)
        self.assertEqual(summary["unattributed_review_time_sec"], 75)
        self.assertEqual(summary["audio_duration_sec"], 30)

        with self.assertRaisesRegex(EvaluationError, "review_granularity"):
            summarize_correction_session(
                {
                    "schema": CORRECTION_SESSION_SCHEMA,
                    "session_id": "session-missing-review",
                    "benchmark_freeze_sha256": "a" * 64,
                    "excerpt_id": "excerpt-1",
                    "candidate_sha256": "b" * 64,
                    "audio_duration_sec": 30,
                    "total_edit_time_sec": 0,
                    "operations": [],
                }
            )

        with self.assertRaisesRegex(EvaluationError, "and decision"):
            summarize_correction_session(
                {
                    "schema": CORRECTION_SESSION_SCHEMA,
                    "session_id": "session-no-decision",
                    "benchmark_freeze_sha256": "a" * 64,
                    "excerpt_id": "excerpt-1",
                    "candidate_sha256": "b" * 64,
                    "audio_duration_sec": 12,
                    "total_edit_time_sec": 12,
                    "review_granularity": "whole_excerpt_aural_comparison",
                    "full_playback_count": 1,
                    "additional_review_sec": 0,
                    "operations": [],
                }
            )
        with self.assertRaisesRegex(EvaluationError, "at least one logged operation"):
            summarize_correction_session(
                {
                    "schema": CORRECTION_SESSION_SCHEMA,
                    "session_id": "session-empty-note-review",
                    "benchmark_freeze_sha256": "a" * 64,
                    "excerpt_id": "excerpt-1",
                    "candidate_sha256": "b" * 64,
                    "audio_duration_sec": 30,
                    "total_edit_time_sec": 1,
                    "review_granularity": "note_level_edit",
                    "operations": [],
                }
            )

    def test_confidence_threshold_rows_are_absent_when_confidence_is_unavailable(
        self,
    ) -> None:
        report = evaluate_notes(
            [_reference("reference", onset=1, offset=2, pitch=60)],
            [_estimate("estimate", onset=1, offset=2, pitch=60)],
        )
        self.assertEqual(
            report["confidence_coverage_status"],
            "unavailable_no_candidate_confidence",
        )
        self.assertEqual(report["confidence_coverage"], [])

    def test_whole_excerpt_review_time_must_cover_playbacks(self) -> None:
        with self.assertRaisesRegex(
            EvaluationError,
            "does not account for declared full playbacks",
        ):
            summarize_correction_session(
                {
                    "schema": CORRECTION_SESSION_SCHEMA,
                    "session_id": "session-2",
                    "benchmark_freeze_sha256": "a" * 64,
                    "excerpt_id": "excerpt-1",
                    "candidate_sha256": "b" * 64,
                    "audio_duration_sec": 12,
                    "total_edit_time_sec": 0,
                    "review_granularity": "whole_excerpt_aural_comparison",
                    "full_playback_count": 3,
                    "additional_review_sec": 7,
                    "decision": "accept_seed",
                    "operations": [],
                }
            )


if __name__ == "__main__":
    unittest.main()
