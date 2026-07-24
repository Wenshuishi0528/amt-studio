from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from scripts import verify_run_manifest
from tests.test_separator_compare import _fixture as _comparison_fixture
from workers.separator import compare_amt

REPO_ROOT = Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return verify_run_manifest.sha256_file(path)


def _write_run(
    root: Path,
    *,
    run_id: str = "separator-test",
    worker: str = "separator",
    preset: str | None = "vocal_quality_a",
) -> tuple[Path, Path]:
    run_dir = root / "project 日本語" / "runs" / run_id
    output = run_dir / "raw" / "stems" / "vocals sample.flac"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"verified stem bytes")
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "worker": worker,
        "preset": preset,
        "status": "succeeded",
        "outputs": [
            {
                "path": "raw/stems/vocals sample.flac",
                "sha256": _sha256(output),
                "size_bytes": output.stat().st_size,
            }
        ],
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return run_dir, output


def _write_complete_run(
    project: Path,
    *,
    run_id: str,
    worker: str,
    output_paths: tuple[str, ...],
    preset: str | None = None,
) -> Path:
    run_dir = project / "runs" / run_id
    records: list[dict[str, object]] = []
    for relative_path in output_paths:
        output = run_dir.joinpath(*relative_path.split("/"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(f"{run_id}:{relative_path}".encode())
        records.append(
            {
                "path": relative_path,
                "sha256": _sha256(output),
                "size_bytes": output.stat().st_size,
            }
        )
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "worker": worker,
        "preset": preset,
        "status": "succeeded",
        "outputs": records,
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    return run_dir


def _slurm_test_environment(project: Path) -> dict[str, str]:
    return {
        **os.environ,
        "SLURM_JOB_ID": "fixture-job",
        "AMT_REPO_ROOT": str(REPO_ROOT),
        "AMT_ROOT_PYTHON": sys.executable,
        "PROJECT_DIR": str(project),
    }


def _source_records(paths: tuple[Path, ...]) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for path in paths:
        resolved = path.resolve(strict=True)
        try:
            display_path = str(resolved.relative_to(REPO_ROOT))
        except ValueError:
            display_path = str(resolved)
        records.append({"path": display_path, "sha256": _sha256(resolved)})
    return records


def _bind_separator_request(
    run_dir: Path,
    *,
    preset: str,
    audio: Path,
) -> None:
    pins_path = REPO_ROOT / "workers" / "separator" / "pins.json"
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    parameters, provenance = verify_run_manifest._expected_separator_provenance(
        pins,
        preset,
    )
    sources = (
        pins_path,
        REPO_ROOT / "workers" / "separator" / "pyproject.toml",
        REPO_ROOT / "workers" / "separator" / "uv.lock",
        REPO_ROOT / "workers" / "separator" / "metrics.py",
        REPO_ROOT / "workers" / "separator" / "run_baseline.py",
        REPO_ROOT / "scripts" / "verify_run_manifest.py",
        REPO_ROOT / "slurm" / "16_separator_baseline.slurm",
    )
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        {
            "configuration": parameters,
            "model_provenance": provenance,
            "inputs": [
                {
                    "path": str(audio.resolve(strict=True)),
                    "sha256": _sha256(audio),
                }
            ],
            "code": {"source_files": _source_records(sources)},
        }
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def _bind_muscriptor_requests(
    project: Path,
    run_dirs: dict[str, Path],
) -> Path:
    pins_path = REPO_ROOT / "workers" / "muscriptor" / "pins.json"
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    provenance_path = project / "model-provenance.json"
    provenance = {
        "schema_version": 1,
        "repository": pins["model"]["repository"],
        "revision": pins["model"]["revision"],
        "license": pins["model"]["license"],
        "weight": {
            "filename": pins["model"]["weight_filename"],
            "path": str(project / pins["model"]["weight_filename"]),
            "sha256": "a" * 64,
            "size_bytes": 123,
        },
        "config": {
            "filename": pins["model"]["config_filename"],
            "path": str(project / pins["model"]["config_filename"]),
            "sha256": "b" * 64,
            "size_bytes": 456,
        },
    }
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    package = pins["package"]
    sources = (
        pins_path,
        REPO_ROOT / "workers" / "muscriptor" / "pyproject.toml",
        REPO_ROOT / "workers" / "muscriptor" / "uv.lock",
        REPO_ROOT / "workers" / "muscriptor" / "normalize.py",
        REPO_ROOT / "workers" / "muscriptor" / "run_baseline.py",
        REPO_ROOT / "scripts" / "verify_run_manifest.py",
        REPO_ROOT / "slurm" / "17_muscriptor_stem_compare.slurm",
    )
    for run_dir in run_dirs.values():
        manifest_path = run_dir / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        input_path = Path(manifest["inputs"][0]["path"]).resolve(strict=True)
        manifest["inputs"] = [
            {
                "path": str(input_path),
                "sha256": _sha256(input_path),
            }
        ]
        manifest["model"] = pins["model"]["name"]
        manifest["model_provenance"] = {
            "package": {
                "name": package["name"],
                "version": package["version"],
                "pypi_wheel_sha256": package["pypi_wheel_sha256"],
                "upstream_git_commit": package["upstream_git_commit"],
            },
            "repository": pins["model"]["repository"],
            "revision": pins["model"]["revision"],
            "license": pins["model"]["license"],
            "weight_filename": provenance["weight"]["filename"],
            "weight_sha256": provenance["weight"]["sha256"],
            "weight_size_bytes": provenance["weight"]["size_bytes"],
            "config_sha256": provenance["config"]["sha256"],
        }
        manifest["decoding"].update(
            {
                "dtype": "float32",
                "device": "cuda",
                "skip_midi": True,
            }
        )
        manifest["code"] = {
            "pins_sha256": _sha256(pins_path),
            "source_files": _source_records(sources),
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return provenance_path


class RunManifestVerifierTests(unittest.TestCase):
    def test_accepts_succeeded_matching_run_and_cli(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir, _ = _write_run(Path(temporary))

            summary = verify_run_manifest.validate_run_manifest(
                run_dir,
                expected_worker="separator",
                expected_preset="vocal_quality_a",
                required_outputs=("raw/stems/vocals sample.flac",),
            )
            self.assertEqual(summary["run_id"], "separator-test")
            self.assertEqual(summary["output_count"], 1)

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = verify_run_manifest.main(
                    [
                        "--run-dir",
                        str(run_dir),
                        "--worker",
                        "separator",
                        "--preset",
                        "vocal_quality_a",
                        "--require-output",
                        "raw/stems/vocals sample.flac",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["run_id"], "separator-test")

    def test_request_binding_rejects_stale_input_source_and_decoding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project 日本語"
            run_dirs = _comparison_fixture(project)
            provenance_path = _bind_muscriptor_requests(project, run_dirs)
            direct_run = run_dirs["direct"]
            canonical = project / "audio" / "canonical" / "mix.flac"
            pins_path = REPO_ROOT / "workers" / "muscriptor" / "pins.json"
            sources = (
                pins_path,
                REPO_ROOT / "workers" / "muscriptor" / "pyproject.toml",
                REPO_ROOT / "workers" / "muscriptor" / "uv.lock",
                REPO_ROOT / "workers" / "muscriptor" / "normalize.py",
                REPO_ROOT / "workers" / "muscriptor" / "run_baseline.py",
                REPO_ROOT / "scripts" / "verify_run_manifest.py",
                REPO_ROOT / "slurm" / "17_muscriptor_stem_compare.slurm",
            )
            expected_fields = (
                ("decoding.beam_size", 4),
                ("decoding.instruments", ["voice"]),
                ("decoding.dtype", "float32"),
                ("decoding.device", "cuda"),
                ("decoding.skip_midi", True),
            )

            summary = verify_run_manifest.validate_run_manifest(
                direct_run,
                expected_worker="muscriptor",
                required_outputs=(
                    "normalized/events.jsonl",
                    "normalized/summary.json",
                ),
                expected_input=canonical,
                expected_pins=pins_path,
                expected_model_provenance=provenance_path,
                repo_root=REPO_ROOT,
                expected_sources=sources,
                expected_fields=expected_fields,
            )
            self.assertTrue(summary["request_bound"])

            original_audio = canonical.read_bytes()
            canonical.write_bytes(b"changed request audio")
            with self.assertRaisesRegex(
                verify_run_manifest.ManifestValidationError,
                "input SHA-256",
            ):
                verify_run_manifest.validate_run_manifest(
                    direct_run,
                    expected_worker="muscriptor",
                    expected_input=canonical,
                )
            canonical.write_bytes(original_audio)

            with self.assertRaisesRegex(
                verify_run_manifest.ManifestValidationError,
                "does not match the current request",
            ):
                verify_run_manifest.validate_run_manifest(
                    direct_run,
                    expected_worker="muscriptor",
                    expected_fields=(("decoding.beam_size", 8),),
                )

            unexpected_source = Path(temporary) / "unexpected.py"
            unexpected_source.write_text("print('different source')\n", encoding="utf-8")
            with self.assertRaisesRegex(
                verify_run_manifest.ManifestValidationError,
                "exactly one current source record",
            ):
                verify_run_manifest.validate_run_manifest(
                    direct_run,
                    expected_worker="muscriptor",
                    repo_root=REPO_ROOT,
                    expected_sources=(unexpected_source,),
                )

    def test_rejects_status_worker_preset_and_run_id_mismatch(self) -> None:
        cases = {
            "status": ("status", "failed", "status is not succeeded"),
            "worker": ("worker", "muscriptor", "worker does not match"),
            "preset": ("preset", "multistem_quality_a", "preset does not match"),
            "run_id": ("run_id", "another-run", "does not match directory name"),
            "unsafe_run_id": ("run_id", "separator..test", "run_id is missing or unsafe"),
        }
        for name, (field, value, message) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                run_dir, _ = _write_run(Path(temporary))
                manifest_path = run_dir / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest[field] = value
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                with self.assertRaisesRegex(
                    verify_run_manifest.ManifestValidationError,
                    message,
                ):
                    verify_run_manifest.validate_run_manifest(
                        run_dir,
                        expected_worker="separator",
                        expected_preset="vocal_quality_a",
                    )

    def test_separator_slurm_preserves_invalid_base_and_reuses_valid_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project 日本語"
            canonical = project / "audio" / "canonical" / "mix.flac"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"canonical separator input")
            invalid_base = project / "runs" / "separator-vocal"
            invalid_base.mkdir(parents=True)
            (invalid_base / "interrupted.marker").write_text(
                "preserve me",
                encoding="utf-8",
            )
            vocal_run = _write_complete_run(
                project,
                run_id="separator-vocal-attempt-1",
                worker="separator",
                preset="vocal_quality_a",
                output_paths=(
                    "raw/stems/vocals.flac",
                    "raw/stems/instrumental.flac",
                ),
            )
            multistem_run = _write_complete_run(
                project,
                run_id="separator-multistem",
                worker="separator",
                preset="multistem_quality_a",
                output_paths=(
                    "raw/stems/vocals.flac",
                    "raw/stems/drums.flac",
                    "raw/stems/bass.flac",
                    "raw/stems/other.flac",
                ),
            )
            _bind_separator_request(
                vocal_run,
                preset="vocal_quality_a",
                audio=canonical,
            )
            _bind_separator_request(
                multistem_run,
                preset="multistem_quality_a",
                audio=canonical,
            )
            environment = {
                **_slurm_test_environment(project),
                "SEPARATOR_VOCAL_RUN_ID": "separator-vocal",
                "SEPARATOR_MULTISTEM_RUN_ID": "separator-multistem",
            }

            result = subprocess.run(
                ["bash", str(REPO_ROOT / "slurm" / "16_separator_baseline.slurm")],
                check=False,
                capture_output=True,
                text=True,
                errors="replace",
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                "resolved_vocal_run_id=separator-vocal-attempt-1 skip=1",
                result.stdout,
            )
            self.assertIn(
                "resolved_multistem_run_id=separator-multistem skip=1",
                result.stdout,
            )
            self.assertEqual(
                (invalid_base / "interrupted.marker").read_text(encoding="utf-8"),
                "preserve me",
            )

    def test_muscriptor_slurm_reuses_only_complete_untampered_report(self) -> None:
        mutations: tuple[tuple[str, tuple[str | int, ...], Any], ...] = (
            ("comparison_type", ("comparison_type",), "unsupported"),
            ("accuracy_claim", ("claims", "accuracy_claimed"), True),
            ("shared_configuration", ("controlled_configuration", "beam_size"), 99),
            (
                "timeline_validation",
                ("timeline_validation", "all_paths_share_canonical_mix"),
                False,
            ),
            ("path_agreement", ("path_agreement",), []),
            (
                "per_run_summary",
                ("runs", "direct", "descriptive_event_summary", "event_count"),
                999,
            ),
            (
                "artifact_hash",
                ("runs", "direct", "normalized_events_sha256"),
                "0" * 64,
            ),
            (
                "lineage",
                ("runs", "vocal_a", "lineage", "parent_stem_sha256"),
                "0" * 64,
            ),
            ("missing_field", ("limitations",), None),
        )
        for name, path, replacement in mutations:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                project = Path(temporary) / "project 日本語"
                run_dirs = _comparison_fixture(project)
                provenance_path = _bind_muscriptor_requests(project, run_dirs)
                run_ids = {run_name: run_dir.name for run_name, run_dir in run_dirs.items()}
                input_paths = {
                    run_name: json.loads(
                        (run_dir / "run_manifest.json").read_text(encoding="utf-8")
                    )["inputs"][0]["path"]
                    for run_name, run_dir in run_dirs.items()
                }
                complete_report = compare_amt.compare_runs(
                    {run_name: run_dir.resolve() for run_name, run_dir in run_dirs.items()}
                )
                tampered_report = copy.deepcopy(complete_report)
                target = tampered_report
                for key in path[:-1]:
                    target = target[key]
                if name == "missing_field":
                    del target[path[-1]]
                else:
                    target[path[-1]] = replacement

                reports = project / "reports"
                reports.mkdir(parents=True)
                base_report = reports / "comparison.json"
                tampered_text = json.dumps(tampered_report)
                base_report.write_text(tampered_text, encoding="utf-8")
                attempt_report = reports / "comparison-attempt-1.json"
                attempt_report.write_text(
                    json.dumps(complete_report),
                    encoding="utf-8",
                )
                environment = {
                    **_slurm_test_environment(project),
                    "MUSCRIPTOR_DIRECT_RUN_ID": run_ids["direct"],
                    "MUSCRIPTOR_VOCAL_A_RUN_ID": run_ids["vocal_a"],
                    "MUSCRIPTOR_VOCAL_B_RUN_ID": run_ids["vocal_b"],
                    "MUSCRIPTOR_COMPARE_REPORT": str(base_report),
                    "MUSCRIPTOR_WEIGHT_PROVENANCE": str(provenance_path),
                    "MUSCRIPTOR_DTYPE": "float32",
                    "DIRECT_MIX_AUDIO": input_paths["direct"],
                    "VOCAL_A_AUDIO": input_paths["vocal_a"],
                    "VOCAL_B_AUDIO": input_paths["vocal_b"],
                }

                result = subprocess.run(
                    [
                        "bash",
                        str(REPO_ROOT / "slurm" / "17_muscriptor_stem_compare.slurm"),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                    errors="replace",
                    env=environment,
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    "Preserving mismatched or invalid report",
                    result.stderr,
                )
                self.assertIn("Reusing verified comparison report", result.stdout)
                self.assertIn("comparison-attempt-1.json", result.stdout)
                self.assertEqual(
                    base_report.read_text(encoding="utf-8"),
                    tampered_text,
                )

    def test_rejects_unsafe_or_escaping_output_paths(self) -> None:
        for unsafe_path in (
            "../outside.flac",
            "/tmp/outside.flac",
            "raw//vocals.flac",
            r"raw\vocals.flac",
        ):
            with (
                self.subTest(path=unsafe_path),
                tempfile.TemporaryDirectory() as temporary,
            ):
                run_dir, _ = _write_run(Path(temporary))
                manifest_path = run_dir / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifest["outputs"][0]["path"] = unsafe_path
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                with self.assertRaises(verify_run_manifest.ManifestValidationError):
                    verify_run_manifest.validate_run_manifest(
                        run_dir,
                        expected_worker="separator",
                        expected_preset="vocal_quality_a",
                    )

    def test_rejects_missing_size_hash_duplicate_and_required_output(self) -> None:
        mutations = {
            "missing": lambda run_dir, output, manifest: output.unlink(),
            "size": lambda run_dir, output, manifest: manifest["outputs"][0].update(
                {"size_bytes": output.stat().st_size + 1}
            ),
            "hash": lambda run_dir, output, manifest: manifest["outputs"][0].update(
                {"sha256": "0" * 64}
            ),
            "duplicate": lambda run_dir, output, manifest: manifest["outputs"].append(
                dict(manifest["outputs"][0])
            ),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                run_dir, output = _write_run(Path(temporary))
                manifest_path = run_dir / "run_manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(run_dir, output, manifest)
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

                with self.assertRaises(verify_run_manifest.ManifestValidationError):
                    verify_run_manifest.validate_run_manifest(
                        run_dir,
                        expected_worker="separator",
                        expected_preset="vocal_quality_a",
                    )

        with tempfile.TemporaryDirectory() as temporary:
            run_dir, _ = _write_run(Path(temporary))
            with self.assertRaisesRegex(
                verify_run_manifest.ManifestValidationError,
                "required output",
            ):
                verify_run_manifest.validate_run_manifest(
                    run_dir,
                    expected_worker="separator",
                    expected_preset="vocal_quality_a",
                    required_outputs=("raw/stems/instrumental.flac",),
                )


if __name__ == "__main__":
    unittest.main()
