from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workers.beat_this import run_baseline

from amt_core.contracts import load_worker_request, load_worker_result
from amt_core.utils import atomic_write_json, sha256_file


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
    path.write_bytes(
        b"\x93NUMPY\x01\x00"
        + struct.pack("<H", len(header))
        + header
        + b"\x00" * (shape[0] * shape[1] * 4)
    )


class BeatThisRunnerTests(unittest.TestCase):
    def test_run_id_validation_rejects_path_escape(self) -> None:
        self.assertEqual(
            run_baseline.validate_run_id("beat-this-task005.1"),
            "beat-this-task005.1",
        )
        for value in ("../escape", "/absolute", "contains/slash", "a..b", "", "空"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_baseline.validate_run_id(value)

    def test_complete_fake_run_writes_versioned_contract_and_native_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_repo = root / "repo"
            fake_worker = fake_repo / "workers" / "beat_this"
            worker_env = fake_worker / ".venv"
            (worker_env / "bin").mkdir(parents=True)
            (worker_env / "bin" / "python").symlink_to(Path(sys.executable))
            (worker_env / "bin" / "beat_this").write_text("# fixture\n", encoding="utf-8")

            checkpoint = root / "private assets" / "final0.ckpt"
            checkpoint.parent.mkdir()
            checkpoint.write_bytes(b"fixture checkpoint")
            pins = {
                "schema_version": 1,
                "package": {
                    "name": "beat-this",
                    "version": "1.1.0",
                    "upstream_git_commit": "a" * 40,
                },
                "runtime": {
                    "torch_distribution": "2.8.0+cu129",
                    "torchaudio_distribution": "2.8.0+cu129",
                    "cuda_runtime": "12.9",
                    "numpy": "1.26.4",
                    "soundfile": "0.13.1",
                },
                "model": {
                    "name": "final0",
                    "filename": checkpoint.name,
                    "sha256": sha256_file(checkpoint),
                    "size_bytes": checkpoint.stat().st_size,
                },
                "decoding": {
                    "dbn": False,
                    "float16": False,
                    "gpu_index": 0,
                    "activations": True,
                    "postprocessor": "minimal",
                    "frame_rate_hz": 50,
                },
            }
            pins_path = fake_worker / "pins.json"
            atomic_write_json(pins_path, pins)

            project = root / "project"
            canonical = project / "audio" / "canonical" / "mix.flac"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"fixture canonical mix")
            atomic_write_json(
                project / "manifest.json",
                {
                    "schema_version": 1,
                    "project_id": project.name,
                    "canonical_audio": {
                        "path": "audio/canonical/mix.flac",
                        "sha256": sha256_file(canonical),
                    },
                },
            )
            ffprobe = root / "ffprobe"
            ffprobe.write_text("fixture\n", encoding="utf-8")
            diagnostics = {
                "python": "3.12.11",
                "platform": "fixture",
                "machine": "x86_64",
                "beat_this": "1.1.0",
                "torch": "2.8.0+cu129",
                "torchaudio": "2.8.0+cu129",
                "numpy": "1.26.4",
                "soundfile": "0.13.1",
                "soxr": "1.0.0",
                "einops": "0.8.1",
                "rotary_embedding_torch": "0.8.9",
                "cuda_available": True,
                "cuda_version": "12.9",
                "cuda_device_count": 1,
                "cuda_device_name": "fixture GPU",
                "checkpoint_keys": ["hyper_parameters", "state_dict"],
            }

            def fake_run_logged(
                argv: list[str],
                *,
                stdout_path: Path,
                stderr_path: Path,
            ) -> dict[str, object]:
                output = Path(argv[argv.index("--output") + 1])
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    "\n".join(f"{index * 0.5:.2f}\t{index % 4 + 1}" for index in range(9)) + "\n",
                    encoding="utf-8",
                )
                _write_npy(output.with_suffix(".npy"), (2, 201))
                stdout_path.write_text("fixture success\n", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                return {
                    "argv": argv,
                    "started_at": "fixture",
                    "ended_at": "fixture",
                    "wall_time_sec": 1.0,
                    "exit_code": 0,
                    "peak_child_rss_bytes": 1,
                    "stdout": str(stdout_path),
                    "stderr": str(stderr_path),
                }

            completed = run_baseline.subprocess.CompletedProcess(
                args=["fixture"],
                returncode=0,
                stdout="fixture help\n",
                stderr="",
            )
            argv = [
                "--project",
                str(project),
                "--worker-env",
                str(worker_env),
                "--checkpoint",
                str(checkpoint),
                "--run-id",
                "beat-fixture",
                "--pins",
                str(pins_path),
                "--ffprobe",
                str(ffprobe),
                "--require-cuda",
            ]
            with (
                mock.patch.object(run_baseline, "WORKER_DIR", fake_worker),
                mock.patch.object(run_baseline, "REPO_ROOT", fake_repo),
                mock.patch.object(
                    run_baseline,
                    "worker_diagnostics",
                    return_value=diagnostics,
                ),
                mock.patch.object(
                    run_baseline,
                    "probe_audio",
                    return_value={
                        "command": ["ffprobe"],
                        "duration_sec": 4.0,
                        "sample_rate": 44100,
                        "channels": 2,
                    },
                ),
                mock.patch.object(run_baseline, "run_capture", return_value=completed),
                mock.patch.object(run_baseline, "run_logged", side_effect=fake_run_logged),
                mock.patch.object(run_baseline, "source_records", return_value=[]),
            ):
                exit_code = run_baseline.main(argv)

            self.assertEqual(exit_code, 0)
            run_dir = project / "runs" / "beat-fixture"
            result = load_worker_result(run_dir)
            request = load_worker_request(run_dir / "request.json")
            rhythm = result.read_rhythm_map()
            manifest = result.manifest
            self.assertEqual(manifest["contract_version"], "amt-worker-result/v1")
            self.assertEqual(request.contract_version, "amt-worker-request/v1")
            self.assertEqual(request.configuration, manifest["configuration"])
            self.assertEqual(manifest["worker"], "beat_this")
            self.assertEqual(
                manifest["input_lineage"]["canonical_mix_sha256"],
                sha256_file(canonical),
            )
            self.assertEqual(len(rhythm["events"]), 9)
            self.assertFalse(rhythm["uncertainty"]["event_confidence_available"])
            self.assertIn("raw/native/mix.beats", result.outputs)
            self.assertIn("raw/native/mix.npy", result.outputs)

            with (
                mock.patch.object(run_baseline, "WORKER_DIR", fake_worker),
                mock.patch.object(run_baseline, "REPO_ROOT", fake_repo),
                mock.patch.object(
                    run_baseline,
                    "worker_diagnostics",
                    return_value=diagnostics,
                ),
                self.assertRaises(FileExistsError),
            ):
                run_baseline.main(argv)


if __name__ == "__main__":
    unittest.main()
