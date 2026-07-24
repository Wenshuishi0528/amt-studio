from __future__ import annotations

import unittest
from pathlib import Path


class BeatThisSetupScriptTests(unittest.TestCase):
    def test_setup_is_compute_only_and_clears_only_worker_environment(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script = (repo_root / "scripts" / "hyak" / "setup_beat_this.sh").read_text(encoding="utf-8")
        self.assertIn('[[ -z "${SLURM_JOB_ID:-}"', script)
        self.assertIn('"$(hostname)" == klone-login*', script)
        self.assertIn("BEAT_THIS_ENV must resolve inside workers/beat_this", script)
        self.assertIn('"$UV_BIN" venv \\\n    --clear', script)
        self.assertIn('"$WORKER_ENV"', script)
        self.assertNotIn('--clear "$ROOT_ENV"', script)
        self.assertIn("refusing to overwrite it", script)
        self.assertIn('mv "$TEMP_CHECKPOINT" "$CHECKPOINT"', script)

    def test_slurm_baseline_requires_compute_and_preserves_invalid_runs(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script = (repo_root / "slurm" / "26_beat_this_baseline.slurm").read_text(encoding="utf-8")
        self.assertIn('[[ -z "${SLURM_JOB_ID:-}"', script)
        self.assertIn('"$(hostname)" == klone-login*', script)
        self.assertIn('RUN_ID="${RUN_BASE}-attempt-${ATTEMPT}"', script)
        self.assertNotIn("rm -", script)
        self.assertIn('--pins "$PINS_PATH"', script)
        self.assertIn("--require-output raw/native/mix.npy", script)


if __name__ == "__main__":
    unittest.main()
