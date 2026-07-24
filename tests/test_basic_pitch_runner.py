from __future__ import annotations

import contextlib
import io
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import verify_run_manifest
from workers.basic_pitch import run_baseline

from amt_core.events import read_jsonl
from amt_core.utils import sha256_file

FAKE_BASIC_PITCH = r"""#!/usr/bin/env python3
import csv
import pathlib
import struct
import sys
import zipfile

args = sys.argv[1:]
if args == ["--help"]:
    print("fake Basic Pitch help")
    raise SystemExit(0)
output_dir = pathlib.Path(args[0])
audio = pathlib.Path(args[1])
prefix = f"{audio.stem}_basic_pitch"
output_dir.mkdir(parents=True, exist_ok=True)

track = b"\x00\x90\x43\x63\x60\x80\x43\x00\x00\xff\x2f\x00"
midi = (
    b"MThd"
    + struct.pack(">IHHH", 6, 1, 1, 480)
    + b"MTrk"
    + struct.pack(">I", len(track))
    + track
)
(output_dir / f"{prefix}.mid").write_bytes(midi)

header = b"{'descr': '|O', 'fortran_order': False, 'shape': (), }"
padding = (16 - ((10 + len(header) + 1) % 16)) % 16
header = header + (b" " * padding) + b"\n"
npy = b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header + b"\x00"
with zipfile.ZipFile(output_dir / f"{prefix}.npz", "w") as archive:
    archive.writestr("basic_pitch_model_output.npy", npy)

with (output_dir / f"{prefix}.csv").open("w", encoding="utf-8", newline="") as handle:
    writer = csv.writer(handle)
    writer.writerow(
        ["start_time_s", "end_time_s", "pitch_midi", "velocity", "pitch_bend"]
    )
    writer.writerow([0.25, 0.75, 67, 99, -10, 20])
"""

FAKE_SUCCESS_WITHOUT_OUTPUTS = """#!/usr/bin/env python3
import sys

if sys.argv[1:] == ["--help"]:
    print("fake help")
raise SystemExit(0)
"""


def create_project_fixture(root: Path) -> tuple[Path, Path]:
    project = root / "project 日本語"
    canonical = project / "audio" / "canonical" / "mix.flac"
    canonical.parent.mkdir(parents=True)
    canonical.write_bytes(b"canonical mix")

    separator_run = project / "runs" / "separator-selected-a"
    vocal_stem = separator_run / "raw" / "stems" / "vocals.flac"
    vocal_stem.parent.mkdir(parents=True)
    vocal_stem.write_bytes(b"selected separated vocals")
    manifest = {
        "schema_version": 1,
        "run_id": "separator-selected-a",
        "worker": "separator",
        "status": "succeeded",
        "preset": "vocal_quality_a",
        "inputs": [
            {
                "path": str(canonical.resolve()),
                "sha256": sha256_file(canonical),
            }
        ],
        "outputs": [
            {
                "path": "raw/stems/vocals.flac",
                "sha256": sha256_file(vocal_stem),
                "size_bytes": vocal_stem.stat().st_size,
            }
        ],
        "metrics": {
            "audio": {
                "mix": {"duration_sec": 10.0},
                "stems": {
                    "vocals": {
                        "duration_sec": 10.0,
                        "duration_drift_sec": 0.0,
                    }
                },
            }
        },
    }
    (separator_run / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return project, vocal_stem


def create_worker_fixture(root: Path, script: str) -> Path:
    worker_env = root / "worker env"
    bin_dir = worker_env / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").symlink_to(Path(sys.executable))
    cli = bin_dir / "basic-pitch"
    cli.write_text(script, encoding="utf-8")
    cli.chmod(cli.stat().st_mode | stat.S_IXUSR)
    return worker_env.resolve()


class BasicPitchRunnerTests(unittest.TestCase):
    def test_run_id_validation_rejects_path_escape(self) -> None:
        self.assertEqual(
            run_baseline.validate_run_id("basic-pitch-20260724_a.1"),
            "basic-pitch-20260724_a.1",
        )
        for value in ("../escape", "/absolute", "contains/slash", "a..b", "", "空"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_baseline.validate_run_id(value)

    def test_complete_fake_run_preserves_all_native_outputs_and_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, vocal_stem = create_project_fixture(root)
            worker_env = create_worker_fixture(root, FAKE_BASIC_PITCH)
            diagnostics = {
                "python": "3.10.20",
                "platform": "test",
                "machine": "x86_64",
                "basic_pitch": "0.4.0",
                "numpy": "1.26.4",
                "onnxruntime": "1.23.2",
                "setuptools": "80.9.0",
                "onnxruntime_available_providers": ["CPUExecutionProvider"],
                "model_type": "ONNX",
                "model_path": str(worker_env / "fake" / "nmp.onnx"),
                "model_session_providers": ["CPUExecutionProvider"],
            }
            argv = [
                "--project",
                str(project),
                "--audio",
                str(vocal_stem),
                "--worker-env",
                str(worker_env),
                "--run-id",
                "basic-pitch-fixture",
            ]
            with (
                mock.patch.object(
                    run_baseline,
                    "worker_diagnostics",
                    return_value=diagnostics,
                ),
                mock.patch.object(
                    run_baseline,
                    "verify_worker_environment",
                    return_value={
                        "path": diagnostics["model_path"],
                        "filename": "nmp.onnx",
                        "sha256": "fixture",
                        "size_bytes": 1,
                    },
                ),
                mock.patch.object(
                    run_baseline,
                    "probe_midi",
                    return_value={
                        "format": 1,
                        "track_count": 1,
                        "division": 480,
                        "track_sizes": [12],
                        "note_on_count": 1,
                        "length_sec": 0.1,
                    },
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = run_baseline.main(argv)

            self.assertEqual(exit_code, 0)
            run_dir = project / "runs" / "basic-pitch-fixture"
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["worker"], "basic_pitch")
            self.assertEqual(
                manifest["input_lineage"]["kind"],
                "separator_vocal_stem",
            )
            self.assertEqual(
                manifest["input_lineage"]["canonical_mix_sha256"],
                sha256_file(project / "audio" / "canonical" / "mix.flac"),
            )
            self.assertEqual(
                manifest["input_lineage"]["parent_stem_sha256"],
                sha256_file(vocal_stem),
            )
            self.assertEqual(
                manifest["environment"]["model_session_providers"],
                ["CPUExecutionProvider"],
            )
            command = manifest["command"]
            self.assertEqual(
                command[command.index("--model-serialization") + 1],
                "onnx",
            )
            self.assertIn("--save-midi", command)
            self.assertIn("--save-model-outputs", command)
            self.assertIn("--save-note-events", command)
            self.assertNotIn("--minimum-frequency", command)
            self.assertNotIn("--maximum-frequency", command)
            self.assertNotIn("--multiple-pitch-bends", command)
            self.assertNotIn("--no-melodia", command)
            self.assertNotIn("--sonify-midi", command)
            self.assertEqual(request["decoding"], manifest["decoding"])
            for suffix in ("mid", "npz", "csv"):
                self.assertTrue(
                    (run_dir / "raw" / "native" / f"vocals_basic_pitch.{suffix}").is_file()
                )
            events = read_jsonl(run_dir / "normalized" / "events.jsonl")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].pitch_midi, 67.0)
            self.assertTrue(events[0].is_main_melody_candidate)
            self.assertEqual(
                manifest["validation"]["model_outputs_npz"]["members"],
                ["basic_pitch_model_output.npy"],
            )
            self.assertGreater(len(manifest["outputs"]), 0)
            verifier_args = [
                "--run-dir",
                str(run_dir),
                "--worker",
                "basic_pitch",
                "--input",
                str(vocal_stem),
                "--repo-root",
                str(run_baseline.REPO_ROOT),
            ]
            for source in (
                run_baseline.DEFAULT_PINS,
                run_baseline.WORKER_DIR / "pyproject.toml",
                run_baseline.WORKER_DIR / "uv.lock",
                run_baseline.WORKER_DIR / "normalize.py",
                Path(run_baseline.__file__).resolve(),
                run_baseline.REPO_ROOT / "scripts" / "verify_run_manifest.py",
                run_baseline.REPO_ROOT / "slurm" / "22_basic_pitch_baseline.slurm",
            ):
                verifier_args.extend(["--source", str(source)])
            verifier_args.extend(
                [
                    "--expect-field",
                    'model_provenance.serialization="onnx"',
                    "--require-output",
                    "raw/native/vocals_basic_pitch.mid",
                    "--require-output",
                    "raw/native/vocals_basic_pitch.npz",
                    "--require-output",
                    "raw/native/vocals_basic_pitch.csv",
                    "--require-output",
                    "normalized/events.jsonl",
                    "--quiet",
                ]
            )
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(verify_run_manifest.main(verifier_args), 0)

            with self.assertRaisesRegex(RuntimeError, "immutable run directory"):
                run_baseline.main(argv)

    def test_zero_exit_without_native_outputs_is_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, vocal_stem = create_project_fixture(root)
            worker_env = create_worker_fixture(root, FAKE_SUCCESS_WITHOUT_OUTPUTS)
            diagnostics = {
                "python": "3.10.20",
                "platform": "test",
                "machine": "x86_64",
                "basic_pitch": "0.4.0",
                "numpy": "1.26.4",
                "onnxruntime": "1.23.2",
                "setuptools": "80.9.0",
                "onnxruntime_available_providers": ["CPUExecutionProvider"],
                "model_type": "ONNX",
                "model_path": str(worker_env / "fake" / "nmp.onnx"),
                "model_session_providers": ["CPUExecutionProvider"],
            }
            with (
                mock.patch.object(
                    run_baseline,
                    "worker_diagnostics",
                    return_value=diagnostics,
                ),
                mock.patch.object(
                    run_baseline,
                    "verify_worker_environment",
                    return_value={"path": diagnostics["model_path"]},
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = run_baseline.main(
                    [
                        "--project",
                        str(project),
                        "--audio",
                        str(vocal_stem),
                        "--worker-env",
                        str(worker_env),
                        "--run-id",
                        "missing-native-output",
                    ]
                )

            self.assertEqual(exit_code, 1)
            manifest = json.loads(
                (project / "runs" / "missing-native-output" / "run_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(manifest["status"], "failed")
            self.assertIn("MIDI output is missing", manifest["error"]["message"])

    def test_worker_environment_requires_pinned_cpu_onnx_model(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            worker_env = Path(temporary).resolve()
            model_path = worker_env / "lib" / "nmp.onnx"
            model_path.parent.mkdir()
            model_path.write_bytes(b"fake onnx")
            pins = json.loads(run_baseline.DEFAULT_PINS.read_text(encoding="utf-8"))
            pins["model"]["sha256"] = sha256_file(model_path)
            pins["model"]["size_bytes"] = model_path.stat().st_size
            diagnostics = {
                "python": "3.10.20",
                "basic_pitch": pins["package"]["version"],
                "numpy": pins["runtime"]["numpy"],
                "onnxruntime": pins["runtime"]["onnxruntime"],
                "setuptools": pins["runtime"]["setuptools"],
                "onnxruntime_available_providers": ["CPUExecutionProvider"],
                "model_type": "ONNX",
                "model_path": str(model_path),
                "model_session_providers": ["CPUExecutionProvider"],
            }
            verified = run_baseline.verify_worker_environment(
                worker_env,
                diagnostics,
                pins,
            )
            self.assertEqual(verified["sha256"], sha256_file(model_path))

            diagnostics["model_session_providers"] = [
                "CUDAExecutionProvider",
                "CPUExecutionProvider",
            ]
            with self.assertRaisesRegex(RuntimeError, "not CPU-only"):
                run_baseline.verify_worker_environment(
                    worker_env,
                    diagnostics,
                    pins,
                )

    def test_native_midi_note_count_must_match_decoded_csv(self) -> None:
        run_baseline.verify_native_event_count({"note_on_count": 1}, 1)
        with self.assertRaisesRegex(RuntimeError, "does not match decoded CSV events"):
            run_baseline.verify_native_event_count({"note_on_count": 0}, 1)
        with self.assertRaisesRegex(RuntimeError, "invalid note-on count"):
            run_baseline.verify_native_event_count({"note_on_count": True}, 1)

    def test_rejects_non_separator_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, _ = create_project_fixture(root)
            canonical = project / "audio" / "canonical" / "mix.flac"
            with self.assertRaisesRegex(ValueError, "separator vocal stem"):
                run_baseline.input_lineage(
                    project.resolve(),
                    canonical.resolve(),
                    audio_sha256=sha256_file(canonical),
                )

    def test_rejects_separator_parent_bound_to_stale_canonical_mix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project, vocal_stem = create_project_fixture(root)
            canonical = project / "audio" / "canonical" / "mix.flac"
            canonical.write_bytes(b"replacement canonical mix")

            with self.assertRaisesRegex(RuntimeError, "current canonical mix"):
                run_baseline.input_lineage(
                    project.resolve(),
                    vocal_stem.resolve(),
                    audio_sha256=sha256_file(vocal_stem),
                )

    def test_slurm_reuse_binds_current_canonical_and_parent_manifest_hashes(self) -> None:
        script = (run_baseline.REPO_ROOT / "slurm" / "22_basic_pitch_baseline.slurm").read_text(
            encoding="utf-8"
        )
        self.assertIn('CANONICAL_MIX="$PROJECT_DIR/audio/canonical/mix.flac"', script)
        self.assertIn('PARENT_MANIFEST="$PARENT_RUN_DIR/run_manifest.json"', script)
        self.assertIn(
            '--expect-field "input_lineage.canonical_mix_sha256=\\"$CANONICAL_SHA\\""',
            script,
        )
        self.assertIn(
            '--expect-field "input_lineage.parent_manifest_sha256=\\"$PARENT_MANIFEST_SHA\\""',
            script,
        )


if __name__ == "__main__":
    unittest.main()
