from __future__ import annotations

import unittest

from amt_core.events import NoteEvent
from amt_core.product_postprocess import (
    automatic_voice_candidate_admission,
    clean_trailing_fragments,
    residual_melody_gaps,
    soft_mask_melody_candidates,
)


def _event(
    event_id: str,
    *,
    onset: float,
    offset: float,
    pitch: float,
    instrument: str = "clean_electric_guitar",
) -> NoteEvent:
    return NoteEvent(
        event_id=event_id,
        track_id=f"native:{instrument}",
        instrument=instrument,
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        quantized_pitch_midi=round(pitch),
        velocity=80,
        confidence=None,
        is_main_melody_candidate=instrument == "voice",
        source_run_id="fixture-run",
        source_model="fixture-model",
        source_event_ids=[f"source:{event_id}"],
        tags=["fixture"],
        extra={},
    )


class ProductPostprocessTests(unittest.TestCase):
    def test_voice_candidate_admission_has_no_song_length_blind_cap(self) -> None:
        short_gap = automatic_voice_candidate_admission(
            source_note_count=322,
            candidate_note_count=16,
        )
        long_gap = automatic_voice_candidate_admission(
            source_note_count=338,
            candidate_note_count=841,
        )

        self.assertTrue(short_gap["accepted_for_automatic_merge"])
        self.assertTrue(long_gap["accepted_for_automatic_merge"])
        self.assertEqual(
            long_gap["decision"],
            "accepted_owner_selected_raw_generation",
        )
        self.assertEqual(long_gap["candidate_selection"], "raw_generated")
        self.assertFalse(long_gap["count_limit_applied"])
        self.assertNotIn("maximum_candidate_note_count", long_gap)
        self.assertTrue(long_gap["candidate_preserved_for_diagnosis"])

    def test_trailing_sustain_cleanup_is_derived_and_keeps_source_provenance(
        self,
    ) -> None:
        fragments = [
            _event(
                f"fragment-{index}",
                onset=8 + index * 0.25,
                offset=8.25 + index * 0.25,
                pitch=60,
            )
            for index in range(8)
        ]
        cleaned, report = clean_trailing_fragments(
            fragments,
            timeline_end=10,
            run_id="product-cleanup",
        )

        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0].onset_sec, 8)
        self.assertEqual(cleaned[0].offset_sec, 10)
        self.assertIn("automatic-sustain-cleanup", cleaned[0].tags)
        self.assertEqual(
            set(cleaned[0].source_event_ids),
            {
                *(event.event_id for event in fragments),
                *(source for event in fragments for source in event.source_event_ids),
            },
        )
        self.assertEqual(report["fragment_count"], 8)
        self.assertEqual(report["merged_note_count"], 1)
        self.assertFalse(report["source_overwritten"])
        self.assertEqual([event.event_id for event in fragments], [
            f"fragment-{index}" for index in range(8)
        ])

    def test_percussion_repeat_is_collapsed_to_one_short_hit_not_a_sustain(
        self,
    ) -> None:
        hits = [
            _event(
                f"hit-{index}",
                onset=8 + index * 0.25,
                offset=8.01 + index * 0.25,
                pitch=42,
                instrument="drums",
            )
            for index in range(8)
        ]

        cleaned, report = clean_trailing_fragments(
            hits,
            timeline_end=10,
            run_id="product-cleanup",
        )

        self.assertEqual(len(cleaned), 1)
        self.assertEqual(cleaned[0].onset_sec, hits[0].onset_sec)
        self.assertEqual(cleaned[0].offset_sec, hits[0].offset_sec)
        self.assertIn(
            "automatic-percussion-repeat-cleanup",
            cleaned[0].tags,
        )
        self.assertEqual(
            report["decision"],
            "derived_trailing_percussion_repeat_cleanup",
        )

    def test_accompaniment_shadow_is_removed_before_monophonic_selection(
        self,
    ) -> None:
        candidates = [
            _event(
                "shadowed",
                onset=1,
                offset=1.5,
                pitch=60,
                instrument="voice",
            ),
            _event(
                "melody-a",
                onset=1,
                offset=1.45,
                pitch=67,
                instrument="voice",
            ),
            _event(
                "melody-b",
                onset=1.5,
                offset=2,
                pitch=69,
                instrument="voice",
            ),
        ]
        accompaniment = [
            _event("guitar-copy", onset=1, offset=1.5, pitch=60)
        ]

        filtered, report = soft_mask_melody_candidates(
            candidates,
            accompaniment,
            probe_id="soft-mask",
        )

        self.assertEqual([event.event_id for event in filtered], [
            "melody-a",
            "melody-b",
        ])
        self.assertEqual(report["raw_candidate_count"], 3)
        self.assertEqual(report["accompaniment_shadow_count"], 1)
        self.assertEqual(report["filtered_candidate_count"], 2)
        self.assertFalse(report["accuracy_claimed"])

    def test_residual_gap_finds_unrecovered_intro(self) -> None:
        recovered = [
            _event(
                "starts-late",
                onset=15,
                offset=16,
                pitch=67,
                instrument="voice",
            )
        ]

        gaps = residual_melody_gaps(
            start_sec=0,
            end_sec=30,
            events=recovered,
            minimum_gap_sec=3,
        )

        self.assertEqual(gaps[0], (0, 15))
        self.assertEqual(gaps[1], (16, 30))


if __name__ == "__main__":
    unittest.main()
