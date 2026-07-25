from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.create_annotation_topline import ToplineError, create_topline

from amt_core.events import NoteEvent, read_jsonl, write_jsonl


def _event(event_id: str, onset: float, offset: float, pitch: int) -> NoteEvent:
    return NoteEvent(
        event_id=event_id,
        track_id="source:guitar",
        instrument="guitar",
        onset_sec=onset,
        offset_sec=offset,
        pitch_midi=float(pitch),
        quantized_pitch_midi=pitch,
        velocity=None,
        confidence=None,
        source_run_id="source-run",
        source_model="source-model",
    )


class AnnotationToplineTests(unittest.TestCase):
    def test_selects_highest_simultaneous_pitch_merges_and_clips(self) -> None:
        events = [
            _event("chord-low", 1.0, 1.4, 60),
            _event("chord-high", 1.0, 1.4, 72),
            _event("repeat", 1.4, 1.6, 72),
            _event("next", 1.55, 2.0, 74),
        ]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "events.jsonl"
            write_jsonl(source, events)
            output = root / "proposal"
            summary = create_topline(
                events_path=source,
                instrument="guitar",
                excerpts=[("excerpt-1", 1.0, 2.0)],
                output_dir=output,
            )
            proposed = read_jsonl(output / "excerpt-1" / "events.jsonl")
            run_manifest = json.loads(
                (output / "run_manifest.json").read_text(encoding="utf-8")
            )

        self.assertEqual([event.pitch_midi for event in proposed], [72.0, 74.0])
        self.assertEqual(proposed[0].onset_sec, 1.0)
        self.assertEqual(proposed[0].offset_sec, 1.55)
        self.assertEqual(
            proposed[0].source_event_ids,
            ["chord-high", "repeat"],
        )
        self.assertEqual(summary["excerpts"][0]["source_event_count"], 4)
        self.assertEqual(summary["excerpts"][0]["proposed_event_count"], 2)
        self.assertFalse(summary["claims"]["human_confirmed"])
        self.assertEqual(run_manifest["status"], "succeeded")
        self.assertEqual(
            {record["path"] for record in run_manifest["outputs"]},
            {"excerpt-1/events.jsonl", "summary.json"},
        )
        self.assertEqual(
            run_manifest["model"]["name"],
            "deterministic-highest-pitch-topline",
        )

    def test_refuses_overwrite_and_missing_instrument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "events.jsonl"
            write_jsonl(source, [_event("one", 0.0, 1.0, 60)])
            with self.assertRaisesRegex(ToplineError, "no events match"):
                create_topline(
                    events_path=source,
                    instrument="voice",
                    excerpts=[("excerpt-1", 0.0, 1.0)],
                    output_dir=root / "proposal",
                )
            existing = root / "existing"
            existing.mkdir()
            with self.assertRaisesRegex(ToplineError, "refusing to overwrite"):
                create_topline(
                    events_path=source,
                    instrument="guitar",
                    excerpts=[("excerpt-1", 0.0, 1.0)],
                    output_dir=existing,
                )
            alias = root / "events-alias.jsonl"
            alias.symlink_to(source)
            with self.assertRaisesRegex(ToplineError, "non-symlink"):
                create_topline(
                    events_path=alias,
                    instrument="guitar",
                    excerpts=[("excerpt-1", 0.0, 1.0)],
                    output_dir=root / "alias-output",
                )


if __name__ == "__main__":
    unittest.main()
