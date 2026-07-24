from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "scripts" / "hyak" / "setup_separator.sh"


def run_setup_with_env(
    root_env: str | Path,
    worker_env: str | Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "SLURM_JOB_ID": "fixture",
            "AMT_REPO_ROOT": str(REPO_ROOT),
            "AMT_ROOT_ENV": str(root_env),
            "SEPARATOR_ENV": str(worker_env),
            "SEPARATOR_MODEL_DIR": str(REPO_ROOT / "weights" / "fixture"),
            "SEPARATOR_MODEL_PROVENANCE": str(REPO_ROOT / "weights" / "fixture-provenance.json"),
            "UV_BIN": "/usr/bin/true",
        }
    )
    return subprocess.run(
        ["bash", str(SETUP_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
    )


class SeparatorSetupScriptTests(unittest.TestCase):
    def test_rejects_lexical_alias_before_any_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root_env = Path(temporary) / "root-env"
            worker_alias = f"{root_env}/."
            result = run_setup_with_env(root_env, worker_alias)

            self.assertEqual(result.returncode, 2)
            self.assertIn("resolve to the same environment", result.stderr)
            self.assertNotIn("module", result.stderr)

    def test_rejects_symlink_alias_before_any_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            root_env = root / "root-env"
            root_env.mkdir()
            worker_alias = root / "worker-link"
            worker_alias.symlink_to(root_env, target_is_directory=True)
            result = run_setup_with_env(root_env, worker_alias)

            self.assertEqual(result.returncode, 2)
            self.assertIn("resolve to the same environment", result.stderr)
            self.assertNotIn("module", result.stderr)

    def test_rejects_environment_outside_approved_worker_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root_env = REPO_ROOT / ".fixture-root-env"
            worker_env = Path(temporary) / "external-worker-env"
            result = run_setup_with_env(root_env, worker_env)

            self.assertEqual(result.returncode, 2)
            self.assertIn(
                "must resolve inside the separator worker directory",
                result.stderr,
            )
            self.assertNotIn("module", result.stderr)


if __name__ == "__main__":
    unittest.main()
