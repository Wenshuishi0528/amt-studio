from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SETUP_SCRIPT = REPO_ROOT / "scripts" / "hyak" / "setup_game.sh"


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
            "GAME_ENV": str(worker_env),
            "GAME_ASSET_ROOT": str(REPO_ROOT / "weights" / "game-fixture"),
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


class GameSetupScriptTests(unittest.TestCase):
    def test_large_product_pin_matches_verified_official_inventory(self) -> None:
        pins = json.loads(
            (REPO_ROOT / "workers/game/pins-large.json").read_text(
                encoding="utf-8"
            )
        )
        model = pins["model"]

        self.assertEqual(model["name"], "GAME-1.0-large")
        self.assertEqual(model["archive_size_bytes"], 366_297_733)
        self.assertEqual(
            model["archive_sha256"],
            "f45eac9fbb92b82fe67c00f29efad52954469897eb64e5bd5924a43dc5deb9b6",
        )
        self.assertEqual(
            {item["path"]: item["size_bytes"] for item in model["expected_files"]},
            {
                "GAME-1.0-large/config.yaml": 1_692,
                "GAME-1.0-large/lang_map.json": 37,
                "GAME-1.0-large/model.pt": 396_393_454,
            },
        )

    def test_setup_never_clears_shared_root_environment(self) -> None:
        script = SETUP_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('ROOT_PYTHON="$ROOT_ENV/bin/python"', script)
        self.assertNotIn('UV_PROJECT_ENVIRONMENT="$ROOT_ENV"', script)
        self.assertNotIn(
            '--python "$GAME_PYTHON" \\\n    "$ROOT_ENV"',
            script,
        )

    def test_rejects_lexical_alias_before_any_clear(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root_env = Path(temporary) / "root-env"
            result = run_setup_with_env(root_env, f"{root_env}/.")
            self.assertEqual(result.returncode, 2)
            self.assertIn("safety boundary", result.stderr)
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
            self.assertIn("safety boundary", result.stderr)
            self.assertNotIn("module", result.stderr)

    def test_rejects_worker_environment_outside_worker_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root_env = REPO_ROOT / ".fixture-game-root-env"
            worker_env = Path(temporary) / "external-game-worker"
            result = run_setup_with_env(root_env, worker_env)
            self.assertEqual(result.returncode, 2)
            self.assertIn("must resolve inside workers/game", result.stderr)
            self.assertNotIn("module", result.stderr)


if __name__ == "__main__":
    unittest.main()
