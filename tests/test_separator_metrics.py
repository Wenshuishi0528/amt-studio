from __future__ import annotations

import array
import math
import random
import shutil
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

from workers.separator.metrics import (
    ALIGNMENT_MIN_CORRELATION,
    _estimate_lag,
    alignment_stats,
    analyze_stem_set,
)


class AlignmentReliabilityTests(unittest.TestCase):
    def test_low_correlation_lag_is_an_unreliable_candidate(self) -> None:
        reference_source = random.Random(20260723)
        candidate_source = random.Random(20260724)
        reference = array.array(
            "f",
            (reference_source.uniform(-1.0, 1.0) for _ in range(4_000)),
        )
        candidate = array.array(
            "f",
            (candidate_source.uniform(-1.0, 1.0) for _ in range(4_000)),
        )

        segment = _estimate_lag(
            reference,
            candidate,
            reference_start=0,
            reference_end=len(reference),
        )
        self.assertTrue(segment["measurable"])
        self.assertFalse(segment["reliable"])
        self.assertLess(segment["correlation"], ALIGNMENT_MIN_CORRELATION)
        self.assertIsNone(segment["within_tolerance"])
        self.assertEqual(
            segment["estimate_status"],
            "candidate_diagnostic_unreliable",
        )

        with patch(
            "workers.separator.metrics._mono_float_stream",
            side_effect=[reference, candidate],
        ):
            aggregate = alignment_stats(Path("mix.wav"), [Path("stem.wav")])
        self.assertFalse(aggregate["all_segments_reliable"])
        self.assertIsNone(aggregate["within_tolerance"])
        self.assertIsNone(aggregate["maximum_absolute_lag_sec"])


@unittest.skipUnless(
    shutil.which("ffmpeg") and shutil.which("ffprobe"),
    "ffmpeg and ffprobe are required",
)
class SeparatorMetricTests(unittest.TestCase):
    @staticmethod
    def _write_wav(path: Path, samples: list[float], *, sample_rate: int) -> None:
        pcm = array.array("h")
        for sample in samples:
            quantized = round(max(-1.0, min(1.0, sample)) * 32767)
            pcm.extend((quantized, quantized))
        if sys.byteorder != "little":
            pcm.byteswap()
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(2)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(pcm.tobytes())

    def test_exact_vocal_plus_silence_has_no_drift_or_lag(self) -> None:
        sample_rate = 8_000
        duration_sec = 13
        random_source = random.Random(20260723)
        samples = []
        for frame in range(sample_rate * duration_sec):
            time_sec = frame / sample_rate
            sample = (
                0.24 * math.sin(2 * math.pi * (137 + 11 * time_sec) * time_sec)
                + 0.11 * math.sin(2 * math.pi * 293 * time_sec)
                + 0.025 * random_source.uniform(-1.0, 1.0)
            )
            samples.append(sample)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mix = root / "mix 日本語.wav"
            vocals = root / "vocals.wav"
            instrumental = root / "instrumental silence.wav"
            self._write_wav(mix, samples, sample_rate=sample_rate)
            self._write_wav(vocals, samples, sample_rate=sample_rate)
            self._write_wav(
                instrumental,
                [0.0] * len(samples),
                sample_rate=sample_rate,
            )

            result = analyze_stem_set(
                mix,
                {
                    "vocals": vocals,
                    "instrumental": instrumental,
                },
            )

        self.assertEqual(result["schema_version"], 2)
        self.assertEqual(result["mix"]["decoded"]["sample_rate_hz"], 44_100)
        self.assertEqual(result["mix"]["decoded"]["channels"], 2)
        self.assertGreater(result["mix"]["decoded"]["sample_frames"], 0)
        self.assertIn("integrated_lufs", result["mix"]["loudness"])
        self.assertIn("true_peak_dbfs", result["mix"]["loudness"])

        for stem in result["stems"].values():
            self.assertEqual(stem["decoded_frame_drift"], 0)
            self.assertEqual(stem["decoded_endpoint_drift_sec"], 0.0)
            self.assertTrue(stem["endpoint_drift"]["within_tolerance"])
            self.assertIn("integrated_lufs", stem["loudness"])
            self.assertIn("true_peak_dbfs", stem["loudness"])
        self.assertTrue(result["timeline"]["all_stems_within_endpoint_tolerance"])
        self.assertEqual(
            result["timeline"]["maximum_absolute_stem_frame_drift"],
            0,
        )

        reconstruction = result["reconstruction"]
        self.assertLessEqual(reconstruction["rms"], 1e-7)
        self.assertLessEqual(reconstruction["relative_l2"], 1e-7)
        self.assertEqual(reconstruction["decoded_frame_drift"], 0)
        self.assertEqual(
            result["stems"]["instrumental"]["near_silent_fraction"],
            1.0,
        )
        self.assertEqual(result["stems"]["vocals"]["clipping_fraction"], 0.0)

        alignment = result["alignment"]
        self.assertEqual(alignment["status"], "diagnostic_only")
        self.assertTrue(alignment["global"]["measurable"])
        self.assertTrue(alignment["global"]["reliable"])
        self.assertEqual(alignment["global"]["lag_frames"], 0)
        self.assertEqual(alignment["global"]["lag_sec"], 0.0)
        self.assertTrue(alignment["within_tolerance"])
        self.assertEqual(
            [window["name"] for window in alignment["windows"]],
            ["beginning", "middle", "end"],
        )
        for window in alignment["windows"]:
            self.assertTrue(window["measurable"])
            self.assertTrue(window["reliable"])
            self.assertEqual(window["lag_frames"], 0)
            self.assertTrue(window["within_tolerance"])

        for candidates in result["review_candidates"].values():
            for candidate in candidates:
                self.assertEqual(candidate["status"], "candidate_unconfirmed")
                self.assertFalse(candidate["confirmed_by_listening"])


if __name__ == "__main__":
    unittest.main()
