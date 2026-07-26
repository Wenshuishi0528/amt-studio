from __future__ import annotations

import copy
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.prepare_vocadito_split import (
    RECOVERY_EXCLUDED_SINGERS,
    RECOVERY_EXPECTED_ROUTES,
    RECOVERY_EXPECTED_TRACKS,
    VocaditoPreparationError,
    load_split_config,
    validate_split_config,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = REPO_ROOT / "configs" / "task007b" / "vocadito_v3_recovery_split.json"
TASK007B_SLURM_SCRIPTS = (
    REPO_ROOT / "slurm" / "32_task007b_vocadito_candidates.slurm",
    REPO_ROOT / "slurm" / "33_task007b_fusion_calibrate.slurm",
    REPO_ROOT / "slurm" / "34_task007b_blind_fusion_and_seal.slurm",
    REPO_ROOT / "slurm" / "35_task007b_fusion_evaluate.slurm",
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


class Task007BRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_split_config(CONFIG_PATH)

    def test_recovery_split_is_exact_and_disjoint_from_prior_singers(self) -> None:
        self.assertEqual(
            tuple(self.config["candidate_routes"]),
            RECOVERY_EXPECTED_ROUTES,
        )
        observed_singers: set[str] = set()
        for split_name, expected_pairs in RECOVERY_EXPECTED_TRACKS.items():
            tracks = self.config["splits"][split_name]["tracks"]
            observed_pairs = tuple(
                (record["track_id"], record["singer_id"]) for record in tracks
            )
            self.assertEqual(observed_pairs, expected_pairs)
            singers = {record["singer_id"] for record in tracks}
            self.assertEqual(len(singers), len(tracks))
            self.assertTrue(observed_singers.isdisjoint(singers))
            self.assertTrue(RECOVERY_EXCLUDED_SINGERS.isdisjoint(singers))
            observed_singers.update(singers)
        self.assertEqual(len(observed_singers), 11)

    def test_recovery_split_rejects_prior_singer_and_duplicate_singer(self) -> None:
        prior = copy.deepcopy(self.config)
        prior["splits"]["development"]["tracks"][0]["singer_id"] = "S1"
        with self.assertRaisesRegex(VocaditoPreparationError, "prior experiments"):
            validate_split_config(prior)

        duplicate = copy.deepcopy(self.config)
        duplicate["splits"]["blind_test"]["tracks"][0]["singer_id"] = "S9"
        with self.assertRaisesRegex(VocaditoPreparationError, "split-disjoint"):
            validate_split_config(duplicate)

    def test_candidate_job_freezes_only_the_two_predeclared_routes(self) -> None:
        script = TASK007B_SLURM_SCRIPTS[0].read_text(encoding="utf-8")
        self.assertIn("freeze_evaluation_candidates.py", script)
        self.assertIn("--confirm-output-quality-uninspected", script)
        self.assertIn("game-vocal-a", script)
        self.assertIn("basic-pitch-vocal-a", script)
        self.assertNotIn("muscriptor-vocal-a", script)
        self.assertNotIn("muscriptor-direct", script)

    def test_task007b_slurm_entrypoints_reject_login_nodes(self) -> None:
        for script_path in TASK007B_SLURM_SCRIPTS:
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
            for script_path in TASK007B_SLURM_SCRIPTS:
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

    def test_blind_fusion_is_sealed_before_separate_evaluation(self) -> None:
        fusion_script = TASK007B_SLURM_SCRIPTS[2].read_text(encoding="utf-8")
        fusion_commands = _logical_shell_commands(fusion_script)
        run_command = next(
            command
            for command in fusion_commands
            if "$REPO_ROOT/scripts/run_fusion.py" in command
        )
        seal_command = next(
            command
            for command in fusion_commands
            if "$REPO_ROOT/scripts/evaluate_fusion.py" in command and " seal " in command
        )
        self.assertLess(
            fusion_commands.index(run_command),
            fusion_commands.index(seal_command),
        )
        self.assertIn("--confirm-blind-output-uninspected", seal_command)
        self.assertIn("--confirm-reference-not-used", seal_command)
        self.assertIn("--minimum-candidates 2", seal_command)

        evaluation_script = TASK007B_SLURM_SCRIPTS[3].read_text(encoding="utf-8")
        evaluation_commands = _logical_shell_commands(evaluation_script)
        evaluate_command = next(
            command
            for command in evaluation_commands
            if "$REPO_ROOT/scripts/evaluate_fusion.py" in command
        )
        self.assertIn(" evaluate ", evaluate_command)
        self.assertNotIn(" seal ", evaluate_command)
        self.assertIn('--seal "$SEAL_PATH"', evaluate_command)
        self.assertIn("--minimum-candidates 2", evaluate_command)


if __name__ == "__main__":
    unittest.main()
