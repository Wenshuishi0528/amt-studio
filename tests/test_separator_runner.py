from __future__ import annotations

import contextlib
import io
import json
import math
import stat
import struct
import sys
import tempfile
import unittest
import wave
from pathlib import Path
from unittest import mock

from workers.separator import run_baseline

from amt_core.utils import sha256_file

FAKE_SEPARATOR = """#!/usr/bin/env python3
import pathlib
import shutil
import sys

args = sys.argv[1:]
if not args or "--help" in args or "--env_info" in args or "--list_models" in args:
    print("fake audio-separator")
    raise SystemExit(0)
source = pathlib.Path(args[0])
output_dir = pathlib.Path(args[args.index("--output_dir") + 1])
output_dir.mkdir(parents=True, exist_ok=True)
for stem in ("vocals", "instrumental"):
    shutil.copyfile(source, output_dir / f"{stem}.flac")
"""


def write_fixture_wav(path: Path) -> None:
    sample_rate = 44_100
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        frames = bytearray()
        for index in range(sample_rate // 4):
            value = int(4_000 * math.sin(2 * math.pi * 440 * index / sample_rate))
            frames.extend(struct.pack("<hh", value, value))
        handle.writeframes(bytes(frames))


class SeparatorRunnerTests(unittest.TestCase):
    def test_run_id_validation_rejects_path_escape(self) -> None:
        self.assertEqual(
            run_baseline.validate_run_id("separator-20260723_a.1"),
            "separator-20260723_a.1",
        )
        for value in ("../escape", "/absolute", "contains/slash", "a..b", "", "空"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_baseline.validate_run_id(value)

    def test_complete_fake_run_and_refuse_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project 日本語"
            audio = project / "audio" / "canonical" / "mix.flac"
            write_fixture_wav(audio)

            worker_env = root / "separator env"
            bin_dir = worker_env / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").symlink_to(Path(sys.executable))
            fake_cli = bin_dir / "audio-separator"
            fake_cli.write_text(FAKE_SEPARATOR, encoding="utf-8")
            fake_cli.chmod(fake_cli.stat().st_mode | stat.S_IXUSR)

            model_dir = root / "models"
            model_dir.mkdir()
            model = model_dir / "fixture.ckpt"
            model.write_bytes(b"fixture weights")
            pins = {
                "schema_version": 1,
                "package": {"name": "audio-separator", "version": "0.44.5"},
                "runtime": {
                    "torch": "2.7.1",
                    "numpy": "2.2.6",
                    "numba": "0.61.2",
                    "onnxruntime": "1.27.0",
                    "onnxruntime_provider": "CPUExecutionProvider",
                    "ffmpeg": "8.1",
                },
                "presets": {
                    "fixture": {
                        "model_filename": model.name,
                        "friendly_name": "fixture",
                        "architecture": "MDXC",
                        "expected_stems": ["vocals", "instrumental"],
                        "custom_output_names": {
                            "Vocals": "vocals",
                            "Instrumental": "instrumental",
                        },
                        "parameters": {
                            "normalization": 1.0,
                            "amplification": 0.0,
                            "sample_rate": 44_100,
                            "autocast": False,
                            "chunk_duration_sec": None,
                            "mdxc_overlap": 8,
                            "mdxc_batch_size": 1,
                        },
                        "expected_files": [
                            {
                                "path": model.name,
                                "sha256": sha256_file(model),
                                "size_bytes": model.stat().st_size,
                                "source": "fixture",
                            }
                        ],
                        "license": {"weights": "fixture only"},
                    }
                },
            }
            pins_path = root / "pins.json"
            pins_path.write_text(json.dumps(pins), encoding="utf-8")

            diagnostics = {
                "python": "test",
                "platform": "test",
                "machine": "x86_64",
                "audio_separator": "0.44.5",
                "numpy": "2.2.6",
                "numba": "0.61.2",
                "onnxruntime": "1.27.0",
                "onnxruntime_providers": ["CPUExecutionProvider"],
                "ffmpeg": {
                    "path": "/fixture/bin/ffmpeg",
                    "version": "ffmpeg version 8.1 fixture",
                    "exit_code": 0,
                },
                "ffprobe": {
                    "path": "/fixture/bin/ffprobe",
                    "version": "ffprobe version 8.1 fixture",
                    "exit_code": 0,
                },
                "torch": "2.7.1+fixture",
                "cuda_available": True,
                "cuda_version": "test",
                "cuda_device_count": 1,
                "cuda_device_name": "fixture",
            }
            argv = [
                "--project",
                str(project),
                "--worker-env",
                str(worker_env),
                "--model-dir",
                str(model_dir),
                "--run-id",
                "separator-fixture",
                "--preset",
                "fixture",
                "--pins",
                str(pins_path),
            ]
            with (
                mock.patch.object(
                    run_baseline,
                    "worker_diagnostics",
                    return_value=diagnostics,
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = run_baseline.main(argv)

            self.assertEqual(exit_code, 0)
            run_dir = project / "runs" / "separator-fixture"
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["environment"]["cuda_device_name"], "fixture")
            self.assertFalse(manifest["metrics"]["accuracy_claimed"])
            self.assertFalse(manifest["metrics"]["subjective_listening_complete"])
            self.assertTrue((run_dir / "raw" / "stems" / "vocals.flac").is_file())
            self.assertGreater(len(manifest["outputs"]), 0)

            with self.assertRaisesRegex(RuntimeError, "immutable run directory"):
                run_baseline.main(argv)

            missing_ffmpeg = {
                **diagnostics,
                "ffmpeg": {"path": None, "version": None},
            }
            missing_ffmpeg_argv = list(argv)
            missing_ffmpeg_argv[missing_ffmpeg_argv.index("separator-fixture")] = (
                "separator-missing-ffmpeg"
            )
            with (
                mock.patch.object(
                    run_baseline,
                    "worker_diagnostics",
                    return_value=missing_ffmpeg,
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                missing_ffmpeg_exit_code = run_baseline.main(missing_ffmpeg_argv)

            self.assertEqual(missing_ffmpeg_exit_code, 1)
            missing_ffmpeg_manifest = json.loads(
                (project / "runs" / "separator-missing-ffmpeg" / "run_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(missing_ffmpeg_manifest["status"], "failed")
            self.assertIn(
                "working ffmpeg",
                missing_ffmpeg_manifest["error"]["message"],
            )

    def test_refuses_unpinned_model_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            model_dir = Path(temporary)
            model = model_dir / "fixture.ckpt"
            model.write_bytes(b"fixture")
            with self.assertRaisesRegex(RuntimeError, "hash is missing"):
                run_baseline.verify_model_files(
                    model_dir,
                    [
                        {
                            "path": model.name,
                            "sha256": None,
                            "size_bytes": model.stat().st_size,
                        }
                    ],
                )


if __name__ == "__main__":
    unittest.main()
