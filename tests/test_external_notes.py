from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.evaluate_external_notes import (
    ExternalNoteEvaluationError,
    _correction_proxy,
    _external_reference_records,
    _portable_candidate_events_path,
    _voice_events_in_window,
    read_external_note_csv,
)

from amt_core.evaluation import evaluate_notes
from amt_core.events import NoteEvent


def _event(
    identifier: str,
    *,
    onset: float,
    offset: float,
    pitch: float,
    instrument: str = "voice",
) -> NoteEvent:
    return NoteEvent(
        event_id=identifier,
        track_id="candidate",
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=pitch,
        source_run_id="fixture",
        source_model="fixture",
        instrument=instrument,
    )


class ExternalNoteEvaluationTests(unittest.TestCase):
    def test_reads_hz_note_rows_into_canonical_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "notes.csv"
            path.write_text("0.5,440.0,0.25\n1.0,880.0,0.5\n", encoding="utf-8")
            notes = read_external_note_csv(
                path,
                excerpt_id="blind-01",
                annotator="a1",
                start_sec=10.0,
                duration_sec=2.0,
            )
            self.assertEqual(len(notes), 2)
            self.assertEqual(notes[0].onset_sec, 10.5)
            self.assertEqual(notes[0].offset_sec, 10.75)
            self.assertEqual(notes[0].pitch_midi, 69.0)
            self.assertEqual(notes[1].pitch_midi, 81.0)

            path.write_text("1.9,440.0,0.25\n", encoding="utf-8")
            with self.assertRaisesRegex(
                ExternalNoteEvaluationError,
                "exceed",
            ):
                read_external_note_csv(
                    path,
                    excerpt_id="blind-01",
                    annotator="a1",
                    start_sec=10.0,
                    duration_sec=2.0,
                )

    def test_voice_window_and_correction_proxy_are_explicit(self) -> None:
        references = read_external_note_csv_fixture()
        events = [
            _event("correct", onset=10.0, offset=10.5, pitch=69),
            _event("bad-offset", onset=11.0, offset=11.2, pitch=71),
            _event("outside", onset=12.0, offset=12.5, pitch=72),
            _event(
                "guitar",
                onset=10.0,
                offset=10.5,
                pitch=80,
                instrument="guitar",
            ),
        ]
        selected = _voice_events_in_window(events, start_sec=10.0, end_sec=12.0)
        self.assertEqual([event.event_id for event in selected], ["correct", "bad-offset"])
        report = evaluate_notes(references, selected)
        proxy = _correction_proxy(report, duration_sec=2.0)
        self.assertEqual(proxy["note_object_discrepancy_count"], 1)
        self.assertEqual(proxy["onset_pitch_matched_offset_mismatch"], 1)
        self.assertFalse(proxy["manual_edit_time_measured"])

        mergeable = [
            _event("first", onset=10.0, offset=10.25, pitch=69),
            _event("second", onset=10.25, offset=10.5, pitch=69),
        ]
        merge_proxy = _correction_proxy(
            evaluate_notes(references[:1], mergeable),
            duration_sec=1.0,
        )
        self.assertEqual(merge_proxy["note_object_discrepancy_count"], 2)
        self.assertIn("not an edit-action lower bound", merge_proxy["interpretation"])

    def test_external_manifest_binding_requires_exact_source_and_annotations(self) -> None:
        reference_a1 = {"sha256": "a1-hash", "note_count": 2}
        reference_a2 = {"sha256": "a2-hash", "note_count": 3}
        excerpt = {
            "excerpt_id": "blind-01",
            "track_id": 7,
            "singer_group_id": "singer-7",
            "language": "fixture",
            "average_midi_pitch": 60,
            "source_audio_sha256": "audio-hash",
            "evaluation_start_sec": 1.0,
            "evaluation_end_sec": 3.0,
            "duration_sec": 2.0,
            "note_references": {"a1": reference_a1, "a2": reference_a2},
        }
        selection = {
            "schema": "amt-external-note-selection/v1",
            "selection_before_candidate_inference": True,
            "candidate_output_inspected": False,
            "split": "blind_test",
            "tracks": [
                {
                    "track_id": 7,
                    "singer_id": "singer-7",
                    "language": "fixture",
                    "average_midi_pitch": 60,
                    "audio_sha256": "audio-hash",
                    "notes_a1_sha256": "a1-hash",
                    "notes_a1_count": 2,
                    "notes_a2_sha256": "a2-hash",
                    "notes_a2_count": 3,
                }
            ],
        }
        concatenation = {
            "schema": "amt-external-note-concatenation/v1",
            "created_before_candidate_inference": True,
            "tracks": [
                {
                    "excerpt_id": "blind-01",
                    "track_id": 7,
                    "singer_id": "singer-7",
                    "language": "fixture",
                    "average_midi_pitch": 60,
                    "audio_sha256": "audio-hash",
                    "start_sec": 1.0,
                    "end_sec": 3.0,
                    "duration_sec": 2.0,
                    "note_references": {
                        "a1": reference_a1,
                        "a2": reference_a2,
                    },
                }
            ],
        }
        _external_reference_records(
            {"excerpts": [excerpt]},
            selection,
            concatenation,
        )
        selection["tracks"][0]["notes_a2_sha256"] = "wrong-track"
        with self.assertRaisesRegex(
            ExternalNoteEvaluationError,
            "not bound",
        ):
            _external_reference_records(
                {"excerpts": [excerpt]},
                selection,
                concatenation,
            )

    def test_sealed_candidate_path_relocates_by_run_identity(self) -> None:
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


def read_external_note_csv_fixture():
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "notes.csv"
        path.write_text("0.0,440.0,0.5\n1.0,493.883301,0.5\n", encoding="utf-8")
        return read_external_note_csv(
            path,
            excerpt_id="blind-01",
            annotator="a1",
            start_sec=10.0,
            duration_sec=2.0,
        )


if __name__ == "__main__":
    unittest.main()
