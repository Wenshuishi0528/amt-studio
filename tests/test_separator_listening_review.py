from __future__ import annotations

import json
import math
import struct
import tempfile
import unittest
import wave
from pathlib import Path

from workers.separator.prepare_listening_review import (
    ListeningReviewError,
    load_candidate,
    prepare_review,
)

from amt_core.utils import sha256_file


def write_wav(path: Path, *, frequency_hz: float) -> None:
    sample_rate = 8_000
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate):
            value = int(4_000 * math.sin(2 * math.pi * frequency_hz * index / sample_rate))
            frames.extend(struct.pack("<h", value))
        handle.writeframes(bytes(frames))


def write_candidate(
    run_dir: Path,
    *,
    run_id: str,
    frequency_hz: float,
    mix: Path,
) -> None:
    vocals = run_dir / "raw" / "stems" / "vocals.flac"
    write_wav(vocals, frequency_hz=frequency_hz)
    manifest = {
        "schema_version": 1,
        "worker": "separator",
        "status": "succeeded",
        "run_id": run_id,
        "preset": "fixture",
        "model": "fixture.ckpt",
        "model_provenance": {"bundle_sha256": "bundle"},
        "inputs": [{"path": str(mix), "sha256": sha256_file(mix)}],
        "outputs": [
            {
                "path": "raw/stems/vocals.flac",
                "sha256": sha256_file(vocals),
                "size_bytes": vocals.stat().st_size,
            }
        ],
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )


class SeparatorListeningReviewTests(unittest.TestCase):
    def test_rejects_unsafe_or_reserved_labels_before_creating_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mix = root / "mix.wav"
            write_wav(mix, frequency_hz=440.0)
            run_a = root / "run-a"
            run_b = root / "run-b"
            write_candidate(run_a, run_id="a", frequency_hz=440.0, mix=mix)
            write_candidate(run_b, run_id="b", frequency_hz=442.0, mix=mix)

            unsafe_labels = (
                ".",
                "..",
                "../escape",
                "/absolute",
                "nested/path",
                r"nested\path",
                "bad\nlabel",
                "bad:label",
                "bad label",
                "mix",
                "MIX",
                "ＭＩＸ",
            )
            for index, label in enumerate(unsafe_labels):
                with self.subTest(label=label):
                    output_dir = root / f"unsafe-review-{index}"
                    with self.assertRaisesRegex(ValueError, "Candidate label"):
                        prepare_review(
                            mix=mix,
                            candidates={label: run_a, "safe": run_b},
                            starts_sec=[0.0],
                            duration_sec=0.5,
                            output_dir=output_dir,
                        )
                    self.assertFalse(output_dir.exists())

            collision_output = root / "collision-review"
            with self.assertRaisesRegex(ValueError, "collide"):
                prepare_review(
                    mix=mix,
                    candidates={"Candidate": run_a, "candidate": run_b},
                    starts_sec=[0.0],
                    duration_sec=0.5,
                    output_dir=collision_output,
                )
            self.assertFalse(collision_output.exists())

    def test_cli_candidate_parser_rejects_unsafe_label(self) -> None:
        with self.assertRaisesRegex(ValueError, "filename component"):
            load_candidate("../escape=/tmp/run")
        with self.assertRaisesRegex(ValueError, "control character"):
            load_candidate("bad\u0000label=/tmp/run")
        with self.assertRaisesRegex(ValueError, "reserved"):
            load_candidate("Mix=/tmp/run")

    def test_review_package_is_explicitly_awaiting_user(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mix = root / "mix 日本語.wav"
            write_wav(mix, frequency_hz=440.0)
            run_a = root / "run a"
            run_b = root / "run b"
            write_candidate(run_a, run_id="a", frequency_hz=440.0, mix=mix)
            write_candidate(run_b, run_id="b", frequency_hz=442.0, mix=mix)
            output_dir = root / "review"

            result = prepare_review(
                mix=mix,
                candidates={"candidate-a": run_a, "candidate-b": run_b},
                starts_sec=[0.1],
                duration_sec=0.5,
                output_dir=output_dir,
            )

            self.assertEqual(result["status"], "awaiting_user")
            review = result["passages"][0]["review"]
            self.assertEqual(review["status"], "awaiting_user")
            self.assertIsNone(review["vocal_deletion"])
            self.assertTrue((output_dir / "passage-01-00000.100s" / "mix.flac").is_file())
            self.assertEqual(
                result["candidates"]["candidate-a"]["parent_manifest_sha256"],
                sha256_file(run_a / "run_manifest.json"),
            )
            self.assertEqual(
                result["candidates"]["candidate-a"]["vocals"]["size_bytes"],
                (run_a / "raw" / "stems" / "vocals.flac").stat().st_size,
            )

            with self.assertRaisesRegex(ListeningReviewError, "Refusing to reuse"):
                prepare_review(
                    mix=mix,
                    candidates={"candidate-a": run_a, "candidate-b": run_b},
                    starts_sec=[0.1],
                    duration_sec=0.5,
                    output_dir=output_dir,
                )

    def test_rejects_duplicate_candidate_path_or_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mix = root / "mix.wav"
            write_wav(mix, frequency_hz=440.0)
            run_a = root / "run-a"
            run_b = root / "run-b"
            write_candidate(run_a, run_id="same", frequency_hz=440.0, mix=mix)
            write_candidate(run_b, run_id="same", frequency_hz=442.0, mix=mix)

            with self.assertRaisesRegex(ListeningReviewError, "distinct candidate run paths"):
                prepare_review(
                    mix=mix,
                    candidates={"a": run_a, "b": run_a},
                    starts_sec=[0.0],
                    duration_sec=0.5,
                    output_dir=root / "path-review",
                )
            with self.assertRaisesRegex(ListeningReviewError, "distinct candidate run_id"):
                prepare_review(
                    mix=mix,
                    candidates={"a": run_a, "b": run_b},
                    starts_sec=[0.0],
                    duration_sec=0.5,
                    output_dir=root / "id-review",
                )

    def test_rejects_candidate_bound_to_another_mix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mix = root / "mix.wav"
            other_mix = root / "other-mix.wav"
            write_wav(mix, frequency_hz=440.0)
            write_wav(other_mix, frequency_hz=220.0)
            run_a = root / "run-a"
            run_b = root / "run-b"
            write_candidate(run_a, run_id="a", frequency_hz=440.0, mix=mix)
            write_candidate(
                run_b,
                run_id="b",
                frequency_hz=442.0,
                mix=other_mix,
            )

            with self.assertRaisesRegex(ListeningReviewError, "input SHA"):
                prepare_review(
                    mix=mix,
                    candidates={"a": run_a, "b": run_b},
                    starts_sec=[0.0],
                    duration_sec=0.5,
                    output_dir=root / "review",
                )

    def test_rejects_tampered_or_duplicate_vocals_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mix = root / "mix.wav"
            write_wav(mix, frequency_hz=440.0)
            run_a = root / "run-a"
            run_b = root / "run-b"
            write_candidate(run_a, run_id="a", frequency_hz=440.0, mix=mix)
            write_candidate(run_b, run_id="b", frequency_hz=442.0, mix=mix)

            write_wav(
                run_b / "raw" / "stems" / "vocals.flac",
                frequency_hz=443.0,
            )
            with self.assertRaisesRegex(ListeningReviewError, "vocals hash mismatch"):
                prepare_review(
                    mix=mix,
                    candidates={"a": run_a, "b": run_b},
                    starts_sec=[0.0],
                    duration_sec=0.5,
                    output_dir=root / "tampered-review",
                )

            write_candidate(run_b, run_id="b", frequency_hz=442.0, mix=mix)
            manifest_path = run_b / "run_manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["outputs"].append(dict(manifest["outputs"][0]))
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ListeningReviewError, "exactly one output"):
                prepare_review(
                    mix=mix,
                    candidates={"a": run_a, "b": run_b},
                    starts_sec=[0.0],
                    duration_sec=0.5,
                    output_dir=root / "duplicate-review",
                )


if __name__ == "__main__":
    unittest.main()
