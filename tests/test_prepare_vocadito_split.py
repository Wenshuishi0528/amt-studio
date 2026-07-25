from __future__ import annotations

import copy
import json
import os
import stat
import subprocess
import tempfile
import unittest
import wave
from pathlib import Path

from scripts.prepare_vocadito_split import (
    BETWEEN_SILENCE_FRAMES,
    CHANNELS,
    EXPECTED_ROUTES,
    EXPECTED_TRACKS,
    LEAD_SILENCE_FRAMES,
    SAMPLE_RATE,
    SAMPLE_WIDTH,
    TAIL_SILENCE_FRAMES,
    TASK006_BLIND_SINGERS,
    VocaditoPreparationError,
    ensure_project,
    freeze_benchmark_pack,
    load_split_config,
    prepare_concatenation,
    require_slurm_compute_node,
    validate_split_config,
)

from amt_core.benchmark import canonical_json_sha256
from amt_core.utils import sha256_file

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "task007" / "vocadito_v3_split.json"
FUSION_SLURM_SCRIPTS = (
    REPO_ROOT / "slurm" / "27_task007_fusion_calibrate.slurm",
    REPO_ROOT / "slurm" / "28_task007_blind_fusion_and_seal.slurm",
    REPO_ROOT / "slurm" / "29_task007_fusion_evaluate.slurm",
)


def _logical_shell_commands(script: str) -> list[str]:
    commands: list[str] = []
    pending = ""
    for raw_line in script.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        pending = f"{pending} {line}".strip()
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        commands.append(pending)
        pending = ""
    if pending:
        commands.append(pending)
    return commands


def _write_dataset(root: Path, track_specs: list[dict[str, object]]) -> None:
    audio_root = root / "Audio"
    note_root = root / "Annotations" / "Notes"
    audio_root.mkdir(parents=True)
    note_root.mkdir(parents=True)
    metadata_rows = ["track_id,singer_id,average_pitch,language"]
    for spec in track_specs:
        track_id = int(spec["track_id"])
        metadata_rows.append(
            f"{track_id},{spec['singer_id']},{spec['average_midi_pitch']},{spec['language']}"
        )
        with wave.open(str(audio_root / f"vocadito_{track_id}.wav"), "wb") as handle:
            handle.setnchannels(CHANNELS)
            handle.setsampwidth(SAMPLE_WIDTH)
            handle.setframerate(SAMPLE_RATE)
            handle.writeframes(b"\x01\x00" * 441)
        for annotator in ("A1", "A2"):
            (note_root / f"vocadito_{track_id}_notes{annotator}.csv").write_text(
                "0.0,440.0,0.005\n",
                encoding="utf-8",
            )
    (root / "vocadito_metadata.csv").write_text(
        "\n".join(metadata_rows) + "\n",
        encoding="utf-8",
    )


class PrepareVocaditoSplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_split_config(CONFIG_PATH)

    def test_committed_split_is_exact_and_singer_disjoint(self) -> None:
        self.assertEqual(tuple(self.config["candidate_routes"]), EXPECTED_ROUTES)
        observed_singers: set[str] = set()
        for split_name, expected_pairs in EXPECTED_TRACKS.items():
            tracks = self.config["splits"][split_name]["tracks"]
            observed_pairs = tuple((record["track_id"], record["singer_id"]) for record in tracks)
            self.assertEqual(observed_pairs, expected_pairs)
            singers = {record["singer_id"] for record in tracks}
            self.assertTrue(observed_singers.isdisjoint(singers))
            self.assertTrue(TASK006_BLIND_SINGERS.isdisjoint(singers))
            observed_singers.update(singers)

    def test_config_rejects_task006_blind_singer_overlap(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["splits"]["development"]["tracks"][0]["singer_id"] = "S1"
        with self.assertRaisesRegex(VocaditoPreparationError, "Task 006"):
            validate_split_config(changed)

    def test_config_rejects_changed_fixed_track(self) -> None:
        changed = copy.deepcopy(self.config)
        changed["splits"]["blind_test"]["tracks"][0]["track_id"] = 3
        with self.assertRaisesRegex(VocaditoPreparationError, "fixed Task 007 split"):
            validate_split_config(changed)

    def test_refuses_login_node_and_non_slurm_execution(self) -> None:
        with self.assertRaisesRegex(VocaditoPreparationError, "sbatch"):
            require_slurm_compute_node({}, hostname="n001")
        with self.assertRaisesRegex(VocaditoPreparationError, "login node"):
            require_slurm_compute_node(
                {"SLURM_JOB_ID": "123"},
                hostname="klone-login01",
            )
        require_slurm_compute_node({"SLURM_JOB_ID": "123"}, hostname="n001")

    def test_concatenation_is_hash_bound_and_reusable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = root / "extracted"
            artifact_root = root / "artifacts"
            split = self.config["splits"]["development"]
            _write_dataset(extracted, split["tracks"])
            config_sha256 = sha256_file(CONFIG_PATH)

            audio, mapping_path, mapping, selection = prepare_concatenation(
                extracted,
                artifact_root,
                "development",
                split,
                config=self.config,
                config_sha256=config_sha256,
            )

            expected_frames = (
                LEAD_SILENCE_FRAMES + 6 * 441 + 5 * BETWEEN_SILENCE_FRAMES + TAIL_SILENCE_FRAMES
            )
            self.assertEqual(mapping["frame_count"], expected_frames)
            self.assertEqual(mapping["concatenated_audio"]["sha256"], sha256_file(audio))
            self.assertFalse(selection["candidate_output_inspected"])
            self.assertEqual(
                [record["excerpt_id"] for record in mapping["tracks"]],
                [f"dev-{index:02d}" for index in range(1, 7)],
            )
            first_hash = sha256_file(mapping_path)
            reused = prepare_concatenation(
                extracted,
                artifact_root,
                "development",
                split,
                config=self.config,
                config_sha256=config_sha256,
            )
            self.assertEqual(sha256_file(reused[1]), first_hash)

            first_audio = extracted / "Audio" / "vocadito_2.wav"
            with wave.open(str(first_audio), "wb") as handle:
                handle.setnchannels(CHANNELS)
                handle.setsampwidth(SAMPLE_WIDTH)
                handle.setframerate(SAMPLE_RATE)
                handle.writeframes(b"\x02\x00" * 441)
            with self.assertRaisesRegex(
                VocaditoPreparationError,
                "do not match the fixed split",
            ):
                prepare_concatenation(
                    extracted,
                    artifact_root,
                    "development",
                    split,
                    config=self.config,
                    config_sha256=config_sha256,
                )

    def test_freezes_both_annotators_inside_private_pack(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            extracted = root / "extracted"
            artifact_root = root / "artifacts"
            project = root / "vocadito-task007-development-v1"
            split = self.config["splits"]["development"]
            _write_dataset(extracted, split["tracks"])
            config_sha256 = sha256_file(CONFIG_PATH)
            audio, mapping_path, mapping, selection = prepare_concatenation(
                extracted,
                artifact_root,
                "development",
                split,
                config=self.config,
                config_sha256=config_sha256,
            )
            canonical = project / "audio" / "canonical" / "mix.flac"
            canonical.parent.mkdir(parents=True)
            canonical.write_bytes(b"canonical-fixture")
            manifest = {
                "schema_version": 1,
                "project_id": project.name,
                "source": {"sha256": sha256_file(audio)},
                "canonical_audio": {
                    "path": "audio/canonical/mix.flac",
                    "sha256": sha256_file(canonical),
                    "metadata": {"duration_sec": mapping["duration_sec"]},
                },
            }
            (project / "manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            verified_manifest = ensure_project(
                audio,
                project,
                split_name="development",
            )
            selection_path = artifact_root / "development" / "selection_manifest.json"
            pack, benchmark = freeze_benchmark_pack(
                project,
                "development",
                split,
                verified_manifest,
                mapping_path,
                mapping,
                selection_path,
                selection,
                CONFIG_PATH,
                config_sha256=config_sha256,
            )

            payload = benchmark["freeze_payload"]
            self.assertEqual(
                benchmark["benchmark_freeze_sha256"],
                canonical_json_sha256(payload),
            )
            self.assertEqual(payload["split"], "development")
            self.assertFalse(benchmark["claims"]["blind_test"])
            self.assertFalse(benchmark["claims"]["candidate_output_quality_inspected"])
            self.assertEqual(len(payload["excerpts"]), 6)
            for excerpt in payload["excerpts"]:
                for annotator in ("a1", "a2"):
                    reference = excerpt["note_references"][annotator]
                    path = Path(reference["path"])
                    self.assertTrue(path.is_relative_to(pack))
                    self.assertEqual(sha256_file(path), reference["sha256"])
                    self.assertEqual(reference["note_count"], 1)

    def test_slurm_entrypoints_keep_compute_and_blind_freeze_guards(self) -> None:
        prepare_script = (REPO_ROOT / "slurm" / "25_task007_vocadito_prepare.slurm").read_text(
            encoding="utf-8"
        )
        candidate_script = (REPO_ROOT / "slurm" / "26_task007_vocadito_candidates.slurm").read_text(
            encoding="utf-8"
        )
        for script in (prepare_script, candidate_script):
            self.assertIn("SLURM_JOB_ID:-", script)
            self.assertIn('hostname)" == klone-login*', script)
        self.assertIn("freeze_evaluation_candidates.py", candidate_script)
        self.assertIn("--confirm-output-quality-uninspected", candidate_script)
        for route in EXPECTED_ROUTES:
            self.assertIn(route, candidate_script)

    def test_fusion_slurm_entrypoints_reject_non_slurm_and_login_node(self) -> None:
        for script_path in FUSION_SLURM_SCRIPTS:
            no_allocation = subprocess.run(
                ["/bin/bash", str(script_path)],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env={"PATH": os.environ["PATH"]},
            )
            self.assertEqual(no_allocation.returncode, 2, script_path.name)
            self.assertIn("sbatch", no_allocation.stderr, script_path.name)

        with tempfile.TemporaryDirectory() as temporary:
            fake_bin = Path(temporary)
            hostname = fake_bin / "hostname"
            hostname.write_text(
                "#!/bin/sh\nprintf '%s\\n' klone-login01\n",
                encoding="utf-8",
            )
            hostname.chmod(hostname.stat().st_mode | stat.S_IXUSR)
            environment = {
                "PATH": f"{fake_bin}:{os.environ['PATH']}",
                "SLURM_JOB_ID": "fixture",
            }
            for script_path in FUSION_SLURM_SCRIPTS:
                login_node = subprocess.run(
                    ["/bin/bash", str(script_path)],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    env=environment,
                )
                self.assertEqual(login_node.returncode, 2, script_path.name)
                self.assertIn("login node", login_node.stderr, script_path.name)

    def test_blind_fusion_runs_then_seals_in_the_same_slurm_job(self) -> None:
        path = REPO_ROOT / "slurm" / "28_task007_blind_fusion_and_seal.slurm"
        script = path.read_text(encoding="utf-8")
        commands = _logical_shell_commands(script)
        run_commands = [
            command for command in commands if "$REPO_ROOT/scripts/run_fusion.py" in command
        ]
        seal_commands = [
            command
            for command in commands
            if "$REPO_ROOT/scripts/evaluate_fusion.py" in command and " seal " in command
        ]

        self.assertEqual(len(run_commands), 1)
        self.assertEqual(len(seal_commands), 1)
        self.assertTrue(run_commands[0].startswith('srun "$ROOT_PYTHON"'))
        self.assertTrue(seal_commands[0].startswith('srun "$ROOT_PYTHON"'))
        self.assertLess(commands.index(run_commands[0]), commands.index(seal_commands[0]))
        self.assertNotIn("sbatch ", "\n".join(commands))
        self.assertIn('--fusion-run "$FUSION_DIR"', seal_commands[0])
        self.assertIn("--confirm-blind-output-uninspected", seal_commands[0])
        self.assertIn("--confirm-reference-not-used", seal_commands[0])
        self.assertIn(
            'if [[ -e "$FUSION_DIR" || -L "$FUSION_DIR" ]]',
            script,
        )
        self.assertIn("seal will independently verify it before reuse", script)

    def test_blind_evaluation_requires_and_consumes_the_fusion_seal(self) -> None:
        path = REPO_ROOT / "slurm" / "29_task007_fusion_evaluate.slurm"
        script = path.read_text(encoding="utf-8")
        commands = _logical_shell_commands(script)
        evaluation_commands = [
            command for command in commands if "$REPO_ROOT/scripts/evaluate_fusion.py" in command
        ]

        self.assertEqual(len(evaluation_commands), 1)
        command = evaluation_commands[0]
        self.assertTrue(command.startswith('srun "$ROOT_PYTHON"'))
        self.assertIn(" evaluate ", command)
        self.assertIn('--seal "$SEAL_PATH"', command)
        self.assertIn('! -f "$SEAL_PATH"', script)
        self.assertNotIn(" seal ", command)

    def test_fusion_recomputation_commands_are_srun_only(self) -> None:
        expected_entrypoints = {
            "27_task007_fusion_calibrate.slurm": {"calibrate_fusion.py"},
            "28_task007_blind_fusion_and_seal.slurm": {
                "run_fusion.py",
                "evaluate_fusion.py",
            },
            "29_task007_fusion_evaluate.slurm": {"evaluate_fusion.py"},
        }
        for script_path in FUSION_SLURM_SCRIPTS:
            script = script_path.read_text(encoding="utf-8")
            commands = _logical_shell_commands(script)
            compute_commands = [command for command in commands if "$REPO_ROOT/scripts/" in command]
            observed_entrypoints = {
                Path(command.split("$REPO_ROOT/scripts/", 1)[1].split('"', 1)[0]).name
                for command in compute_commands
            }
            self.assertEqual(
                observed_entrypoints,
                expected_entrypoints[script_path.name],
                script_path.name,
            )
            self.assertTrue(compute_commands, script_path.name)
            for command in compute_commands:
                self.assertTrue(
                    command.startswith('srun "$ROOT_PYTHON"'),
                    f"non-srun recomputation in {script_path.name}: {command}",
                )


if __name__ == "__main__":
    unittest.main()
