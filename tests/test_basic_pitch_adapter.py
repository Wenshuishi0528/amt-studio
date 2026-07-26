from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from workers.basic_pitch.normalize import NativeEventError, normalize_note_events

from amt_core.events import read_jsonl


class BasicPitchAdapterTests(unittest.TestCase):
    def test_normalizes_native_rows_and_preserves_pitch_bends(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "native 日本語.csv"
            native.write_text(
                "start_time_s,end_time_s,pitch_midi,velocity,pitch_bend\n"
                "1.25,1.75,64,91\n"
                "0.5,0.9,60,80,-100,200\n",
                encoding="utf-8",
            )
            output = root / "normalized" / "events.jsonl"
            summary_path = root / "normalized" / "summary.json"
            summary = normalize_note_events(
                native,
                output,
                summary_path,
                run_id="basic-pitch-fixture",
                source_model="spotify/basic-pitch@revision:model",
            )
            events = read_jsonl(output)

        self.assertEqual(summary["event_count"], 2)
        self.assertEqual([event.onset_sec for event in events], [0.5, 1.25])
        self.assertEqual([event.pitch_midi for event in events], [60.0, 64.0])
        self.assertEqual([event.velocity for event in events], [80, 91])
        self.assertEqual(events[0].extra["pitch_bend_values"], [-100, 200])
        self.assertEqual(events[1].extra["pitch_bend_values"], [])
        self.assertTrue(all(event.is_main_melody_candidate for event in events))
        self.assertTrue(all(event.instrument == "voice" for event in events))
        self.assertTrue(all(event.confidence is None for event in events))
        self.assertTrue(summary["confidence"]["raw_model_outputs_preserved"])
        self.assertFalse(summary["decoding_cleanup"]["song_specific_tuning"])

    def test_rejects_unsupported_header(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "events.csv"
            native.write_text(
                "onset,offset,pitch,velocity\n0,1,60,100\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(NativeEventError, "unsupported CSV header"):
                normalize_note_events(
                    native,
                    root / "events.jsonl",
                    root / "summary.json",
                    run_id="run",
                    source_model="model",
                )

    def test_direct_mix_instrument_is_explicitly_unknown_not_voice(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native = root / "events.csv"
            native.write_text(
                "start_time_s,end_time_s,pitch_midi,velocity,pitch_bend\n"
                "0.0,1.0,72,90\n",
                encoding="utf-8",
            )
            output = root / "events.jsonl"
            summary = normalize_note_events(
                native,
                output,
                root / "summary.json",
                run_id="direct-mix",
                source_model="model",
                instrument="other",
            )
            events = read_jsonl(output)

        self.assertEqual([event.instrument for event in events], ["other"])
        self.assertIn("direct-mix-main-melody-candidate", events[0].tags)
        self.assertEqual(summary["instrument_counts"], {"other": 1})
        self.assertFalse(summary["instrument_assignment"]["model_inferred"])

    def test_rejects_nonfinite_and_invalid_note_rows(self) -> None:
        invalid_rows = (
            ("nan,1,60,100\n", "must be finite"),
            ("1,0.5,60,100\n", "invalid onset/offset"),
            ("0,1,128,100\n", "pitch_midi must be in"),
            ("0,1,60,200\n", "velocity must be in"),
            ("0,1,60,100,not-an-int\n", "must be an integer"),
        )
        for row, message in invalid_rows:
            with self.subTest(row=row), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                native = root / "events.csv"
                native.write_text(
                    "start_time_s,end_time_s,pitch_midi,velocity,pitch_bend\n" + row,
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(NativeEventError, message):
                    normalize_note_events(
                        native,
                        root / "events.jsonl",
                        root / "summary.json",
                        run_id="run",
                        source_model="model",
                    )


if __name__ == "__main__":
    unittest.main()
