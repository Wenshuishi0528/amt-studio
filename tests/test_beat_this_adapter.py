from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from workers.beat_this.normalize import (
    NativeRhythmError,
    normalize_native_rhythm,
    parse_beats,
    probe_npy,
)


def _write_npy(path: Path, shape: tuple[int, int]) -> None:
    header = repr(
        {
            "descr": "<f4",
            "fortran_order": False,
            "shape": shape,
        }
    ).encode("latin1")
    padding = (16 - ((10 + len(header) + 1) % 16)) % 16
    header = header + b" " * padding + b"\n"
    payload = (
        b"\x93NUMPY\x01\x00"
        + struct.pack("<H", len(header))
        + header
        + b"\x00" * (shape[0] * shape[1] * 4)
    )
    path.write_bytes(payload)


class BeatThisAdapterTests(unittest.TestCase):
    def test_normalizes_native_beats_and_preserves_uncertainty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            beats = root / "mix.beats"
            beats.write_text(
                "\n".join(f"{index * 0.5:.2f}\t{index % 4 + 1}" for index in range(17)) + "\n",
                encoding="utf-8",
            )
            activations = root / "mix.npy"
            _write_npy(activations, (2, 401))
            rhythm, summary = normalize_native_rhythm(
                beats,
                activations,
                run_id="beat-run",
                source_model="final0",
                canonical_audio_sha256="a" * 64,
                duration_sec=8.0,
            )

        self.assertEqual(len(rhythm.events), 17)
        self.assertEqual(sum(event.is_downbeat for event in rhythm.events), 5)
        self.assertEqual(len(rhythm.tempo_map), 16)
        self.assertEqual(rhythm.meter_map[0].numerator, 4)
        self.assertEqual(rhythm.meter_map[0].status, "inferred")
        self.assertFalse(rhythm.uncertainty["event_confidence_available"])
        self.assertTrue(rhythm.uncertainty["raw_framewise_logits_preserved"])
        self.assertEqual(
            rhythm.uncertainty["raw_framewise_logits_path"],
            "raw/native/mix.npy",
        )
        self.assertEqual(summary["activation_npy"]["shape"], [2, 401])
        self.assertEqual(summary["tempo_bpm"]["median"], 120.0)
        self.assertFalse(summary["accuracy_claimed"])

    def test_rejects_bad_time_and_beat_number_sequences(self) -> None:
        cases = (
            ("0.0\t1\n0.0\t2\n", "must increase"),
            ("0.0\t1\n0.5\t3\n", "increment or reset"),
            ("0.0\t1\n9.0\t2\n", "outside the audio"),
        )
        for payload, message in cases:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / "bad.beats"
                path.write_text(payload, encoding="utf-8")
                with self.assertRaisesRegex(NativeRhythmError, message):
                    parse_beats(path, duration_sec=8.0)

    def test_rejects_activation_shape_and_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wrong_shape = root / "wrong.npy"
            _write_npy(wrong_shape, (1, 100))
            with self.assertRaisesRegex(NativeRhythmError, r"shape \(2"):
                probe_npy(wrong_shape)

            truncated = root / "truncated.npy"
            _write_npy(truncated, (2, 100))
            truncated.write_bytes(truncated.read_bytes()[:-1])
            with self.assertRaisesRegex(NativeRhythmError, "size does not match"):
                probe_npy(truncated)

    def test_defaults_meter_when_downbeats_are_insufficient(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            beats = root / "mix.beats"
            beats.write_text("0.0\t2\n0.5\t3\n1.0\t4\n", encoding="utf-8")
            activations = root / "mix.npy"
            _write_npy(activations, (2, 51))
            rhythm, _ = normalize_native_rhythm(
                beats,
                activations,
                run_id="beat-run",
                source_model="final0",
                canonical_audio_sha256="a" * 64,
                duration_sec=1.0,
            )
        self.assertEqual(rhythm.meter_map[0].status, "defaulted")
        self.assertEqual(rhythm.meter_map[0].numerator, 4)


if __name__ == "__main__":
    unittest.main()
