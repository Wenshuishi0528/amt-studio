from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from workers.separator.compare_repeatability import RepeatabilityError, compare_runs

from amt_core.utils import sha256_file


def write_fixture_wav(path: Path, *, frequency_hz: float) -> None:
    sample_rate = 8_000
    frame_count = sample_rate // 2
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        for index in range(frame_count):
            value = int(8_000 * math.sin(2 * math.pi * frequency_hz * index / sample_rate))
            handle.writeframesraw(struct.pack("<h", value))


def write_run(run_dir: Path, *, run_id: str, frequency_hz: float) -> None:
    stem_path = run_dir / "raw" / "stems" / "vocals.flac"
    write_fixture_wav(stem_path, frequency_hz=frequency_hz)
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "worker": "separator",
        "status": "succeeded",
        "preset": "fixture",
        "model": "fixture.ckpt",
        "configuration": {"normalization": 1.0},
        "model_provenance": {"bundle_sha256": "bundle"},
        "inputs": [{"sha256": "input"}],
        "outputs": [
            {
                "path": "raw/stems/vocals.flac",
                "sha256": sha256_file(stem_path),
                "size_bytes": stem_path.stat().st_size,
            }
        ],
        "metrics": {
            "audio": {
                "stems": {
                    "vocals": {
                        "sample_rate_hz": 8_000,
                        "channels": 1,
                        "sample_frames": 4_000,
                    }
                }
            }
        },
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


class SeparatorRepeatabilityTests(unittest.TestCase):
    def test_exact_decoded_pcm_and_difference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a = root / "run a"
            run_b = root / "run 日本語"
            write_run(run_a, run_id="a", frequency_hz=440.0)
            write_run(run_b, run_id="b", frequency_hz=440.0)

            exact = compare_runs(run_a, run_b)
            self.assertEqual(exact["status"], "exact")
            self.assertTrue(exact["stems"]["vocals"]["decoded_pcm_equal"])

            write_run(run_b, run_id="b", frequency_hz=442.0)
            different = compare_runs(run_a, run_b)
            self.assertEqual(different["status"], "different")
            self.assertFalse(different["stems"]["vocals"]["decoded_pcm_equal"])

    def test_refuses_different_input_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a = root / "a"
            run_b = root / "b"
            write_run(run_a, run_id="a", frequency_hz=440.0)
            write_run(run_b, run_id="b", frequency_hz=440.0)
            manifest_path = run_b / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["inputs"][0]["sha256"] = "different"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(RepeatabilityError, "input_sha256"):
                compare_runs(run_a, run_b)

    def test_refuses_same_path_or_same_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a = root / "a"
            run_b = root / "b"
            write_run(run_a, run_id="same", frequency_hz=440.0)
            write_run(run_b, run_id="same", frequency_hz=440.0)

            with self.assertRaisesRegex(RepeatabilityError, "distinct run paths"):
                compare_runs(run_a, run_a)
            with self.assertRaisesRegex(RepeatabilityError, "distinct run_id"):
                compare_runs(run_a, run_b)

    def test_refuses_tampered_or_duplicate_stem_output_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_a = root / "a"
            run_b = root / "b"
            write_run(run_a, run_id="a", frequency_hz=440.0)
            write_run(run_b, run_id="b", frequency_hz=440.0)

            write_fixture_wav(
                run_b / "raw" / "stems" / "vocals.flac",
                frequency_hz=442.0,
            )
            with self.assertRaisesRegex(RepeatabilityError, "Manifest (size|hash) mismatch"):
                compare_runs(run_a, run_b)

            write_run(run_b, run_id="b", frequency_hz=440.0)
            manifest_path = run_b / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"].append(dict(manifest["outputs"][0]))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RepeatabilityError, "exactly one output record"):
                compare_runs(run_a, run_b)


if __name__ == "__main__":
    unittest.main()
