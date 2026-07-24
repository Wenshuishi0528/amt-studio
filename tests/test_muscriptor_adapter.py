from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from workers.muscriptor.normalize import NativeEventError, normalize_native_events

from amt_core.events import read_jsonl


class MuScriptorAdapterTests(unittest.TestCase):
    def _write_native(self, directory: Path, values: list[dict]) -> Path:
        path = directory / "native events 日本語.jsonl"
        path.write_text(
            "".join(json.dumps(value) + "\n" for value in values),
            encoding="utf-8",
        )
        return path

    def test_pairs_events_and_preserves_native_instrument(self) -> None:
        native = [
            {
                "type": "start",
                "pitch": 64,
                "start_time": 0.5,
                "index": 7,
                "instrument": "distorted_electric_guitar",
            },
            {"type": "end", "end_time": 1.25, "start_event_index": 7},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            native_path = self._write_native(root, native)
            output = root / "normalized" / "events.jsonl"
            summary = root / "normalized" / "summary.json"
            result = normalize_native_events(
                native_path,
                output,
                summary,
                run_id="run 日本語",
                source_model="MuScriptor/muscriptor-large@revision",
            )
            events = read_jsonl(output)

        self.assertEqual(result["event_count"], 1)
        self.assertEqual(result["instrument_counts"], {"distorted_electric_guitar": 1})
        self.assertEqual(events[0].instrument, "distorted_electric_guitar")
        self.assertEqual(
            events[0].track_id,
            "muscriptor-native:distorted_electric_guitar",
        )
        self.assertEqual(events[0].extra["native_start_event"], native[0])
        self.assertEqual(events[0].extra["native_end_event"], native[1])
        self.assertIsNone(events[0].confidence)
        self.assertIsNone(events[0].velocity)

    def test_sorts_by_onset_without_losing_source_index(self) -> None:
        native = [
            {
                "type": "start",
                "pitch": 72,
                "start_time": 1.0,
                "index": 9,
                "instrument": "voice",
            },
            {
                "type": "start",
                "pitch": 60,
                "start_time": 0.25,
                "index": 2,
                "instrument": "acoustic_piano",
            },
            {"type": "end", "end_time": 1.5, "start_event_index": 9},
            {"type": "end", "end_time": 0.75, "start_event_index": 2},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "events.jsonl"
            normalize_native_events(
                self._write_native(root, native),
                output,
                root / "summary.json",
                run_id="run-1",
                source_model="model",
            )
            events = read_jsonl(output)

        self.assertEqual([event.onset_sec for event in events], [0.25, 1.0])
        self.assertEqual(
            [event.extra["native_start_index"] for event in events],
            [2, 9],
        )

    def test_rejects_missing_end(self) -> None:
        native = [
            {
                "type": "start",
                "pitch": 60,
                "start_time": 0.0,
                "index": 1,
                "instrument": "acoustic_piano",
            }
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(NativeEventError, "have no end"):
                normalize_native_events(
                    self._write_native(root, native),
                    root / "events.jsonl",
                    root / "summary.json",
                    run_id="run",
                    source_model="model",
                )

    def test_rejects_duplicate_end(self) -> None:
        native = [
            {
                "type": "start",
                "pitch": 36,
                "start_time": 0.0,
                "index": 3,
                "instrument": "drums",
            },
            {"type": "end", "end_time": 0.01, "start_event_index": 3},
            {"type": "end", "end_time": 0.02, "start_event_index": 3},
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(NativeEventError, "duplicate end"):
                normalize_native_events(
                    self._write_native(root, native),
                    root / "events.jsonl",
                    root / "summary.json",
                    run_id="run",
                    source_model="model",
                )


if __name__ == "__main__":
    unittest.main()
