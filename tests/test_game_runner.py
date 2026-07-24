from __future__ import annotations

import contextlib
import copy
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from workers.game import run_baseline

from amt_core.events import read_jsonl
from amt_core.utils import sha256_file


class GameRunnerTests(unittest.TestCase):
    def test_native_midi_note_count_must_match_decoded_csv(self) -> None:
        run_baseline.verify_native_event_count({"note_on_count": 1}, 1)
        with self.assertRaisesRegex(RuntimeError, "does not match decoded CSV events"):
            run_baseline.verify_native_event_count({"note_on_count": 0}, 1)
        with self.assertRaisesRegex(RuntimeError, "invalid note-on count"):
            run_baseline.verify_native_event_count({"note_on_count": True}, 1)

    def test_run_id_validation_rejects_path_escape(self) -> None:
        self.assertEqual(
            run_baseline.validate_run_id("game-task004_20260724.1"),
            "game-task004_20260724.1",
        )
        for value in ("../escape", "/absolute", "contains/slash", "a..b", "", "空"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                run_baseline.validate_run_id(value)

    def test_worker_environment_is_bound_to_runtime_pins(self) -> None:
        pins = json.loads(run_baseline.DEFAULT_PINS.read_text(encoding="utf-8"))
        diagnostics = {
            "python": "3.12.13",
            "torch": "2.8.0+cu129",
            "lightning": "2.6.1",
            "numpy": "1.26.4",
            "librosa": "0.11.0",
            "colorednoise": "2.2.0",
            "h5py": "3.16.0",
            "matplotlib": "3.11.1",
            "mido": "1.3.3",
            "cuda_available": True,
            "cuda_version": "12.9",
            "cuda_device_count": 1,
        }
        run_baseline.verify_worker_environment(diagnostics, pins, require_cuda=True)
        diagnostics["h5py"] = "changed"
        with self.assertRaisesRegex(RuntimeError, "h5py does not match pins"):
            run_baseline.verify_worker_environment(diagnostics, pins, require_cuda=True)

    def test_input_lineage_rejects_direct_mix(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            canonical = project / "audio" / "canonical" / "mix.flac"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"mix")
            with self.assertRaisesRegex(ValueError, "selected separator vocal stem"):
                run_baseline.input_lineage(
                    project,
                    canonical.resolve(),
                    audio_sha256=sha256_file(canonical),
                )

    def test_complete_fake_run_records_contract_and_refuses_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project 日本語"
            canonical = project / "audio" / "canonical" / "mix.flac"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"canonical mix")
            separator_run = project / "runs" / "separator-selected-a"
            audio = separator_run / "raw" / "stems" / "vocals.flac"
            audio.parent.mkdir(parents=True)
            audio.write_bytes(b"selected vocal stem")
            (separator_run / "run_manifest.json").write_text(
                json.dumps(
                    {
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
                                "sha256": sha256_file(audio),
                                "size_bytes": audio.stat().st_size,
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
                ),
                encoding="utf-8",
            )
            worker_env = root / "worker env"
            (worker_env / "bin").mkdir(parents=True)
            (worker_env / "bin" / "python").symlink_to(Path(sys.executable))
            provenance = root / "model provenance.json"
            provenance.write_text('{"schema_version": 1}\n', encoding="utf-8")
            infer_script = root / "GAME source" / "infer.py"
            infer_script.parent.mkdir()
            infer_script.write_text("# fake\n", encoding="utf-8")
            model_path = infer_script.parent / "model.pt"
            model_path.write_bytes(b"model")

            diagnostics = {
                "python": "3.12.13",
                "platform": "test",
                "machine": "x86_64",
                "torch": "2.8.0+cu129",
                "lightning": "2.6.1",
                "librosa": "0.11.0",
                "numpy": "1.26.4",
                "colorednoise": "2.2.0",
                "h5py": "3.16.0",
                "matplotlib": "3.11.1",
                "mido": "1.3.3",
                "cuda_available": True,
                "cuda_version": "12.9",
                "cuda_device_count": 1,
                "cuda_device_name": "fixture",
                "cuda_device_capability": [8, 0],
            }

            def fake_run_logged(
                argv: list[str],
                *,
                stdout_path: Path,
                stderr_path: Path,
                cwd: Path,
                env: dict[str, str],
            ) -> dict[str, object]:
                del cwd
                self.assertEqual(env["PYTHONHASHSEED"], "3407")
                output_dir = Path(argv[argv.index("--output-dir") + 1])
                output_stem = Path(argv[argv.index("extract") + 1]).stem
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / f"{output_stem}.csv").write_text(
                    "onset,offset,pitch\n0.100,0.800,60.250\n",
                    encoding="utf-8",
                )
                (output_dir / f"{output_stem}.txt").write_text(
                    "0.100\t0.800\t60.250\n",
                    encoding="utf-8",
                )
                (output_dir / f"{output_stem}.mid").write_bytes(b"MThdFAKE")
                stdout_path.write_text("ok\n", encoding="utf-8")
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

            argv = [
                "--project",
                str(project),
                "--audio",
                str(audio),
                "--worker-env",
                str(worker_env),
                "--model-provenance",
                str(provenance),
                "--run-id",
                "game-fixture",
                "--require-cuda",
            ]
            model_provenance = {
                "provenance_path": str(provenance),
                "provenance_sha256": "fixture",
                "source": {},
                "archive": {},
                "model": {},
                "code_license": "MIT",
                "model_license": "CC-BY-NC-SA-4.0",
                "commercial_use": False,
            }
            with (
                mock.patch.object(
                    run_baseline,
                    "verify_model_assets",
                    return_value=(infer_script, model_path, model_provenance),
                ),
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
                        "duration_sec": 10.0,
                        "sample_rate": 44100,
                        "channels": 2,
                    },
                ),
                mock.patch.object(run_baseline, "run_logged", side_effect=fake_run_logged),
                mock.patch.object(
                    run_baseline,
                    "probe_midi",
                    return_value={
                        "type": 1,
                        "ticks_per_beat": 480,
                        "track_count": 1,
                        "note_on_count": 1,
                        "length_sec": 0.8,
                    },
                ),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                exit_code = run_baseline.main(argv)

            self.assertEqual(exit_code, 0)
            run_dir = project / "runs" / "game-fixture"
            manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "succeeded")
            self.assertEqual(manifest["worker"], "game")
            self.assertEqual(manifest["input_lineage"]["kind"], "separator_vocal_stem")
            self.assertEqual(manifest["decoding"]["language"], "ja")
            self.assertEqual(manifest["decoding"]["seed"], 3407)
            self.assertFalse(manifest["metrics"]["accuracy_claimed"])
            self.assertFalse(manifest["model_provenance"]["commercial_use"])
            events = read_jsonl(run_dir / "normalized" / "events.jsonl")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].pitch_midi, 60.25)

            with (
                mock.patch.object(
                    run_baseline,
                    "verify_model_assets",
                    return_value=(infer_script, model_path, model_provenance),
                ),
                contextlib.redirect_stdout(io.StringIO()),
                self.assertRaisesRegex(RuntimeError, "immutable run directory"),
            ):
                run_baseline.main(argv)

    def test_model_provenance_cannot_redirect_to_unpinned_external_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_dir = root / "source"
            source_dir.mkdir()
            infer_script = source_dir / "infer.py"
            infer_script.write_text("# pinned infer\n", encoding="utf-8")

            model_dir = root / "model"
            bundle_dir = model_dir / "bundle"
            bundle_dir.mkdir(parents=True)
            pinned_model = bundle_dir / "model.pt"
            pinned_config = bundle_dir / "config.yaml"
            pinned_lang_map = bundle_dir / "lang_map.json"
            pinned_model.write_bytes(b"pinned model")
            pinned_config.write_text("pinned: true\n", encoding="utf-8")
            pinned_lang_map.write_text('{"ja": 2}\n', encoding="utf-8")
            records = [
                {
                    "path": path.relative_to(model_dir).as_posix(),
                    "sha256": sha256_file(path),
                    "size_bytes": path.stat().st_size,
                }
                for path in sorted((pinned_model, pinned_config, pinned_lang_map))
            ]

            pins = copy.deepcopy(json.loads(run_baseline.DEFAULT_PINS.read_text(encoding="utf-8")))
            pins["model"]["expected_files"] = records
            pins_path = root / "pins.json"
            pins_path.write_text(json.dumps(pins), encoding="utf-8")

            external = root / "external"
            external.mkdir()
            external_model = external / "model.pt"
            external_config = external / "config.yaml"
            external_lang_map = external / "lang_map.json"
            external_model.write_bytes(b"untrusted model")
            external_config.write_text("untrusted: true\n", encoding="utf-8")
            external_lang_map.write_text('{"ja": 2}\n', encoding="utf-8")

            provenance = {
                "schema_version": 1,
                "source": {
                    "path": str(source_dir),
                    "commit": pins["package"]["upstream_git_commit"],
                    "infer_script": str(infer_script),
                    "infer_script_sha256": sha256_file(infer_script),
                },
                "archive": {
                    "sha256": pins["model"]["archive_sha256"],
                    "size_bytes": pins["model"]["archive_size_bytes"],
                },
                "model": {
                    "directory": str(model_dir),
                    "files": records,
                    "model_path": str(external_model),
                    "model_relative_path": pinned_model.relative_to(model_dir).as_posix(),
                    "config_path": str(external_config),
                    "config_relative_path": pinned_config.relative_to(model_dir).as_posix(),
                    "lang_map_path": str(external_lang_map),
                    "lang_map_relative_path": pinned_lang_map.relative_to(model_dir).as_posix(),
                },
                "pins": {"sha256": sha256_file(pins_path)},
            }
            provenance_path = root / "provenance.json"
            provenance_path.write_text(json.dumps(provenance), encoding="utf-8")

            with (
                mock.patch.object(
                    run_baseline,
                    "upstream_git_state",
                    return_value={
                        "commit": pins["package"]["upstream_git_commit"],
                        "dirty": False,
                    },
                ),
                self.assertRaisesRegex(
                    RuntimeError,
                    "absolute path does not match its pinned relative path",
                ),
            ):
                run_baseline.verify_model_assets(
                    pins,
                    provenance,
                    pins_path=pins_path,
                    provenance_path=provenance_path,
                )


if __name__ == "__main__":
    unittest.main()
