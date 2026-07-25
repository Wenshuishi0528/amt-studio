from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

from amt_core.events import EventValidationError, NoteEvent, read_jsonl, write_jsonl


class NoteEventTests(unittest.TestCase):
    def test_round_trip_with_unicode_track(self) -> None:
        event = NoteEvent(
            event_id="e-1",
            track_id="主旋律",
            instrument="voice",
            onset_sec=0.1,
            offset_sec=0.5,
            pitch_midi=69.2,
            confidence=0.9,
            source_run_id="run-1",
            source_model="test",
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events 日本語.jsonl"
            write_jsonl(path, [event])
            loaded = read_jsonl(path)
        self.assertEqual(loaded[0].track_id, "主旋律")
        self.assertAlmostEqual(loaded[0].pitch_midi, 69.2)

    def test_offset_must_follow_onset(self) -> None:
        event = NoteEvent(
            event_id="bad",
            track_id="melody",
            onset_sec=1.0,
            offset_sec=1.0,
            pitch_midi=60,
            source_run_id="run",
            source_model="test",
        )
        with self.assertRaises(EventValidationError):
            event.validate()

    def test_rejects_non_finite_numeric_fields(self) -> None:
        base = {
            "event_id": "bad",
            "track_id": "melody",
            "onset_sec": 1.0,
            "offset_sec": 2.0,
            "pitch_midi": 60.0,
            "source_run_id": "run",
            "source_model": "test",
        }
        for field_name in ("onset_sec", "offset_sec", "pitch_midi", "confidence"):
            with self.subTest(field_name=field_name):
                values = {**base, field_name: math.nan}
                with self.assertRaisesRegex(EventValidationError, "finite"):
                    NoteEvent(**values).validate()


if __name__ == "__main__":
    unittest.main()
