from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unicodedata
from pathlib import Path
from unittest import mock

from amt_core.private_beta import (
    GPU_TEST_START_PATTERN,
    HyakGPUProbe,
    PrivateBetaError,
    _fallback_gpu_plan,
    _gpu_candidates_from_associations,
    _local_worker_command,
    _load_hyak_configuration,
    _load_state,
    _pipeline_stage,
    _plan_hyak_gpu,
    _select_gpu_probe,
    _slurm_time_limit,
    _unique_project_dir,
    _validate_state,
    build_parser,
    local_readiness,
    start_game_vocal_job,
)
from amt_core.utils import atomic_write_json, slugify
from workers.muscriptor import run_baseline


class PrivateBetaTests(unittest.TestCase):
    def test_gpu_auto_plan_discovers_only_verified_compatible_resources(self) -> None:
        candidates = _gpu_candidates_from_associations(
            "\n".join(
                (
                    "ckpt-team||ckpt,ckpt-gpu,ckpt-scav",
                    "gpu-l40-team||normal",
                    "gpu-l40s-team||normal",
                    "gpu-h200-other||normal",
                    "compute-team||normal",
                )
            )
        )

        self.assertEqual(
            {candidate.gpu_type for candidate in candidates},
            {"a100", "a40", "l40", "l40s"},
        )
        self.assertTrue(
            next(candidate for candidate in candidates if candidate.gpu_type == "a100")
            .preemptible
        )
        self.assertFalse(
            next(candidate for candidate in candidates if candidate.gpu_type == "l40")
            .preemptible
        )
        self.assertNotIn("h200", {candidate.gpu_type for candidate in candidates})

    def test_gpu_auto_plan_uses_earliest_start_then_five_minute_speed_tie(self) -> None:
        candidates = {
            candidate.gpu_type: candidate
            for candidate in _gpu_candidates_from_associations(
                "\n".join(
                    (
                        "ckpt-team||ckpt,ckpt-gpu",
                        "gpu-l40-team||normal",
                        "gpu-l40s-team||normal",
                    )
                )
            )
        }
        selected, wait = _select_gpu_probe(
            (
                HyakGPUProbe(candidates["a40"], "fixture-a40", 1_000),
                HyakGPUProbe(candidates["a100"], "fixture-a100", 1_000),
                HyakGPUProbe(candidates["l40"], "fixture-l40", 1_200),
            ),
            now_epoch=900,
        )
        self.assertEqual(selected.candidate.gpu_type, "a100")
        self.assertEqual(wait, 100)

        selected, _wait = _select_gpu_probe(
            (
                HyakGPUProbe(candidates["l40"], "fixture-l40", 1_000),
                HyakGPUProbe(candidates["a100"], "fixture-a100", 1_301),
            ),
            now_epoch=900,
        )
        self.assertEqual(selected.candidate.gpu_type, "l40")

    def test_gpu_auto_plan_fallback_keeps_stable_l40_and_one_hour(self) -> None:
        candidates = _gpu_candidates_from_associations(
            "gpu-l40-team||normal"
        )
        plan = _fallback_gpu_plan(
            candidates,
            time_limit_hours=1,
            reason="fixture fallback",
        )

        self.assertEqual(plan.candidate.gpu_type, "l40")
        self.assertIn("--partition=gpu-l40", plan.submission_arguments)
        self.assertIn("--time=01:00:00", plan.submission_arguments)
        self.assertEqual(plan.state_fields()["gpu_selection_reason"], "fixture fallback")
        self.assertIsNotNone(
            GPU_TEST_START_PATTERN.search(
                "sbatch: Job 123 to start at 2026-07-27T20:19:38 using node"
            )
        )

    def test_gpu_auto_plan_captures_slurm_test_only_stderr(self) -> None:
        class FixtureConnection:
            def remote(self, command: str, *, timeout: float | None = None) -> str:
                del timeout
                if command.startswith("sacctmgr "):
                    return "\n".join(
                        (
                            "ckpt-team||ckpt,ckpt-gpu",
                            "gpu-l40-team||normal",
                            "gpu-l40s-team||normal",
                        )
                    )
                if command == "date +%s":
                    return "1785200000"
                if command.startswith("sbatch "):
                    self.assert_test_only_command(command)
                    return (
                        "sbatch: Job 123 to start at "
                        "2026-07-27T20:19:38 using node"
                    )
                if command.startswith("date -d "):
                    return "1785200001"
                raise AssertionError(f"unexpected command: {command}")

            @staticmethod
            def assert_test_only_command(command: str) -> None:
                if not command.endswith(" 2>&1"):
                    raise AssertionError("Slurm test-only stderr was not captured")

        plan = _plan_hyak_gpu(FixtureConnection(), time_limit_hours=1)

        self.assertEqual(plan.candidate.gpu_type, "a100")
        self.assertEqual(plan.probed_candidate_count, 4)

        stable_plan = _plan_hyak_gpu(
            FixtureConnection(),
            time_limit_hours=1,
            allow_preemptible=False,
        )
        self.assertEqual(stable_plan.candidate.gpu_type, "l40s")
        self.assertFalse(stable_plan.candidate.preemptible)
        self.assertEqual(stable_plan.probed_candidate_count, 2)

    def test_hyak_time_limit_defaults_to_one_hour_and_is_bounded(self) -> None:
        parser = build_parser()
        default = parser.parse_args(
            [
                "start",
                "song.mp3",
                "--repo-root",
                "repo",
                "--local-root",
                "projects",
            ]
        )
        selected = parser.parse_args(
            [
                "start-gap-recovery",
                "project",
                "--repo-root",
                "repo",
                "--source-bundle",
                "bundle",
                "--source-track",
                "voice",
                "--gap",
                "1:2",
                "--time-limit-hours",
                "6",
            ]
        )
        game = parser.parse_args(
            [
                "start",
                "song.mp3",
                "--repo-root",
                "repo",
                "--local-root",
                "projects",
                "--recognition-mode",
                "game_vocal",
            ]
        )
        existing_game = parser.parse_args(
            [
                "start-game-vocal",
                "project",
                "--repo-root",
                "repo",
            ]
        )

        self.assertEqual(default.time_limit_hours, 1)
        self.assertEqual(default.recognition_mode, "multitrack")
        self.assertEqual(game.recognition_mode, "game_vocal")
        self.assertEqual(existing_game.command, "start-game-vocal")
        self.assertEqual(selected.time_limit_hours, 6)
        self.assertEqual(_slurm_time_limit(1), "01:00:00")
        self.assertEqual(_slurm_time_limit(24), "24:00:00")
        for invalid in (0, 25, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(PrivateBetaError, "1–24"):
                    _slurm_time_limit(invalid)

    def test_console_entrypoint_can_load_repository_workers(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script = """
import pathlib
import sys

repo_root = pathlib.Path(sys.argv[1]).resolve()
if str(repo_root) in sys.path:
    raise SystemExit("fixture unexpectedly inherited the repository root")
from amt_core.private_beta import _ensure_repository_imports
_ensure_repository_imports(repo_root)
import workers.muscriptor.targeted_gap_recovery
print("worker import ok")
"""
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run(
                [sys.executable, "-c", script, str(repo_root)],
                cwd=temporary,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "worker import ok")

    def test_project_directory_is_worker_project_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = _unique_project_dir(root, "STILL LOVE HER (失われた風景)")
            self.assertEqual(project.name, slugify(project.name))
            project.mkdir()
            second = _unique_project_dir(root, "STILL LOVE HER (失われた風景)")
            self.assertNotEqual(second, project)
            self.assertEqual(second.name, slugify(second.name))

    def test_local_configuration_is_explicit_and_not_identity_coded(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "configs").mkdir()
            atomic_write_json(
                root / "configs" / "local_hyak.json",
                {
                    "schema_version": 1,
                    "host": "netid@klone.hyak.uw.edu",
                    "remote_root": "/mmfs1/gscratch/group/netid/amt-studio",
                },
            )
            self.assertEqual(
                _load_hyak_configuration(root, host=None, remote_root=None),
                (
                    "netid@klone.hyak.uw.edu",
                    "/mmfs1/gscratch/group/netid/amt-studio",
                ),
            )

    def test_state_rejects_path_escape_and_project_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "song"
            (project / "app").mkdir(parents=True)
            atomic_write_json(
                project / "manifest.json",
                {"schema_version": 1, "project_id": "song"},
            )
            state = {
                "schema_version": 1,
                "status": "submitted",
                "submitted_at": "2026-07-26T00:00:00+00:00",
                "updated_at": "2026-07-26T00:00:00+00:00",
                "project_id": "song",
                "local_project_dir": str(project),
                "remote_project_dir": (
                    "/mmfs1/gscratch/group/netid/amt-studio/projects/private/song"
                ),
                "host": "netid@klone.hyak.uw.edu",
                "remote_root": "/mmfs1/gscratch/group/netid/amt-studio",
                "job_id": "12345",
                "run_id": "safe-run",
                "bundle_id": "safe-run-multitrack",
                "weight_provenance_path": (
                    "/mmfs1/gscratch/group/netid/weights/provenance.json"
                ),
                "slurm_state": "PENDING",
            }
            state_path = project / "app" / "private_beta_job.json"
            atomic_write_json(state_path, state)
            loaded = _load_state(project)
            self.assertEqual(loaded["run_id"], "safe-run")
            self.assertEqual(loaded["pipeline_stage"], "queued")

            state["pipeline_stage"] = "invented-stage"
            atomic_write_json(state_path, state)
            with self.assertRaisesRegex(PrivateBetaError, "pipeline_stage"):
                _load_state(project)
            state.pop("pipeline_stage")

            state["run_id"] = "../../escaped"
            atomic_write_json(state_path, state)
            with self.assertRaisesRegex(PrivateBetaError, "run_id"):
                _load_state(project)

            state["run_id"] = "safe-run"
            state["project_id"] = "another-song"
            atomic_write_json(state_path, state)
            with self.assertRaisesRegex(PrivateBetaError, "project_id"):
                _load_state(project)

    def test_state_accepts_canonically_equivalent_macos_project_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project_id = "大沢誉志幸-ゴーゴーヘブン"
            decomposed_id = unicodedata.normalize("NFD", project_id)
            self.assertNotEqual(decomposed_id, project_id)
            project = root / decomposed_id
            project.mkdir()
            atomic_write_json(
                project / "manifest.json",
                {"schema_version": 1, "project_id": project_id},
            )
            state = {
                "schema_version": 1,
                "status": "submitted",
                "submitted_at": "2026-07-26T00:00:00+00:00",
                "project_id": project_id,
                "local_project_dir": str(project),
                "remote_project_dir": (
                    "/mmfs1/gscratch/group/netid/amt-studio/projects/private/"
                    + project_id
                ),
                "host": "netid@klone.hyak.uw.edu",
                "remote_root": "/mmfs1/gscratch/group/netid/amt-studio",
                "job_id": "12345",
                "run_id": "safe-run",
                "bundle_id": "safe-run-multitrack",
                "weight_provenance_path": (
                    "/mmfs1/gscratch/group/netid/weights/provenance.json"
                ),
                "slurm_state": "PENDING",
            }

            loaded = _validate_state(project.resolve(), state)

            self.assertEqual(loaded["project_id"], project_id)
            self.assertEqual(loaded["pipeline_stage"], "queued")

    def test_local_state_and_readiness_do_not_start_inference(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "projects/private/local-song"
            (project / "app").mkdir(parents=True)
            (project / "logs").mkdir()
            atomic_write_json(
                project / "manifest.json",
                {"schema_version": 1, "project_id": "local-song"},
            )
            worker_bin = root / "workers/muscriptor/.venv/bin"
            worker_bin.mkdir(parents=True)
            for executable in ("python", "muscriptor"):
                path = worker_bin / executable
                path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                path.chmod(0o755)
            model_dir = root / "model"
            model_dir.mkdir()
            weight = model_dir / "model.safetensors"
            config = model_dir / "config.json"
            weight.write_bytes(b"fixture")
            config.write_text("{}", encoding="utf-8")
            provenance = root / "weights/muscriptor/large-provenance.json"
            provenance.parent.mkdir(parents=True)
            atomic_write_json(
                provenance,
                {
                    "schema_version": 1,
                    "repository": "MuScriptor/muscriptor-large",
                    "weight": {"path": str(weight)},
                    "config": {"path": str(config)},
                },
            )
            readiness = local_readiness(
                root,
                device="cpu",
                probe_device=False,
            )
            self.assertTrue(readiness["ready"])
            self.assertEqual(readiness["local_device"], "cpu")

            state = {
                "schema_version": 1,
                "backend": "local",
                "status": "running",
                "submitted_at": "2026-07-26T00:00:00+00:00",
                "project_id": "local-song",
                "local_project_dir": str(project),
                "job_id": "local-0123456789ab",
                "run_id": "muscriptor-local-fixture",
                "bundle_id": "muscriptor-local-fixture-multitrack",
                "weight_provenance_path": str(provenance),
                "slurm_state": "RUNNING",
                "pipeline_stage": "full_transcription",
                "local_device": "cpu",
                "local_pid": 12345,
                "local_log_path": str(project / "logs/local-compute.log"),
            }
            loaded = _validate_state(project.resolve(), state)
            self.assertEqual(loaded["backend"], "local")
            self.assertEqual(loaded["local_device"], "cpu")

            command = _local_worker_command(project, repo_root=root)
            self.assertIn("run-local-worker", command)
            self.assertIn(str(project), command)

            state["local_log_path"] = str(root / "outside/local-compute.log")
            with self.assertRaisesRegex(PrivateBetaError, "日志路径"):
                _validate_state(project.resolve(), state)

    def test_state_file_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "song"
            (project / "app").mkdir(parents=True)
            target = root / "outside.json"
            target.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
            (project / "app" / "private_beta_job.json").symlink_to(target)
            with self.assertRaisesRegex(PrivateBetaError, "符号链接"):
                _load_state(project)

    def test_worker_prefers_verified_synchronized_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            atomic_write_json(
                root / ".amt-code-snapshot.json",
                {
                    "schema_version": 1,
                    "commit": "a" * 40,
                    "dirty": False,
                    "source": "git_archive",
                },
            )
            self.assertEqual(
                run_baseline.git_state(root),
                {"commit": "a" * 40, "dirty": False},
            )

    def test_pipeline_stage_reports_the_current_single_job_phase(self) -> None:
        class LocalConnection:
            def remote(self, command: str, *, timeout: float | None = None) -> str:
                del timeout
                result = subprocess.run(
                    ["bash", "-c", command],
                    check=True,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                )
                return result.stdout.strip()

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "remote project"
            state = {
                "remote_project_dir": str(project),
                "run_id": "full-run",
                "bundle_id": "full-run-multitrack",
            }
            connection = LocalConnection()
            self.assertEqual(_pipeline_stage(connection, state), "starting")

            run_manifest = project / "runs/full-run/run_manifest.json"
            run_manifest.parent.mkdir(parents=True)
            run_manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(
                _pipeline_stage(connection, state),
                "full_transcription",
            )

            rhythm_manifest = (
                project / "runs/full-run-rhythm/run_manifest.json"
            )
            rhythm_manifest.parent.mkdir(parents=True)
            rhythm_manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(
                _pipeline_stage(connection, state),
                "rhythm_analysis",
            )

            raw_bundle = (
                project
                / "exports/full-run-multitrack-raw/bundle_manifest.json"
            )
            raw_bundle.parent.mkdir(parents=True)
            raw_bundle.write_text("{}", encoding="utf-8")
            self.assertEqual(_pipeline_stage(connection, state), "gap_planning")

            gap_manifest = (
                project / "runs/full-run-auto-gap/run_manifest.json"
            )
            gap_manifest.parent.mkdir(parents=True)
            gap_manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(
                _pipeline_stage(connection, state),
                "automatic_gap_recovery",
            )

            final_bundle = (
                project / "exports/full-run-multitrack/bundle_manifest.json"
            )
            final_bundle.parent.mkdir(parents=True)
            final_bundle.write_text("{}", encoding="utf-8")
            self.assertEqual(_pipeline_stage(connection, state), "packaging")

            targeted = {
                "task_kind": "targeted_gap_recovery",
                "remote_project_dir": str(project / "targeted"),
                "run_id": "gap-run",
                "bundle_id": "gap-run-multitrack",
            }
            self.assertEqual(_pipeline_stage(connection, targeted), "starting")
            targeted_manifest = (
                project / "targeted/runs/gap-run/run_manifest.json"
            )
            targeted_manifest.parent.mkdir(parents=True)
            targeted_manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(
                _pipeline_stage(connection, targeted),
                "targeted_gap_recovery",
            )

            game_project = project / "game"
            game = {
                "recognition_mode": "game_vocal",
                "task_kind": "game_vocal_transcription",
                "remote_project_dir": str(game_project),
                "run_id": "game-run",
                "separator_run_id": "game-run-separator-vocal",
                "bundle_id": "game-run-multitrack",
            }
            self.assertEqual(_pipeline_stage(connection, game), "starting")
            separator_manifest = (
                game_project
                / "runs/game-run-separator-vocal/run_manifest.json"
            )
            separator_manifest.parent.mkdir(parents=True)
            separator_manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(
                _pipeline_stage(connection, game),
                "source_separation",
            )
            game_manifest = game_project / "runs/game-run/run_manifest.json"
            game_manifest.parent.mkdir(parents=True)
            game_manifest.write_text("{}", encoding="utf-8")
            self.assertEqual(
                _pipeline_stage(connection, game),
                "game_vocal_transcription",
            )

    def test_game_state_requires_private_assets_and_hyak_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "song"
            project.mkdir()
            atomic_write_json(
                project / "manifest.json",
                {"schema_version": 1, "project_id": "song"},
            )
            state = {
                "schema_version": 1,
                "task_kind": "game_vocal_transcription",
                "recognition_mode": "game_vocal",
                "backend": "hyak",
                "status": "submitted",
                "submitted_at": "2026-07-27T00:00:00+00:00",
                "project_id": "song",
                "local_project_dir": str(project),
                "remote_project_dir": "/remote/projects/private/song",
                "host": "netid@klone.hyak.uw.edu",
                "remote_root": "/remote",
                "job_id": "12345",
                "run_id": "game-run",
                "separator_run_id": "game-run-separator-vocal",
                "bundle_id": "game-run-multitrack",
                "separator_model_dir": "/remote/weights/separator",
                "game_model_provenance_path": (
                    "/remote/weights/game/model-provenance.json"
                ),
                "weight_provenance_path": (
                    "/remote/weights/game/model-provenance.json"
                ),
                "slurm_state": "PENDING",
            }

            loaded = _validate_state(project.resolve(), state)
            self.assertEqual(loaded["recognition_mode"], "game_vocal")
            self.assertEqual(loaded["task_kind"], "game_vocal_transcription")

            invalid = dict(state)
            invalid["separator_model_dir"] = "../escaped"
            with self.assertRaisesRegex(
                PrivateBetaError,
                "separator_model_dir",
            ):
                _validate_state(project.resolve(), invalid)

            invalid_backend = dict(state)
            invalid_backend["backend"] = "local"
            with self.assertRaisesRegex(PrivateBetaError, "只允许 Hyak"):
                _validate_state(project.resolve(), invalid_backend)

    def test_game_job_rejects_active_state_before_hyak_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "song"
            project.mkdir()
            atomic_write_json(
                project / "manifest.json",
                {"schema_version": 1, "project_id": "song"},
            )
            atomic_write_json(
                project / "app" / "private_beta_job.json",
                {
                    "schema_version": 1,
                    "task_kind": "game_vocal_transcription",
                    "recognition_mode": "game_vocal",
                    "backend": "hyak",
                    "status": "submitted",
                    "submitted_at": "2026-07-27T00:00:00+00:00",
                    "project_id": "song",
                    "local_project_dir": str(project),
                    "remote_project_dir": "/remote/projects/private/song",
                    "host": "netid@klone.hyak.uw.edu",
                    "remote_root": "/remote",
                    "job_id": "12345",
                    "run_id": "game-run",
                    "separator_run_id": "game-run-separator-vocal",
                    "bundle_id": "game-run-multitrack",
                    "separator_model_dir": "/remote/weights/separator",
                    "game_model_provenance_path": (
                        "/remote/weights/game/model-provenance.json"
                    ),
                    "weight_provenance_path": (
                        "/remote/weights/game/model-provenance.json"
                    ),
                    "slurm_state": "PENDING",
                },
            )

            with mock.patch(
                "amt_core.private_beta._load_hyak_configuration"
            ) as load_hyak:
                with self.assertRaisesRegex(
                    PrivateBetaError,
                    "已有计算任务",
                ):
                    start_game_vocal_job(
                        project,
                        repo_root=root,
                        host=None,
                        remote_root=None,
                        game_model_provenance=None,
                        separator_model_dir=None,
                    )
                load_hyak.assert_not_called()


if __name__ == "__main__":
    unittest.main()
