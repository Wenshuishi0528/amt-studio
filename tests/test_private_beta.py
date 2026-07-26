from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
import unicodedata
from pathlib import Path

from amt_core.private_beta import (
    PrivateBetaError,
    _load_hyak_configuration,
    _load_state,
    _pipeline_stage,
    _unique_project_dir,
    _validate_state,
)
from amt_core.utils import atomic_write_json, slugify
from workers.muscriptor import run_baseline


class PrivateBetaTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
