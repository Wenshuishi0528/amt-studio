from __future__ import annotations

import fcntl
import importlib.util
import json
import os
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import amt_core.batch as batch_module
from amt_core.batch import (
    BATCH_INDEX_CONTRACT,
    BatchInterrupted,
    BatchValidationError,
    _output_record,
    freeze_batch_spec,
    load_batch_manifest,
    prune_batch_cache,
    run_batch_row,
    summarize_batch,
)
from amt_core.utils import atomic_write_json, load_json, sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_WORKER = REPO_ROOT / "scripts" / "task008_fixture_worker.py"


class BatchSystemTest(unittest.TestCase):
    def _spec(
        self,
        root: Path,
        *,
        interrupt_once: bool = False,
        max_cache_bytes: int = 1024 * 1024,
        max_failed_attempts_per_cache: int = 1,
    ) -> Path:
        input_path = root / "输入 音频.txt"
        configuration_path = root / "配置 参数.json"
        model_path = root / "模型 权重.bin"
        code_path = root / "代码 实现.py"
        input_path.write_text("authorized fixture\n", encoding="utf-8")
        configuration_path.write_text('{"seed": 3407}\n', encoding="utf-8")
        model_path.write_bytes(b"fixture-model")
        code_path.write_text("print('fixture code')\n", encoding="utf-8")
        infer_command = [
            "{python}",
            "{repo_root}/scripts/task008_fixture_worker.py",
            "--input",
            "{run_dir}/stages/prepare/prepared.json",
            "--configuration",
            "{configuration}",
            "--model",
            "{model:fixture}",
            "--output",
            "{stage_dir}/result.json",
        ]
        if interrupt_once:
            infer_command.extend(
                [
                    "--checkpoint-dir",
                    "{checkpoint_dir}",
                    "--interrupt-once",
                ]
            )
        spec = {
            "schema_version": 1,
            "contract_version": "amt-batch-spec/v1",
            "batch_id": "fixture-batch",
            "created_at": "2026-07-25T00:00:00+00:00",
            "retention": {
                "max_cache_bytes": max_cache_bytes,
                "max_failed_attempts_per_cache": max_failed_attempts_per_cache,
                "keep_recent_completed": 0,
            },
            "rows": [
                {
                    "row_id": "row-a",
                    "authorization_id": "project-owned-fixture",
                    "repository_root_path": str(REPO_ROOT),
                    "python_path": str(Path(sys.executable)),
                    "input_path": input_path.name,
                    "configuration_path": configuration_path.name,
                    "models": [{"name": "fixture", "path": model_path.name}],
                    "code_revision": "test-revision",
                    "code_paths": [
                        {
                            "name": "batch-core",
                            "path": str(REPO_ROOT / "src" / "amt_core" / "batch.py"),
                        },
                        {
                            "name": "fixture-worker",
                            "path": str(FIXTURE_WORKER),
                        },
                        {
                            "name": "test-code",
                            "path": code_path.name,
                        },
                    ],
                    "stages": [
                        {
                            "stage_id": "prepare",
                            "command": [
                                "{python}",
                                "{repo_root}/scripts/task008_fixture_worker.py",
                                "--input",
                                "{input}",
                                "--configuration",
                                "{configuration}",
                                "--model",
                                "{model:fixture}",
                                "--output",
                                "{stage_dir}/prepared.json",
                            ],
                            "outputs": ["prepared.json"],
                        },
                        {
                            "stage_id": "infer",
                            "command": infer_command,
                            "outputs": ["result.json"],
                        },
                    ],
                    "selected_outputs": ["infer/result.json"],
                }
            ],
        }
        spec_path = root / "spec.json"
        atomic_write_json(spec_path, spec)
        return spec_path

    def _run(
        self,
        root: Path,
        manifest_path: Path,
        *,
        allow_local: bool = True,
    ) -> str:
        return run_batch_row(
            manifest_path=manifest_path,
            row_index=0,
            cache_root=root / "cache",
            selected_root=root / "selected",
            index_root=root / "index",
            repo_root=REPO_ROOT,
            python_path=Path(sys.executable),
            allow_local=allow_local,
        )

    def test_freeze_hashes_input_configuration_model_and_execution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(spec_path, manifest_path)
            row = manifest["rows"][0]
            self.assertEqual(row["input"]["sha256"], sha256_file(root / "输入 音频.txt"))
            self.assertEqual(
                row["configuration"]["sha256"],
                sha256_file(root / "配置 参数.json"),
            )
            self.assertEqual(
                row["models"][0]["artifact"]["sha256"],
                sha256_file(root / "模型 权重.bin"),
            )
            self.assertEqual(row["code"]["revision"], "test-revision")
            self.assertEqual(len(row["code"]["artifacts"]), 3)
            self.assertEqual(row["python"]["sha256"], sha256_file(Path(sys.executable)))
            self.assertEqual(row["python"]["path"], str(Path(sys.executable)))
            self.assertEqual(
                row["python"]["resolved_path"],
                str(Path(sys.executable).resolve()),
            )
            self.assertEqual(len(row["python"]["environment_sha256"]), 64)
            self.assertEqual(row["execution_contract"], "amt-batch-execution/v2")
            self.assertEqual(row["repository_root"], str(REPO_ROOT))
            self.assertEqual(load_batch_manifest(manifest_path), manifest)
            self.assertEqual(len(row["cache_key"]), 64)

    def test_freeze_hashes_shared_artifacts_only_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            second_configuration = root / "配置 参数 B.json"
            second_configuration.write_text('{"seed": 85}\n', encoding="utf-8")
            spec = load_json(spec_path)
            second_row = json.loads(json.dumps(spec["rows"][0]))
            second_row["row_id"] = "row-b"
            second_row["configuration_path"] = second_configuration.name
            spec["rows"].append(second_row)
            atomic_write_json(spec_path, spec)

            with patch(
                "amt_core.batch._artifact",
                wraps=batch_module._artifact,
            ) as artifact:
                freeze_batch_spec(spec_path, root / "manifest.json")

            hashed_paths = [call.args[0] for call in artifact.call_args_list]
            self.assertEqual(hashed_paths.count((root / "模型 权重.bin").resolve()), 1)
            self.assertEqual(hashed_paths.count((root / "输入 音频.txt").resolve()), 1)
            self.assertEqual(hashed_paths.count((root / "代码 实现.py").resolve()), 1)
            self.assertEqual(
                hashed_paths.count((REPO_ROOT / "src" / "amt_core" / "batch.py").resolve()),
                1,
            )

    def test_duplicate_content_addressed_rows_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            spec = load_json(spec_path)
            duplicate = json.loads(json.dumps(spec["rows"][0]))
            duplicate["row_id"] = "row-b"
            spec["rows"].append(duplicate)
            atomic_write_json(spec_path, spec)
            with self.assertRaisesRegex(BatchValidationError, "duplicates another row"):
                freeze_batch_spec(spec_path, root / "manifest.json")

    def test_interrupted_row_resumes_completed_stage_then_becomes_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(
                self._spec(root, interrupt_once=True),
                manifest_path,
            )
            run_dir = root / "cache" / manifest["rows"][0]["cache_key"]
            with self.assertRaises(BatchInterrupted):
                self._run(root, manifest_path)
            prepared = run_dir / "stages" / "prepare" / "prepared.json"
            prepared_hash = sha256_file(prepared)
            prepared_mtime = prepared.stat().st_mtime_ns
            self.assertFalse((run_dir / "complete.json").exists())
            self.assertEqual(list((run_dir / "tmp").iterdir()), [])

            self.assertEqual(self._run(root, manifest_path), "completed")
            self.assertEqual(sha256_file(prepared), prepared_hash)
            self.assertEqual(prepared.stat().st_mtime_ns, prepared_mtime)
            self.assertEqual(self._run(root, manifest_path), "cached")
            selected = (
                root
                / "selected"
                / "fixture-batch"
                / "row-a"
                / manifest["rows"][0]["cache_key"]
                / "stages"
                / "infer"
                / "result.json"
            )
            self.assertTrue(selected.is_file())
            statuses = {
                load_json(path)["status"] for path in (run_dir / "attempts").glob("*/attempt.json")
            }
            self.assertEqual(statuses, {"interrupted", "completed", "cached"})
            persistent_attempts = list(
                (root / "index" / "fixture-batch" / "attempts" / "row-a").glob("*.json")
            )
            self.assertEqual(len(persistent_attempts), 3)
            persistent_statuses = {
                load_json(path)["attempt"]["status"] for path in persistent_attempts
            }
            self.assertEqual(persistent_statuses, statuses)
            completed = next(
                load_json(path)["attempt"]
                for path in persistent_attempts
                if load_json(path)["attempt"]["status"] == "completed"
            )
            self.assertTrue(completed["stages"][-1]["command"])
            self.assertTrue(completed["stages"][-1]["outputs"])

    def test_unchanged_work_is_reused_across_batch_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            first_manifest_path = root / "first-manifest.json"
            first_manifest = freeze_batch_spec(spec_path, first_manifest_path)
            self.assertEqual(self._run(root, first_manifest_path), "completed")

            spec = load_json(spec_path)
            spec["batch_id"] = "fixture-batch-two"
            spec["rows"][0]["row_id"] = "row-b"
            atomic_write_json(spec_path, spec)
            second_manifest_path = root / "second-manifest.json"
            second_manifest = freeze_batch_spec(spec_path, second_manifest_path)

            self.assertEqual(
                first_manifest["rows"][0]["cache_key"],
                second_manifest["rows"][0]["cache_key"],
            )
            self.assertEqual(self._run(root, second_manifest_path), "cached")
            second_selected = (
                root
                / "selected"
                / "fixture-batch-two"
                / "row-b"
                / second_manifest["rows"][0]["cache_key"]
                / "stages"
                / "infer"
                / "result.json"
            )
            self.assertTrue(second_selected.is_file())
            complete = load_json(
                root / "cache" / second_manifest["rows"][0]["cache_key"] / "complete.json"
            )
            self.assertNotIn("batch_id", complete)
            self.assertNotIn("manifest_sha256", complete)
            self.assertIn("cache_payload", complete)
            _index, resources = summarize_batch(
                manifest_path=second_manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
            )
            self.assertEqual(resources["attempt_status_counts"], {"cached": 1})
            self.assertEqual(resources["cache_hit_rate"], 1.0)

    def test_stage_uses_immutable_snapshot_and_controlled_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            spec = load_json(spec_path)
            prepare = spec["rows"][0]["stages"][0]
            prepare["command"].extend(
                [
                    "--record-input-name",
                    "--environment-key",
                    "UNFROZEN_MODE",
                ]
            )
            atomic_write_json(spec_path, spec)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(spec_path, manifest_path)

            with patch.dict(os.environ, {"UNFROZEN_MODE": "live-value"}):
                self.assertEqual(self._run(root, manifest_path), "completed")

            run_dir = root / "cache" / manifest["rows"][0]["cache_key"]
            prepared = load_json(run_dir / "stages" / "prepare" / "prepared.json")
            self.assertEqual(prepared["input_name"], "input")
            self.assertIsNone(prepared["environment_value"])
            attempt = next((run_dir / "attempts").glob("*/attempt.json"))
            command = load_json(attempt)["stages"][0]["command"]
            self.assertIn("/frozen/repo/scripts/task008_fixture_worker.py", command[1])
            self.assertTrue((run_dir / "frozen" / "snapshot.json").is_file())

    def test_declared_stage_environment_is_cache_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            spec = load_json(spec_path)
            prepare = spec["rows"][0]["stages"][0]
            prepare["command"].extend(["--environment-key", "FROZEN_MODE"])
            prepare["environment"] = {"FROZEN_MODE": "A"}
            atomic_write_json(spec_path, spec)
            first_manifest_path = root / "first-manifest.json"
            first = freeze_batch_spec(spec_path, first_manifest_path)
            self.assertEqual(self._run(root, first_manifest_path), "completed")

            prepared = load_json(
                root
                / "cache"
                / first["rows"][0]["cache_key"]
                / "stages"
                / "prepare"
                / "prepared.json"
            )
            self.assertEqual(prepared["environment_value"], "A")

            spec["batch_id"] = "fixture-batch-environment-b"
            spec["rows"][0]["row_id"] = "row-b"
            spec["rows"][0]["stages"][0]["environment"]["FROZEN_MODE"] = "B"
            atomic_write_json(spec_path, spec)
            second = freeze_batch_spec(spec_path, root / "second-manifest.json")
            self.assertNotEqual(
                first["rows"][0]["cache_key"],
                second["rows"][0]["cache_key"],
            )

    def test_changed_input_is_rejected_before_cache_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            freeze_batch_spec(self._spec(root), manifest_path)
            (root / "输入 音频.txt").write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(BatchValidationError, "input size changed"):
                self._run(root, manifest_path)

    def test_changed_code_is_rejected_before_cache_use(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            freeze_batch_spec(self._spec(root), manifest_path)
            (root / "代码 实现.py").write_text("print('tampered')\n", encoding="utf-8")
            with self.assertRaisesRegex(BatchValidationError, "code artifact.*changed"):
                self._run(root, manifest_path)

    def test_execution_root_and_python_must_match_frozen_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            freeze_batch_spec(self._spec(root), manifest_path)
            fake_repo = root / "fake-repo"
            fake_repo.mkdir()
            with self.assertRaisesRegex(BatchValidationError, "repo_root does not match"):
                run_batch_row(
                    manifest_path=manifest_path,
                    row_index=0,
                    cache_root=root / "cache",
                    selected_root=root / "selected",
                    index_root=root / "index",
                    repo_root=fake_repo,
                    python_path=Path(sys.executable),
                    allow_local=True,
                )
            fake_python = root / "fake-python"
            fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            fake_python.chmod(0o700)
            with self.assertRaisesRegex(BatchValidationError, "python_path does not match"):
                run_batch_row(
                    manifest_path=manifest_path,
                    row_index=0,
                    cache_root=root / "cache",
                    selected_root=root / "selected",
                    index_root=root / "index",
                    repo_root=REPO_ROOT,
                    python_path=fake_python,
                    allow_local=True,
                )
            if Path(sys.executable).is_symlink():
                with self.assertRaisesRegex(BatchValidationError, "python_path does not match"):
                    run_batch_row(
                        manifest_path=manifest_path,
                        row_index=0,
                        cache_root=root / "cache",
                        selected_root=root / "selected",
                        index_root=root / "index",
                        repo_root=REPO_ROOT,
                        python_path=Path(sys.executable).resolve(),
                        allow_local=True,
                    )

    def test_repository_tokens_must_reference_frozen_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            spec = load_json(spec_path)
            spec["rows"][0]["stages"][0]["command"][1] = "{repo_root}/scripts/unrecorded-worker.py"
            atomic_write_json(spec_path, spec)
            with self.assertRaisesRegex(BatchValidationError, "repository reference"):
                freeze_batch_spec(spec_path, root / "manifest.json")

    def test_python_entry_point_must_be_a_frozen_repository_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            external = root / "mutable-worker.py"
            external.write_text("print('mutable')\n", encoding="utf-8")
            spec = load_json(spec_path)
            spec["rows"][0]["stages"][0]["command"][1] = str(external)
            atomic_write_json(spec_path, spec)
            with self.assertRaisesRegex(BatchValidationError, "Python entry point"):
                freeze_batch_spec(spec_path, root / "manifest.json")

    def test_freeze_refuses_to_replace_a_different_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            spec_path = self._spec(root)
            manifest_path = root / "manifest.json"
            first = freeze_batch_spec(spec_path, manifest_path)
            self.assertEqual(freeze_batch_spec(spec_path, manifest_path), first)
            spec = load_json(spec_path)
            spec["created_at"] = "2026-07-25T01:00:00+00:00"
            atomic_write_json(spec_path, spec)
            with self.assertRaisesRegex(BatchValidationError, "different content"):
                freeze_batch_spec(spec_path, manifest_path)

    def test_selected_result_tamper_breaks_cache_hit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(self._spec(root), manifest_path)
            self.assertEqual(self._run(root, manifest_path), "completed")
            selected = (
                root
                / "selected"
                / "fixture-batch"
                / "row-a"
                / manifest["rows"][0]["cache_key"]
                / "stages"
                / "infer"
                / "result.json"
            )
            selected.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(BatchValidationError, "selected result output changed"):
                self._run(root, manifest_path)

    def test_summary_reports_failures_resources_and_traceability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            freeze_batch_spec(self._spec(root, interrupt_once=True), manifest_path)
            with self.assertRaises(BatchInterrupted):
                self._run(root, manifest_path)
            self.assertEqual(self._run(root, manifest_path), "completed")
            index, resources = summarize_batch(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
            )
            self.assertEqual(index["contract_version"], BATCH_INDEX_CONTRACT)
            self.assertEqual(index["status_counts"], {"completed": 1})
            self.assertEqual(index["rows"][0]["authorization_id"], "project-owned-fixture")
            self.assertEqual(resources["failure_rate"], 0.5)
            self.assertGreater(resources["stage_wall_seconds_total"], 0)
            self.assertGreater(resources["cache_bytes"], 0)

    def test_retention_prunes_only_after_selected_copy_survives(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(
                self._spec(root, max_cache_bytes=1),
                manifest_path,
            )
            self.assertEqual(self._run(root, manifest_path), "completed")
            cache = root / "cache" / manifest["rows"][0]["cache_key"]
            selected_root = (
                root / "selected" / "fixture-batch" / "row-a" / manifest["rows"][0]["cache_key"]
            )
            selected = selected_root / "stages" / "infer" / "result.json"
            raw_prepare_output = selected_root / "stages" / "prepare" / "prepared.json"
            self.assertTrue(raw_prepare_output.is_file())
            _index_before, resources_before = summarize_batch(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
            )
            preview = prune_batch_cache(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
                apply=False,
            )
            self.assertEqual(preview["removed_caches"], [str(cache.resolve())])
            report = prune_batch_cache(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
                apply=True,
            )
            self.assertTrue(report["within_budget"])
            self.assertFalse(cache.exists())
            self.assertTrue(selected.is_file())
            index, _resources = summarize_batch(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
            )
            self.assertEqual(index["status_counts"], {"pruned_selected": 1})
            self.assertTrue(raw_prepare_output.is_file())
            _index_after, resources_after = summarize_batch(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
            )
            for field in (
                "attempt_status_counts",
                "failure_rate",
                "failure_rate_numerator",
                "failure_rate_denominator",
                "stage_wall_seconds_total",
                "peak_max_rss_kb",
            ):
                self.assertEqual(resources_after[field], resources_before[field])

    def test_retention_safely_prunes_terminal_incomplete_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(
                self._spec(
                    root,
                    interrupt_once=True,
                    max_cache_bytes=1,
                    max_failed_attempts_per_cache=0,
                ),
                manifest_path,
            )
            with self.assertRaises(BatchInterrupted):
                self._run(root, manifest_path)
            attempts_root = root / "cache" / manifest["rows"][0]["cache_key"] / "attempts"
            attempt_directories = list(attempts_root.iterdir())
            self.assertEqual(len(attempt_directories), 1)

            report = prune_batch_cache(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
                apply=True,
            )
            self.assertTrue(report["within_budget"])
            self.assertFalse(attempt_directories[0].exists())
            persistent_attempts = list(
                (root / "index" / "fixture-batch" / "attempts" / "row-a").glob("*.json")
            )
            persistent_logs = list(
                (root / "index" / "fixture-batch" / "attempt-logs" / "row-a").glob("*/*.log")
            )
            self.assertEqual(len(persistent_attempts), 1)
            self.assertEqual(len(persistent_logs), 4)

    def test_retention_skips_active_cache_without_partial_deletion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(
                self._spec(root, max_cache_bytes=1),
                manifest_path,
            )
            self.assertEqual(self._run(root, manifest_path), "completed")
            cache = root / "cache" / manifest["rows"][0]["cache_key"]
            with (cache / ".lock").open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(BatchValidationError, "exceeds its budget"):
                    prune_batch_cache(
                        manifest_path=manifest_path,
                        cache_root=root / "cache",
                        selected_root=root / "selected",
                        index_root=root / "index",
                        apply=True,
                    )
            self.assertTrue(cache.is_dir())

    def test_retention_does_not_prune_attempts_from_active_cache(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(
                self._spec(
                    root,
                    interrupt_once=True,
                    max_failed_attempts_per_cache=0,
                ),
                manifest_path,
            )
            with self.assertRaises(BatchInterrupted):
                self._run(root, manifest_path)
            cache = root / "cache" / manifest["rows"][0]["cache_key"]
            attempt_directories = list((cache / "attempts").iterdir())
            self.assertEqual(len(attempt_directories), 1)
            with (cache / ".lock").open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                report = prune_batch_cache(
                    manifest_path=manifest_path,
                    cache_root=root / "cache",
                    selected_root=root / "selected",
                    index_root=root / "index",
                    apply=True,
                )
            self.assertEqual(report["removed_attempts"], [])
            self.assertTrue(attempt_directories[0].is_dir())

    def test_new_cache_is_blocked_while_shared_root_exceeds_budget(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_spec_path = self._spec(root, max_cache_bytes=1)
            first_manifest_path = root / "first-manifest.json"
            freeze_batch_spec(first_spec_path, first_manifest_path)
            self.assertEqual(self._run(root, first_manifest_path), "completed")

            second_spec = load_json(first_spec_path)
            second_spec["batch_id"] = "fixture-batch-two"
            second_spec["rows"][0]["row_id"] = "row-b"
            second_config = root / "配置 参数 B.json"
            second_config.write_text('{"seed": 99}\n', encoding="utf-8")
            second_spec["rows"][0]["configuration_path"] = second_config.name
            second_spec_path = root / "second-spec.json"
            atomic_write_json(second_spec_path, second_spec)
            second_manifest_path = root / "second-manifest.json"
            freeze_batch_spec(second_spec_path, second_manifest_path)

            with self.assertRaisesRegex(BatchValidationError, "retention budget"):
                self._run(root, second_manifest_path)

    def test_finalization_recreates_missing_persistent_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(self._spec(root), manifest_path)
            self.assertEqual(self._run(root, manifest_path), "completed")
            archive = (
                root / "selected" / "fixture-batch" / "row-a" / manifest["rows"][0]["cache_key"]
            )
            for path in sorted(archive.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            archive.rmdir()

            index, _resources = summarize_batch(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
            )
            self.assertEqual(index["status_counts"], {"completed_unarchived": 1})
            prune_batch_cache(
                manifest_path=manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
                apply=True,
            )
            self.assertTrue((archive / "selection.json").is_file())

    def test_shared_cache_budget_counts_prior_manifests(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first_spec_path = self._spec(root, max_cache_bytes=10**9)
            first_manifest_path = root / "first-manifest.json"
            freeze_batch_spec(first_spec_path, first_manifest_path)
            self.assertEqual(self._run(root, first_manifest_path), "completed")
            first_size = sum(
                path.stat().st_size for path in (root / "cache").rglob("*") if path.is_file()
            )

            second_spec = load_json(first_spec_path)
            second_spec["batch_id"] = "fixture-batch-two"
            second_spec["rows"][0]["row_id"] = "row-b"
            second_configuration = root / "配置 参数 B.json"
            second_configuration.write_text('{"seed": 99}\n', encoding="utf-8")
            second_spec["rows"][0]["configuration_path"] = second_configuration.name
            second_spec["retention"]["max_cache_bytes"] = first_size + 2000
            second_spec_path = root / "second-spec.json"
            atomic_write_json(second_spec_path, second_spec)
            second_manifest_path = root / "second-manifest.json"
            freeze_batch_spec(second_spec_path, second_manifest_path)
            self.assertEqual(self._run(root, second_manifest_path), "completed")

            before = sum(
                path.stat().st_size for path in (root / "cache").rglob("*") if path.is_file()
            )
            report = prune_batch_cache(
                manifest_path=second_manifest_path,
                cache_root=root / "cache",
                selected_root=root / "selected",
                index_root=root / "index",
                apply=False,
            )
            self.assertEqual(report["cache_bytes_before"], before)
            self.assertLessEqual(
                report["cache_bytes_after"],
                second_spec["retention"]["max_cache_bytes"],
            )
            self.assertTrue(report["removed_caches"])

    def test_run_row_refuses_non_slurm_execution_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            freeze_batch_spec(self._spec(root), manifest_path)
            with self.assertRaisesRegex(BatchValidationError, "Slurm compute step"):
                self._run(root, manifest_path, allow_local=False)

    def test_run_row_requires_an_active_slurm_step(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            freeze_batch_spec(self._spec(root), manifest_path)
            with (
                patch.dict(
                    os.environ,
                    {"SLURM_JOB_ID": "123", "SLURM_STEP_ID": "batch"},
                    clear=True,
                ),
                self.assertRaisesRegex(BatchValidationError, "Slurm compute step"),
            ):
                self._run(root, manifest_path, allow_local=False)

    def test_stage_output_rejects_symbolic_links(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            (root / "result.json").symlink_to(target)
            with self.assertRaisesRegex(BatchValidationError, "symbolic link"):
                _output_record(root, "result.json")

    def test_signal_during_publication_cleans_attempt_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(self._spec(root), manifest_path)
            original = batch_module._output_record

            def interrupt_during_hash(output_root: Path, relative: str) -> dict[str, object]:
                os.kill(os.getpid(), signal.SIGTERM)
                return original(output_root, relative)

            with (
                patch(
                    "amt_core.batch._output_record",
                    side_effect=interrupt_during_hash,
                ),
                self.assertRaises(BatchInterrupted),
            ):
                self._run(root, manifest_path)

            run_dir = root / "cache" / manifest["rows"][0]["cache_key"]
            self.assertEqual(list((run_dir / "tmp").iterdir()), [])
            attempts = list((run_dir / "attempts").glob("*/attempt.json"))
            self.assertEqual(len(attempts), 1)
            self.assertEqual(load_json(attempts[0])["status"], "interrupted")
            persistent = list(
                (root / "index" / "fixture-batch" / "attempts" / "row-a").glob("*.json")
            )
            self.assertEqual(len(persistent), 1)

    def test_archived_manifest_can_load_without_live_hyak_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(self._spec(root), manifest_path)
            missing_root = Path("/missing-hyak-checkout")
            manifest["source_spec"]["path"] = str(missing_root / "spec.json")
            manifest["rows"][0]["repository_root"] = str(missing_root)
            for field in ("python", "input", "configuration"):
                manifest["rows"][0][field]["path"] = str(missing_root / field)
            for model in manifest["rows"][0]["models"]:
                model["artifact"]["path"] = str(missing_root / model["name"])
            for artifact in manifest["rows"][0]["code"]["artifacts"]:
                original_path = Path(artifact["artifact"]["path"])
                try:
                    relative = original_path.relative_to(REPO_ROOT)
                except ValueError:
                    relative = Path("external") / original_path.name
                artifact["artifact"]["path"] = str(missing_root / relative)
            atomic_write_json(manifest_path, manifest)

            self.assertEqual(
                load_batch_manifest(manifest_path, verify_source=False),
                manifest,
            )
            with self.assertRaises(BatchValidationError):
                load_batch_manifest(manifest_path)

    def test_task008_scripts_use_slurm_capabilities_not_node_names(self) -> None:
        paths = [
            REPO_ROOT / "scripts" / "hyak" / "bootstrap_hyak.sh",
            REPO_ROOT / "scripts" / "hyak" / "submit_batch.py",
            REPO_ROOT / "slurm" / "29_task008_freeze.slurm",
            REPO_ROOT / "slurm" / "30_task008_batch_array.slurm",
            REPO_ROOT / "slurm" / "31_task008_batch_finalize.slurm",
        ]
        for path in paths:
            self.assertNotIn("klone-login", path.read_text(encoding="utf-8"))
        submitter = paths[1].read_text(encoding="utf-8")
        self.assertIn('shutil.which("sbatch")', submitter)

    def test_hyak_freeze_cli_requires_compute_step(self) -> None:
        module_path = REPO_ROOT / "scripts" / "manage_hyak_batch.py"
        spec = importlib.util.spec_from_file_location("task008_manager_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "manifest.json"
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        str(module_path),
                        "freeze",
                        "--spec",
                        str(Path(temporary) / "missing.json"),
                        "--output",
                        str(output),
                    ],
                ),
                patch.dict(os.environ, {}, clear=True),
                patch.object(module.shutil, "which", return_value="/usr/bin/sbatch"),
            ):
                self.assertEqual(module.main(), 2)
            self.assertFalse(output.exists())

    def test_array_submission_is_persisted_when_finalizer_submit_fails(self) -> None:
        module_path = REPO_ROOT / "scripts" / "hyak" / "submit_batch.py"
        spec = importlib.util.spec_from_file_location("task008_submit_test", module_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = root / "manifest.json"
            manifest = freeze_batch_spec(self._spec(root), manifest_path)
            index_root = root / "index"
            argv = [
                str(module_path),
                "--manifest",
                str(manifest_path),
                "--repo-root",
                str(REPO_ROOT),
                "--cache-root",
                str(root / "cache"),
                "--selected-root",
                str(root / "selected"),
                "--index-root",
                str(index_root),
                "--profile",
                "cpu-smoke",
            ]
            finalizer_error = subprocess.CalledProcessError(
                1,
                ["sbatch"],
                output="",
                stderr="scheduler unavailable",
            )
            with (
                patch.object(sys, "argv", argv),
                patch.dict(os.environ, {}, clear=True),
                patch.object(module.shutil, "which", return_value="/usr/bin/sbatch"),
                patch.object(
                    module.subprocess,
                    "run",
                    side_effect=[
                        subprocess.CompletedProcess(["sbatch"], 0, "12345;cluster\n", ""),
                        finalizer_error,
                    ],
                ),
                self.assertRaises(subprocess.CalledProcessError),
            ):
                module.main()
            submission = load_json(
                index_root / manifest["batch_id"] / "submission-12345.json"
            )
            self.assertEqual(submission["array_job_id"], "12345")
            self.assertEqual(submission["finalizer_status"], "failed")
            self.assertIsNone(submission["finalizer_job_id"])


if __name__ == "__main__":
    unittest.main()
