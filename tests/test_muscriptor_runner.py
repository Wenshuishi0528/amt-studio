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

from workers.muscriptor import run_baseline

from amt_core.events import read_jsonl
from amt_core.utils import sha256_file

FAKE_MUSCRIPTOR = """#!/usr/bin/env python3
import json
import pathlib
import sys

args = sys.argv[1:]
if args == ["list-instruments"]:
    print("acoustic_piano")
    raise SystemExit(0)
if not args or args == ["--help"] or args == ["transcribe", "--help"]:
    print("fake muscriptor help")
    raise SystemExit(0)
if args[0] != "transcribe":
    raise SystemExit(2)
output = pathlib.Path(args[args.index("--output") + 1])
output.parent.mkdir(parents=True, exist_ok=True)
format_name = args[args.index("--format") + 1]
instrument = (
    args[args.index("--instruments") + 1].split(",")[0]
    if "--instruments" in args
    else "acoustic_piano"
)
if format_name == "jsonl":
    values = [
        {
            "type": "start",
            "pitch": 60,
            "start_time": 0.1,
            "index": 0,
            "instrument": instrument,
        },
        {"type": "end", "end_time": 0.8, "start_event_index": 0},
    ]
    output.write_text(
        "".join(json.dumps(value) + "\\n" for value in values),
        encoding="utf-8",
    )
elif format_name == "midi":
    output.write_bytes(b"MThdFAKE")
else:
    raise SystemExit(2)
"""


class MuScriptorRunnerTests(unittest.TestCase):
    def test_run_id_validation_rejects_path_escape(self) -> None:
        self.assertEqual(
            run_baseline.validate_run_id("muscriptor-20260723_a.1"),
            "muscriptor-20260723_a.1",
        )
        for value in ("../escape", "/absolute", "contains/slash", "a..b", "", "空"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_baseline.validate_run_id(value)

    def test_complete_fake_run_and_refuse_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project 日本語"
            audio = project / "audio" / "canonical" / "mix.flac"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"fake flac")

            worker_env = root / "worker env"
            bin_dir = worker_env / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").symlink_to(Path(sys.executable))
            fake_cli = bin_dir / "muscriptor"
            fake_cli.write_text(FAKE_MUSCRIPTOR, encoding="utf-8")
            fake_cli.chmod(fake_cli.stat().st_mode | stat.S_IXUSR)

            model_dir = root / "model"
            model_dir.mkdir()
            weight = model_dir / "model.safetensors"
            config = model_dir / "config.json"
            weight.write_bytes(b"fake weights")
            config.write_text("{}\n", encoding="utf-8")

            pins = json.loads(run_baseline.DEFAULT_PINS.read_text(encoding="utf-8"))
            provenance = {
                "schema_version": 1,
                "repository": pins["model"]["repository"],
                "revision": pins["model"]["revision"],
                "license": pins["model"]["license"],
                "weight": {
                    "filename": weight.name,
                    "path": str(weight),
                    "sha256": sha256_file(weight),
                    "size_bytes": weight.stat().st_size,
                },
                "config": {
                    "filename": config.name,
                    "path": str(config),
                    "sha256": sha256_file(config),
                    "size_bytes": config.stat().st_size,
                },
            }
            provenance_path = root / "provenance.json"
            provenance_path.write_text(
                json.dumps(provenance),
                encoding="utf-8",
            )

            diagnostics = {
                "python": "test",
                "platform": "test",
                "machine": "arm64",
                "muscriptor": pins["package"]["version"],
                "torch": "test",
                "mps_built": True,
                "mps_available": True,
                "cuda_available": False,
                "cuda_version": None,
                "cuda_device_count": 0,
            }
            argv = [
                "--project",
                str(project),
                "--worker-env",
                str(worker_env),
                "--weight-provenance",
                str(provenance_path),
                "--run-id",
                "fixture-run",
                "--beam-size",
                "1",
                "--device",
                "mps",
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
            run_dir = project / "runs" / "fixture-run"
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["decoding"]["beam_size"], 1)
            self.assertIsNone(manifest["decoding"]["instruments"])
            self.assertEqual(manifest["decoding"]["device"], "mps")
            self.assertFalse(manifest["decoding"]["skip_midi"])
            self.assertIn("midi", manifest["commands"])
            self.assertIn("midi", manifest["timings"])
            self.assertNotIn("--instruments", manifest["commands"]["jsonl"])
            self.assertTrue((run_dir / "raw" / "events.native.jsonl").is_file())
            self.assertEqual(
                (run_dir / "raw" / "full.native.mid").read_bytes(),
                b"MThdFAKE",
            )
            events = read_jsonl(run_dir / "normalized" / "events.jsonl")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].instrument, "acoustic_piano")
            self.assertGreater(len(manifest["outputs"]), 0)

            with self.assertRaisesRegex(RuntimeError, "immutable run directory"):
                run_baseline.main(argv)

            failed_argv = list(argv)
            failed_argv[failed_argv.index("fixture-run")] = "diagnostics-failure"
            with (
                mock.patch.object(
                    run_baseline,
                    "worker_diagnostics",
                    side_effect=RuntimeError("diagnostics boom"),
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                failed_exit_code = run_baseline.main(failed_argv)

            self.assertEqual(failed_exit_code, 1)
            failed_manifest = json.loads(
                (project / "runs" / "diagnostics-failure" / "run_manifest.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(failed_manifest["status"], "failed")
            self.assertEqual(failed_manifest["error"]["message"], "diagnostics boom")
            self.assertIsNone(failed_manifest["environment"])

    def test_voice_jsonl_only_run_records_parent_stem_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project 日本語"
            canonical = project / "audio" / "canonical" / "mix.flac"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"canonical mix")

            separator_run = project / "runs" / "separator-a"
            vocal_stem = separator_run / "raw" / "stems" / "vocals.flac"
            vocal_stem.parent.mkdir(parents=True)
            vocal_stem.write_bytes(b"separated vocals")
            separator_manifest = {
                "schema_version": 1,
                "run_id": "separator-a",
                "worker": "separator",
                "status": "succeeded",
                "preset": "vocal-quality-a",
                "inputs": [
                    {
                        "path": str(canonical),
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
                json.dumps(separator_manifest),
                encoding="utf-8",
            )

            worker_env = root / "worker env"
            bin_dir = worker_env / "bin"
            bin_dir.mkdir(parents=True)
            (bin_dir / "python").symlink_to(Path(sys.executable))
            fake_cli = bin_dir / "muscriptor"
            fake_cli.write_text(FAKE_MUSCRIPTOR, encoding="utf-8")
            fake_cli.chmod(fake_cli.stat().st_mode | stat.S_IXUSR)

            model_dir = root / "model"
            model_dir.mkdir()
            weight = model_dir / "model.safetensors"
            config = model_dir / "config.json"
            weight.write_bytes(b"fake weights")
            config.write_text("{}\n", encoding="utf-8")

            pins = json.loads(run_baseline.DEFAULT_PINS.read_text(encoding="utf-8"))
            provenance = {
                "schema_version": 1,
                "repository": pins["model"]["repository"],
                "revision": pins["model"]["revision"],
                "license": pins["model"]["license"],
                "weight": {
                    "filename": weight.name,
                    "path": str(weight),
                    "sha256": sha256_file(weight),
                    "size_bytes": weight.stat().st_size,
                },
                "config": {
                    "filename": config.name,
                    "path": str(config),
                    "sha256": sha256_file(config),
                    "size_bytes": config.stat().st_size,
                },
            }
            provenance_path = root / "provenance.json"
            provenance_path.write_text(
                json.dumps(provenance),
                encoding="utf-8",
            )

            diagnostics = {
                "python": "test",
                "platform": "test",
                "machine": "x86_64",
                "muscriptor": pins["package"]["version"],
                "torch": "test",
                "mps_built": False,
                "mps_available": False,
                "cuda_available": True,
                "cuda_version": "test",
                "cuda_device_count": 1,
            }
            argv = [
                "--project",
                str(project),
                "--audio",
                str(vocal_stem),
                "--worker-env",
                str(worker_env),
                "--weight-provenance",
                str(provenance_path),
                "--run-id",
                "voice-jsonl-only",
                "--beam-size",
                "4",
                "--device",
                "cuda",
                "--dtype",
                "float32",
                "--instruments",
                " Voice ",
                "--skip-midi",
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
            run_dir = project / "runs" / "voice-jsonl-only"
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            request = json.loads((run_dir / "request.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["decoding"]["instruments"], ["voice"])
            self.assertEqual(manifest["decoding"]["dtype"], "float32")
            self.assertEqual(manifest["decoding"]["device"], "cuda")
            self.assertTrue(manifest["decoding"]["skip_midi"])
            self.assertEqual(set(manifest["commands"]), {"jsonl"})
            self.assertEqual(set(manifest["timings"]), {"jsonl"})
            self.assertEqual(request["skip_midi"], True)
            command = manifest["commands"]["jsonl"]
            instrument_index = command.index("--instruments")
            self.assertEqual(command[instrument_index + 1], "voice")
            self.assertFalse((run_dir / "raw" / "full.native.mid").exists())
            self.assertFalse((run_dir / "logs" / "transcribe-midi.stdout").exists())
            self.assertEqual(
                manifest["input_lineage"]["canonical_mix_sha256"],
                sha256_file(canonical),
            )
            self.assertEqual(
                manifest["input_lineage"]["parent_stem_sha256"],
                sha256_file(vocal_stem),
            )
            events = read_jsonl(run_dir / "normalized" / "events.jsonl")
            self.assertEqual(events[0].instrument, "voice")

    def test_instrument_list_validation(self) -> None:
        self.assertEqual(
            run_baseline.normalize_instruments(" Voice, Acoustic_Piano "),
            ["voice", "acoustic_piano"],
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            run_baseline.normalize_instruments("voice,VOICE")
        with self.assertRaisesRegex(ValueError, "comma-separated"):
            run_baseline.normalize_instruments("voice,")


if __name__ == "__main__":
    unittest.main()
