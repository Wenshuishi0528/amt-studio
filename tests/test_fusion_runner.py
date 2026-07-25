from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.run_fusion import (
    FusionRunError,
    _stable_route_binding,
    create_fusion_run,
)

from amt_core.contracts import load_worker_result
from amt_core.events import NoteEvent, write_jsonl
from amt_core.utils import sha256_file


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _event(run_id: str, index: int, onset: float, pitch: float) -> NoteEvent:
    return NoteEvent(
        event_id=f"{run_id}:{index}",
        track_id=f"{run_id}:voice",
        onset_sec=onset,
        offset_sec=onset + 0.4,
        pitch_midi=pitch,
        source_run_id=run_id,
        source_model="fixture",
        instrument="voice",
        is_main_melody_candidate=True,
    )


def _artifact(path: Path, run_dir: Path) -> dict[str, object]:
    return {
        "path": str(path.relative_to(run_dir)),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


class FusionRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "fixture-project"
        canonical = self.project / "audio" / "canonical" / "mix.flac"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"fixture-canonical-audio")
        self.canonical_hash = hashlib.sha256(canonical.read_bytes()).hexdigest()
        _write_json(
            self.project / "manifest.json",
            {
                "schema_version": 1,
                "project_id": "fixture-project",
                "canonical_audio": {"sha256": self.canonical_hash},
            },
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, run_id: str, worker: str, events: list[NoteEvent]) -> Path:
        run_dir = self.project / "runs" / run_id
        events_path = run_dir / "normalized" / "events.jsonl"
        write_jsonl(events_path, events)
        _write_json(run_dir / "normalized" / "summary.json", {"count": len(events)})
        outputs = [
            _artifact(path, run_dir)
            for path in (
                events_path,
                run_dir / "normalized" / "summary.json",
            )
        ]
        _write_json(
            run_dir / "run_manifest.json",
            {
                "schema_version": 1,
                "contract_version": "amt-worker-result/v1",
                "status": "succeeded",
                "run_id": run_id,
                "project_id": "fixture-project",
                "worker": worker,
                "input_lineage": {
                    "canonical_mix_sha256": self.canonical_hash,
                },
                "outputs": outputs,
            },
        )
        return run_dir

    def _profiles_and_config(
        self,
        game: Path,
        basic: Path,
    ) -> tuple[Path, Path]:
        profiles = self.root / "profiles.json"
        config = self.root / "config.json"
        _write_json(
            profiles,
            {
                "schema": "amt-fusion-source-profiles/v1",
                "profiles": [
                    {
                        "label": "game",
                        "reliability": 0.8,
                        "stem_quality": 1.0,
                        "instrument_presence": 1.0,
                    },
                    {
                        "label": "basic",
                        "reliability": 0.7,
                        "stem_quality": 1.0,
                        "instrument_presence": 1.0,
                    },
                ],
                "route_bindings": [
                    {
                        "label": label,
                        **_stable_route_binding(
                            load_worker_result(run_dir),
                            load_worker_result(run_dir).read_note_events(),
                        ),
                    }
                    for label, run_dir in (
                        ("game", game),
                        ("basic", basic),
                    )
                ],
            },
        )
        from amt_core.fusion import FusionConfig

        _write_json(
            config,
            {
                "schema": "amt-fusion-config/v1",
                "config": FusionConfig(minimum_raw_score=0.0).to_dict(),
            },
        )
        return profiles, config

    def test_runner_verifies_inputs_and_writes_immutable_artifact(self) -> None:
        game = self._run(
            "game-run",
            "game",
            [_event("game-run", 1, 1.0, 60)],
        )
        basic = self._run(
            "basic-run",
            "basic_pitch",
            [_event("basic-run", 1, 1.02, 60.1)],
        )
        profiles, config = self._profiles_and_config(game, basic)
        output = self.project / "fusion" / "fusion-v1"
        output.parent.mkdir()
        manifest = create_fusion_run(
            [("game", game), ("basic", basic)],
            profiles,
            config,
            output,
            run_id="fusion-v1",
        )
        self.assertEqual(manifest["status"], "succeeded")
        self.assertTrue(manifest["claims"]["all_eligible_candidates_preserved"])
        self.assertTrue(manifest["claims"]["all_input_candidates_accounted_for"])
        self.assertTrue(manifest["claims"]["final_note_provenance_complete"])
        self.assertFalse(manifest["claims"]["manual_edits_applied"])
        event = json.loads((output / "events.jsonl").read_text().strip())
        self.assertEqual(
            event["source_event_ids"],
            ["basic:basic-run:1", "game:game-run:1"],
        )
        with self.assertRaisesRegex(FusionRunError, "already exists"):
            create_fusion_run(
                [("game", game), ("basic", basic)],
                profiles,
                config,
                output,
                run_id="fusion-v1",
            )

    def test_runner_rejects_cross_project_lineage(self) -> None:
        game = self._run(
            "game-run",
            "game",
            [_event("game-run", 1, 1.0, 60)],
        )
        basic = self._run(
            "basic-run",
            "basic_pitch",
            [_event("basic-run", 1, 1.02, 60.1)],
        )
        manifest_path = basic / "run_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["input_lineage"]["canonical_mix_sha256"] = "f" * 64
        _write_json(manifest_path, manifest)
        profiles, config = self._profiles_and_config(game, basic)
        output = self.project / "fusion" / "fusion-v1"
        output.parent.mkdir()
        with self.assertRaisesRegex(FusionRunError, "lineage differs"):
            create_fusion_run(
                [("game", game), ("basic", basic)],
                profiles,
                config,
                output,
                run_id="fusion-v1",
            )

    def test_runner_records_prefilter_rejections_with_reasons(self) -> None:
        guitar = NoteEvent(
            event_id="game-run:guitar",
            track_id="game-run:guitar",
            onset_sec=1.0,
            offset_sec=1.5,
            pitch_midi=67,
            source_run_id="game-run",
            source_model="fixture",
            instrument="guitar",
        )
        game = self._run(
            "game-run",
            "game",
            [_event("game-run", 1, 1.0, 60), guitar],
        )
        basic = self._run(
            "basic-run",
            "basic_pitch",
            [_event("basic-run", 1, 1.02, 60.1)],
        )
        profiles, config = self._profiles_and_config(game, basic)
        output = self.project / "fusion" / "fusion-v1"
        output.parent.mkdir()
        manifest = create_fusion_run(
            [("game", game), ("basic", basic)],
            profiles,
            config,
            output,
            run_id="fusion-v1",
        )
        rejected = json.loads((output / "prefilter_rejected.jsonl").read_text().strip())
        self.assertEqual(rejected["event_id"], "game-run:guitar")
        self.assertEqual(rejected["reason"], "non_target_instrument")
        self.assertTrue(manifest["claims"]["all_input_candidates_accounted_for"])

    def test_runner_rejects_label_route_substitution(self) -> None:
        game = self._run(
            "game-run",
            "game",
            [_event("game-run", 1, 1.0, 60)],
        )
        basic = self._run(
            "basic-run",
            "basic_pitch",
            [_event("basic-run", 1, 1.02, 60.1)],
        )
        profiles, config = self._profiles_and_config(game, basic)
        output = self.project / "fusion" / "fusion-v1"
        output.parent.mkdir()
        with self.assertRaisesRegex(FusionRunError, "route does not match"):
            create_fusion_run(
                [("game", basic), ("basic", game)],
                profiles,
                config,
                output,
                run_id="fusion-v1",
            )


if __name__ == "__main__":
    unittest.main()
