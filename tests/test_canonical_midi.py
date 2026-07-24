from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import mido

from amt_core.canonical import (
    MeterPoint,
    RhythmEvent,
    RhythmMap,
    TempoPoint,
    build_score_grid,
)
from amt_core.events import NoteEvent
from amt_core.midi import export_performance_midi


def _rhythm() -> RhythmMap:
    events = tuple(
        RhythmEvent(
            event_id=f"beat-{index + 1}",
            time_sec=time_sec,
            beat_number=index % 4 + 1,
            is_downbeat=index % 4 == 0,
            confidence=None,
            source_frame_index=round(time_sec * 50),
        )
        for index, time_sec in enumerate((0.0, 0.5, 1.0, 1.5, 2.0, 2.666667, 3.333333, 4.0))
    )
    return RhythmMap(
        source_run_id="beat-run",
        source_model="final0",
        canonical_audio_sha256="a" * 64,
        events=events,
        tempo_map=(
            TempoPoint(
                time_sec=0.0,
                bpm=120.0,
                confidence=None,
                uncertainty_bpm=None,
                source_event_ids=("beat-1", "beat-2"),
                method="adjacent_beat_interval",
            ),
            TempoPoint(
                time_sec=2.0,
                bpm=90.0,
                confidence=None,
                uncertainty_bpm=None,
                source_event_ids=("beat-5", "beat-6"),
                method="adjacent_beat_interval",
            ),
        ),
        meter_map=(
            MeterPoint(
                time_sec=0.0,
                numerator=4,
                denominator=4,
                confidence=None,
                source_event_ids=("beat-1", "beat-5"),
                status="inferred",
            ),
        ),
        uncertainty={
            "event_confidence_available": False,
            "raw_framewise_logits_preserved": True,
        },
    )


def _events() -> list[NoteEvent]:
    return [
        NoteEvent(
            event_id="note-a",
            track_id="voice",
            instrument="voice",
            onset_sec=0.123,
            offset_sec=1.789,
            pitch_midi=69.2,
            source_run_id="run-a",
            source_model="model-a",
        ),
        NoteEvent(
            event_id="note-b",
            track_id="voice",
            instrument="voice",
            onset_sec=2.345,
            offset_sec=3.901,
            pitch_midi=71.8,
            source_run_id="run-a",
            source_model="model-a",
        ),
    ]


class CanonicalMidiTests(unittest.TestCase):
    def test_performance_midi_round_trips_time_through_mido(self) -> None:
        rhythm = _rhythm()
        source_events = _events()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "performance.mid"
            report = export_performance_midi(
                path,
                {"candidate": source_events},
                rhythm.tempo_map,
                rhythm.meter_map,
            )
            parsed = mido.MidiFile(path)
            elapsed = 0.0
            parsed_onsets: list[float] = []
            parsed_offsets: list[float] = []
            for message in parsed:
                elapsed += message.time
                if message.type == "note_on" and message.velocity > 0:
                    parsed_onsets.append(elapsed)
                elif message.type == "note_off" or (
                    message.type == "note_on" and message.velocity == 0
                ):
                    parsed_offsets.append(elapsed)

        self.assertEqual(report["representation"], "performance")
        self.assertEqual(report["note_count"], 2)
        self.assertEqual(len(parsed_onsets), 2)
        self.assertEqual(len(parsed_offsets), 2)
        for actual, event in zip(parsed_onsets, source_events, strict=True):
            self.assertLess(abs(actual - event.onset_sec), 0.002)
        for actual, event in zip(parsed_offsets, source_events, strict=True):
            self.assertLess(abs(actual - event.offset_sec), 0.002)
        self.assertLess(report["maximum_internal_roundtrip_error_sec"], 0.002)

    def test_score_grid_is_separate_and_preserves_performance_source(self) -> None:
        rhythm = _rhythm()
        event = _events()[0]
        score = build_score_grid({"candidate": [event]}, rhythm, subdivision=4)
        self.assertEqual(len(score), 1)
        self.assertEqual(score[0].source_event_id, event.event_id)
        self.assertEqual(score[0].performance_onset_sec, event.onset_sec)
        self.assertEqual(score[0].performance_offset_sec, event.offset_sec)
        self.assertEqual(score[0].pitch_midi, 69)
        self.assertEqual(score[0].grid_subdivision, 4)
        self.assertAlmostEqual(score[0].onset_beats * 4, round(score[0].onset_beats * 4))
        self.assertEqual(event.quantized_pitch_midi, None)
        self.assertAlmostEqual(event.onset_sec, 0.123)

    def test_rhythm_rejects_downbeat_number_disagreement(self) -> None:
        value = _rhythm().to_dict()
        value["events"][0]["beat_number"] = 2
        with self.assertRaisesRegex(ValueError, "downbeat flag"):
            RhythmMap.from_dict(value)

        value = _rhythm().to_dict()
        value["canonical_audio_sha256"] = "x" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            RhythmMap.from_dict(value)

        with self.assertRaisesRegex(ValueError, "subdivision"):
            build_score_grid({"candidate": _events()}, _rhythm(), subdivision=True)


if __name__ == "__main__":
    unittest.main()
